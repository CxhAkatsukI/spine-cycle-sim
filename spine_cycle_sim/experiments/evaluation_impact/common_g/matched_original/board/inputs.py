"""Require the reviewed Release/UBSan host and independent original capture."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.execution import inputs as original_inputs
from ...search_pipeline.synthesis import unchanged
from .. import analysis

PREFLIGHT_SHA256 = "67bdac62a571202901363a612e7868b55d09e3d7d911cb30b5f8b53ddb44d58e"


def load(preflight, original_preflight):
    pin = identity(preflight / "results.json")
    report = json.loads((preflight / "results.json").read_text())
    _, cases, original_pins = original_inputs(original_preflight)
    if pin["sha256"] != PREFLIGHT_SHA256 or report.get("status") != analysis.STATUS or report.get("errors") != [] or \
            any(report.get(flag) is not False for flag in analysis.CLAIMS) or \
            report.get("original_preflight") != identity(original_preflight / "results.json") or \
            len(report.get("steps", [])) != 22 or len(report.get("cases", [])) != 2 * len(cases):
        raise ValueError("reviewed matched-G no-device host prerequisite required")
    observed = report["cases"]
    expected = [{"variant": variant, "id": case["id"], **analysis.expected(case)}
                for variant in ("release", "ubsan") for case in cases]
    if json.dumps(observed, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("matched-G model matrix differs from original capture")
    binaries = [row for row in report["binaries"] if row["variant"] == "release"]
    if len(binaries) != 1:
        raise ValueError("one real-XRT Release host required")
    binary = binaries[0]
    pins = [pin, *original_pins, *report["pins"], *report["runtime_libraries"],
            {key: binary[key] for key in ("path", "sha256")}]
    unchanged(pins)
    return Path(binary["path"]), cases, pins
