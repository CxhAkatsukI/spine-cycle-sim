"""Predeclare small warm-SSSP cases and serialize both native input formats."""

import argparse
import json
from pathlib import Path


CASES = (
    ("dev_narrow", "development", 8, 2),
    ("dev_wide", "development", 256, 3),
    ("test_32x3", "holdout", 32, 3),
    ("test_64x5", "holdout", 64, 5),
    ("test_128x2", "holdout", 128, 2),
    ("test_512x4", "holdout", 512, 4),
)


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for name, split, width, depth in CASES:
        folder = output / name
        folder.mkdir()
        vertices = max(256, 3 + width * depth)
        pivot = vertices - 1
        edges = [(0, pivot, 50), (pivot, 1, 50)]
        edges += [(1, 2 + lane, 1) for lane in range(width)]
        edges += [(2 + layer * width + lane, 2 + (layer + 1) * width + lane, 1)
                  for layer in range(depth - 1) for lane in range(width)]
        edges.sort()
        updates = [(0, 1, 1)]
        graph = folder / "graph.txt"
        graph.write_text(f"{vertices} {len(edges)} 1\n" +
                         "".join(f"{s} {d} {w}\n" for s, d, w in edges) + "0 1 1 1\n")
        for tag, values in (("initial", edges), ("update", updates)):
            (folder / f"{tag}.slice").write_text(
                f"# spine_real_slice_version=1\n# case={name}_{tag}\n# vertices={vertices}\n"
                "# columns=src dst weight diff\n" +
                "".join(f"{s} {d} {w} 1\n" for s, d, w in values))
        rows.append(dict(name=name, split=split, width=width, depth=depth,
                         vertices=vertices, initial_edges=len(edges), graph=str(graph),
                         initial=str(folder / "initial.slice"), update=str(folder / "update.slice")))
    plan = dict(algorithm="weighted_sssp", source=0, initial_state="CPU old-graph convergence",
                update="insert absent edge 0->1 with weight 1", cases=rows)
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args().output.resolve())
