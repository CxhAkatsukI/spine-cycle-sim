#!/usr/bin/env python3
"""Convert a GraSU benchmark .graph into initial and update Spine slices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert_graph(
    graph: Path, initial_output: Path, update_output: Path, metadata_output: Path
) -> dict[str, object]:
    lines = [line.strip() for line in graph.read_text(encoding="ascii").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if not lines:
        raise ValueError("GraSU graph is empty")
    header = lines[0].split()
    if len(header) != 3:
        raise ValueError("GraSU graph header must be: vertices static updates")
    vertices, static_count, update_count = map(int, header)
    if vertices <= 0 or static_count < 0 or update_count < 0:
        raise ValueError("GraSU graph header contains an invalid count")
    if len(lines) != 1 + static_count + update_count:
        raise ValueError("GraSU graph row count does not match its header")

    initial_rows: list[tuple[int, int, int, int]] = []
    for line in lines[1 : 1 + static_count]:
        fields = line.split()
        if len(fields) != 2:
            raise ValueError("GraSU static edge must contain src dst")
        source, destination = map(int, fields)
        if not (0 <= source < vertices and 0 <= destination < vertices):
            raise ValueError("GraSU static edge is out of range")
        initial_rows.append((source, destination, 1, 1))

    update_rows: list[tuple[int, int, int, int]] = []
    for line in lines[1 + static_count :]:
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("GraSU update edge must contain src dst operation")
        source, destination, operation = map(int, fields)
        if not (0 <= source < vertices and 0 <= destination < vertices):
            raise ValueError("GraSU update edge is out of range")
        if operation not in (0, 1):
            raise ValueError("GraSU update operation must be 0 (delete) or 1 (insert)")
        update_rows.append((source, destination, 1, 1 if operation == 1 else -1))

    def write_slice(path: Path, case: str, rows: list[tuple[int, int, int, int]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = [
            "# spine_real_slice_version=1",
            f"# case={case}",
            f"# vertices={vertices}",
            "# columns=src dst weight diff",
        ]
        text.extend(" ".join(map(str, row)) for row in rows)
        path.write_text("\n".join(text) + "\n", encoding="ascii")

    write_slice(initial_output, f"{graph.stem}_initial", initial_rows)
    write_slice(update_output, f"{graph.stem}_update", update_rows)
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
        "unit_weight": 1,
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
    args = parser.parse_args()
    metadata = convert_graph(
        args.graph.resolve(), args.initial_out, args.update_out, args.metadata_out
    )
    print(
        "PASS convert_grasu_graph_to_slices: "
        f"vertices={metadata['vertices']} static={metadata['static_edges']} "
        f"updates={metadata['update_edges']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
