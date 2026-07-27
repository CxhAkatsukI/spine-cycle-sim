#!/usr/bin/env python3
"""Build fail-closed evidence for the finite Spine reader working set."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


_CLOCK_RE = re.compile(
    r"\|ap_clk\s*\|\s*([0-9.]+) ns\|\s*([0-9.]+) ns\|"
)
_TOTAL_RE = re.compile(
    r"\|Total\s*\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|"
)
_CORE_RE = re.compile(r"([a-z_]+)=([^\s]+)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _summary(
    path: Path,
    *,
    expected_path: int,
    expected_cache: bool,
    expected_gate: int | None,
) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "success",
        "cycles",
        "backend_requests",
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
        "memory_locality_ledger_match",
        "reader_memory_ledger_match",
        "compute_memory_ledger_match",
        "reader_memory_requests_issued",
        "reader_memory_requests_completed",
        "reader_range_path",
        "reader_range_fallback_reason",
        "reader_range_active_records",
        "reader_edges",
        "reader_source_page_cache_hits",
        "reader_source_page_cache_misses",
        "reader_source_page_cache_fills",
        "source_page_index_cache",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"{path}: missing fields {missing}")
    if raw["success"] is not True:
        raise ValueError(f"{path}: run did not pass")
    mismatch_fields = (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    )
    if any(int(raw[name]) != 0 for name in mismatch_fields):
        raise ValueError(f"{path}: correctness gate failed")
    ledger_fields = (
        "memory_locality_ledger_match",
        "reader_memory_ledger_match",
        "compute_memory_ledger_match",
    )
    if any(raw[name] is not True for name in ledger_fields):
        raise ValueError(f"{path}: memory ledger gate failed")
    if raw["reader_memory_requests_issued"] != raw["reader_memory_requests_completed"]:
        raise ValueError(f"{path}: reader request ledger is open")
    if int(raw["reader_range_path"]) != expected_path:
        raise ValueError(f"{path}: expected reader path {expected_path}")
    if bool(raw["source_page_index_cache"]) is not expected_cache:
        raise ValueError(f"{path}: source-page cache state mismatch")
    if expected_gate is not None and int(raw.get("range_task_active_gate", -1)) != expected_gate:
        raise ValueError(f"{path}: expected active gate {expected_gate}")
    if expected_cache:
        if int(raw["reader_source_page_cache_hits"]) <= 0:
            raise ValueError(f"{path}: enabled cache had no hits")
        if int(raw["reader_source_page_cache_misses"]) <= 0:
            raise ValueError(f"{path}: enabled cache had no finite misses")
        if raw["reader_source_page_cache_misses"] != raw["reader_source_page_cache_fills"]:
            raise ValueError(f"{path}: cache miss/fill ledger is open")
    names = required | {
        "architecture_profile_id",
        "architecture_profile_sha256",
        "initial_edges",
        "input_edges",
        "vertices",
        "sst_host_wall_seconds",
        "range_task_active_gate",
        "reader_metadata_bytes",
        "reader_graph_index_bytes",
        "reader_graph_payload_bytes",
        "maintenance_cycles",
    }
    return {name: raw.get(name) for name in sorted(names)}


def _csynth(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    clock = _CLOCK_RE.search(text)
    total = _TOTAL_RE.search(text)
    if clock is None or total is None:
        raise ValueError(f"{path}: top timing or utilization summary not found")
    target_ns, estimated_ns = (float(value) for value in clock.groups())
    bram, dsp, ff, lut, uram = (int(value) for value in total.groups())
    return {
        "target_ns": target_ns,
        "estimated_ns": estimated_ns,
        "estimated_mhz": 1000.0 / estimated_ns,
        "target_met": estimated_ns <= target_ns,
        "bram_18k": bram,
        "dsp": dsp,
        "ff": ff,
        "lut": lut,
        "uram": uram,
        "sha256": _sha256(path),
    }


def _core_evidence(binary: Path) -> dict[str, object]:
    result = subprocess.run(
        [str(binary), "spine_pagerank_source_page_cache"],
        check=True,
        capture_output=True,
        text=True,
    )
    line = next(
        line for line in result.stdout.splitlines() if line.startswith("EVIDENCE ")
    )
    fields: dict[str, object] = {}
    for key, value in _CORE_RE.findall(line):
        try:
            fields[key] = int(value)
        except ValueError:
            fields[key] = value
    if fields.get("exact_ranks_equal") != 1 or fields.get("fallback_ranks_equal") != 1:
        raise ValueError("core cache A/B rank vectors differ")
    for prefix in ("exact", "fallback"):
        if int(fields[f"{prefix}_hits"]) <= 0 or int(fields[f"{prefix}_misses"]) < 2:
            raise ValueError(f"core {prefix} cache did not demonstrate finite replacement")
    return fields


def _ratio(parent: int, optimized: int) -> dict[str, float]:
    return {
        "speedup": parent / optimized,
        "reduction_percent": 100.0 * (parent - optimized) / parent,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-parent", type=Path, required=True)
    parser.add_argument("--exact-cache", type=Path, required=True)
    parser.add_argument("--fallback-parent", type=Path, required=True)
    parser.add_argument("--fallback-cache", type=Path, required=True)
    parser.add_argument("--large-parent", type=Path, required=True)
    parser.add_argument("--large-gate", type=Path, required=True)
    parser.add_argument("--large-combined", type=Path, required=True)
    parser.add_argument("--parent-csynth", type=Path, required=True)
    parser.add_argument("--optimized-csynth", type=Path, required=True)
    parser.add_argument("--optimized-csynth-log", type=Path, required=True)
    parser.add_argument("--core-test-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    exact_parent = _summary(
        args.exact_parent, expected_path=1, expected_cache=False, expected_gate=32768
    )
    exact_cache = _summary(
        args.exact_cache, expected_path=1, expected_cache=True, expected_gate=32768
    )
    fallback_parent = _summary(
        args.fallback_parent, expected_path=2, expected_cache=False, expected_gate=127
    )
    fallback_cache = _summary(
        args.fallback_cache, expected_path=2, expected_cache=True, expected_gate=127
    )
    # The parent large run predates explicit effective-gate provenance in the
    # runner. Path 2 plus 19,058 active records proves the native 16,384 gate
    # was crossed; the two new rows must self-report their 32,768 gate.
    large_parent = _summary(
        args.large_parent, expected_path=2, expected_cache=False, expected_gate=None
    )
    large_gate = _summary(
        args.large_gate, expected_path=1, expected_cache=False, expected_gate=32768
    )
    large_combined = _summary(
        args.large_combined, expected_path=1, expected_cache=True, expected_gate=32768
    )
    for left, right, name in (
        (exact_parent, exact_cache, "exact cache A/B"),
        (fallback_parent, fallback_cache, "fallback cache A/B"),
        (large_parent, large_gate, "large gate A/B"),
        (large_gate, large_combined, "large cache A/B"),
    ):
        if left["reader_edges"] != right["reader_edges"]:
            raise ValueError(f"{name}: emitted edge counts differ")
        if left["initial_edges"] != right["initial_edges"]:
            raise ValueError(f"{name}: initial edge counts differ")

    parent_csynth = _csynth(args.parent_csynth)
    optimized_csynth = _csynth(args.optimized_csynth)
    csynth_log = args.optimized_csynth_log.read_text(encoding="utf-8")
    burst_evidence = (
        "Multiple burst reads of length 4 and bit width 64 in loop "
        "'PARTITIONED_SOURCE_PAGE_CACHE_FILL_BITMAP'"
    )
    if burst_evidence not in csynth_log:
        raise ValueError("csynth did not infer the required length-4 bitmap burst")

    output = {
        "schema_version": 1,
        "optimization": "finite_reader_source_page_working_set",
        "claims": {
            "exact_source_page_cache_cycles": _ratio(
                int(exact_parent["cycles"]), int(exact_cache["cycles"])
            ),
            "fallback_source_page_cache_cycles": _ratio(
                int(fallback_parent["cycles"]), int(fallback_cache["cycles"])
            ),
            "large_gate_cycles": _ratio(
                int(large_parent["cycles"]), int(large_gate["cycles"])
            ),
            "large_combined_cycles": _ratio(
                int(large_parent["cycles"]), int(large_combined["cycles"])
            ),
            "all_correctness_and_ledgers_pass": True,
            "hls_length4_bitmap_burst_inferred": True,
            "csynth_target_met": bool(optimized_csynth["target_met"]),
        },
        "core_microbenchmark": _core_evidence(args.core_test_bin),
        "sst_compact_exact": {"parent": exact_parent, "cached": exact_cache},
        "sst_compact_fallback": {
            "parent": fallback_parent,
            "cached": fallback_cache,
        },
        "sst_large_full_pagerank": {
            "native_gate_parent": large_parent,
            "expanded_gate": large_gate,
            "expanded_gate_and_cache": large_combined,
        },
        "hls_csynth": {
            "parent": parent_csynth,
            "optimized": optimized_csynth,
            "delta": {
                name: int(optimized_csynth[name]) - int(parent_csynth[name])
                for name in ("bram_18k", "dsp", "ff", "lut", "uram")
            },
            "length4_bitmap_burst_inferred": True,
            "log_sha256": _sha256(args.optimized_csynth_log),
        },
        "input_sha256": {
            name: _sha256(path)
            for name, path in (
                ("exact_parent", args.exact_parent),
                ("exact_cache", args.exact_cache),
                ("fallback_parent", args.fallback_parent),
                ("fallback_cache", args.fallback_cache),
                ("large_parent", args.large_parent),
                ("large_gate", args.large_gate),
                ("large_combined", args.large_combined),
            )
        },
        "limitations": [
            "The native-gate large parent predates explicit effective-gate output; its path-2 result with 19058 active records is tied to the frozen 16384-gate runner revision.",
            "Focused csynth is a resource and pre-route timing gate, not integrated placement-and-route timing closure.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(output["claims"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
