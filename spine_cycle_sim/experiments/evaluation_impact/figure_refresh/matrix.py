"""Predeclared historical inputs and explicit current-model coverage."""

import json
from pathlib import Path


DATASETS = {"AU": "sx_askubuntu", "SU": "sx_superuser", "WK": "wiki_talk_temporal",
            "SO": "sx_stackoverflow", "PK": "soc_pokec"}
WORKLOADS = Path("/data/tmp/chuxiao/large_graph_campaign_v1/workloads")
HISTORICAL_ROOTS = {"AU": 11, "SU": 23, "WK": 0}


def cases():
    result = []
    for dataset, name in DATASETS.items():
        manifest_path = WORKLOADS / name / "materialization_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        graph = manifest["graphs"]["directed"]
        updates = {int(row["user_mutations"]): row for row in manifest["updates"]
                   if row["projection"] == "directed" and row["scenario"] == "insert"}
        sizes = (64, 512, 4096) if dataset == "AU" else (512,)
        for count in sizes:
            result.append(dict(figure=8, dataset=dataset, algorithm="update_only", updates=count,
                graph=graph["path"], update_file=updates[count]["path"], root=graph["source_cohorts"]["default"],
                vertices=graph["vertices"], initial_edges=graph["records"], manifest=str(manifest_path)))
        if dataset in ("AU", "SU", "WK"):
            result.append(dict(figure=9, dataset=dataset, algorithm="SSSP", updates=8,
                graph=graph["path"], update_file=updates[8]["path"], root=HISTORICAL_ROOTS[dataset],
                vertices=graph["vertices"], initial_edges=graph["records"], manifest=str(manifest_path)))
    return result


def unsupported():
    return [dict(figure=9, dataset=dataset, algorithm=algorithm,
                 status="UNSUPPORTED_LATEST_R", reason="RoutedReGraphSystem currently admits SSSP only")
            for algorithm in ("CC", "ResPR") for dataset in ("AU", "SU", "WK")]
