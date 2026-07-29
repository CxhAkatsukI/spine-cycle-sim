"""Formal publication-case selection and execution de-duplication."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


PUBLICATION_ALGORITHMS = (
    "weighted_sssp",
    "connected_components",
    "full_pagerank",
    "thresholded_residual_pagerank",
)
PUBLICATION_SYSTEMS = (
    "spine",
    "grasu_regraph_k1",
    "grasu_regraph_k4_shared",
)


@dataclass(frozen=True)
class PublicationCase:
    dataset_id: str
    system: str
    algorithm: str
    scenario: str
    batch_size: int
    graph: Mapping[str, Any]
    update: Mapping[str, Any]
    source: int
    algorithm_parameters: Mapping[str, Any]
    execution_id: str


def load_materialization_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="ascii"))
    if manifest.get("schema_version") != 1 or manifest.get("status") != "pass":
        raise ValueError(f"materialization manifest is not passing: {path}")
    if not isinstance(manifest.get("updates"), list):
        raise ValueError(f"materialization manifest lacks updates: {path}")
    return manifest


def _artifact_identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(Path(str(artifact["path"])).resolve()),
        "sha256": str(artifact["sha256"]),
        "vertices": int(artifact["vertices"]),
        "records": int(artifact["records"]),
        "case_id": str(artifact["case_id"]),
    }


def _select_update(
    manifest: Mapping[str, Any],
    *,
    projection: str,
    scenario: str,
    batch_size: int,
) -> Mapping[str, Any]:
    matches = [
        update
        for update in manifest["updates"]
        if update.get("projection") == projection
        and update.get("scenario") == scenario
        and update.get("user_mutations") == batch_size
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {projection}/{scenario}/u{batch_size} update; "
            f"found {len(matches)}"
        )
    return matches[0]


def _full_pagerank_graph(
    manifest: Mapping[str, Any], edge_cap: int
) -> tuple[Mapping[str, Any], int]:
    slices = manifest.get("full_pagerank_slices", [])
    matches = [row for row in slices if int(row.get("requested_edges", -1)) == edge_cap]
    if len(matches) != 1:
        raise ValueError(f"expected one Full PageRank e{edge_cap} slice")
    return matches[0], edge_cap


def select_publication_case(
    manifest: Mapping[str, Any],
    *,
    system: str,
    algorithm: str,
    scenario: str,
    batch_size: int,
    full_pagerank_edge_cap: int = 4_000_000,
    source_cohort: str = "default",
) -> PublicationCase:
    if system not in PUBLICATION_SYSTEMS:
        raise ValueError(f"unknown publication system: {system}")
    if algorithm not in PUBLICATION_ALGORITHMS:
        raise ValueError(f"unknown publication algorithm: {algorithm}")
    if scenario not in {"insert", "delete", "weight_change", "mixed"}:
        raise ValueError(f"unknown publication update scenario: {scenario}")
    if batch_size <= 0:
        raise ValueError("publication batch size must be positive")

    graphs = manifest["graphs"]
    parameters: dict[str, Any]
    source = 0
    if algorithm == "weighted_sssp":
        graph = graphs["directed"]
        projection = "directed"
        cohorts = graph.get("source_cohorts", {})
        if source_cohort not in cohorts:
            raise ValueError(f"weighted SSSP source cohort is absent: {source_cohort}")
        source = int(cohorts[source_cohort])
        parameters = {"source_cohort": source_cohort}
    elif algorithm == "connected_components":
        graph = graphs["reciprocal"]
        projection = "reciprocal"
        parameters = {
            "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
            "deletion_policy": "full_recompute",
        }
    elif algorithm == "full_pagerank":
        graph, requested = _full_pagerank_graph(
            manifest, full_pagerank_edge_cap
        )
        projection = f"full_pagerank_e{requested}"
        parameters = {"iterations": 3, "damping": 0.85}
    else:
        graph = graphs["residual_sink_free"]
        projection = "residual_sink_free"
        if graph.get("sink_vertices_after_projection") != 0:
            raise ValueError("residual PageRank graph is not sink-free")
        parameters = {
            "damping": 0.85,
            "epsilon": 1.0e-6,
            "max_iterations": 256,
            "residual_contract": "deltahls_sink_free_linf_warm",
        }
    update = _select_update(
        manifest,
        projection=projection,
        scenario=scenario,
        batch_size=batch_size,
    )
    identity = {
        "dataset_id": manifest["dataset_id"],
        "system": system,
        "algorithm": algorithm,
        "scenario": scenario,
        "batch_size": batch_size,
        "graph_sha256": graph["sha256"],
        "update_sha256": update["sha256"],
        "source": source,
        "parameters": parameters,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return PublicationCase(
        dataset_id=str(manifest["dataset_id"]),
        system=system,
        algorithm=algorithm,
        scenario=scenario,
        batch_size=batch_size,
        graph=_artifact_identity(graph),
        update={
            **_artifact_identity(update),
            "user_mutations": int(update["user_mutations"]),
            "physical_records": int(update["physical_records"]),
            "projection": str(update["projection"]),
        },
        source=source,
        algorithm_parameters=parameters,
        execution_id=digest[:20],
    )


def deduplicate_publication_cases(
    cases: Sequence[tuple[str, PublicationCase]],
) -> tuple[list[PublicationCase], dict[str, list[str]]]:
    by_id: dict[str, PublicationCase] = {}
    views: dict[str, list[str]] = {}
    for tier, case in cases:
        existing = by_id.get(case.execution_id)
        if existing is not None and existing != case:
            raise ValueError("publication execution hash collision")
        by_id[case.execution_id] = case
        views.setdefault(case.execution_id, []).append(tier)
    ordered = sorted(
        by_id.values(),
        key=lambda case: (
            case.dataset_id,
            case.algorithm,
            case.scenario,
            case.batch_size,
            case.system,
        ),
    )
    return ordered, {key: sorted(set(value)) for key, value in views.items()}


def comparison_run(case: PublicationCase) -> dict[str, Any]:
    if case.algorithm == "weighted_sssp":
        algorithm = "weighted_dynamic_sssp"
        scenario = {
            "insert": "incremental_insert",
            "delete": "full_rebuild_delete",
            "weight_change": "full_rebuild_increase",
            "mixed": "full_rebuild_delete",
        }[case.scenario]
    else:
        algorithm = case.algorithm
        scenario = case.scenario
    run: dict[str, Any] = {
        "run_id": case.execution_id,
        "fixture_id": case.dataset_id,
        "dataset_kind": "real",
        "role": "publication_large_graph",
        "algorithm": algorithm,
        "reporting_algorithm": case.algorithm,
        "scenario": scenario,
        "graph": dict(case.graph),
        "update": dict(case.update),
        "source": case.source,
        "max_rounds": 4_096,
    }
    run.update(case.algorithm_parameters)
    if case.algorithm == "full_pagerank":
        run["iterations"] = int(case.algorithm_parameters["iterations"])
        run["damping"] = float(case.algorithm_parameters["damping"])
    elif case.algorithm == "thresholded_residual_pagerank":
        run["damping"] = float(case.algorithm_parameters["damping"])
        run["epsilon"] = float(case.algorithm_parameters["epsilon"])
        run["max_iterations"] = int(case.algorithm_parameters["max_iterations"])
        run["residual_contract"] = str(
            case.algorithm_parameters["residual_contract"]
        )
    return run


def architecture_profile_paths(
    contract: Mapping[str, Any], system: str, repository_root: Path
) -> tuple[Path, ...]:
    root = repository_root.resolve()
    baselines = contract["architecture_baselines"]
    if system == "spine":
        return (root / str(baselines["spine"]["profile"]),)
    profiles = baselines[system]["profiles"]
    return tuple(
        root / str(profiles[algorithm][0])
        for algorithm in (
            "weighted_sssp",
            "full_pagerank",
            "thresholded_residual_pagerank",
        )
    )
