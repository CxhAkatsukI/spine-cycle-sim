"""Whole original-host/kernel functional admission with exact known diagnostics."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..analysis import WIDTH_WARNING, unique_fields
from .layout import verify as verify_layout
from .protocol import verify as verify_protocol

STATUS = "GRASU_HOST_TWO_GUARDS_DEFINED_PADDING_FUNCTIONAL_PASS_NOT_TIMING"
CAPTURES = ("mapping.u32le", "row_offsets.u64le", "binary.u64le", "prepared.u64le", "mapped_initial.u64le", "mapped_updates.u64le", "updated.u64le", "protocol.u32le")


def analyze(input_path: Path, directory: Path, stdout: Path, stderr: Path):
    facts, binary, offsets, updates, insertions = verify_layout(input_path, directory)
    facts["memory_requests"] = verify_protocol((directory / "protocol.u32le").read_bytes(), binary, offsets, updates)
    if stderr.read_text() != WIDTH_WARNING * insertions: raise ValueError("G host unexpected runtime diagnostics")
    lines = stdout.read_text().splitlines(); records = [line for line in lines if line.startswith("GRASU_HOST ")]
    expected = [f"node_num: {facts['vertices']}", f"static_edge_num: {facts['initial_edges']}", f"update_edge_num: {facts['updates']}",
        f"update_edge_size is {facts['updates']}", "read graph file finish", "dispatch finish"]
    if len(records) != 1 or [line for line in lines if not line.startswith("GRASU_HOST ")] != expected: raise ValueError("G host stdout/stream diagnostics")
    observed = json.loads(records[0][len("GRASU_HOST "):], object_pairs_hook=unique_fields)
    if json.dumps(observed, sort_keys=True) != json.dumps(facts, sort_keys=True): raise ValueError("G host observed counters mismatch")
    return {**facts, "captures": [{"name": name, "bytes": (directory / name).stat().st_size,
        "sha256": sha256_file(directory / name)} for name in CAPTURES], "known_width_warning_lines": insertions * 2,
        "source_loop_cache_read_bytes": 16777216, "source_loop_cache_write_bytes": 16777216,
        "logical_DDR_read_bytes": (facts["route_updates"][1] + facts["route_updates"][3]) * 64,
        "logical_DDR_write_bytes": (facts["route_updates"][1] + facts["route_updates"][3]) * 64,
        "device_cycles": None, "publication_error_pct": None}
