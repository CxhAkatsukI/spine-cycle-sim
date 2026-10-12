"""Freeze and replay the predeclared original-A4/V3/finite-directory matrix."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...execution import identity
from ..continuous_directory.study import ROOT, checked, freeze_sources, verify_pins
from .analysis import ARMS, SCENARIOS, admit, directory_lines, matrix
from .contract import BASIS_SHA
from .validation import model_schedule

HARNESS = "cpp/tests/routed_regraph/directory_tile"


def run(basis_dir, hls, output, bank_read_beats=False):
    basis_path = basis_dir / "results.json"
    if sha256_file(basis_path) != BASIS_SHA:
        raise ValueError("immutable V3/A4 basis required")
    hls_result = json.loads(hls.read_text())
    tile_rows, packet_pipeline, bank_stream = model_schedule(hls_result)
    bank_fifo_lines = hls_result.get("bank_fifo_lines", 128)
    geometry = {"bank_fifo_lines": bank_fifo_lines} if bank_fifo_lines != 128 else {}
    if bank_read_beats and not bank_stream:
        raise ValueError("progressive AXI beats require the admitted bank-stream topology")
    output.mkdir(parents=True, exist_ok=False)
    basis = json.loads(basis_path.read_text())
    pins = freeze_sources(output)
    plugin = ROOT / "build/sst/libspine_cycle.so"
    plugin_sha = sha256_file(plugin)
    for mode in ("cold", "warm_update"):
        shutil.copytree(basis_dir / "inputs" / mode, output / "inputs" / mode)
    input_pins = [identity(p) for p in (output / "inputs").rglob("*") if p.is_file()]
    old = json.loads((basis_dir / "manifest.json").read_text())
    for item in old["inputs"]:
        mode = Path(item["files"][0]["path"]).parent.name
        for pin in item["files"]:
            if sha256_file(output / "inputs" / mode / Path(pin["path"]).name) != pin["sha256"]:
                raise ValueError("frozen input differs")
    lines = {mode: directory_lines(output / "inputs" / mode) for mode in ("cold", "warm_update")}
    targets = ("routed_regraph_directory_tile_round", "original_regraph_sssp_real_round", "routed_pma_adapter_tests")
    commands = [["cmake", "-S", str(ROOT / HARNESS), "-B", str(output / "build"),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=/usr/bin/g++",
                 "-DBUILD_TESTING=ON", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
                ["cmake", "--build", str(output / "build"), "--target", *targets, "-j2"]]
    atomic_write_json(output / "manifest.json", {"schema": 1, "sources": pins, "input_pins": input_pins,
        "hls": identity(hls), "basis": identity(basis_path), "directory_lines": lines,
        "tile_rows": tile_rows, "packet_pipeline": packet_pipeline, "bank_stream": bank_stream,
        "bank_read_beats": bank_read_beats, **geometry,
        "compiler": subprocess.check_output(["g++", "--version"], text=True), "build_commands": commands,
        "plugin_sha256_before": plugin_sha, "boundary": "resident one synchronous SSSP round",
        "hardware_timing_admitted": False, "strict_resource_match_admitted": False})
    for name, command in zip(("configure", "compile"), commands):
        checked(command, ROOT, output / "raw" / name, timeout=600, budget=6)
    adapter = output / "build/simulator/cpp/routed_pma_adapter_tests"
    for name, args in (("legacy", []), ("tile", ["--directory-tile"]),
                       *(([("packet", ["--packet-pipeline"])]) if packet_pipeline else []),
                       *(([("bank", ["--bank-stream"])]) if bank_stream else []),
                       *(([("beats", ["--bank-read-beats"])]) if bank_read_beats else []),
                       *(([("wide", ["--bank-read-beats-wide"])]) if bank_fifo_lines != 128 else [])):
        checked([str(adapter), *args], ROOT, output / "raw" / name)
    binaries = {"original": output / "build/simulator/cpp/original_regraph_sssp_real_round",
                "candidate": output / "build/routed_regraph_directory_tile_round"}
    cases = []
    for mode, latency in SCENARIOS:
        for reverse in (0, 1):
            for arm in ARMS:
                verify_pins(pins + input_pins)
                label = f"{mode}_lat{latency}_reverse{reverse}_{arm}"
                state = output / "states" / label
                state.mkdir(parents=True)
                binary = binaries["original" if arm == "original" else "candidate"]
                command = ["taskset", "-c", "112-113", str(binary), str(output / "inputs" / mode),
                           str(state), str(latency), str(reverse), "100000000"]
                if arm != "original":
                    command.append(str(tile_rows if arm == "tile" else 8))
                    if arm == "tile" and packet_pipeline:
                        command.append("1")
                        if bank_stream:
                            command.append("1")
                            if bank_read_beats or bank_fifo_lines != 128:
                                command.append(str(int(bank_read_beats)))
                            if bank_fifo_lines != 128:
                                command.append(str(bank_fifo_lines))
                prefix = output / "raw" / label
                checked(command, ROOT, prefix, timeout=180)
                old_arm = "original" if arm == "original" else "cross_row"
                historical = basis_dir / "raw" / f"{mode}_lat{latency}_reverse{reverse}_{old_arm}.stdout.txt"
                cases.append(admit(prefix.with_suffix(".stdout.txt").read_text(), state, basis,
                                   (mode, latency, reverse, arm), historical.read_text(), lines[mode],
                                   tile_rows, packet_pipeline, bank_stream, bank_read_beats, bank_fifo_lines))
                atomic_write_json(output / "partial_results.json", cases)
    summary = matrix(cases)
    verify_pins(pins + input_pins)
    if sha256_file(plugin) != plugin_sha:
        raise ValueError("production plugin changed")
    result = summary | {"schema": 1, "cases": cases, "default_plugin_unchanged": True,
        "tile_rows": tile_rows, "packet_pipeline": packet_pipeline, "bank_stream": bank_stream,
        "bank_read_beats": bank_read_beats, **geometry,
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "build_files": [identity(path) for path in (*binaries.values(), adapter,
                        output / "build/CMakeCache.txt", output / "build/compile_commands.json")]}
    atomic_write_json(output / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("basis", "hls", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bank-read-beats", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.basis.resolve(), args.hls.resolve(), args.output.resolve(), args.bank_read_beats)
        print(json.dumps({"status": result["status"], "runs": len(result["cases"])}))
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
