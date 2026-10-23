"""Preserve historical projections and explicitly count physical records."""

import json
from ..matrix import DATASETS, WORKLOADS, HISTORICAL_ROOTS


def cases(datasets=("AU", "SU", "WK"), algorithms=("SSSP", "CC", "ResPR")):
    if not datasets or not algorithms or set(datasets) - {"AU", "SU", "WK"} or set(algorithms) - {"SSSP", "CC", "ResPR"}:
        raise ValueError("nonempty registered dataset and algorithm selections required")
    result = []
    for algorithm in algorithms:
        projection = {"SSSP": "directed", "CC": "reciprocal", "ResPR": "residual_sink_free"}[algorithm]
        for dataset in datasets:
            path = WORKLOADS / DATASETS[dataset] / "materialization_manifest.json"
            manifest = json.loads(path.read_text())
            graph = manifest["graphs"][projection]
            updates = [r for r in manifest["updates"] if r["projection"] == projection and
                       r["scenario"] == "insert" and r["user_mutations"] == 8]
            if len(updates) != 1:
                raise ValueError("one registered eight-mutation batch required")
            result.append(dict(figure=9, algorithm=algorithm, dataset=dataset, projection=projection,
                updates=8, physical_update_records=updates[0]["records"], graph=graph["path"],
                update_file=updates[0]["path"], vertices=graph["vertices"], initial_edges=graph["records"],
                manifest=str(path)))
            if algorithm == "SSSP":
                result[-1]["root"] = HISTORICAL_ROOTS[dataset]
    return result
