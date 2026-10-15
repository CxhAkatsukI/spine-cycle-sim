"""Recheck a retained ABI-parser failure without changing the original run."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..search_pipeline.preparation import ROOT
from ..search_pipeline.synthesis import unchanged
from .rtl_analysis import analyze, status

STABLE = ("csim", "csim_pass", "rtl_pass", "transactions", "top_clock_ns",
          "top_resources", "target_5ns_met", "external_RTL_backpressure_tested",
          "integrated_g_admitted", "hardware_timing_admitted",
          "production_baseline_admitted", "publication_match_admitted")


def review(output: Path, attempt: Path):
    report_path = attempt / "results.json"
    report_pin = {"path": str(report_path), "sha256": sha256_file(report_path)}
    original = json.loads(report_path.read_text())
    if original["status"] != "FAILED_RETAINED" or set(original["analysis"]["errors"]) != {"abi"} or \
            not all(original["analysis"][key] for key in ("csim_pass", "rtl_pass")):
        raise ValueError("only a terminal ABI-only failure can be reviewed")
    execution = original["execution"]
    resource_path = attempt / "attempt/execution.resources.json"
    if execution != json.loads(resource_path.read_text()) or execution["exit_code"] or execution["timed_out"]:
        raise ValueError("successful unchanged HLS/RTL/export execution required")
    pins = (original["source"] + original["basis"] + [original["script"], report_pin] +
            original["analysis"]["artifacts"] +
            [{"path": row["frozen_path"], "sha256": row["sha256"]}
             for row in original["runner_source"]])
    unchanged(pins)
    output.mkdir(parents=True, exist_ok=False)
    runners = [Path(__file__), Path(__file__).with_name("abi.py"),
               Path(__file__).with_name("rtl_analysis.py"),
               ROOT / "spine_cycle_sim/experiments/campaign_runtime.py",
               ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
               *(Path(__file__).parent.parent / "search_pipeline").glob("*.py")]
    runner_pins = []
    for path in runners:
        frozen = output / "runner" / path.relative_to(ROOT)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, frozen)
        runner_pins.append({"path": str(path), "frozen_path": str(frozen), "sha256": sha256_file(frozen)})
    result = {"status": "REVIEWING_RETAINED_ABI_FAILURE", "errors": [], "original": report_pin,
              "original_status": original["status"], "runner_source": runner_pins,
              "new_hardware_execution": False, "hardware_timing_admitted": False,
              "production_baseline_admitted": False, "publication_match_admitted": False,
              "claim": "same_frozen_RTL_and_XO_reviewed_with_canonical_ABI_parser_not_new_execution"}
    save = lambda: atomic_write_json(output / "results.json", result)
    save()
    try:
        observation = analyze(attempt / "attempt", attempt / "reference")
        result["analysis"] = observation
        if any(observation[key] != original["analysis"][key] for key in STABLE):
            raise ValueError("ABI review changed a non-ABI observation")
        unchanged(pins + runner_pins)
        result["status"] = status(observation)
        if result["status"] == "FAILED_RETAINED":
            raise ValueError("corrected review still fails wrapper gates")
    except Exception as error:
        result["errors"].append(repr(error))
        result["status"] = "FAILED_RETAINED"
        save()
        raise
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, required=True)
    args = parser.parse_args()
    review(args.output.resolve(), args.attempt.resolve())
