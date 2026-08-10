#!/usr/bin/env python3
"""Prepare deterministic, domain-checked real slices for refactor31 transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = (
    ROOT
    / "configs"
    / "experiments"
    / "spine_refactor31_fpga_calibration_matrix_v2.json"
)


def source_edges(path: Path) -> Iterator[tuple[int, int]]:
    """Read zero-based text or one-based MatrixMarket coordinate input."""

    matrix_market = False
    dimensions_consumed = False
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("%%MatrixMarket"):
                matrix_market = True
                continue
            if line.startswith("%") or line.startswith("#"):
                continue
            fields = line.split()
            if matrix_market and not dimensions_consumed:
                if len(fields) < 3:
                    raise ValueError(f"{path}: malformed MatrixMarket dimensions")
                dimensions_consumed = True
                continue
            if len(fields) < 2:
                raise ValueError(f"{path}: malformed edge row: {line}")
            src, dst = int(fields[0]), int(fields[1])
            if matrix_market:
                src -= 1
                dst -= 1
            if src < 0 or dst < 0:
                raise ValueError(f"{path}: negative endpoint after normalization")
            yield src, dst


def endpoint_weight(src: int, dst: int) -> int:
    mixed = ((src * 0x9E3779B1) ^ (dst * 0x85EBCA77)) & 0xFFFFFFFF
    return 1 + mixed % 255


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_for_slice(path: Path, vertices: int) -> int:
    outdegree = [0] * vertices
    with path.open("r", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("#"):
                continue
            src = int(line.split(maxsplit=1)[0])
            outdegree[src] += 1
    for vertex, degree in enumerate(outdegree):
        if 4 <= degree <= 16:
            return vertex
    for vertex, degree in enumerate(outdegree):
        if degree:
            return vertex
    raise ValueError(f"{path}: generated slice has no source")


def prepare_dataset(
    *,
    dataset_id: str,
    source_path: Path,
    targets: list[int],
    out_dir: Path,
    vertex_limit: int,
    expected_reject_targets: set[int],
) -> list[dict[str, Any]]:
    if not targets or min(targets) <= 0:
        raise ValueError("edge targets must be positive")
    unique_targets = sorted(set(targets))
    output_paths = {
        target: out_dir / f"{dataset_id.lower()}_e{target}.slice"
        for target in unique_targets
    }
    body_paths = {
        target: path.with_suffix(path.suffix + ".body")
        for target, path in output_paths.items()
    }
    streams: dict[int, Any] = {}
    for target, path in body_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        streams[target] = path.open("w", encoding="ascii")

    remap: dict[int, int] = {}
    endpoints: set[int] = set()
    completed: dict[int, int] = {}
    overflow_at_edge: int | None = None
    unique_edges = 0
    try:
        for external_src, external_dst in source_edges(source_path):
            new_vertices = int(external_src not in remap) + int(
                external_dst not in remap and external_dst != external_src
            )
            if len(remap) + new_vertices > vertex_limit:
                overflow_at_edge = unique_edges + 1
                break
            src = remap.setdefault(external_src, len(remap))
            dst = remap.setdefault(external_dst, len(remap))
            key = (src << 32) | dst
            if key in endpoints:
                continue
            endpoints.add(key)
            unique_edges += 1
            weight = endpoint_weight(src, dst)
            for target, stream in streams.items():
                if target >= unique_edges:
                    stream.write(f"{src} {dst} {weight} 1\n")
                if target == unique_edges:
                    completed[target] = len(remap)
                    stream.flush()
            if unique_edges >= unique_targets[-1]:
                break
    finally:
        for stream in streams.values():
            stream.close()

    rows: list[dict[str, Any]] = []
    for target in unique_targets:
        path = output_paths[target]
        body = body_paths[target]
        if target not in completed:
            path.unlink(missing_ok=True)
            body.unlink(missing_ok=True)
            status = "vertex_domain_exceeded" if overflow_at_edge else "source_exhausted"
            if target not in expected_reject_targets:
                raise ValueError(
                    f"{dataset_id} e{target}: {status} after {unique_edges} unique edges"
                )
            rows.append(
                {
                    "dataset": dataset_id,
                    "target_edges": target,
                    "status": status,
                    "unique_edges_before_stop": unique_edges,
                    "vertices_before_stop": len(remap),
                    "overflow_at_unique_edge": overflow_at_edge,
                }
            )
            continue
        vertices = completed[target]
        sorted_body = body.with_suffix(body.suffix + ".sorted")
        subprocess.run(
            [
                "sort",
                "-n",
                "-k1,1",
                "-k2,2",
                "-k3,3",
                "--temporary-directory",
                str(out_dir),
                "-o",
                str(sorted_body),
                str(body),
            ],
            check=True,
        )
        with path.open("w", encoding="ascii") as stream:
            stream.write("# spine_real_slice_version=1\n")
            stream.write(f"# case={dataset_id}_e{target}\n")
            stream.write(f"# vertices={vertices}\n")
            stream.write("# columns=src dst weight diff\n")
            with sorted_body.open("r", encoding="ascii") as sorted_stream:
                shutil.copyfileobj(sorted_stream, stream, 1024 * 1024)
        body.unlink()
        sorted_body.unlink()
        source = _source_for_slice(path, vertices)
        rows.append(
            {
                "dataset": dataset_id,
                "target_edges": target,
                "status": "generated",
                "vertices": vertices,
                "source": source,
                "path": str(path.resolve()),
                "sha256": sha256(path),
            }
        )
    return rows


def matrix_jobs(matrix: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    jobs: dict[tuple[str, str], dict[str, Any]] = {}
    calibration_scales = matrix["calibration"]["edge_scales"]
    for dataset in matrix["calibration"]["datasets"]:
        jobs[(dataset["id"], dataset["path"])] = {
            "targets": list(calibration_scales),
            "reject": set(),
        }
    for dataset in matrix["holdout"]["datasets"]:
        jobs[(dataset["id"], dataset["path"])] = {
            "targets": [int(dataset["edge_scale"])],
            "reject": set(),
        }
    for probe in matrix.get("capacity_probes", []):
        key = (probe["id"].removesuffix("8M"), probe["path"])
        job = jobs.setdefault(key, {"targets": [], "reject": set()})
        target = int(probe["edge_scale"])
        job["targets"].append(target)
        if probe["expected_status"] == "vertex_domain_exceeded":
            job["reject"].add(target)
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--datasets", nargs="*")
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    output = args.out_dir.resolve()
    selected = None if not args.datasets else set(args.datasets)
    rows: list[dict[str, Any]] = []
    for (dataset_id, source), job in matrix_jobs(matrix).items():
        if selected is not None and dataset_id not in selected:
            continue
        rows.extend(
            prepare_dataset(
                dataset_id=dataset_id,
                source_path=Path(source),
                targets=job["targets"],
                out_dir=output,
                vertex_limit=int(matrix["vertex_domain_limit"]),
                expected_reject_targets=job["reject"],
            )
        )
    manifest = {
        "schema_version": 1,
        "matrix_id": matrix["matrix_id"],
        "matrix_path": str(matrix_path),
        "matrix_sha256": sha256(matrix_path),
        "rows": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"REFACTOR31_REAL_SLICE_MATRIX_PASS generated="
        f"{sum(row['status'] == 'generated' for row in rows)} "
        f"rejected={sum(row['status'] != 'generated' for row in rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
