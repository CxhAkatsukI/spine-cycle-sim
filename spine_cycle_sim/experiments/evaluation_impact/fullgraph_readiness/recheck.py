"""Replay terminal preparation evidence without running hosts or requiring a board."""

import json
from pathlib import Path

from . import analysis, diagnostics, preparation

CLAIMS = ("board_programmed", "hardware_timing_measured", "publication_match", "production_baseline_admitted")


def smoke_rows(output):
    return [{"dataset": "SMOKE", "algorithm": algorithm, "vertices": 327681,
             "initial_edges": 6 if algorithm == "connected_components" else 3,
             "updates": 2 if algorithm == "connected_components" else 1, "source": 0,
             "graph": str(output / (algorithm + ".smoke.graph"))}
            for algorithm in preparation.ALGORITHMS]


def recheck(report, read):
    """`read` supplies a relative archive member as text, not a machine-local path."""
    success = report["status"] == analysis.PASS
    if report["status"] not in (analysis.PASS, "FAILED_RETAINED"):
        raise ValueError("only terminal attempts can be delivered")
    if any(report.get(key) is not False for key in CLAIMS):
        raise ValueError("preparation cannot establish board, timing or baseline claims")
    events = dict(line.split() for line in report["memory_events_after"].splitlines())
    if success and any(int(events[key]) != 0 for key in ("max", "oom", "oom_kill", "oom_group_kill")):
        raise ValueError("successful preparation requires no memory-limit or OOM event")
    matrix = report["matrix"]
    keys = [(row["dataset"], row["algorithm"]) for row in matrix]
    expected = [(d, a) for d in preparation.DATASETS for a in preparation.ALGORITHMS]
    if keys != expected:
        raise ValueError("exact ordered 24-input matrix required")
    for row in matrix:
        if (any(type(row.get(key)) is not int or row[key] < 0
                for key in ("vertices", "initial_edges", "updates", "source")) or
                not 0 <= row["source"] < row["vertices"] <= 255 * 65536 or
                row["updates"] != (16 if row["algorithm"] == "connected_components" else 8) or
                row["input_identity"]["path"] != row["graph"] or
                row["input_identity"]["sha256"] != row["sha256"] or
                row["input_identity"] not in report["pins"]):
            raise ValueError("frozen workload dimensions or identity disagree")
    if not report["steps"]:
        raise ValueError("unique executed steps required")
    output = Path(report["steps"][0]["cwd"])
    labels = replay_steps(report, read, algorithms=preparation.ALGORITHMS,
                          rows=[*smoke_rows(output), *matrix],
                          prepare_command=preparation.prepare_command, analyze=analysis.analyze,
                          successful=success)
    if success and (report["errors"] or len(report["steps"]) != len(labels) or
            [(case["dataset"], case["algorithm"]) for case in report["cases"]] != expected or
            [(case["dataset"], case["algorithm"]) for case in report["smokes"]] !=
            [("SMOKE", a) for a in preparation.ALGORITHMS] or
            any(case["status"] != "PASS" for case in report["smokes"]) or
            analysis.decision(report["cases"]) != analysis.PASS):
        raise ValueError("successful delivery requires all three smokes and 24 admitted cases")
    return {"status": report["status"], "source_revision": report["source_revision"],
            "cases": len(report["cases"]), "smokes": len(report["smokes"]),
            "errors": report["errors"], **{key: False for key in CLAIMS}}


def replay_steps(report, read, *, algorithms, rows, prepare_command, analyze, successful):
    """Replay bounded compile/preparation outputs; cohort policy stays with its owner."""
    steps = report["steps"]
    if not steps or len({step["label"] for step in steps}) != len(steps):
        raise ValueError("unique executed steps required")
    output = Path(steps[0]["cwd"])
    by_label = {row["dataset"] + "_" + row["algorithm"]: row for row in rows}
    labels = ["compile_" + a for a in algorithms] + list(by_label)
    if [step["label"] for step in steps] != labels[:len(steps)]:
        raise ValueError("execution order differs from declared compilation/smoke/matrix")
    for step in steps:
        label = step["label"]
        resource = json.loads(read("raw/" + label + ".resources.json"))
        stdout, stderr = (read("raw/" + label + suffix) for suffix in (".stdout.txt", ".stderr.txt"))
        if resource != {key: value for key, value in step.items() if key != "label"}:
            raise ValueError("saved resource log differs from report")
        if successful and (step["exit_code"] != 0 or step["stop_reason"] != "process_exit" or
                        step["cleanup_snapshot_error"] is not None):
            raise ValueError("successful report contains failed or interrupted child")
        if not label.startswith("compile_"):
            row = by_label[label]
            command = prepare_command(output / row["algorithm"], row, output / (label + ".unused-result"))
            if step["command"] != command or step["cwd"] != str(output):
                raise ValueError("prepare-only command boundary changed")
        elif successful:
            algorithm = label.removeprefix("compile_")
            command = step["command"]
            includes = [Path(token[2:]) for token in command if token.startswith("-I")]
            if (len(includes) != 4 or command != preparation.compile_command(
                    Path(command[0]), output / "source", algorithm, output / algorithm,
                    includes[0].parent, includes[1].parent)):
                raise ValueError("full-cache, row-line or compiler contract changed")
            note = diagnostics.review(stdout, stderr)
            if note != report["compiler_diagnostics"][algorithm]:
                raise ValueError("reviewed compilation diagnostics differ from raw output")
    for case in [*report["smokes"], *report["cases"]]:
        if case["status"] == "PASS":
            label = case["dataset"] + "_" + case["algorithm"]
            replay = analyze(by_label[label], read("raw/" + label + ".stdout.txt"),
                                      read("raw/" + label + ".stderr.txt"))
            if replay != case:
                raise ValueError("saved case differs from raw preparation evidence")
    return labels
