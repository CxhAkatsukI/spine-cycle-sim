#!/usr/bin/env python3
"""Parse routed sharded-K4 update event phases into auditable CSV evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Iterable


LAYOUT_PREFIX = "GRASU_SHARDED_UPDATE_LAYOUT"
EVENT_PREFIX = "GRASU_SHARDED_UPDATE_EVENTS"
PHASE_PREFIX = "GRASU_SHARDED_UPDATE_EVENTS_PHASE"
CASE_PATTERN = re.compile(
    r"^(?P<dataset>.+)_(?P<algorithm>weighted_sssp|connected_components|residual_pagerank)$"
)


def parse_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return fields


def prefixed_rows(path: Path, prefix: str) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    return [
        parse_fields(line)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(prefix + " ")
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_for_case(case_dir: Path) -> dict[str, object]:
    run_log = case_dir / "run.log"
    run_env = case_dir / "run.env"
    if not run_log.is_file() or not run_env.is_file():
        raise ValueError(f"missing routed evidence file: {case_dir}")
    env_text = run_env.read_text(encoding="utf-8", errors="replace")

    def field(name: str) -> str:
        match = re.search(rf"(?:^|\s){re.escape(name)}=([^\s]+)", env_text)
        if not match:
            raise ValueError(f"missing {name} in {run_env}")
        return match.group(1)

    row: dict[str, object] = {
        "case": case_dir.name,
        "status": field("STATUS"),
        "target": field("TARGET"),
        "algorithm": field("ALGORITHM"),
        "repository_head": field("REPO_HEAD"),
        "repository_dirty": int(field("REPO_DIRTY")),
        "host_sha256": field("HOST_SHA256"),
        "xclbin_sha256": field("XCLBIN_SHA256"),
        "graph_sha256": field("GRAPH_SHA256"),
        "run_log_sha256": sha256(run_log),
        "run_env_sha256": sha256(run_env),
    }
    prepare_log = case_dir / "prepare.log"
    if prepare_log.is_file():
        row["prepare_log_sha256"] = sha256(prepare_log)
    if row["status"] != "PASS" or row["target"] != "hw":
        raise ValueError(f"case is not a passing hardware run: {case_dir}")
    return row


def _int(fields: dict[str, str], key: str) -> int:
    return int(fields[key])


def _float(fields: dict[str, str], key: str) -> float:
    return float(fields[key])


def collect_case(case_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    match = CASE_PATTERN.match(case_dir.name)
    if not match:
        raise ValueError(f"unrecognized event case directory: {case_dir}")
    dataset = match.group("dataset")
    algorithm = match.group("algorithm")
    run_log = case_dir / "run.log"
    layout_rows = prefixed_rows(run_log, LAYOUT_PREFIX)
    if not layout_rows:
        layout_rows = prefixed_rows(case_dir / "prepare.log", LAYOUT_PREFIX)
    event_rows = prefixed_rows(run_log, EVENT_PREFIX)
    phase_rows = prefixed_rows(run_log, PHASE_PREFIX)
    if not layout_rows or not event_rows or not phase_rows:
        raise ValueError(f"incomplete layout/event/phase evidence: {case_dir}")

    layouts = {_int(row, "shard"): row for row in layout_rows}
    events = {_int(row, "shard"): row for row in event_rows}
    phases: dict[int, list[dict[str, str]]] = {}
    for row in phase_rows:
        phases.setdefault(_int(row, "shard"), []).append(row)
    if set(layouts) != set(events) or set(events) != set(phases):
        raise ValueError(f"shard identity mismatch: {case_dir}")

    shard_output: list[dict[str, object]] = []
    phase_output: list[dict[str, object]] = []
    for shard in sorted(events):
        layout = layouts[shard]
        event = events[shard]
        shard_phases = phases[shard]
        submit_to_start = [_float(row, "submit_to_start_ms") for row in shard_phases]
        queued_to_submit = [_float(row, "queued_to_submit_ms") for row in shard_phases]
        execute = [_float(row, "execute_ms") for row in shard_phases]
        shard_output.append(
            {
                "dataset": dataset,
                "algorithm": algorithm,
                "shard": shard,
                "updates": _int(layout, "updates"),
                "unique_sources": _int(layout, "unique_sources"),
                "pma_slots": _int(layout, "pma_slots"),
                "source_segments": _int(layout, "source_segments"),
                "binary_probes": _int(layout, "binary_probes"),
                "cache_updates": _int(layout, "cache_updates"),
                "ddr_updates": _int(layout, "ddr_updates"),
                "gap_from_previous_ms": _float(event, "gap_from_previous_ms"),
                "union_ms": _float(event, "union_ms"),
                "max_queued_to_submit_ms": max(queued_to_submit),
                "median_queued_to_submit_ms": statistics.median(queued_to_submit),
                "max_submit_to_start_ms": max(submit_to_start),
                "max_execute_ms": max(execute),
                "phase_count": len(shard_phases),
            }
        )
        for row in shard_phases:
            phase_output.append(
                {
                    "dataset": dataset,
                    "algorithm": algorithm,
                    "shard": shard,
                    "cu": row["cu"],
                    "queued_offset_ms": _float(row, "queued_offset_ms"),
                    "queued_to_submit_ms": _float(row, "queued_to_submit_ms"),
                    "submit_to_start_ms": _float(row, "submit_to_start_ms"),
                    "execute_ms": _float(row, "execute_ms"),
                    "start_offset_ms": _float(row, "start_offset_ms"),
                    "end_offset_ms": _float(row, "end_offset_ms"),
                }
            )
    return shard_output, phase_output


def pearson_r2(xs: Iterable[float], ys: Iterable[float]) -> float:
    x = tuple(float(value) for value in xs)
    y = tuple(float(value) for value in ys)
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("Pearson R2 requires aligned samples")
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    numerator = sum((left - x_mean) * (right - y_mean) for left, right in zip(x, y))
    x_norm = sum((value - x_mean) ** 2 for value in x)
    y_norm = sum((value - y_mean) ** 2 for value in y)
    if x_norm == 0 or y_norm == 0:
        return 0.0
    return (numerator * numerator) / (x_norm * y_norm)


def correlation_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    features = {
        "updates": lambda row: float(row["updates"]),
        "unique_sources": lambda row: float(row["unique_sources"]),
        "pma_slots": lambda row: float(row["pma_slots"]),
        "log2_pma_slots_plus_one": lambda row: math.log2(float(row["pma_slots"]) + 1.0),
        "source_segments": lambda row: float(row["source_segments"]),
        "binary_probes": lambda row: float(row["binary_probes"]),
    }
    output: list[dict[str, object]] = []
    groups = {"all": rows}
    groups.update(
        {
            algorithm: [row for row in rows if row["algorithm"] == algorithm]
            for algorithm in sorted({str(row["algorithm"]) for row in rows})
        }
    )
    for group, group_rows in groups.items():
        target = [float(row["union_ms"]) for row in group_rows]
        for feature, transform in features.items():
            output.append(
                {
                    "group": group,
                    "feature": feature,
                    "samples": len(group_rows),
                    "pearson_r2_with_union_ms": pearson_r2(
                        [transform(row) for row in group_rows], target
                    ),
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(
            sink, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    shard_rows: list[dict[str, object]] = []
    phase_rows: list[dict[str, object]] = []
    provenance: list[dict[str, object]] = []
    case_dirs = sorted(path for path in evidence_root.iterdir() if path.is_dir())
    for case_dir in case_dirs:
        case_shards, case_phases = collect_case(case_dir)
        shard_rows.extend(case_shards)
        phase_rows.extend(case_phases)
        provenance.append(provenance_for_case(case_dir))
    correlations = correlation_rows(shard_rows)
    write_csv(out_dir / "shard_event_rows.csv", shard_rows)
    write_csv(out_dir / "cu_phase_rows.csv", phase_rows)
    write_csv(out_dir / "univariate_correlations.csv", correlations)
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "DIAGNOSTIC_ONLY",
                "evidence_root": str(evidence_root),
                "cases": len(case_dirs),
                "shards": len(shard_rows),
                "cu_phases": len(phase_rows),
                "fit_performed": False,
                "routed_evidence": provenance,
                "hls_path": "direct-cache/compact-HBM update pipeline",
                "excluded_interpretation": (
                    "pma_slots are not an executed full-PMA update scan"
                ),
                "claim_boundary": (
                    "PMA slots are a host/XRT envelope candidate, not direct-cache "
                    "HLS scan work; correlations do not establish a timing model."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    print(
        f"GRASU_UPDATE_EVENT_PHASE_ANALYSIS cases={len(case_dirs)} "
        f"shards={len(shard_rows)} phases={len(phase_rows)} out={out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
