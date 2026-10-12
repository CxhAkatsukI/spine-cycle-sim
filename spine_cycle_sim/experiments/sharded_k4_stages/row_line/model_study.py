"""Freeze and replay small resident fixtures with an isolated whole-line plugin."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from spine_cycle_sim.sst_library import forced_sst_library_binding
from ..execution import identity
from ..link_runtime import run_link
from ..sst_candidate import component_parameters, load_profile
from .model_contract import BASIS, PROFILE_ID
from .model_validation import compare, inventory


def run(root: Path, plugin: Path, fixtures: list[Path], output: Path) -> dict:
    if not fixtures or len(fixtures) > 4 or len(set(fixtures)) != len(fixtures):
        raise ValueError("declare one to four distinct bounded resident fixture directories")
    profile_path = root / f"configs/architectures/{PROFILE_ID}.json"
    profile = load_profile(root, profile_path)
    contract_path = root / "configs/experiments/grasu_component_refactor_v1.json"
    source = source_snapshot(root, contract_path, json.loads(contract_path.read_text()))
    binding = forced_sst_library_binding(Path("/data/feiyang/sst/bin/sst"), plugin)
    test_files = [root / f"cpp/tests/routed_regraph/{name}_tests.cpp" for name in ("adapter", "system")]
    test_files += sorted((root / "tests").glob("test_sharded_k4_row_line_model*.py"))
    pins = [identity(path) for path in (profile_path, root / BASIS["path"], plugin / "libspine_cycle.so", *test_files)]
    declarations = []
    for index, directory in enumerate(fixtures):
        geometry = inventory(directory / "resident.bin")
        values = directory / "result.json.values.txt"
        pins += [identity(directory / "resident.bin"), identity(values)]
        declarations.append({"id": f"case{index + 1}", "geometry": geometry,
                             "fixture": identity(directory / "resident.bin"), "expected_values": identity(values)})
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for row in source["files"]:
            stream.add(root / row["path"], arcname=row["path"], recursive=False)
        for path in (profile_path, root / BASIS["path"], *test_files):
            stream.add(path, arcname=path.relative_to(root), recursive=False)
    manifest = {"schema": 1, "source": source, "source_archive": identity(archive), "pins": pins,
                "plugin": binding, "profile": profile, "cases": declarations,
                "claim": "bounded_whole_line_SST_smoke_not_FPGA_calibration_or_A4_comparison",
                "reference": "unrouted_skip_empty_prefetch_not_historical_routed_original",
                "limits": {"timeout_seconds": 180, "max_cycles": 1000000, "tree_memory_gib": 3,
                           "reserve_gib": 16, "affinity": "112-113", "parallel_workers": 1}}
    atomic_write_json(output / "manifest.json", manifest)

    def require_pins():
        verify_source_snapshot(root, source)
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("a frozen input, profile or plugin changed")

    rows = []
    for declaration in declarations:
        directory = output / declaration["id"]
        directory.mkdir()
        shutil.copyfile(declaration["fixture"]["path"], directory / "resident.bin")
        shutil.copyfile(declaration["expected_values"]["path"], directory / "expected.values.txt")
        if (sha256_file(directory / "resident.bin") != declaration["fixture"]["sha256"]
                or sha256_file(directory / "expected.values.txt") != declaration["expected_values"]["sha256"]):
            raise ValueError("frozen fixture copy changed")
        arms = {}
        for arm in ("original", "candidate"):
            require_pins()
            target = directory / arm
            target.mkdir()
            config = {"profile": str(profile_path), "fixture": str(directory / "resident.bin"),
                      "output": str(target / "result.json"), "dram_output": str(target / "dram"),
                      "arm": arm, "max_cycles": 1000000}
            component_parameters(root, config)
            atomic_write_json(target / "run_config.json", config)
            command = ["taskset", "-c", "112-113", "env", f"ROUTED_K4_RUN_CONFIG={target}/run_config.json",
                       "/data/feiyang/sst/bin/sst", binding["command_option"], str(root / "sst/routed_k4_compute.py")]
            record = run_link(command, root, target / "sst", timeout=180,
                              tree_memory_gib=3, reserve_gib=16, poll_seconds=1)
            if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
                    or record["cleanup_snapshot_error"] is not None):
                raise ValueError("bounded SST replay failed; raw attempt retained")
            arms[arm] = json.loads((target / "result.json").read_text())
            if sha256_file(target / "result.json.values.txt") != declaration["expected_values"]["sha256"]:
                raise ValueError("complete external state differs from preserved fixture oracle")
            print(declaration["id"], arm, "COMPLETE_STATE_PASS", flush=True)
        row = {"id": declaration["id"], "geometry": declaration["geometry"],
               "complete_external_state_equal": True, **compare(arms["original"], arms["candidate"], declaration["geometry"])}
        atomic_write_json(directory / "comparison.json", row)
        rows.append(row)
    require_pins()
    result = {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "rows": rows,
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False}
    atomic_write_json(output / "results.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    try:
        result = run(root, args.plugin.resolve(), [p.resolve() for p in args.fixture], args.output.resolve())
        print(result["status"], flush=True)
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
