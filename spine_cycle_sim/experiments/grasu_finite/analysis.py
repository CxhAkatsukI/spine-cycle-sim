"""Validate all state, per-lane memory requests and conserved finite ledgers."""

import csv
import hashlib
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..upstream_controls.grasu.fixtures import HALF, HOT, SEGMENTS, batches, final_state, request_rows, route
from ..upstream_controls.grasu.analysis import unique_fields


def analyze(capture: Path, case: int, stdout: Path, stderr: Path):
    if stderr.read_text():
        raise ValueError("finite G emitted diagnostics")
    prefix = "G_FINITE_RESULT "
    lines = stdout.read_text().splitlines()
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise ValueError("finite G missing unique structured result")
    result = json.loads(lines[0][len(prefix):], object_pairs_hook=unique_fields)
    if result["status"] != "SOURCE16_STATE_AND_FINITE_LEDGER_PASS" or result["timing_kind"] != "declared_prediction":
        raise ValueError("finite G evidence status")
    updates = sum(map(len, batches(case)))
    expected_requests = []
    for batch, items in enumerate(batches(case)):
        expected_requests.extend((batch, *row) for row in request_rows(items))
    with (capture / "search.tsv").open() as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["batch", "kernel", "lane", "kind", "address", "value"]:
            raise ValueError("finite G search schema")
        rows = [tuple(int(row[name]) for name in reader.fieldnames) for row in reader]
    # Preserve within-lane order; only asynchronous lanes may interleave.
    normalize = lambda rows: sorted(rows, key=lambda row: row[:3])
    if normalize(rows) != normalize(expected_requests):
        raise ValueError("finite G per-lane request sequence differs from original source")
    oracle = final_state(case)
    if (capture / "merged.u32le").read_bytes() != oracle:
        raise ValueError("finite G full merged state differs from independent oracle")
    counts = [0] * 4
    for batch in batches(case):
        for item in batch:
            counts[route(item[0])] += 1
    fixed = len(batches(case)) * 2 * HOT * 64
    cold = counts[1] + counts[3]
    expected = {"batches": len(batches(case)), "updates": updates, "cache_updates": updates - cold,
        "ddr_updates": cold, "search_reads": len(expected_requests),
        "read_bytes": fixed + updates * 8 + len(expected_requests) * 8 + cold * 64, "write_bytes": fixed + cold * 64}
    if any(type(result[key]) is not int or result[key] != value for key, value in expected.items()):
        raise ValueError("finite G independent payload/count ledger differs")
    if result["parents"] != result["completed"] or result["beats"] != result["finished_beats"]:
        raise ValueError("finite G transaction conservation")
    if len(result["predicted_cycles"]) != len(batches(case)) or any(type(value) is not int or value <= 0 for value in result["predicted_cycles"]):
        raise ValueError("finite G cycle extent")
    if len(result["component_done_windows"]) != len(batches(case)):
        raise ValueError("finite G window extent")
    for cycle, windows in zip(result["predicted_cycles"], result["component_done_windows"]):
        if len(windows) != 10 or any(type(value) is not int or not 0 < value <= cycle for value in windows):
            raise ValueError("finite G incomplete/invalid component windows")
    initial = final_state(0)
    for bank in range(4):
        path = capture / f"bank{bank}.bin"
        actual = path.read_bytes()
        if len(actual) != HALF * 64 + 64 or actual[-64:] != b"\xa5" * 64:
            raise ValueError("finite G full buffer extent/guard")
        for index in range(HALF):
            global_index = index * 2 + bank // 2
            owner = (global_index & 1) * 2 + int(index >= HOT)
            expected = oracle if bank == owner else initial
            if actual[index * 64:(index + 1) * 64] != expected[global_index * 64:(global_index + 1) * 64]:
                raise ValueError("finite G complete physical buffer mismatch")
    with (capture / "ports.tsv").open() as stream:
        ports = list(csv.DictReader(stream, delimiter="\t"))
    if len(ports) != 46:
        raise ValueError("finite G requires 36 search and 10 PMA AXI ports")
    for index, row in enumerate(ports):
        if any(not value.isdecimal() for value in row.values()):
            raise ValueError("finite G port counters must be unsigned integers")
        port = {key: int(value) for key, value in row.items()}
        bank = index // 9 if index < 36 else (index - 36) // 5 * 2 + int((index - 36) % 5 != 0)
        if port["initiator"] != index + 1 or port["bank"] != bank or port["width"] != (8 if index < 36 else 64):
            raise ValueError("finite G original bank/AXI-width mapping differs")
        if port["parents"] != port["completed"] or port["beats"] != port["finished_beats"]:
            raise ValueError("finite G per-port transaction conservation")
    for key, field in (("reads", "read_bytes"), ("writes", "write_bytes"), ("parents", "parents"),
                       ("completed", "completed"), ("beats", "beats"), ("finished_beats", "finished_beats"),
                       ("backend_stalls", "backend_stalls")):
        if sum(int(port[key]) for port in ports) != result[field]:
            raise ValueError("finite G port aggregate differs")
    if result["fpga_timing_match"] is not None or result["publication_timing_match"] is not None:
        raise ValueError("finite prediction cannot claim hardware timing admission")
    files = [{"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
             for path in sorted(capture.iterdir())]
    return {**result, "case": case, "checked_buffer_slots": len(batches(case)) * HALF * 4 * 16,
            "oracle_state_sha256": hashlib.sha256(oracle).hexdigest(), "files": files}


def equivalent(first, second):
    """All observed numerical fields and captures must agree, not just total time."""
    if first != second:
        raise ValueError("finite G exact repeated/registration-order observations differ")
