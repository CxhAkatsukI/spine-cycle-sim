"""Preserve historical projections and explicitly count physical records."""

import json
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...r_credits.freeze import ROOT
from ..matrix import DATASETS, WORKLOADS, HISTORICAL_ROOTS


HISTORICAL_RESIDUAL = (
    ("FL", "deltahls_sinkfree_real_v1.json", "deltahls_soc_flickr_insert_u8"),
    ("AU540", "askubuntu_reciprocal_large_v1.json", "askubuntu_reciprocal_large_bridge_u8"),
    ("AU904", "askubuntu_reciprocal_full_v1.json", "askubuntu_reciprocal_full_bridge_u8"),
)


def historical_residual_cases():
    """Reuse the declared reciprocal u8 inputs, not historical K1 timings."""
    result = []
    for dataset, filename, run_id in HISTORICAL_RESIDUAL:
        manifest = ROOT / "configs/experiments" / filename
        matches = [r for r in json.loads(manifest.read_text())["runs"] if r["run_id"] == run_id]
        if len(matches) != 1:
            raise ValueError("one registered historical u8 case required")
        run = matches[0]
        if run["user_mutations"] != 8 or run["physical_records"] != 16 or run["scenario"] != "insert":
            raise ValueError("historical reciprocal eight-insertion batch required")
        for key in ("graph", "update"):
            if sha256_file(ROOT / run[key]["path"]) != run[key]["sha256"]:
                raise ValueError("historical input identity changed")
        result.append(dict(figure=9, algorithm="ResPR", dataset=dataset, projection="residual_sink_free",
            updates=8, physical_update_records=16, graph=str(ROOT / run["graph"]["path"]),
            update_file=str(ROOT / run["update"]["path"]), vertices=run["graph"]["vertices"],
            initial_edges=run["graph"]["records"], manifest=str(manifest), historical_run_id=run_id))
    return result


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
