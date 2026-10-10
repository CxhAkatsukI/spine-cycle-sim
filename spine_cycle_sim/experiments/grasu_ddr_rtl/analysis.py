"""Separate source agreement, shared-bus protocol gates, and RTL state mismatches."""

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..upstream_controls.grasu.analysis import WIDTH_WARNING, unique_fields
from .fixtures import read_hex, updates
from .trace import validate

STATUS = "G_DDR_SOURCE_RTL_STATE_PASS_UNDER_DECLARED_MEMORY"
MISMATCH = "G_DDR_SOURCE_RTL_STATE_MISMATCH_NOT_ADMITTED"


def source(stdout: str, stderr: str, directory: Path, case):
    items = updates(case["sequence"])
    if stderr != WIDTH_WARNING * sum(not item[2] for item in items):
        raise ValueError("original DDR source emitted unexpected diagnostics")
    lines = stdout.splitlines()
    if len(lines) != 1 or not lines[0].startswith("G_DDR_SOURCE "):
        raise ValueError("original DDR source result missing")
    row = json.loads(lines[0].removeprefix("G_DDR_SOURCE "), object_pairs_hook=unique_fields)
    if json.dumps(row, sort_keys=True) != json.dumps({"passed": True, "updates": len(items), "all_prefix_and_end_guards_unchanged": True}, sort_keys=True):
        raise ValueError("original DDR source extent/guard gate differs")
    observed = directory / "source.u32le"
    if observed.read_bytes() != (directory / "expected.u32le").read_bytes():
        raise ValueError("original DDR C++ source differs from independent oracle")
    return {"status": "ORIGINAL_SOURCE_COMPLETE_STATE_PASS", "bytes": observed.stat().st_size, "sha256": sha256_file(observed)}


def rtl(stdout: str, stderr: str, capture: Path, fixture: Path, case, contract):
    if stderr or re.search(r"(?:FATAL|ERROR|WARNING|Error:|Fatal:)", stdout):
        raise ValueError("RTL simulation diagnostics are not admitted")
    records = [line.removeprefix("DDR_RTL_RESULT ") for line in stdout.splitlines() if line.startswith("DDR_RTL_RESULT ")]
    if len(records) != 1:
        raise ValueError("original DDR RTL result missing or duplicated")
    row = json.loads(records[0], object_pairs_hook=unique_fields)
    count = len(updates(case["sequence"]))
    fields = {"protocol_passed", "updates", "reads", "writes", "read_acks", "write_acks", "start_cycle", "done_cycle", "drained_cycle"}
    if set(row) != fields or row.get("protocol_passed") is not True or any(type(value) is not int or value < 0 for key, value in row.items() if key != "protocol_passed"):
        raise ValueError("original DDR RTL counter type/protocol gate failed")
    if any(row.get(key) != count for key in ("updates", "reads", "writes", "read_acks", "write_acks")) or not 0 <= row["start_cycle"] < row["done_cycle"] <= row["drained_cycle"] <= contract["max_cycles"]:
        raise ValueError("original DDR RTL event window or conservation differs")
    events, inputs, hazards = validate(stdout, row, case, contract)
    last_ack = max((event["cycle"] for event in events if event["operation"] in ("RACK", "BACK")), default=row["done_cycle"])
    if row["drained_cycle"] - max(row["done_cycle"], last_ack) != contract["capture_settle_cycles"]:
        raise ValueError("DDR capture-settling interval changed")
    actual = read_hex(capture); expected = (fixture / "expected.u32le").read_bytes()
    mismatches = [index for index in range(512) if actual[index*4:index*4+4] != expected[index*4:index*4+4]]
    return {"status": STATUS if not mismatches else MISMATCH, "result": row, "events": events, "inputs": inputs,
        "state_sha256": sha256_file(capture), "state_bytes": len(actual), "mismatched_words": mismatches,
        "same_line_reads_before_prior_write": hazards, "cycles": row["drained_cycle"] - row["start_cycle"],
        "kernel_cycles": row["done_cycle"] - row["start_cycle"], "capture_settle_cycles": contract["capture_settle_cycles"],
        "FPGA_measured_cycles": None, "publication_rate_error_pct": None}


def bus(stdout, stderr, control):
    if stderr or "Abnormal program termination" in stdout:
        raise ValueError("bus control emitted stderr")
    marker = "DDR_BUS_SELFTEST_PASS alias=1 delayed_pairing=1 stable_responses=1 finite_backpressure=1 one_service=1 reads=20 writes=2"
    if control["rejection"] is None:
        if stdout.splitlines().count(marker) != 1 or re.search(r"(?:FATAL|ERROR|WARNING|Error:|Fatal:)", stdout):
            raise ValueError("shared-memory selftest did not pass")
        return {"status": "SHARED_MEMORY_SELFTEST_PASS"}
    if marker in stdout or control["rejection"] not in stdout or not re.search(r"(?:FATAL|Fatal:)", stdout):
        raise ValueError("bus invalid request was not rejected for the declared reason")
    return {"status": "EXPECTED_BUS_REJECTION", "reason": control["rejection"]}
