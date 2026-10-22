"""Fresh SST software-only default replay for a source-pinned core campaign."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from ..r_credits.freeze import ROOT, pin
from .runtime import LOCAL, reservation, settings


def run(output, core_result, baseline):
    core = json.loads(core_result.read_text())
    if core.get("pins_unchanged") is not True or not core.get("steps"):
        raise ValueError("completed source-pinned core checks required")
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="WAITING_FOR_ADMISSION", steps=[], pins=core["pins"] + [pin(core_result)],
        claim="default SST software compatibility only; no FPGA or candidate timing admission")

    def save():
        atomic_write_json(output / "results.json", report)

    def verify():
        if any(sha256_file(Path(p["path"])) != p["sha256"] for p in report["pins"]):
            raise ValueError("SST pinned source/compiler/input/binary/reference changed")

    save()
    try:
        with reservation(output, settings(LOCAL, 1), 600) as safety:
            report.update(status="RUNNING", safety=safety); save(); verify()
            commands = [("build", ["make", "-C", "cpp/sst", "-j1", "BUILD_DIR=" + str(output / "plugin"),
                "CXX=/usr/bin/g++", "DRAMSIM3_ROOT=/data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729",
                "NATIVE_HOST=0", "PGO_MODE=off", "SPINE_HOST_OPT_FLAGS=-O3 -DNDEBUG -flto"]),
                ("legacy", ["python3", "scripts/run_component_refactor_regression.py", "--lib-dir",
                str(output / "plugin"), "--out-dir", str(output / "legacy"), "--baseline-dir", str(baseline),
                "--jobs", "1", "--case-timeout-seconds", "600"])]
            baseline_files = sorted(p for p in baseline.rglob("*") if p.is_file())
            if not baseline_files:
                raise ValueError("nonempty SST reference required")
            report["pins"] += [pin(p) for p in baseline_files]
            for label, command in commands:
                print("RUN SST " + label, flush=True)
                step = run_bounded(command, ROOT, output / "raw" / label, timeout=1800,
                                   memory_gib=4, reserve_gib=24)
                report["steps"].append(step); save()
                if step["exit_code"] or step["timed_out"]:
                    raise ValueError("SST check failed: " + label)
                if label == "build":
                    report["plugin"] = pin(output / "plugin/libspine_cycle.so")
                    report["pins"].append(report["plugin"]); save()
            equivalent = json.loads((output / "legacy/equivalence.json").read_text())
            if equivalent["status"] != "PASS" or len(equivalent["cases"]) != 5:
                raise ValueError("incomplete or changed five-case SST replay")
            verify(); report.update(status="PASS_SST_COMPATIBILITY_NOT_TIMING_ADMISSION", pins_unchanged=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error)); save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "core-result", "baseline"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.core_result.resolve(),
                                  args.baseline.resolve())["status"]}))
