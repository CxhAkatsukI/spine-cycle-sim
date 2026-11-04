"""Convert frozen directed insert-only Fig. 8 inputs to the native G host ABI."""

import argparse
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_rows(source, destination, *, vertices, count, batch):
    declared_extent = None
    seen = 0
    with source.open(encoding="ascii") as stream:
        for line_number, raw in enumerate(stream, start=1):
            line = raw.strip()
            if line.startswith("# vertices="):
                if declared_extent is not None or int(line.split("=", 1)[1]) != vertices:
                    raise ValueError(f"{source}:{line_number}: invalid vertex extent")
                declared_extent = vertices
            if not line or line.startswith("#"):
                continue
            src, dst, weight, diff = map(int, line.split())
            if not (0 <= src < vertices and 0 <= dst < vertices
                    and 1 <= weight <= 4095 and diff == 1):
                raise ValueError(f"{source}:{line_number}: edge does not fit insert-only G ABI")
            seen += 1
            if seen > count:
                raise ValueError(f"{source}: more than {count} edges")
            suffix = " 1" if batch else ""
            destination.write(f"{src} {dst} {weight}{suffix}\n")
    if declared_extent != vertices or seen != count:
        raise ValueError(f"{source}: expected extent {vertices} and {count} edges, got "
                         f"{declared_extent} and {seen}")


def prepare(graph: Path, updates: Path, output: Path, *, vertices: int, edges: int,
            batch_size: int) -> None:
    if not 1 <= vertices <= 255 * 65536 or edges < 1 or batch_size < 1:
        raise ValueError("expected positive counts within the native 255-partition ABI")
    if output.exists():
        raise FileExistsError(output)
    # Stream the largest inputs without loading tens of millions of Python records.
    with NamedTemporaryFile(mode="w", encoding="ascii", newline="\n",
                            dir=output.parent) as staging:
        staging.write(f"{vertices} {edges} {batch_size}\n")
        write_rows(graph, staging, vertices=vertices, count=edges, batch=False)
        write_rows(updates, staging, vertices=vertices, count=batch_size, batch=True)
        staging.flush()
        output.hardlink_to(staging.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("updates", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vertices", type=int, required=True)
    parser.add_argument("--edges", type=int, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    args = parser.parse_args()
    prepare(args.graph, args.updates, args.output, vertices=args.vertices, edges=args.edges,
            batch_size=args.batch_size)


if __name__ == "__main__":
    main()
