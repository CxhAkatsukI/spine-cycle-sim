"""Recompute cross-row admission from portable raw evidence."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...empty_segment.production import PLATFORM, require_report
from ..evidence import bounded, rtl, sources
from .study import compile_command
from .validation import BASE_SHA, CLAIM, FLAGS, REFERENCE_SHA, STATUS
from .validation import compare, require_functional, require_xos
from ..validation import require_functional as require_legacy


def recheck(run):
    manifest = json.loads((run / "manifest.json").read_text())
    stored = json.loads((run / "results.json").read_text())
    if ((run / "failure.json").exists() or stored["status"] != STATUS or manifest["claim"] != CLAIM
            or manifest["flags"] != FLAGS or stored["simulator_modified"] is not False
            or stored["FPGA_timing_admitted"] is not False):
        raise ValueError("cross-row admission differs")
    copies = sources(run, manifest, ("v++", PLATFORM.name, "xvlog", "xelab", "xsim"))
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    for key, digest in (("reference", REFERENCE_SHA), ("base", BASE_SHA)):
        if pins.get(manifest[key]["path"]) != manifest[key] or manifest[key]["sha256"] != digest:
            raise ValueError("immutable reference not pinned")
    candidate = run / "production/adapter.hw.xo"
    if sha256_file(candidate) != stored["xo"]["sha256"]:
        raise ValueError("candidate XO differs")
    contract = require_xos(copies[manifest["reference"]["path"]], candidate)
    hls = require_report(run / "production")
    for key in ("report", "burst_report"):
        if hls[key]["sha256"] != stored["hls"][key]["sha256"]:
            raise ValueError("production report differs")
    if (contract != stored["contract"] or {k: v for k, v in hls.items() if k not in ("report", "burst_report")}
            != {k: v for k, v in stored["hls"].items() if k not in ("report", "burst_report")}):
        raise ValueError("stored ABI/HLS analysis differs")
    output = Path(stored["xo"]["path"]).parent.parent
    integration = Path(manifest["integration"])
    for step, script in (("legacy", "check_pma_to_regraph_adapter.sh"),
                         ("functional", "check_pma_adapter_cross_row.sh")):
        command = ["bash", "scripts/" + script, "--out-dir", str(output / step)]
        bounded(run / f"{step}.resources.json", command, str(integration), 240, 3)
    require_legacy((run / "legacy/test.log").read_text())
    require_functional((run / "functional.stdout.txt").read_text())
    command = compile_command(integration, output / "production")
    if json.loads((run / "production/command.json").read_text()) != command:
        raise ValueError("production compile command differs")
    bounded(run / "production/compile.resources.json", command, str(output / "production"), 1200, 8)
    arms = {arm: rtl(run, arm, pin, copies, manifest["tools"]) for arm, pin in (
        ("reference", manifest["reference"]), ("candidate", stored["xo"]))}
    comparison = compare(arms["reference"], arms["candidate"],
                         json.loads(copies[manifest["base"]["path"]].read_text()))
    if arms != stored["arms"] or comparison != stored["comparison"]:
        raise ValueError("raw AXI traces differ from stored analysis")
    return stored
