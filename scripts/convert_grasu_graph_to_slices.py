#!/usr/bin/env python3
"""Convert a GraSU benchmark .graph into initial and update Spine slices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.connected_components_workloads import (  # noqa: E402
    analyze_reciprocal_update,
    validate_reciprocal_snapshot,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def convert_graph(
    graph: Path,
    initial_output: Path,
    update_output: Path,
    metadata_output: Path,
    *,
    require_reciprocal: bool = False,
    sort_records: bool = False,
) -> dict[str, object]:
    def graph_lines():
        with graph.open(encoding="ascii") as source:
            for raw_line in source:
                line = raw_line.strip()
                if line and not line.startswith("#"):
                    yield line

    lines = graph_lines()
    try:
        header = next(lines).split()
    except StopIteration as error:
        raise ValueError("GraSU graph is empty") from error
    if len(header) != 3:
        raise ValueError("GraSU graph header must be: vertices static updates")
    vertices, static_count, update_count = map(int, header)
    if vertices <= 0 or static_count < 0 or update_count < 0:
        raise ValueError("GraSU graph header contains an invalid count")

    def slice_header(case: str) -> list[str]:
        return [
            "# spine_real_slice_version=1",
            f"# case={case}",
            f"# vertices={vertices}",
            "# columns=src dst weight diff",
        ]

    def parse_static(line: str) -> tuple[int, int, int, int]:
        fields = line.split()
        if len(fields) not in {2, 3}:
            raise ValueError("GraSU static edge must contain src dst [weight]")
        source, destination = map(int, fields[:2])
        weight = int(fields[2]) if len(fields) == 3 else 1
        if not (0 <= source < vertices and 0 <= destination < vertices):
            raise ValueError("GraSU static edge is out of range")
        if not 1 <= weight <= 4095:
            raise ValueError("GraSU static edge exceeds the weight12 ABI")
        return source, destination, weight, 1

    def parse_update(line: str) -> tuple[int, int, int, int]:
        fields = line.split()
        if len(fields) not in {3, 4}:
            raise ValueError(
                "GraSU update edge must contain src dst [weight] operation"
            )
        source, destination = map(int, fields[:2])
        weight = int(fields[2]) if len(fields) == 4 else 1
        operation = int(fields[-1])
        if not (0 <= source < vertices and 0 <= destination < vertices):
            raise ValueError("GraSU update edge is out of range")
        if not 1 <= weight <= 4095:
            raise ValueError("GraSU update edge exceeds the weight12 ABI")
        if operation not in (0, 1):
            raise ValueError("GraSU update operation must be 0 (delete) or 1 (insert)")
        return source, destination, weight, 1 if operation == 1 else -1

    initial_output.parent.mkdir(parents=True, exist_ok=True)
    update_output.parent.mkdir(parents=True, exist_ok=True)
    initial_rows: list[tuple[int, int, int, int]] = []
    update_rows: list[tuple[int, int, int, int]] = []
    all_unit_weight = True
    with initial_output.open("w", encoding="ascii") as initial_stream, \
            update_output.open("w", encoding="ascii") as update_stream:
        initial_stream.write("\n".join(slice_header(f"{graph.stem}_initial")) + "\n")
        update_stream.write("\n".join(slice_header(f"{graph.stem}_update")) + "\n")
        for _ in range(static_count):
            try:
                row = parse_static(next(lines))
            except StopIteration as error:
                raise ValueError("GraSU graph row count does not match its header") from error
            all_unit_weight = all_unit_weight and row[2] == 1
            if sort_records:
                initial_rows.append(row)
            else:
                initial_stream.write(" ".join(map(str, row)) + "\n")
        for _ in range(update_count):
            try:
                row = parse_update(next(lines))
            except StopIteration as error:
                raise ValueError("GraSU graph row count does not match its header") from error
            all_unit_weight = all_unit_weight and row[2] == 1
            if sort_records:
                update_rows.append(row)
            else:
                update_stream.write(" ".join(map(str, row)) + "\n")
        try:
            next(lines)
        except StopIteration:
            pass
        else:
            raise ValueError("GraSU graph row count does not match its header")
        if sort_records:
            initial_rows.sort()
            update_rows.sort()
            initial_stream.writelines(
                " ".join(map(str, row)) + "\n" for row in initial_rows
            )
            update_stream.writelines(
                " ".join(map(str, row)) + "\n" for row in update_rows
            )

    if require_reciprocal:
        initial_graph = load_slice(initial_output)
        update_graph = load_slice(update_output)
        validate_reciprocal_snapshot(initial_graph)
        analyze_reciprocal_update(initial_graph, update_graph)
    metadata = {
        "schema_version": 1,
        "source_graph": str(graph.resolve()),
        "source_graph_sha256": sha256(graph),
        "vertices": vertices,
        "static_edges": static_count,
        "update_edges": update_count,
        "initial_slice": str(initial_output.resolve()),
        "initial_slice_sha256": sha256(initial_output),
        "update_slice": str(update_output.resolve()),
        "update_slice_sha256": sha256(update_output),
        "weights_preserved": True,
        "unit_weight": 1 if all_unit_weight else None,
        "reciprocal_validated": require_reciprocal,
        "record_order": (
            "deterministic_src_dst_weight_diff" if sort_records else "source_graph"
        ),
        "operation_mapping": {"0": -1, "1": 1},
    }
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path)
    parser.add_argument("--initial-out", type=Path, required=True)
    parser.add_argument("--update-out", type=Path, required=True)
    parser.add_argument("--metadata-out", type=Path, required=True)
    parser.add_argument("--require-reciprocal", action="store_true")
    parser.add_argument("--sort-records", action="store_true")
    args = parser.parse_args()
    metadata = convert_graph(
        args.graph.resolve(),
        args.initial_out,
        args.update_out,
        args.metadata_out,
        require_reciprocal=args.require_reciprocal,
        sort_records=args.sort_records,
    )
    print(
        "PASS convert_grasu_graph_to_slices: "
        f"vertices={metadata['vertices']} static={metadata['static_edges']} "
        f"updates={metadata['update_edges']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
