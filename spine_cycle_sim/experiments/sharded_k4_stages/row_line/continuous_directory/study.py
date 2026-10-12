"""Freeze, build and replay original A4/V3 against a continuous-reader candidate."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...execution import identity
from ...link_runtime import run_link
from .analysis import admit, validate_matrix

ROOT = Path(__file__).resolve().parents[5]
HARNESS = "cpp/tests/routed_regraph/continuous_directory"
TARGETS = ("routed_regraph_continuous_directory_round", "original_regraph_sssp_real_round",
           "routed_pma_adapter_tests")
BASIS_SHA = "07fb710f07189b2e63bf281931d6e08ce1f3397aa6292bc57a6ff0ec3ea8ab60"


def checked(command, cwd, prefix, timeout=300, budget=3):
    result = run_link(command, cwd, prefix, timeout=timeout, tree_memory_gib=budget,
                      reserve_gib=16, poll_seconds=0.5)
    if result["exit_code"] or result["stop_reason"] != "process_exit" or result["cleanup_snapshot_error"]:
        raise RuntimeError(f"bounded step failed: {prefix.name}; raw output retained")
    print(prefix.name, "PASS", flush=True)
    return result


def freeze_sources(output, integration=None):
    paths = [ROOT / "CMakeLists.txt"]
    for owner in (ROOT / "cpp", ROOT / "configs", ROOT / "spine_cycle_sim/experiments"):
        paths += [p for p in owner.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    if integration:
        paths += list((integration / "kernels/pma_to_regraph_adapter").glob("*"))
        paths += [integration / "tests/pma_adapter_row_prefetch_tb.cpp",
                  integration / "scripts/check_pma_adapter_cross_row.sh", integration / "scripts/env.sh"]
    pins = [identity(p) for p in sorted(set(paths)) if p.is_file()]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for pin in pins:
            path = Path(pin["path"])
            relative = (Path("simulator") / path.relative_to(ROOT) if path.is_relative_to(ROOT)
                        else Path("integration") / path.relative_to(integration))
            archive.add(path, arcname=str(relative), recursive=False)
    return pins


def verify_pins(pins):
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("frozen input or source changed during execution")


def run(basis_dir, output):
    basis_path = basis_dir / "results.json"
    if sha256_file(basis_path) != BASIS_SHA:
        raise ValueError("immutable V3/A4 basis required")
    basis = json.loads(basis_path.read_text())
    old_manifest = json.loads((basis_dir / "manifest.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    plugin = ROOT / "build/sst/libspine_cycle.so"
    pins = freeze_sources(output)
    plugin_sha = sha256_file(plugin)
    for entry in old_manifest["inputs"]:
        mode = Path(entry["files"][0]["path"]).parent.name
        source = basis_dir / "inputs" / mode
        for pin in entry["files"]:
            if sha256_file(source / Path(pin["path"]).name) != pin["sha256"]:
                raise ValueError("frozen graph/state/batch input changed")
        shutil.copytree(source, output / "inputs" / mode)
    input_pins = [identity(p) for p in (output / "inputs").rglob("*") if p.is_file()]
    compiler = subprocess.check_output(["g++", "--version"], text=True)
    commands = [["cmake", "-S", str(ROOT / HARNESS), "-B", str(output / "build"),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
                 "-DBUILD_TESTING=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
                ["cmake", "--build", str(output / "build"), "--target", *TARGETS, "-j2"]]
    manifest = {"schema": 1, "version": "continuous_directory_v1", "sources": pins,
                "input_pins": input_pins, "basis": identity(basis_path), "compiler": compiler,
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "dirty_diff": subprocess.check_output(["git", "diff", "--", "cpp"], cwd=ROOT, text=True),
                "build_commands": commands, "plugin_sha256_before": plugin_sha,
                "boundary": "resident one synchronous SSSP round; no GraSU/host/DMA/launch/convergence claim",
                "hardware_timing_admitted": False, "strict_resource_match_admitted": False}
    atomic_write_json(output / "manifest.json", manifest)
    for name, command in zip(("configure", "build"), commands):
        checked(command, ROOT, output / "raw" / name, timeout=600, budget=6)
    adapter = output / "build/simulator/cpp/routed_pma_adapter_tests"
    for name, args in (("legacy_adapter", []), ("continuous_adapter", ["--continuous-directory"]),
                       ("rtl_model_matrix", ["--rtl-continuous-matrix"])):
        checked([str(adapter), *args], ROOT, output / "raw" / name)
    binaries = {"original": output / "build/simulator/cpp/original_regraph_sssp_real_round",
                "candidate": output / "build/routed_regraph_continuous_directory_round"}
    cases = []
    for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128)):
        for reverse in (0, 1):
            for arm in ("original", "cross_row", "continuous"):
                verify_pins(pins + input_pins)
                label = f"{mode}_lat{latency}_reverse{reverse}_{arm}"
                state = output / "states" / label
                state.mkdir(parents=True)
                binary = binaries["original" if arm == "original" else "candidate"]
                command = ["taskset", "-c", "112-113", str(binary), str(output / "inputs" / mode),
                           str(state), str(latency), str(reverse), "100000000"]
                if arm != "original":
                    command.append(str(int(arm == "continuous")))
                prefix = output / "raw" / label
                checked(command, ROOT, prefix, timeout=180)
                old_arm = "original" if arm == "original" else "cross_row"
                historical = basis_dir / "raw" / f"{mode}_lat{latency}_reverse{reverse}_{old_arm}.stdout.txt"
                cases.append(admit(prefix.with_suffix(".stdout.txt").read_text(), state, basis,
                                   mode, latency, reverse, arm, historical.read_text()))
                atomic_write_json(output / "partial_results.json", cases)
    validate_matrix(cases)
    verify_pins(pins + input_pins)
    if sha256_file(plugin) != plugin_sha:
        raise ValueError("production plugin was modified")
    result = {"schema": 1, "status": "PASS_STRUCTURAL_PREDICTION_NOT_FPGA", "cases": cases,
              "default_plugin_unchanged": True, "manifest_sha256": sha256_file(output / "manifest.json"),
              "build_files": [identity(p) for p in (*binaries.values(), adapter,
                              output / "build/CMakeCache.txt", output / "build/compile_commands.json")]}
    atomic_write_json(output / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.basis.resolve(), args.output.resolve())
        print(json.dumps({"status": result["status"], "runs": len(result["cases"])}))
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
