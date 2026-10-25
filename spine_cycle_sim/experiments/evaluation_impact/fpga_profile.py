"""Summarize existing G+R event profiling, without summing overlapping kernels."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import statistics

from .fpga_plot import BOUNDARY, digest, load_delivery


PREFIXES = {
    "sssp": "WEIGHTED_PMA_NATIVE_SHARDED_TIMING",
    "cc": "CC_PMA_NATIVE_SHARDED_TIMING",
    "respr": "RESIDUAL_PR_PMA_NATIVE_SHARDED_TIMING",
}
METRICS = (
    "wall_ms", "g_event_union_ms", "barrier_event_union_ms",
    "kernel_event_union_ms", "convergence_readback_ms", "kernel_uncovered_wall_ms",
)
SCOPE = "measured_GR_event_diagnostics_not_exclusive_stage_or_host_attribution"
NOTES = [
    "One warmup pair is excluded; retain samples 1, 2 and 3. Each median is computed separately.",
    "G events include the GraSU pipeline; ResPR also includes device degree update. "
    "SSSP/CC completion-barrier events are reported separately and may overlap G events.",
    "The total kernel event union counts overlapping kernel execution only once. "
    "Per-kernel adapter, gather, apply and HBM duration sums are not additive stage times.",
    "Kernel-uncovered wall is computed per sample as resident wall minus total kernel event union. "
    "It includes DMA, final readback and launch/wait gaps; it is not pure host orchestration time.",
    "Convergence readback is a host wall interval, not a kernel event; ResPR does not log it "
    "separately. Missing metrics remain absent, not zero. Final-state readback is included in wall.",
    "These diagnostics do not establish a causal before/after improvement, publication matching, "
    "or per-stage simulator timing calibration.",
]


def sample_profile(algorithm: str, text: str, expected_wall_ms: float) -> dict:
    prefix = PREFIXES[algorithm]
    lines = [line for line in text.splitlines() if line.startswith(prefix + " ")]
    if len(lines) != 1:
        raise ValueError("exactly one timing record required: " + prefix)
    fields = {}
    for token in lines[0].split()[1:]:
        key, separator, value = token.partition("=")
        if not separator or not key or key in fields:
            raise ValueError("invalid or duplicate timing field")
        fields[key] = value

    def number(key):
        if key not in fields:
            raise ValueError("missing timing field: " + key)
        value = float(fields[key])
        if not math.isfinite(value) or value < 0:
            raise ValueError("nonnegative finite timing required: " + key)
        return value

    wall = number("setup_inclusive_ms")
    if not math.isfinite(expected_wall_ms) or expected_wall_ms <= 0 or wall != expected_wall_ms:
        raise ValueError("timing wall differs from admitted sample")
    result = {
        "wall_ms": wall,
        "g_event_union_ms": number("update_ms" if algorithm == "respr" else "grasu_ms"),
        "kernel_event_union_ms": number("device_e2e_ms" if algorithm == "respr" else "event_e2e_ms"),
    }
    if algorithm != "respr":
        result["barrier_event_union_ms"] = number("barrier_ms")
        result["convergence_readback_ms"] = number("convergence_readback_ms")
    total = result["kernel_event_union_ms"]
    if total > wall or result["g_event_union_ms"] > total or \
            result.get("barrier_event_union_ms", 0) > total or \
            result.get("convergence_readback_ms", 0) > wall:
        raise ValueError("profile interval exceeds its enclosing interval")
    result["kernel_uncovered_wall_ms"] = wall - total
    return result


def inspect(directory: Path) -> dict:
    rows = load_delivery(directory)
    matrix = json.loads((directory / "matrix.json").read_text())
    cases = {(row["algorithm"], row["dataset"]): row for row in matrix["cases"]}
    indexed = {item["path"] for item in json.loads((directory / "files.json").read_text())}
    summaries = []
    for row in rows:
        algorithm, dataset = row["algorithm"], row["dataset"]
        result = {"algorithm": algorithm, "dataset": dataset, "status": row["status"]}
        if row["status"] == "RESIDENT_PAIR_PASS":
            walls = cases[algorithm, dataset]["summary"]["walls"]["gr"]["samples_ms"]
            if len(walls) != 3 or statistics.median(walls) != float(row["gr_ms"]):
                raise ValueError("three admitted measured wall samples required")
            samples = []
            for index, wall in enumerate(walls, 1):
                relative = f"cases/{algorithm}-{dataset.lower()}/sample-{index}/gr/run.log"
                if relative not in indexed:
                    raise ValueError("unindexed profiling log: " + relative)
                sample = sample_profile(algorithm, (directory / relative).read_text(), wall)
                samples.append({"sample_index": index, "source": relative, **sample})
            result["samples"] = samples
            result["median_ms"] = {key: statistics.median(sample[key] for sample in samples)
                                   for key in METRICS if key in samples[0]}
        summaries.append(result)
    return {
        "scope": SCOPE, "boundary": BOUNDARY, "notes": NOTES, "cases": summaries,
        "source": str(directory),
        "source_sha256": {name: digest(directory / name) for name in
                          ("summary.csv", "matrix.json", "plan.json", "files.json")},
        "analyzer_sha256": digest(Path(__file__)),
    }


def package(directory: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("use a fresh output directory")
    report = inspect(directory)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=("algorithm", "dataset", "status", *METRICS))
    writer.writeheader()
    for row in report["cases"]:
        writer.writerow({key: row[key] for key in ("algorithm", "dataset", "status")} |
                        row.get("median_ms", {}))
    output.mkdir(parents=True, exist_ok=False)
    (output / "profile.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    (output / "profile_medians.csv").write_text(buffer.getvalue())
    (output / "README.md").write_text("# G+R FPGA Event Diagnostics\n\n" +
        "\n\n".join(NOTES) + "\n\n`profile.json` retains the three measured samples and input hashes; "
        "`profile_medians.csv` retains all 24 declared cases, including failures.\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = package(args.delivery.resolve(), args.output.resolve())
    print(json.dumps({"scope": report["scope"], "cases": len(report["cases"]),
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
