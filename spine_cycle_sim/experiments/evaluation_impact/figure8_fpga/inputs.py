"""Stream the existing Fig. 8 slices into the native host input format."""

import argparse
import json
from pathlib import Path
import shutil

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save


DATASETS = ("AU", "SU", "WK", "SO", "PK")


def records(path, state):
    with path.open() as stream:
        for line in stream:
            if line.startswith("#"):
                if line.startswith("# vertices="):
                    vertices = int(line.split("=", 1)[1])
                    if state.get("vertices", vertices) != vertices:
                        raise ValueError("vertex domains differ")
                    state["vertices"] = vertices
                continue
            if not line.strip():
                continue
            values = tuple(map(int, line.split()))
            if (len(values) != 4 or values[3] != 1 or not 0 < values[2] <= 4095
                    or not all(0 <= vertex < state["vertices"] for vertex in values[:2])):
                raise ValueError("valid weight12 insertion records required: " + str(path))
            yield values


def convert(graph, updates, output, expected_updates):
    state, count, update_count = {}, 0, 0
    body = output.with_suffix(".body")
    with body.open("x") as stream:
        for src, dst, weight, _ in records(graph, state):
            stream.write(f"{src} {dst} {weight}\n")
            count += 1
        for src, dst, weight, diff in records(updates, state):
            stream.write(f"{src} {dst} {weight} {diff}\n")
            update_count += 1
    if update_count != expected_updates or not count:
        raise ValueError("unexpected input extent")
    with output.open("x") as stream, body.open() as source:
        stream.write(f"{state['vertices']} {count} {update_count}\n")
        shutil.copyfileobj(source, stream)
    body.unlink()
    return dict(vertices=state["vertices"], initial_edges=count, updates=update_count,
                graph=identity(output), source_graph=identity(graph), source_updates=identity(updates))


def prepare(manifests, output, sweep_updates):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="PREPARING", cases=[])
    journal = output / "inputs.json"
    save(journal, report)
    for dataset in DATASETS:
        source = manifests / dataset.lower() / "manifest.json"
        manifest = json.loads(source.read_text())
        graph, updates = (Path(manifest[key]) for key in ("graph", "updates"))
        native = convert(graph, updates, output / f"{dataset}_u4096.graph", 4096)
        report["cases"].append(dict(native, name=dataset + "_4096_b10", dataset=dataset,
                                    batches=10, panel="a", source_manifest=identity(source)))
        save(journal, report)
        if dataset == "AU":
            large = convert(graph, sweep_updates, output / "AU_u131072.graph", 131072)
            for batches in (10, 100, 1000):
                report["cases"].append(dict(large, name=f"AU_131072_b{batches}", dataset="AU",
                                            batches=batches, panel="b", source_manifest=identity(source)))
            save(journal, report)
    report["cases"].sort(key=lambda row: (row["panel"], DATASETS.index(row["dataset"]), row["batches"]))
    report["status"] = "READY"
    save(journal, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifests", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sweep-updates", required=True, type=Path)
    arguments = parser.parse_args()
    prepare(arguments.manifests, arguments.output, arguments.sweep_updates)
