"""Read every search/route capture field and all merged PMA slots independently."""

import hashlib
import json
import struct
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from .fixtures import HALF, HOT, SEGMENTS, batches, edge, final_state, request_rows, route

STATUS = "GRASU_SOURCE16_KERNEL_COMPOSITION_PASS_NOT_TIMING"
WIDTH_WARNING = ("WARNING: Bitsize mismatch for ap_[u]int|=ap_[u]int.\n"
                 "Warning! Bitsize mismach for ap_[u]int |= ap_[u]int.\n")


def check_diagnostics(text: str, case: int):
    # Unmodified source ORs a 32-bit inserted edge into a 512-bit word.
    insertions = sum(not item[2] for batch in batches(case) for item in batch)
    if text != WIDTH_WARNING * insertions: raise ValueError("G source emitted unexpected runtime diagnostics")
    return insertions * 2


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate G result field")
        result[key] = value
    return result


def check_protocol(payload: bytes, case: int) -> dict:
    if len(payload) % 4 or len(payload) > 8 * 1024**2: raise ValueError("G protocol extent invalid")
    words = struct.unpack(f"<{len(payload) // 4}I", payload); position = 0

    def take(count):
        nonlocal position
        row = words[position:position + count]; position += count
        if len(row) != count: raise ValueError("G protocol truncated")
        return row

    expected_batches = batches(case)
    if take(6) != (0x47535031, 1, case, len(expected_batches), SEGMENTS, HOT): raise ValueError("G protocol header mismatch")
    counts = [0] * 4; total_requests = total_updates = 0; logical_read_bytes = 0
    for index, updates in enumerate(expected_batches):
        expected_requests = request_rows(updates)
        if take(3) != (index, len(updates), len(expected_requests)): raise ValueError("G batch geometry mismatch")
        for item in updates:
            value = edge(item); buffer = route(item[0]); counts[buffer] += 1
            if take(6) != (value & 0xffffffff, value >> 32, item[0] * 16, value & 0xffffffff, value >> 32, buffer):
                raise ValueError("G search packet/dispatch route mismatch")
        for kernel, lane, kind, address, value in expected_requests:
            if take(6) != (kernel, lane, kind, address, value & 0xffffffff, value >> 32): raise ValueError("G memory request mismatch")
        total_updates += len(updates); total_requests += len(expected_requests); logical_read_bytes += len(expected_requests) * 8
    if position != len(words): raise ValueError("G protocol trailing records")
    count = len(expected_batches)
    return {"case": case, "batches": count, "updates": total_updates, "memory_requests": total_requests,
        "route_updates": counts, "checked_buffer_slots": count * HALF * 4 * 16,
        "search_lane_end_checks": count * 4 * 64 * 2, "cache_invocations": count * 2, "ddr_invocations": count * 2,
        "source_loop_cache_read_bytes": count * 2 * HOT * 64, "source_loop_cache_write_bytes": count * 2 * HOT * 64,
        "source_access_ddr_read_bytes": (counts[1] + counts[3]) * 64,
        "source_access_ddr_write_bytes": (counts[1] + counts[3]) * 64,
        "logical_search_read_bytes": logical_read_bytes, "logical_update_input_bytes": total_updates * 8}


def parse_stdout(text: str, expected: dict) -> None:
    lines = text.splitlines(); prefix = "GRASU_PATH "
    records = [line for line in lines if line.startswith(prefix)]
    if len(records) != 1 or [line for line in lines if line != "dispatch finish" and not line.startswith(prefix)]:
        raise ValueError("unexpected G source stdout/stream warning")
    if lines.count("dispatch finish") != expected["batches"]: raise ValueError("G dispatch invocation count mismatch")
    observed = json.loads(records[0][len(prefix):], object_pairs_hook=unique_fields)
    selected = {name: expected[name] for name in ("case", "batches", "updates", "memory_requests", "route_updates",
        "checked_buffer_slots", "search_lane_end_checks", "cache_invocations", "ddr_invocations")}
    # JSON booleans are not accepted as integer counters.
    if json.dumps(observed, sort_keys=True) != json.dumps(selected, sort_keys=True): raise ValueError("G observed counters mismatch")


def analyze(directory: Path, case: int, stdout: Path, stderr: Path) -> dict:
    known_diagnostics = check_diagnostics(stderr.read_text(), case)
    protocol = directory / "protocol.u32le"; state = directory / "state.u32le"
    if protocol.stat().st_size > 8 * 1024**2 or state.stat().st_size != SEGMENTS * 16 * 4: raise ValueError("G capture file extent invalid")
    result = check_protocol(protocol.read_bytes(), case); parse_stdout(stdout.read_text(), result)
    expected = final_state(case)
    if state.read_bytes() != expected: raise ValueError("G merged full-state mismatch")
    return {**result, "known_source_width_warning_lines": known_diagnostics,
        "protocol_sha256": sha256_file(protocol), "protocol_bytes": protocol.stat().st_size,
        "state_sha256": sha256_file(state), "state_bytes": state.stat().st_size,
        "oracle_state_sha256": hashlib.sha256(expected).hexdigest(), "device_cycles": None, "publication_error_pct": None}
