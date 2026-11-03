"""Split an unchanged resident CC workload for the native CC repair host."""

import argparse
from pathlib import Path

from .runtime import identity, save


def prepare(source: Path, output: Path) -> dict:
    pin = identity(source)
    output.mkdir(parents=True, exist_ok=False)
    graph, update = output / "graph.slice", output / "update.slice"
    with source.open() as rows:
        vertices, edges, updates = map(int, next(rows).split())
        if min(vertices, edges, updates) <= 0 or vertices > 16777216:
            raise ValueError("invalid CC workload dimensions")
        for path, count, is_update in ((graph, edges, False), (update, updates, True)):
            with path.open("x") as dest:
                dest.write(f"# vertices={vertices}\n")
                for _ in range(count):
                    fields = rows.readline().split()
                    if len(fields) != (4 if is_update else 3):
                        raise ValueError("invalid CC workload record width or truncated input")
                    u, v, weight = map(int, fields[:3])
                    diff = int(fields[3]) if is_update else 1
                    if not (0 <= u < vertices and 0 <= v < vertices and u != v
                            and 0 <= weight <= 65535 and diff in (-1, 1)):
                        raise ValueError("record is outside the native CC host domain")
                    dest.write(f"{u} {v} {weight} {diff}\n")
        if any(line.strip() for line in rows):
            raise ValueError("trailing CC workload records")
    if identity(source) != pin:
        raise ValueError("source changed while preparing CC inputs")
    result = {"source": pin, "graph": identity(graph), "update": identity(update),
              "vertices": vertices, "edges": edges, "updates": updates}
    save(output / "inputs.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)
