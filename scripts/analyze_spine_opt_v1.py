#!/usr/bin/env python3
"""Build fail-closed evidence for the Spine opt-v1 fallback cache A/B."""

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


def _summary(path: Path) -> dict[str, object]:
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
        "reader_range_path",
        "reader_range_fallback_reason",
        "reader_fallback_level_cache_reuses",
        "reader_fallback_level_cache_empty_skips",
        "reader_metadata_bytes",
        "reader_memory_requests_issued",
        "reader_memory_requests_completed",
        "reader_edges",
        "reader_tiles",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise ValueError(f"{path}: missing fields {missing}")
    if not raw["success"]:
        raise ValueError(f"{path}: run did not pass")
    if any(
        raw[name] != 0
        for name in (
            "correctness_mismatches",
            "architecture_correctness_mismatches",
            "mathematical_correctness_mismatches",
        )
    ):
        raise ValueError(f"{path}: correctness gate failed")
    if not raw["memory_locality_ledger_match"] or not raw["reader_memory_ledger_match"]:
        raise ValueError(f"{path}: memory ledger gate failed")
    if raw["reader_memory_requests_issued"] != raw["reader_memory_requests_completed"]:
        raise ValueError(f"{path}: reader request ledger is open")
    names = sorted(required | {"vertices", "initial_edges", "sst_host_wall_seconds"})
    return {name: raw.get(name) for name in names}


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


def _core_evidence(binary: Path | None) -> dict[str, object] | None:
    if binary is None:
        return None
    result = subprocess.run(
        [str(binary), "spine_pagerank_fallback_level_cache_reuse"],
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
    if fields.get("ranks_equal") != 1:
        raise ValueError("core A/B rank vectors differ")
    return fields


def _ratio(baseline: int, optimized: int) -> dict[str, float]:
    return {
        "speedup": baseline / optimized,
        "reduction_percent": 100.0 * (baseline - optimized) / baseline,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fallback-baseline", type=Path, required=True)
    parser.add_argument("--fallback-optimized", type=Path, required=True)
    parser.add_argument("--control-baseline", type=Path, required=True)
    parser.add_argument("--control-optimized", type=Path, required=True)
    parser.add_argument("--baseline-csynth", type=Path, required=True)
    parser.add_argument("--optimized-csynth", type=Path, required=True)
    parser.add_argument("--core-test-bin", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fallback_base = _summary(args.fallback_baseline)
    fallback_opt = _summary(args.fallback_optimized)
    control_base = _summary(args.control_baseline)
    control_opt = _summary(args.control_optimized)
    if fallback_base["reader_range_path"] != 2 or fallback_opt["reader_range_path"] != 2:
        raise ValueError("fallback A/B did not exercise range path 2")
    if control_base["reader_range_path"] != 1 or control_opt["reader_range_path"] != 1:
        raise ValueError("control A/B did not exercise exact range path 1")
    if fallback_base["reader_edges"] != fallback_opt["reader_edges"]:
        raise ValueError("fallback A/B emitted different edge counts")
    if control_base["cycles"] != control_opt["cycles"]:
        raise ValueError("non-fallback control is not cycle-identical")
    if control_base["backend_requests"] != control_opt["backend_requests"]:
        raise ValueError("non-fallback control changed backend requests")

    baseline_csynth = _csynth(args.baseline_csynth)
    optimized_csynth = _csynth(args.optimized_csynth)
    output = {
        "schema_version": 1,
        "optimization": "fallback_launch_level_cache_reuse",
        "claims": {
            "fallback_cycle": _ratio(
                int(fallback_base["cycles"]), int(fallback_opt["cycles"])
            ),
            "fallback_backend_requests": _ratio(
                int(fallback_base["backend_requests"]),
                int(fallback_opt["backend_requests"]),
            ),
            "fallback_reader_metadata_bytes": _ratio(
                int(fallback_base["reader_metadata_bytes"]),
                int(fallback_opt["reader_metadata_bytes"]),
            ),
            "non_fallback_cycle_identical": True,
            "all_correctness_and_ledgers_pass": True,
            "csynth_target_met": bool(optimized_csynth["target_met"]),
        },
        "core_microbenchmark": _core_evidence(args.core_test_bin),
        "sst_fallback_ab": {"baseline": fallback_base, "optimized": fallback_opt},
        "sst_non_fallback_control": {
            "baseline": control_base,
            "optimized": control_opt,
        },
        "hls_csynth": {
            "baseline": baseline_csynth,
            "optimized": optimized_csynth,
            "delta": {
                name: int(optimized_csynth[name]) - int(baseline_csynth[name])
                for name in ("bram_18k", "dsp", "ff", "lut", "uram")
            },
        },
        "input_sha256": {
            "fallback_baseline": _sha256(args.fallback_baseline),
            "fallback_optimized": _sha256(args.fallback_optimized),
            "control_baseline": _sha256(args.control_baseline),
            "control_optimized": _sha256(args.control_optimized),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output["claims"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
