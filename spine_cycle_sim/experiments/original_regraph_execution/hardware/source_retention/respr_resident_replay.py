"""Audit the queued ResPR resident screen offline without repeating a board run."""

import argparse
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from . import clocks, resident_board, resident_results
from .follow import unchanged
from .runtime import identity, save


def stage_inputs(stage, report):
    if stage["status"] != "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE":
        raise ValueError("independent same-clock G and R audit did not admit this image")
    if (not all(pin in stage["inputs"] for pin in report["stage_gates"]["pins"])
            or report["pins"]["gr_host"] not in stage["inputs"]
            or stage["g"]["driver_mhz"]["current"] != report["stage_gates"]["resident_mhz"]):
        raise ValueError("resident and independent stage evidence refer to different runs")
    unchanged([*stage["inputs"], stage["image"]])


def replay_case(record, report, stage):
    pins = report["pins"]
    graph = pins[record["case"]["dataset"].lower()]
    case = resident_board.frozen_case(record["case"]["dataset"], Path(graph["path"]), graph)
    if record["case"] != case or set(record["rows"]) != {"spine", "gr"}:
        raise ValueError("one completed pair on the frozen case is required")
    rows = record["rows"]
    commands = {
        "spine": [pins["spine_host"]["path"], pins["spine_image"]["path"],
                  "--dynamic-graph", graph["path"], "--source", str(case["source"]), "--resident-benchmark"],
        "gr": [pins["gr_host"]["path"], stage["image"]["path"], graph["path"], rows["gr"]["ranks"]["path"]],
    }
    evidence = [record["comparison_log"], rows["gr"]["ranks"]]
    modes = {
        "spine": {f"SPINE_EXPECT_BDF={report['bdf']}"},
        "gr": {f"GRASU_REGRAPH_EXPECT_BDF={report['bdf']}", "GRASU_UPDATE_REPEATS=1",
               "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
               "GRASU_SHARDED_EVENT_TRACE=0"},
    }
    if record["attempts"] != [
        {"arm": arm, "argv": rows[arm]["command"][3:]} for arm in ("spine", "gr")
    ]:
        raise ValueError("exactly one measured command per arm is required")
    for arm, row in rows.items():
        command = row["command"]
        expected = commands[arm]
        assignments = command[4:-len(expected)]
        # Inherited modes are removed via "-u NAME" before setting the frozen modes.
        actual_modes = {value for value in assignments if value.startswith(("SPINE_", "GRASU_")) and "=" in value}
        if (command[:3] != ["/usr/bin/taskset", "-c", "124,125"]
                or command[3] != "/usr/bin/env" or actual_modes != modes[arm]
                or command[-len(expected):] != expected
                or [value for value in assignments if value.startswith("XCL_DEVICE_INDEX=")]
                != [f"XCL_DEVICE_INDEX={report['device']}"]):
            raise ValueError("resident board command does not match the frozen arm")
        evidence.extend((row["stdout"], row["stderr"]))
        clock = clocks.replay(row["clock_evidence"])
        binary = stage["image"] if arm == "gr" else pins["spine_image"]
        if clock != row["clock"] or (clock["binary"], clock["bdf"]) != (binary, report["bdf"]):
            raise ValueError("resident clock replay does not match the image and board")
    unchanged(evidence)
    with TemporaryDirectory(prefix="respr-resident-replay-") as tmp:
        pair = resident_results.analyze(case, rows, Path(pins["comparator"]["path"]), Path(tmp), report["bdf"])
        original = json.loads(Path(record["comparison_log"]["path"]).read_text())
    if pair != record["pair"] or any(pair[key] != value for key, value in original.items()):
        raise ValueError("raw timing and oracle replay differs from the saved pair")
    mhz = {arm: row["clock"]["driver_reported_mhz"] for arm, row in rows.items()}
    if mhz["gr"] != report["stage_gates"]["resident_mhz"]:
        raise ValueError("G+R was not run at the independently screened clocks")
    propagated = pair["positive_propagation_on_both"]
    if case["requires_propagation"] and not propagated:
        scope = "RETAINED_WITHOUT_REQUIRED_PROPAGATION"
    elif not case["requires_propagation"]:
        scope = "CORRECTION_SCREEN_ONLY_NOT_SHARED_PROPAGATION_EVIDENCE"
    else:
        scope = "PROPAGATING_RESIDENT_SCREEN_PER_ARM_ORACLES"
    return {"case": case, "scope": scope, "pair": pair, "driver_mhz": mhz,
            "same_reported_clocks": mhz["gr"] == mhz["spine"]}


def run(resident, strict_stage, output):
    if output.exists():
        raise FileExistsError(output)
    inputs = [identity(resident), identity(strict_stage)]
    report, stage = (json.loads(Path(pin["path"]).read_text()) for pin in inputs)
    if (report["status"] not in ("PAIRED_SCREEN_MEASURED", "PAIRED_SCREEN_NEEDS_REVIEW")
            or (report["bdf"], report["device"]) != (resident_board.BDF, resident_board.DEVICE)
            or report["repetitions_per_arm"] != 1 or report["warmups"] != 0
            or report["board_launch_attempted"] is not True
            or report["full_evaluation_started"] is not False):
        raise ValueError("a completed, single-run resident screen is required")
    pins = report["pins"]
    for name, sha256 in (("spine_host", resident_board.SPINE_HOST_SHA256),
                         ("spine_image", resident_board.SPINE_IMAGE_SHA256),
                         ("comparator", resident_results.COMPARATOR_SHA256)):
        if pins[name]["sha256"] != sha256:
            raise ValueError("frozen Spine host, image or comparator differs")
    if [row["case"]["dataset"] for row in report["cases"]] != list(resident_board.CASES):
        raise ValueError("both declared cases must be retained")
    unchanged(pins.values())
    stage_inputs(stage, report)
    cases = []
    for row in report["cases"]:
        try:
            cases.append(replay_case(row, report, stage))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            cases.append({"case": row["case"], "scope": "RETAINED_NOT_ADMITTED", "error": repr(error)})
    unchanged(inputs)
    result = {"status": "AUDITED_SCREEN_NOT_FIGURE_EVIDENCE", "inputs": inputs, "cases": cases,
              "boundary": "uploaded resident batch through final readback; no graph bootstrap or batch upload",
              "limitations": ["R19 does not establish common dangling-residual propagation",
                              "Flickr uses per-arm correctness oracles, not direct array comparison",
                              "different Spine clocks, if any, describe deployed images only"]}
    save(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("resident", "strict-stage", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    args = parser.parse_args()
    print(run(args.resident, args.strict_stage, args.output)["status"], flush=True)


if __name__ == "__main__":
    main()
