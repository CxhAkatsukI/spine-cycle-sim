"""Freeze and replay explicitly bounded resident fixtures with an isolated plugin."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tarfile
from typing import Callable

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from spine_cycle_sim.sst_library import forced_sst_library_binding
from ..execution import identity
from ..link_runtime import run_link
from ..sst_candidate import component_parameters, load_profile
from .model_contract import BASIS, PROFILE_ID
from .model_scope import RESIDENT, SMOKE, study_scope
from .model_validation import compare, inventory


@dataclass(frozen=True)
class ModelStudy:
    profile_id: str
    basis: dict
    reference: str
    test_glob: str
    compare: Callable


ROW_LINE = ModelStudy(PROFILE_ID, BASIS, "unrouted_skip_empty_prefetch_not_historical_routed_original",
                      "test_sharded_k4_row_line_model*.py", compare)


def run(root: Path, plugin: Path, fixtures: list[Path], output: Path, *, scope_name: str = SMOKE.name,
        model: ModelStudy = ROW_LINE) -> dict:
    scope = study_scope(scope_name)
    if not fixtures or len(fixtures) > 4 or len(set(fixtures)) != len(fixtures):
        raise ValueError("declare one to four distinct bounded resident fixture directories")
    if scope.cases and len(fixtures) != len(scope.cases):
        raise ValueError("resident scope requires the complete predeclared graph matrix")
    profile_path = root / f"configs/architectures/{model.profile_id}.json"
    profile = load_profile(root, profile_path)
    contract_path = root / "configs/experiments/grasu_component_refactor_v1.json"
    source = source_snapshot(root, contract_path, json.loads(contract_path.read_text()))
    binding = forced_sst_library_binding(Path("/data/feiyang/sst/bin/sst"), plugin)
    test_files = [root / f"cpp/tests/routed_regraph/{name}_tests.cpp" for name in ("adapter", "system")]
    test_files += sorted((root / "tests").glob(model.test_glob))
    pins = [identity(path) for path in (profile_path, root / model.basis["path"], plugin / "libspine_cycle.so", *test_files)]
    declarations = []
    for index, directory in enumerate(fixtures):
        geometry = inventory(directory / "resident.bin", **scope.inventory_limits)
        values = directory / "result.json.values.txt"
        pins += [identity(directory / "resident.bin"), identity(values)]
        declarations.append({"id": scope.case_id(index), "geometry": geometry,
                             "fixture": identity(directory / "resident.bin"), "expected_values": identity(values)})
    scope.require_cases(declarations)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for row in source["files"]:
            stream.add(root / row["path"], arcname=row["path"], recursive=False)
        for path in (profile_path, root / model.basis["path"], *test_files):
            stream.add(path, arcname=path.relative_to(root), recursive=False)
    manifest = {"schema": 1, "source": source, "source_archive": identity(archive), "pins": pins,
                "plugin": binding, "profile": profile, "cases": declarations,
                "study_scope": scope.name, "claim": scope.claim,
                "reference": model.reference,
                "limits": scope.limits}
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
                      "arm": arm, "max_cycles": scope.max_cycles}
            component_parameters(root, config)
            atomic_write_json(target / "run_config.json", config)
            command = ["taskset", "-c", scope.limits["affinity"], "env", f"ROUTED_K4_RUN_CONFIG={target}/run_config.json",
                       "/data/feiyang/sst/bin/sst", binding["command_option"], str(root / "sst/routed_k4_compute.py")]
            record = run_link(command, root, target / "sst", timeout=scope.limits["timeout_seconds"],
                              tree_memory_gib=scope.limits["tree_memory_gib"],
                              reserve_gib=scope.limits["reserve_gib"], poll_seconds=1)
            if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
                    or record["cleanup_snapshot_error"] is not None):
                raise ValueError("bounded SST replay failed; raw attempt retained")
            arms[arm] = json.loads((target / "result.json").read_text())
            if sha256_file(target / "result.json.values.txt") != declaration["expected_values"]["sha256"]:
                raise ValueError("complete external state differs from preserved fixture oracle")
            print(declaration["id"], arm, "COMPLETE_STATE_PASS", flush=True)
        row = {"id": declaration["id"], "geometry": declaration["geometry"],
               "complete_external_state_equal": True,
               **model.compare(arms["original"], arms["candidate"], declaration["geometry"])}
        atomic_write_json(directory / "comparison.json", row)
        rows.append(row)
    require_pins()
    result = {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "rows": rows,
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False}
    atomic_write_json(output / "results.json", result)
    return result


def main(model: ModelStudy = ROW_LINE) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=(SMOKE.name, RESIDENT.name), default=SMOKE.name)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    try:
        result = run(root, args.plugin.resolve(), [p.resolve() for p in args.fixture], args.output.resolve(),
                     scope_name=args.scope, model=model)
        print(result["status"], flush=True)
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
