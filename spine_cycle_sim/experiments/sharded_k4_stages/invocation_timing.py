"""Compare overlapping invocation timelines without fitting or adding gaps."""

import hashlib
import json
from pathlib import Path
import tarfile

from .analysis import analyze_log
from .sst_timing import timing_diagnostic


def compare_invocations(result: dict, board: dict) -> dict:
    timing = timing_diagnostic(result, board)
    count, rounds = result["partitions"], len(result["rounds"])
    expected = {(r + 1, p, p % 4, stage) for r in range(rounds)
                for p in range(count) for stage in ("adapter", "gather")}
    models = {(x["round"], x["partition"], x["worker"], x["stage"]): x for x in result["invocations"]}
    events = [e for e in board["events"] if e["stage"] in ("adapter", "gather")]
    measured = {(x["round"] + 1, x["shard"], x["worker"], x["stage"]): x for x in events}
    if (set(models) != expected or len(models) != len(result["invocations"])
            or set(measured) != expected or len(measured) != len(events)):
        raise ValueError("complete, unique, matching invocation identities required")
    groups = []
    for r in range(1, rounds + 1):
        model_base = result["rounds"][r - 1]["start"]
        board_base = min(e["start_ns"] for e in board["events"]
                         if e["round"] == r - 1 and e["stage"] != "source_prepare")
        for stage in ("adapter", "gather"):
            for worker in range(min(4, count)):
                rows, previous = [], None
                for p in range(worker, count, 4):
                    key = (r, p, worker, stage)
                    m, b = models[key], measured[key]
                    if (m["start"] < model_base or m["end"] <= m["start"]
                            or not 0 <= b["queued_ns"] <= b["submit_ns"] <= b["start_ns"] < b["end_ns"]):
                        raise ValueError("invalid invocation interval")
                    row = {"partition": p, "model_start_ms": (m["start"] - model_base) / 150000,
                           "model_end_ms": (m["end"] - model_base) / 150000,
                           "board_start_ms": (b["start_ns"] - board_base) / 1e6,
                           "board_end_ms": (b["end_ns"] - board_base) / 1e6,
                           "model_duration_ms": (m["end"] - m["start"]) / 150000,
                           "board_duration_ms": (b["end_ns"] - b["start_ns"]) / 1e6,
                           "model_gap_ms": None, "board_gap_ms": None}
                    if previous:
                        pm, pb = previous
                        if m["start"] < pm["end"] or b["start_ns"] < pb["end_ns"]:
                            raise ValueError("same-CU invocation overlap")
                        row.update(model_gap_ms=(m["start"] - pm["end"]) / 150000,
                                   board_gap_ms=(b["start_ns"] - pb["end_ns"]) / 1e6,
                                   queued_before_previous_end=b["queued_ns"] <= pb["end_ns"],
                                   submit_after_previous_end_ms=max(0, b["submit_ns"] - pb["end_ns"]) / 1e6,
                                   start_after_submit_ms=(b["start_ns"] - b["submit_ns"]) / 1e6)
                    rows.append(row)
                    previous = m, b
                groups.append({"round": r, "stage": stage, "worker": worker, "invocations": rows,
                               "board_gap_sum_ms": sum(x["board_gap_ms"] or 0 for x in rows),
                               "model_gap_sum_ms": sum(x["model_gap_ms"] or 0 for x in rows)})
    return {"timing": timing, "groups": groups}


def analyze_package(package: Path) -> dict:
    report = json.loads((package / "matrix.json").read_text())
    expected = {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("original", "candidate")}
    if (report["status"] != "EMPTY_EXIT_REAL_MATRIX_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
            or report["hardware_timing_admitted"] or report["timing_fit_performed"]
            or len(report["rows"]) != 6 or {r["id"] for r in report["rows"]} != expected):
        raise ValueError("complete unfitted six-row diagnostic package required")
    index = json.loads((package / "matrix_raw_index.json").read_text())
    archive = package / "raw_matrix.tar.gz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != index["archive"]["sha256"]:
        raise ValueError("frozen matrix archive changed")
    pins = {p["archive_path"]: p["sha256"] for p in index["files"]}
    rows = []
    with tarfile.open(archive) as stream:
        for row in report["rows"]:
            name = row["id"]
            paths = (f"campaign/matrix_v4/{name}/result.json", f"board/{name}/run.log")
            data = [stream.extractfile(path).read() for path in paths]
            if any(hashlib.sha256(blob).hexdigest() != pins[path] for path, blob in zip(paths, data)):
                raise ValueError("frozen invocation input changed")
            derived = compare_invocations(json.loads(data[0]), analyze_log(data[1].decode(), require_trace=True))
            if derived["timing"] != row["timing"]:
                raise ValueError("matrix timing differs from its raw evidence")
            rows.append({"id": name, **derived})
    return {"status": "INVOCATION_TIMING_DIAGNOSTIC", "rows": rows,
            "matrix_archive_sha256": index["archive"]["sha256"],
            "hardware_timing_admitted": False, "timing_fit_performed": False,
            "limits": ["per-worker gaps overlap; do not sum groups as an E2E penalty",
                       "queued/submit timestamps do not isolate CPU work or a scheduler root cause",
                       "gather denotes the whole lksg invocation, not an exclusive compute stage",
                       "observed gaps are not injected into the predictive simulator"]}
