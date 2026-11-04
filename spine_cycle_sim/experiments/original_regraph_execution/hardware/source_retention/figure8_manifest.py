"""Verify the seven historical Figure 8 pairs against their native G inputs."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .figure8_inputs import write_rows
from .runtime import identity


CASES = (("AU", 64), ("AU", 512), ("AU", 4096),
         ("SU", 512), ("WK", 512), ("SO", 512), ("PK", 512))


class NativeDigest:
    def __init__(self):
        self.digest = hashlib.sha256()

    def write(self, line):
        self.digest.update(line.encode("ascii"))


def paired_arms(arm_table):
    arms = {}
    with arm_table.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            case = row["dataset"], int(row["updates"])
            key = (*case, row["arm"])
            if (case not in CASES or row["arm"] not in {"spine", "gr"}
                    or row["algorithm"] != "update_only" or key in arms):
                raise ValueError(f"unexpected or duplicate arm: {key}")
            arms[key] = row
    if len(arms) != len(CASES) * 2:
        raise ValueError("expected two arms for each of the seven Figure 8 cases")
    return arms


def input_config(row):
    config_path = Path(row["evidence"]) / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["mode"] != "update" or config["arm"] != row["arm"]:
        raise ValueError(f"not the expected update-only arm: {config_path}")
    return config_path, tuple(Path(config[key]).resolve(strict=True)
                              for key in ("graph", "updates"))


def manifest(arm_table: Path, native_dir: Path) -> dict:
    arms = paired_arms(arm_table)
    rows, dataset_graphs, identities = [], {}, {}

    def pinned(path):
        if path not in identities:
            identities[path] = identity(path)
        return identities[path]

    for dataset, batch_size in CASES:
        spine, gr = (arms[dataset, batch_size, arm] for arm in ("spine", "gr"))
        for field in ("source", "vertices", "initial_edges", "report_sha256"):
            if spine[field] != gr[field]:
                raise ValueError(f"{dataset}/{batch_size}: arms differ on {field}")
        vertices, edges = int(gr["vertices"]), int(gr["initial_edges"])
        spine_config, spine_inputs = input_config(spine)
        gr_config, gr_inputs = input_config(gr)
        if spine_inputs != gr_inputs:
            raise ValueError(f"{dataset}/{batch_size}: arms do not use the same inputs")
        graph, updates = gr_inputs
        if dataset_graphs.setdefault(dataset, graph) != graph:
            raise ValueError(f"{dataset}: graph changed between batch sizes")
        if not 1 <= vertices <= 255 * 65536 or edges < 1:
            raise ValueError(f"{dataset}/{batch_size}: graph outside the native G ABI")

        expected = NativeDigest()
        expected.write(f"{vertices} {edges} {batch_size}\n")
        write_rows(graph, expected, vertices=vertices, count=edges, batch=False)
        write_rows(updates, expected, vertices=vertices, count=batch_size, batch=True)
        native = identity(native_dir / f"{dataset}_u{batch_size}.graph")
        if native["sha256"] != expected.digest.hexdigest():
            raise ValueError(f"{dataset}/{batch_size}: native graph differs from frozen rows")
        rows.append({
            "dataset": dataset, "updates": batch_size, "vertices": vertices,
            "initial_edges": edges, "frozen_source": int(gr["source"]),
            "frozen_report_sha256": gr["report_sha256"],
            "spine_config": pinned(spine_config), "gr_config": pinned(gr_config),
            "graph": pinned(graph), "batch": pinned(updates), "native_g_input": native,
        })
    return {"schema": "figure8-native-input-identity-v1", "arm_table": identity(arm_table),
            "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm_table", type=Path)
    parser.add_argument("native_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = manifest(args.arm_table, args.native_dir)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent) as staging:
        json.dump(result, staging, indent=2)
        staging.write("\n")
        staging.flush()
        args.output.hardlink_to(staging.name)


if __name__ == "__main__":
    main()
