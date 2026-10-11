"""Seal real-graph empty-exit diagnostics using the already-tested v4 plugin."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import verify_source_snapshot
from .analysis import analyze_log
from .execution import identity
from .row_exit_delivery import compare_payloads
from .sst_candidate import EMPTY_EXIT_PROFILE_ID, STREAM_PROFILE_ID
from .sst_timing import timing_diagnostic


def compare_real_results(prior: dict, replay: dict, corrected: dict) -> dict:
    if prior != replay or prior["profile_id"] != STREAM_PROFILE_ID:
        raise ValueError("all v3 result fields must replay exactly")
    if corrected["profile_id"] != EMPTY_EXIT_PROFILE_ID:
        raise ValueError("explicit v4 profile required")
    compare_payloads(prior, corrected)
    cycles = [r["counters"]["end_cycle"] - r["counters"]["start_cycle"] for r in (prior, corrected)]
    if min(cycles) <= 0:
        raise ValueError("complete positive cycle windows required")
    return {"v3_every_result_field_equal": True, "ignored_result_fields": [],
            "non_timing_counters_equal": True, "v3_cycles": cycles[0], "v4_cycles": cycles[1],
            "v4_over_v3_cycles": cycles[1] / cycles[0]}


def package_real_matrix(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "matrix.json").exists() or (output / "raw_matrix.tar.gz").exists():
        raise FileExistsError("real-graph empty-exit checkpoint is frozen")
    binding = json.loads((data / "binding.json").read_text())
    verify_source_snapshot(root, binding["source"])
    if identity(Path(binding["plugin"]["path"])) != binding["plugin"]:
        raise ValueError("frozen plugin changed")
    control = json.loads((output.parent / "empty_exit_model/model.json").read_text())
    tested = control["legacy"]["candidate_identity"]
    if binding["plugin"]["sha256"] != tested["plugin_sha256"]:
        raise ValueError("matrix must reuse the fully tested control plugin")
    old_files = {r["path"]: r["sha256"] for r in tested["source"]["files"]}
    new_files = {r["path"]: r["sha256"] for r in binding["source"]["files"]}
    added = "spine_cycle_sim/experiments/sharded_k4_stages/row_exit_matrix.py"
    if new_files != {**old_files, added: new_files[added]}:
        raise ValueError("only this evidence packager may differ from tested numerical sources")
    expected_ids = {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("original", "candidate")}
    for name in ("replay_v3", "matrix_v4"):
        matrix = json.loads((data / name / "summary.json").read_text())
        if (matrix["status"] != "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED"
                or matrix["hardware_timing_admitted"] or len(matrix["rows"]) != 6
                or {r["id"] for r in matrix["rows"]} != expected_ids):
            raise ValueError("both complete six-row matrices required without timing admission")
        gate = json.loads((data / f"{name}.resources.json").read_text())
        if gate["exit_code"] or gate["timed_out"]:
            raise ValueError("matrix execution failed")
    rows, files = [], {}
    for name in sorted(expected_ids):
        prior = Path(binding["parent"]) / "matrix_v3" / name
        replay, corrected = data / "replay_v3" / name, data / "matrix_v4" / name
        directories = (prior, replay, corrected)
        results = [json.loads((d / "result.json").read_text()) for d in directories]
        row = {"id": name, **compare_real_results(*results)}
        if (prior / "result.json").read_bytes() != (replay / "result.json").read_bytes():
            raise ValueError("v3 replay serialization differs")
        for filename in ("result.json.values.txt", "resident.bin"):
            if len({identity(d / filename)["sha256"] for d in directories}) != 1:
                raise ValueError(f"full state or resident input changed: {name}/{filename}")
        for directory in (replay, corrected):
            manifest = json.loads((directory / "manifest.json").read_text())
            if (manifest["source"] != binding["source"]
                    or manifest["plugin"]["plugin_sha256"] != binding["plugin"]["sha256"]):
                raise ValueError("common source and plugin required")
            if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"] + manifest["headers"]):
                raise ValueError("input changed after execution")
        board_log = Path(next(p["path"] for p in manifest["pins"] if Path(p["path"]).name == "run.log"))
        board = analyze_log(board_log.read_text(), require_trace=True)
        row["timing"] = timing_diagnostic(results[-1], board)
        if row["timing"] != json.loads((corrected / "summary.json").read_text())["timing"]:
            raise ValueError("saved timing diagnostic differs")
        if identity(board_log.parent / "result.txt")["sha256"] != identity(corrected / "result.json.values.txt")["sha256"]:
            raise ValueError("complete FPGA output differs")
        files[f"board/{name}/run.log"] = board_log
        files[f"parent/{name}/result.json"] = prior / "result.json"
        rows.append(row)
    for path in data.rglob("*"):
        if path.is_file() and path.name != "resident.bin":
            files["campaign/" + str(path.relative_to(data))] = path
    files["source/row_exit_matrix.py"] = root / added
    for path in root.glob("tests/test_sharded_k4_row_exit_matrix*.py"):
        files["tests/" + path.name] = path
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive = output / "raw_matrix.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"])) != {k: v for k, v in pin.items() if k != "archive_path"} for pin in index):
        raise ValueError("evidence changed during packaging")
    dependencies = [identity(output.parent / path) for path in
                    ("empty_exit_model/model_raw_index.json", "routed_streams/streams_raw_index.json",
                     "sst_raw_index.json")]
    atomic_write_json(output / "matrix_raw_index.json", {"archive": identity(archive), "files": index,
                                                        "dependencies": dependencies})
    report = {"status": "EMPTY_EXIT_REAL_MATRIX_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC", "rows": rows,
              "hardware_timing_admitted": False, "original_A4_match_admitted": False,
              "timing_fit_performed": False, "plugin_reused": binding["plugin"],
              "numerical_sources_unchanged_from_control": True,
              "claim": "same-input prediction with exact v3 replay, not identical-window FPGA calibration"}
    atomic_write_json(output / "matrix.json", report)
    return report
