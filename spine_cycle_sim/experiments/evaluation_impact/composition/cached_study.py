"""Build and check complete cached sharded G, retaining all earlier predictions."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from . import cached_analysis as analysis
from .banked_study import run as run_banked
from .study import ROOT, pin


def run(output, pre_edit, previous_routed, previous_matrix, previous_sst):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "pins": [pin(pre_edit / "banked-handoff.stdout.txt")],
              "steps": [], "baseline_admitted": False, "hardware_timing_admitted": False,
              "boundary": "G preload/update/writeback -> resident PMA -> warm R convergence; setup/seed/host untimed"}

    def save():
        atomic_write_json(output / "results.json", report)

    save()
    try:
        banked = run_banked(output / "banked", pre_edit, previous_routed, previous_matrix, previous_sst)
        report["pins"] += banked["pins"]
        previous = pre_edit / "banked-handoff.stdout.txt"
        current = output / "banked/raw/banked-handoff.stdout.txt"
        if previous.read_bytes() != current.read_bytes():
            raise ValueError("execution-helper extraction changed previous banked results")
        report["previous_banked_stdout_exact"] = True
        build = output / "banked/compatibility/build/cpp"
        step = run_bounded([str(build / "grasu_cached_handoff_tests")], ROOT, output / "raw/cached-handoff",
                           timeout=1200, memory_gib=2, reserve_gib=8)
        report["steps"].append({"label": "cached-handoff", **step})
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("cached sharded handoff failed")
        report["analysis"] = analysis.analyze(Path(step["stdout"]).read_text())
        report["pins"] += [pin(build / "grasu_cached_handoff_tests"), pin(current),
                           pin(output / "banked/results.json"), pin(Path(step["stdout"]))]
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("cached study frozen identity changed")
        report.update(status=analysis.STATUS, pins_unchanged=True, core_tests=banked["core_tests"],
                      exact_previous_g_rows=banked["exact_previous_g_rows"],
                      sst_scope=banked["sst_scope"], previous_default_stdout_and_sst_exact=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    print(json.dumps({"status": report["status"], "rows": len(report["analysis"]["rows"])}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "pre-edit", "previous-routed", "previous-matrix", "previous-sst"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.pre_edit.resolve(), args.previous_routed.resolve(),
        args.previous_matrix.resolve(), args.previous_sst.resolve())
