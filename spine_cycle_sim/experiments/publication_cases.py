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
SPINE_MAX_SORT_EDGES = 131_072
DEFAULT_NONMONOTONIC_SSSP_EDGE_CAP = 64_000


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


@dataclass(frozen=True)
class PublicationCaseRequest:
    tier: str
    dataset_id: str
    system: str
    algorithm: str
    scenario: str
    batch_size: int
    source_cohort: str = "default"


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


def _slice_source_cohorts(artifact: Mapping[str, Any]) -> dict[str, int]:
    """Choose deterministic reachable sources for a bounded weighted slice."""

    degree: dict[int, int] = {}
    path = Path(str(artifact["path"]))
    with path.open("r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 4:
                raise ValueError(f"{path}:{line_number}: expected four edge fields")
            source = int(fields[0])
            degree[source] = degree.get(source, 0) + 1
    if not degree:
        raise ValueError(f"bounded weighted SSSP slice is empty: {path}")
    high = min(degree, key=lambda source: (-degree[source], source))
    ordered = sorted(degree, key=lambda source: (degree[source], source))
    median = ordered[(len(ordered) - 1) // 2]
    random_reachable = min(
        degree,
        key=lambda source: (
            hashlib.sha256(f"bounded-sssp-v1:{source}".encode("ascii")).digest(),
            source,
        ),
    )
    return {
        "default": high,
        "high_degree": high,
        "median_degree": median,
        "random_reachable": random_reachable,
    }


def select_publication_case(
    manifest: Mapping[str, Any],
    *,
    system: str,
    algorithm: str,
    scenario: str,
    batch_size: int,
    full_pagerank_edge_cap: int = 4_000_000,
    nonmonotonic_sssp_edge_cap: int = DEFAULT_NONMONOTONIC_SSSP_EDGE_CAP,
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
        nonmonotonic = scenario in {"delete", "weight_change", "mixed"}
        if nonmonotonic:
            if not 0 < nonmonotonic_sssp_edge_cap <= SPINE_MAX_SORT_EDGES:
                raise ValueError(
                    "non-monotonic SSSP edge cap exceeds the Spine "
                    f"MAX_SORT_EDGES={SPINE_MAX_SORT_EDGES} contract"
                )
            graph, requested = _full_pagerank_graph(
                manifest, nonmonotonic_sssp_edge_cap
            )
            projection = f"full_pagerank_e{requested}"
            cohorts = graph.get("source_cohorts") or _slice_source_cohorts(graph)
        else:
            graph = graphs["directed"]
            projection = "directed"
            cohorts = graph.get("source_cohorts", {})
        if source_cohort not in cohorts:
            raise ValueError(f"weighted SSSP source cohort is absent: {source_cohort}")
        source = int(cohorts[source_cohort])
        parameters = {
            "source_cohort": source_cohort,
            "graph_scope": (
                "bounded_real_topology_nonmonotonic_fallback"
                if nonmonotonic
                else "full_directed_graph"
            ),
            "nonmonotonic_edge_cap": (
                nonmonotonic_sssp_edge_cap if nonmonotonic else None
            ),
        }
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


def publication_dataset_labels(dataset_id: str) -> tuple[str, str]:
    """Return reporting labels without mixing R19 into real-dataset aggregates."""

    if dataset_id == "rmat_19_32":
        return "synthetic", "publication_scalability_endpoint"
    return "real", "publication_large_graph"


def publication_case_requests(
    contract: Mapping[str, Any],
) -> tuple[PublicationCaseRequest, ...]:
    """Expand every logical view in the frozen publication matrix."""

    matrix = contract["experiment_matrix"]
    all_datasets = tuple(str(row["dataset_id"]) for row in contract["datasets"])
    systems = tuple(str(value) for value in matrix["systems"])
    requests: list[PublicationCaseRequest] = []

    def expand(
        tier: str,
        *,
        datasets: Sequence[str],
        algorithms: Sequence[str],
        scenarios: Sequence[str],
        batch_sizes: Sequence[int],
    ) -> None:
        for dataset_id in datasets:
            for algorithm in algorithms:
                for scenario in scenarios:
                    for batch_size in batch_sizes:
                        for system in systems:
                            requests.append(
                                PublicationCaseRequest(
                                    tier=tier,
                                    dataset_id=str(dataset_id),
                                    system=system,
                                    algorithm=str(algorithm),
                                    scenario=str(scenario),
                                    batch_size=int(batch_size),
                                    source_cohort=(
                                        "median_degree"
                                        if str(algorithm) == "weighted_sssp"
                                        else "default"
                                    ),
                                )
                            )

    main = matrix["main_e2e"]
    expand(
        "main_e2e",
        datasets=all_datasets,
        algorithms=main["algorithms"],
        scenarios=(main["scenario"],),
        batch_sizes=main["batch_sizes"],
    )
    endpoint = matrix["endpoint_scalability"]
    expand(
        "endpoint_scalability",
        datasets=endpoint["datasets"],
        algorithms=endpoint["algorithms"],
        scenarios=(endpoint["scenario"],),
        batch_sizes=endpoint["batch_sizes"],
    )
    update = matrix["update_performance"]
    expand(
        "update_performance",
        datasets=all_datasets,
        algorithms=(update["execution_algorithm"],),
        scenarios=update["scenarios"],
        batch_sizes=update["batch_sizes"],
    )
    triggered = matrix["update_triggered_compute"]
    expand(
        "update_triggered_compute",
        datasets=triggered["datasets"],
        algorithms=triggered["algorithms"],
        scenarios=triggered["scenarios"],
        batch_sizes=triggered["batch_sizes"],
    )
    dense = matrix["dense"]
    expand(
        "dense",
        datasets=dense["datasets"],
        algorithms=dense["algorithms"],
        scenarios=(dense["scenario"],),
        batch_sizes=dense["batch_sizes"],
    )
    mixed = matrix["mixed_supplement"]
    expand(
        "mixed_supplement",
        datasets=mixed["datasets"],
        algorithms=mixed["algorithms"],
        scenarios=("mixed",),
        batch_sizes=mixed["batch_sizes"],
    )
    return tuple(requests)


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
    dataset_kind, role = publication_dataset_labels(case.dataset_id)
    run: dict[str, Any] = {
        "run_id": case.execution_id,
        "fixture_id": case.dataset_id,
        "dataset_kind": dataset_kind,
        "role": role,
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


def architecture_profile_path(
    contract: Mapping[str, Any],
    system: str,
    algorithm: str,
    repository_root: Path,
) -> Path:
    """Return the one frozen profile used by a publication system/algorithm pair."""

    if algorithm not in PUBLICATION_ALGORITHMS:
        raise ValueError(f"unknown publication algorithm: {algorithm}")
    root = repository_root.resolve()
    baselines = contract["architecture_baselines"]
    if system == "spine":
        return root / str(baselines["spine"]["profile"])
    if system not in PUBLICATION_SYSTEMS:
        raise ValueError(f"unknown publication system: {system}")
    return root / str(baselines[system]["profiles"][algorithm][0])
