"""Paired routed K4 comparison; never a substitute for original-A4 evidence."""

import json
import os
from pathlib import Path
import statistics

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze_log
from .board import board_lease, hardware_command, require_idle_board
from .execution import identity, select_case


def compare_bitstreams(*, integration: Path, matrix: Path, case: str, host: Path,
                       admission: Path, output: Path, repeats: int = 3,
                       device: int = 0) -> dict:
    if repeats < 3:
        raise ValueError("at least three paired repetitions required")
    row = select_case(matrix, case)
    gate = json.loads(admission.read_text())
    if gate["status"] != "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD":
        raise ValueError("routed timing and topology gate required before programming")
    old, new = (Path(gate[name]["path"]) for name in ("original", "candidate"))
    if identity(old) != gate["original"] or identity(new) != gate["candidate"]:
        raise ValueError("bitstream identity changed after admission")
    if Path(row["gr_xclbin"]).resolve() != old.resolve() or row["algorithm"] != "weighted_sssp":
        raise ValueError("this candidate replaces only the frozen weighted-SSSP bitstream")
    pins = [identity(path) for path in [matrix, Path(row["graph"]), host, admission,
            old, new, integration / "scripts/run_pma_native_hw.sh", Path(__file__),
            Path(__file__).with_name("board.py"), Path(__file__).with_name("analysis.py")]]
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"case": row, "pins": pins, "repeats": repeats,
                "host_affinity": sorted(os.sched_getaffinity(0)), "device_index": device,
                "memory_limit_gib": 8, "reserve_gib": 16, "timeout_seconds": 600,
                "order": "original_candidate_alternating_each_repeat",
                "boundary": "unchanged_production_resident_update_and_convergence",
                "claim": "original_K4_vs_optimized_K4_not_original_A4_or_publication_match"}
    atomic_write_json(output / "manifest.json", manifest)
    attempts = []
    with board_lease(device) as render:
        for repeat in range(repeats):
            arms = [("original", old), ("candidate", new)]
            if repeat % 2:
                arms.reverse()
            for arm, binary in arms:
                require_idle_board(render)
                name = f"r{repeat}_{arm}"
                run_dir = output / name
                command = hardware_command(integration, row, host, binary,
                                           run_dir, device, 600, "1")
                execution = run_bounded(command, integration, output / f"{name}_process",
                                        timeout=600, memory_gib=8, reserve_gib=16)
                attempt = {"arm": arm, "repeat": repeat, "resources": execution}
                attempts.append(attempt)
                atomic_write_json(output / "attempts.json", attempts)
                if execution["exit_code"] != 0:
                    raise RuntimeError("board attempt failed; raw logs retained")
                attempt["analysis"] = analyze_log((run_dir / "run.log").read_text(), require_trace=True)
                attempt["result"] = identity(run_dir / "result.txt")
                atomic_write_json(output / "attempts.json", attempts)
                print(f"{case} {name} PASS", flush=True)
    checks = {"inputs_unchanged": all(identity(Path(pin["path"])) == pin for pin in pins),
              "all_result_bytes_equal": len({a["result"]["sha256"] for a in attempts}) == 1,
              "same_correctness_and_rounds": all(a["analysis"]["result"] == attempts[0]["analysis"]["result"]
                                                 for a in attempts)}
    medians = {}
    for arm in ("original", "candidate"):
        rows = [a["analysis"] for a in attempts if a["arm"] == arm]
        medians[arm] = {"setup_inclusive_ms": statistics.median(r["timing_ms"]["setup_inclusive_ms"] for r in rows),
                        "compute_span_ms": statistics.median(r["compute_span_ms"] for r in rows),
                        "adapter_after_gather_union_ms": statistics.median(r["adapter_after_gather_union_ms"] for r in rows)}
    result = {"status": "PAIRED_BOARD_PASS" if all(checks.values()) else "PAIRED_BOARD_FAIL",
              "checks": checks, "medians": medians, "attempts": attempts,
              "claim": manifest["claim"]}
    atomic_write_json(output / "summary.json", result)
    if result["status"] != "PAIRED_BOARD_PASS":
        raise RuntimeError("paired board result or source identity differs")
    return result
