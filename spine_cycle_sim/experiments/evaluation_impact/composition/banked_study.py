"""Bounded fresh-core/SST checks, physical handoff and all prior G predictions."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..common_g.finite_search.preparation import matrix, prepare
from ..common_g.finite_search.study import settings
from ..common_g.runner import Study, run as run_matrix
from . import banked_analysis as analysis
from .study import ROOT, pin, run as run_compatibility


def run(output, pre_edit, previous_routed, previous_matrix, previous_sst):
    output.mkdir(parents=True, exist_ok=False)
    inputs = [pre_edit / name for name in ("freeze.json", "compatibility.json", "handoff.stdout.txt",
                                           "finite-search.stdout.txt")] + [previous_routed, previous_matrix]
    inputs += [previous_sst / name for name in ("sst-memory/summary.json", "sst-native/result.json")]
    report = {"status": "RUNNING", "pins": [pin(p) for p in inputs], "steps": [],
              "baseline_admitted": False, "hardware_timing_admitted": False,
              "g_implementation": "finite 64/M32 search, unchanged direct processors; cached hot disabled",
              "boundary": "same physical G PMA -> warm SSSP R convergence; state/seed and setup untimed"}

    def save():
        atomic_write_json(output / "results.json", report)

    def execute(command, label):
        step = run_bounded(command, ROOT, output / "raw" / label, timeout=600, memory_gib=2, reserve_gib=8)
        report["steps"].append({"label": label, **step})
        save()
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("banked check failed: " + label)
        return step

    save()
    try:
        compatibility = run_compatibility(output / "compatibility", previous_routed)
        build = output / "compatibility/build/cpp"
        report["pins"] += compatibility["pins"]
        previous_handoff = (pre_edit / "handoff.stdout.txt").read_bytes()
        current_handoff = (output / "compatibility/raw/handoff.stdout.txt").read_bytes()
        if previous_handoff != current_handoff:
            raise ValueError("legacy handoff changed after execution-helper extraction")
        report["legacy_handoff_stdout_exact"] = True
        for name in ("sst-memory/summary.json", "sst-native/result.json"):
            if json.loads((output / "compatibility" / name).read_text()) != json.loads((previous_sst / name).read_text()):
                raise ValueError("default SST numerical observations changed")
        report["default_sst_json_fields_exact"] = True
        search = execute([str(build / "grasu_parallel_search_tests")], "metadata-routing")
        if Path(search["stdout"]).read_bytes() != (pre_edit / "finite-search.stdout.txt").read_bytes():
            raise ValueError("legacy search stdout changed")
        handoff = execute([str(build / "grasu_banked_handoff_tests")], "banked-handoff")
        report["analysis"] = analysis.analyze(Path(handoff["stdout"]).read_text())
        replay = run_matrix(output / "g-replay", build, previous_matrix,
            Study("g_finite_banked_replay", matrix, prepare, analysis.replay, settings(),
                  "G_FINITE_BANK_ROUTING_DEFAULTS_EXACT_228", ("exact_replayed_rows",), True))
        report["exact_previous_g_rows"] = replay["exact_replayed_rows"]
        report["pins"] += replay["pins"]
        report["pins"] += [pin(build / "grasu_banked_handoff_tests"),
                           pin(output / "compatibility/results.json"), pin(output / "g-replay/results.json")]
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("banked study frozen identity changed")
        report.update(status=analysis.STATUS, pins_unchanged=True, core_tests=33,
                      sst_scope="default-only exact compatibility, not banked G timing calibration")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    print(json.dumps({"status": report["status"], "exact_previous_g_rows": report["exact_previous_g_rows"]}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "pre-edit", "previous-routed", "previous-matrix", "previous-sst"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.pre_edit.resolve(), args.previous_routed.resolve(),
        args.previous_matrix.resolve(), args.previous_sst.resolve())
