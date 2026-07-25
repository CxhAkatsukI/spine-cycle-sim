#!/usr/bin/env python3
"""Compare a native GraSU/ReGraph SST run with the routed FPGA event log."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


KEY_VALUE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fields(line: str) -> dict[str, str]:
    return dict(KEY_VALUE_RE.findall(line))


def parse_hardware_log(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {"superstep_events": []}
    for line in text.splitlines():
        if line.startswith("PURE_PIPELINE_INPUT "):
            parsed["input"] = {
                key: int(value) for key, value in _fields(line).items()
            }
        elif line.startswith("PURE_PIPELINE_SUPERSTEP "):
            values = _fields(line)
            parsed["superstep_events"].append(
                {
                    "step": int(values["step"]),
                    "lksg_ms": float(values["lksg_ms"]),
                    "apply_ms": float(values["apply_ms"]),
                    "hbm_ms": float(values["hbm_ms"]),
                }
            )
        elif line.startswith("PURE_PIPELINE_TIMING "):
            parsed["timing_ms"] = {
                key.removesuffix("_ms"): float(value)
                for key, value in _fields(line).items()
                if key.endswith("_ms")
            }
        elif line.startswith("PURE_PIPELINE_RESULT "):
            values = _fields(line)
            parsed["result"] = {
                key: value if key == "status" else int(value)
                for key, value in values.items()
            }

    required = ("input", "timing_ms", "result")
    missing = [key for key in required if key not in parsed]
    if missing:
        raise ValueError(f"hardware log is missing {', '.join(missing)}")
    if parsed["result"]["status"] != "PASS":
        raise ValueError("hardware log does not report PASS")
    return parsed


def _comparison(hardware: int, simulation: int) -> dict[str, Any]:
    return {
        "hardware": hardware,
        "simulation": simulation,
        "match": hardware == simulation,
    }


def _timing_comparison(hardware_ms: float, cycles: int, mhz: float) -> dict[str, Any]:
    simulation_ms = cycles / (mhz * 1000.0)
    signed_error_pct = (simulation_ms - hardware_ms) / hardware_ms * 100.0
    return {
        "hardware_ms": hardware_ms,
        "simulation_cycles": cycles,
        "simulation_ms": simulation_ms,
        "simulation_over_hardware": simulation_ms / hardware_ms,
        "signed_error_pct": signed_error_pct,
        "absolute_error_pct": abs(signed_error_pct),
    }


def analyze(
    simulation: dict[str, Any], hardware: dict[str, Any], kernel_mhz: float
) -> dict[str, Any]:
    if simulation.get("success") is not True:
        raise ValueError("simulation result does not report success")
    if simulation.get("mode") != "grasu_regraph_native_sssp":
        raise ValueError("simulation result is not the native SSSP mode")

    hw_input = hardware["input"]
    hw_result = hardware["result"]
    hw_timing = hardware["timing_ms"]
    structural = {
        "vertices": _comparison(hw_input["vertices"], simulation["vertices"]),
        "source_external": _comparison(
            hw_input["source_external"], simulation["source_external"]
        ),
        "source_internal": _comparison(
            hw_input["source_internal"], simulation["source_internal"]
        ),
        "native_host_vertex_reorder": _comparison(
            1, int(simulation.get("native_host_vertex_reorder") is True)
        ),
        "initial_edges": _comparison(
            hw_input["static_edges"], simulation["initial_edges"]
        ),
        "updates": _comparison(hw_input["update_edges"], simulation["updates"]),
        "final_edges": _comparison(
            hw_input["final_edges"], simulation["final_edges"]
        ),
        "pma_slots": _comparison(hw_input["pma_slots"], simulation["pma_slots"]),
        "compact_edge_slots": _comparison(
            hw_input["compact_edge_slots"], simulation["compact_edge_slots"]
        ),
        "supersteps": _comparison(
            hw_input["supersteps"], simulation["supersteps"]
        ),
        "pma_slots_scanned_once": _comparison(
            hw_result["pma_scan_slots_once"],
            simulation["compactor_pma_slots_scanned"],
        ),
        "edge_slots_per_superstep": _comparison(
            hw_result["processed_edge_slots_per_superstep"],
            simulation["edge_array_slots_scanned"] // simulation["supersteps"],
        ),
        "correctness_mismatches": _comparison(
            hw_result["mismatches"], simulation["correctness_mismatches"]
        ),
    }
    structure_matches = all(item["match"] for item in structural.values())

    conversion_hardware_ms = hw_timing["barrier"] + hw_timing["pma_compact"]
    timing = {
        "update": _timing_comparison(
            hw_timing["grasu"], simulation["update_cycles"], kernel_mhz
        ),
        "conversion": _timing_comparison(
            conversion_hardware_ms, simulation["conversion_cycles"], kernel_mhz
        ),
        # hbm_ms is the union span of the concurrent ReGraph CUs per superstep.
        "compute_span": _timing_comparison(
            hw_timing["hbm"], simulation["compute_cycles"], kernel_mhz
        ),
        "event_e2e": _timing_comparison(
            hw_timing["event_e2e"], simulation["cycles"], kernel_mhz
        ),
    }
    return {
        "schema_version": 1,
        "claim_class": "native_hardware_alignment",
        "structural_claim": "hardware_aligned" if structure_matches else "mismatch",
        "timing_claim": "trend_only_not_cycle_calibrated",
        "kernel_clock_mhz": kernel_mhz,
        "structure_matches": structure_matches,
        "structural_checks": structural,
        "timing": timing,
        "limitations": [
            "FPGA values are OpenCL event windows, not on-kernel cycle counters.",
            "The simulator does not include PCIe launch or host scheduling time.",
            "One workload cannot establish timing calibration or transferability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim-result", type=Path, required=True)
    parser.add_argument("--hardware-log", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    simulation = json.loads(args.sim_result.read_text(encoding="utf-8"))
    hardware = parse_hardware_log(args.hardware_log.read_text(encoding="utf-8"))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    kernel_clock = next(
        clock for clock in profile["clocks"] if clock["name"] == "kernel"
    )
    report = analyze(simulation, hardware, float(kernel_clock["achieved_mhz"]))
    report["inputs"] = {
        "simulation_result": str(args.sim_result.resolve()),
        "simulation_result_sha256": sha256(args.sim_result),
        "hardware_log": str(args.hardware_log.resolve()),
        "hardware_log_sha256": sha256(args.hardware_log),
        "profile": str(args.profile.resolve()),
        "profile_sha256": sha256(args.profile),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not report["structure_matches"]:
        raise RuntimeError("native hardware alignment has structural mismatches")
    print(
        "PASS grasu_native_hw_alignment: "
        f"structure=exact e2e_abs_err_pct="
        f"{report['timing']['event_e2e']['absolute_error_pct']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
