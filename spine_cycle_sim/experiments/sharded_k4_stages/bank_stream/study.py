"""Replay the predeclared AU/SU/WK resident matrix with a source-bound profile."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from ..execution import identity
from ..link_runtime import run_link
from ..row_line.model_scope import RESIDENT
from ..row_line.model_validation import inventory
from ..sst_candidate import component_parameters, load_profile, require_export_headers
from .model_contract import PROFILE_PATH
from .model_validation import require_result, require_values
from .runtime import select


def run(root: Path, gates: Path, integration: Path, fixtures: Path, output: Path, *,
        sst: Path = Path("/data/feiyang/sst/bin/sst"), cpus: tuple[int, ...] = (112, 113),
        dramsim3_root: Path | None = None) -> dict:
    gate = json.loads((gates / "summary.json").read_text())
    if gate["status"] != "PASS" or gate["source_unchanged"] is not True:
        raise ValueError("complete fresh core/plugin/legacy gates are required")
    plugin = gates / "plugin"
    if sha256_file(plugin / "libspine_cycle.so") != gate["plugin_sha256"]:
        raise ValueError("tested plugin changed")
    compiled = json.loads((gates / "source_before.json").read_text())
    for row in compiled["files"]:
        if row["path"].startswith("cpp/") and sha256_file(root / row["path"]) != row["sha256"]:
            raise ValueError("compiled C++ source changed")
    profile_path = root / PROFILE_PATH
    profile = load_profile(root, profile_path)
    hls_sources = require_export_headers(integration, profile)
    contract_path = root / "configs/experiments/grasu_component_refactor_v1.json"
    contract = json.loads(contract_path.read_text())
    dram = dramsim3_root or Path(contract["build"]["dramsim3_root"])
    binding, runtime = select(sst, plugin, cpus, dram, compiled["dramsim3_library_sha256"])
    declarations = []
    for case in RESIDENT.cases:
        directory = fixtures / case.name
        fixture, values = directory / "resident.bin", directory / "expected.values.txt"
        geometry = inventory(fixture, **RESIDENT.inventory_limits)
        declarations.append({"id": case.name, "fixture": identity(fixture),
                             "expected_values": identity(values), "geometry": geometry,
                             "previous_row_line_result": identity(directory / "candidate/result.json")})
    RESIDENT.require_cases(declarations)
    output.mkdir(parents=True, exist_ok=False)
    relocated_contract = {**contract, "build": {**contract["build"], "dramsim3_root": str(dram)}}
    source = source_snapshot(root, contract_path, relocated_contract)
    pins = [identity(profile_path), identity(gates / "summary.json"), identity(gates / "source_before.json"),
            *runtime["files"],
            *hls_sources, *[row[key] for row in declarations
                           for key in ("fixture", "expected_values", "previous_row_line_result")]]
    with tarfile.open(output / "source.tar.gz", "w:gz") as archive:
        for row in source["files"]:
            archive.add(root / row["path"], arcname=row["path"], recursive=False)
        archive.add(profile_path, arcname=PROFILE_PATH, recursive=False)
        for row in hls_sources:
            archive.add(row["path"], arcname="hls/" + str(Path(row["path"]).relative_to(integration)), recursive=False)
    atomic_write_json(output / "manifest.json", {
        "source": source, "profile": profile, "pins": pins, "plugin": binding,
        "runtime": runtime, "plugin_build_source": compiled,
        "source_archive": identity(output / "source.tar.gz"), "cases": declarations,
        "limits": {**RESIDENT.limits, "tree_memory_gib": 1, "timeout_seconds": 600},
        "claim": "resident_SSSP_compute_prediction_not_FPGA_calibration_or_original_A4_match"})
    rows = []
    for declaration in declarations:
        target = output / declaration["id"]
        target.mkdir()
        config = {"profile": str(profile_path), "fixture": declaration["fixture"]["path"],
                  "output": str(target / "result.json"), "dram_output": str(target / "dram"),
                  "arm": "candidate", "max_cycles": RESIDENT.max_cycles}
        component_parameters(root, config)
        atomic_write_json(target / "run_config.json", config)
        command = ["taskset", "-c", ",".join(map(str, cpus)), "env", f"ROUTED_K4_RUN_CONFIG={target}/run_config.json",
                   str(sst), binding["command_option"], str(root / "sst/routed_k4_compute.py")]
        resource = run_link(command, root, target / "sst", timeout=600,
                            tree_memory_gib=1, reserve_gib=16, poll_seconds=1)
        if (resource["exit_code"] or resource["stop_reason"] != "process_exit"
                or resource["cleanup_snapshot_error"] is not None):
            raise RuntimeError("bounded bank-stream SST failed; raw evidence retained")
        result = json.loads((target / "result.json").read_text())
        admitted = require_result(result, declaration["geometry"],
                                  (target / "result.json.diagnostic.txt").read_text())
        require_values(target / "result.json.values.txt", Path(declaration["expected_values"]["path"]))
        previous = json.loads(Path(declaration["previous_row_line_result"]["path"]).read_text())
        if (not previous["success"] or [r["active_vertices"] for r in previous["rounds"]]
                != [r["active_vertices"] for r in result["rounds"]]):
            raise ValueError("complete convergence activity differs from previous preserved fixture")
        row = {"id": declaration["id"], **admitted, "geometry": declaration["geometry"],
               "full_external_state_equal": True, "round_activity_equal": True,
               "previous_row_line_predicted_cycles": previous["observed_cycles"],
               "new_over_previous_prediction": admitted["predicted_cycles"] / previous["observed_cycles"],
               "resource": resource}
        atomic_write_json(target / "admission.json", row)
        rows.append(row)
        print(declaration["id"], admitted["status"], admitted["predicted_cycles"], flush=True)
    verify_source_snapshot(root, source)
    if (sha256_file(plugin / "libspine_cycle.so") != gate["plugin_sha256"]
            or any(identity(Path(pin["path"])) != pin for pin in pins)):
        raise ValueError("bank-stream inputs or plugin changed")
    result = {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "rows": rows,
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False}
    atomic_write_json(output / "results.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gates", "integration", "fixtures", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=Path("/data/feiyang/sst/bin/sst"))
    parser.add_argument("--cpus", type=int, nargs="+", default=[112, 113])
    parser.add_argument("--dramsim3-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    try:
        run(root, args.gates.resolve(), args.integration.resolve(), args.fixtures.resolve(), args.output.resolve(),
            sst=args.sst.resolve(), cpus=tuple(args.cpus), dramsim3_root=args.dramsim3_root)
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
