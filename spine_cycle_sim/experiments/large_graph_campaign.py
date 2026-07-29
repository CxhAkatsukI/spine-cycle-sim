"""Frozen contract helpers for the publication-scale graph campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .publication_cases import (
    deduplicate_publication_cases,
    load_materialization_manifest,
    publication_case_requests,
    select_publication_case,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LARGE_GRAPH_CAMPAIGN_CONTRACT = (
    ROOT / "configs" / "contracts" / "large_graph_publication_campaign_v1.json"
)

REQUIRED_DATASET_IDS = (
    "sx_askubuntu",
    "sx_superuser",
    "wiki_talk_temporal",
    "sx_stackoverflow",
    "soc_bitcoin",
    "hollywood_2009",
    "soc_pokec",
    "soc_orkut",
    "soc_livejournal1",
    "ljournal_2008",
    "uk_2002",
)
REQUIRED_ALGORITHMS = (
    "weighted_sssp",
    "connected_components",
    "full_pagerank",
    "thresholded_residual_pagerank",
)
REQUIRED_SYSTEMS = (
    "spine",
    "grasu_regraph_k1",
    "grasu_regraph_k4_shared",
)


@dataclass(frozen=True)
class SourceVerification:
    dataset_id: str
    path: Path
    expected_size: int
    actual_size: int | None
    expected_sha256: str
    actual_sha256: str | None
    status: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_large_graph_campaign_contract(
    contract: Mapping[str, Any],
) -> None:
    if contract.get("schema_version") != 1:
        raise ValueError("large-graph campaign schema_version must be 1")
    datasets = contract.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("large-graph campaign datasets must be a list")
    dataset_ids = [dataset.get("dataset_id") for dataset in datasets]
    if tuple(dataset_ids) != REQUIRED_DATASET_IDS:
        raise ValueError("large-graph campaign dataset order or membership changed")
    if len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("large-graph campaign dataset IDs are not unique")
    for dataset in datasets:
        source = dataset.get("source")
        if not isinstance(source, Mapping):
            raise ValueError(f"{dataset.get('dataset_id')} lacks source metadata")
        relative_path = source.get("relative_path")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
        ):
            raise ValueError(f"invalid source path for {dataset.get('dataset_id')}")
        if not isinstance(source.get("size_bytes"), int) or source["size_bytes"] <= 0:
            raise ValueError(f"invalid source size for {dataset.get('dataset_id')}")
        if not _is_sha256(source.get("sha256")):
            raise ValueError(f"invalid source hash for {dataset.get('dataset_id')}")

    matrix = contract.get("experiment_matrix")
    if not isinstance(matrix, Mapping):
        raise ValueError("large-graph campaign experiment_matrix is missing")
    if tuple(matrix.get("systems", ())) != REQUIRED_SYSTEMS:
        raise ValueError("large-graph campaign system baselines changed")
    if tuple(matrix["main_e2e"].get("algorithms", ())) != REQUIRED_ALGORITHMS:
        raise ValueError("large-graph campaign algorithm set changed")
    if matrix["main_e2e"].get("batch_sizes") != [8]:
        raise ValueError("large-graph campaign primary batch must remain 8")
    endpoint_tier = matrix.get("endpoint_scalability", {})
    if (
        endpoint_tier.get("datasets") != ["rmat_19_32"]
        or tuple(endpoint_tier.get("algorithms", ())) != REQUIRED_ALGORITHMS
        or endpoint_tier.get("scenario") != "insert"
        or endpoint_tier.get("batch_sizes") != [8]
    ):
        raise ValueError("R19 endpoint scalability tier changed")
    if matrix["update_performance"].get("batch_sizes") != [1, 8, 64]:
        raise ValueError("large-graph campaign small-batch set changed")
    if matrix["update_performance"].get("execution_algorithm") != "weighted_sssp":
        raise ValueError("update-throughput execution algorithm changed")
    if set(matrix["update_performance"].get("scenarios", ())) != {
        "insert",
        "delete",
        "weight_change",
    }:
        raise ValueError("large-graph campaign update scenarios changed")
    if matrix["dense"].get("batch_sizes") != [64, 512, 4096]:
        raise ValueError("large-graph campaign dense batches changed")

    baselines = contract.get("architecture_baselines", {})
    spine = baselines.get("spine", {})
    if (
        spine.get("role") != "primary_projected_optimized"
        or not _is_sha256(spine.get("sha256"))
        or spine.get("partitions") != 16
        or spine.get("hbm_pseudo_channels") != 23
    ):
        raise ValueError("large-graph campaign Spine baseline changed")
    for system in ("grasu_regraph_k1", "grasu_regraph_k4_shared"):
        baseline = baselines.get(system, {})
        profiles = baseline.get("profiles", {})
        if (
            set(profiles) != set(REQUIRED_ALGORITHMS)
            or baseline.get("conversion_free") is not True
            or baseline.get("addressing")
            != "runtime_packed_v1_capacity_checked"
        ):
            raise ValueError(f"large-graph campaign {system} baseline changed")
        for algorithm in REQUIRED_ALGORITHMS:
            profile = profiles.get(algorithm)
            if (
                not isinstance(profile, list)
                or len(profile) != 2
                or not isinstance(profile[0], str)
                or Path(profile[0]).is_absolute()
                or ".." in Path(profile[0]).parts
                or not _is_sha256(profile[1])
            ):
                raise ValueError(f"invalid {system}/{algorithm} profile identity")
    shared = baselines["grasu_regraph_k4_shared"]
    if (
        shared.get("role") != "primary_multi_partition_competitor"
        or shared.get("compute_pipelines") != 4
        or shared.get("downstream_paths") != 1
        or shared.get("shared_hbm_arbitration") is not True
        or any(
            "_k4_shared_multipart_" not in profile[0]
            for profile in shared["profiles"].values()
        )
    ):
        raise ValueError("primary K4 baseline is not shared-downstream")
    ideal = baselines.get("grasu_regraph_k4_ideal", {})
    if (
        ideal.get("role") != "theoretical_no_contention_upper_bound_only"
        or ideal.get("eligible_for_headline_aggregate") is not False
        or set(ideal.get("profiles", {})) != set(REQUIRED_ALGORITHMS)
    ):
        raise ValueError("direct K4 upper-bound labeling changed")
    common_memory = baselines.get("common_memory", {})
    capabilities = baselines.get("grasu_regraph_capability_catalog", {})
    simulator = baselines.get("simulator_baseline", {})
    if (
        common_memory.get("backend") != "direct_dramsim3_transport"
        or common_memory.get("physical_channels") != 32
        or common_memory.get("line_bytes") != 64
        or not _is_sha256(common_memory.get("sha256"))
        or capabilities.get("path")
        != "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
        or capabilities.get("sha256")
        != "93b10252f3a2f998da9a851ebf2abeb588cb8edef4a8ac253d217553a793c346"
        or not _is_sha256(simulator.get("plugin_sha256"))
    ):
        raise ValueError("large-graph campaign common platform changed")

    semantics = contract.get("workload_semantics", {})
    full_pr = semantics.get("full_pagerank", {})
    if full_pr.get("edge_cap") != 4_000_000:
        raise ValueError("Full PageRank edge cap must remain 4M")
    residual = semantics.get("thresholded_residual_pagerank", {})
    if (
        residual.get("per_vertex_threshold") != 1.0e-6
        or residual.get("threshold_semantics")
        != "abs_residual_per_vertex_gt_threshold"
        or residual.get("execution_contract")
        != "deltahls_sink_free_linf_warm"
        or residual.get("graph_projection")
        != "add_self_loop_to_each_zero_outdegree_vertex_v1"
    ):
        raise ValueError("Residual PageRank threshold must remain per-vertex 1e-6")
    if (
        semantics.get("full_pagerank", {}).get("slice_policy")
        != "exact_min_edge_hash_preserving_original_vertex_ids_v2"
    ):
        raise ValueError("Full PageRank slice policy changed")
    if semantics.get("preserve_external_vertex_ids") is not True:
        raise ValueError("large-graph campaign must preserve external vertex IDs")

    endpoint = contract.get("synthetic_endpoint", {})
    endpoint_source = endpoint.get("source", {})
    if (
        endpoint.get("dataset_id") != "rmat_19_32"
        or endpoint.get("expected_unique_directed_edges") != 15_483_485
        or endpoint.get("materialized_source_records") != 15_483_988
        or endpoint.get("self_loops_removed") != 503
        or endpoint_source.get("size_bytes") != 225_511_166
        or endpoint_source.get("sha256")
        != "00a8886a5d0836e2839d50401142056f76cccd854845701b7a6100ca6db31125"
        or endpoint_source.get("encoding") != "one_based_dst_src_text"
    ):
        raise ValueError("R19 source identity or normalization counts changed")

    admission = contract.get("correctness_admission", {})
    required_gates = (
        "architecture_precision_oracle",
        "independent_mathematical_oracle",
        "cross_system_final_state",
        "updated_graph_degree_and_active_state",
        "request_response_byte_and_dram_conservation",
        "full_result_vector_required",
    )
    if not all(admission.get(gate) is True for gate in required_gates):
        raise ValueError("large-graph campaign correctness admission was weakened")

    execution = contract.get("execution", {})
    if execution.get("automatic_timeout_seconds") is not None:
        raise ValueError("formal campaign must use auditable soft-stop, not timeout")
    if execution.get("host_available_memory_reserve_gib") != 32:
        raise ValueError("formal campaign memory reserve changed")


def load_large_graph_campaign_contract(
    path: Path = DEFAULT_LARGE_GRAPH_CAMPAIGN_CONTRACT,
) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="ascii"))
    validate_large_graph_campaign_contract(contract)
    return contract


def verify_large_graph_sources(
    contract: Mapping[str, Any],
    dataset_root: Path,
    *,
    rehash: bool = False,
) -> list[SourceVerification]:
    validate_large_graph_campaign_contract(contract)
    root = dataset_root.resolve()
    rows: list[SourceVerification] = []
    for dataset in contract["datasets"]:
        source = dataset["source"]
        path = root / source["relative_path"]
        expected_size = int(source["size_bytes"])
        expected_hash = str(source["sha256"])
        if not path.is_file():
            rows.append(
                SourceVerification(
                    dataset_id=str(dataset["dataset_id"]),
                    path=path,
                    expected_size=expected_size,
                    actual_size=None,
                    expected_sha256=expected_hash,
                    actual_sha256=None,
                    status="missing",
                )
            )
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256(path) if rehash else None
        size_ok = actual_size == expected_size
        hash_ok = actual_hash == expected_hash if rehash else True
        rows.append(
            SourceVerification(
                dataset_id=str(dataset["dataset_id"]),
                path=path,
                expected_size=expected_size,
                actual_size=actual_size,
                expected_sha256=expected_hash,
                actual_sha256=actual_hash,
                status="ok" if size_ok and hash_ok else "mismatch",
            )
        )
    return rows


def planned_system_runs(contract: Mapping[str, Any]) -> dict[str, int]:
    """Return pre-deduplication system-run counts for each frozen tier."""

    validate_large_graph_campaign_contract(contract)
    dataset_count = len(contract["datasets"])
    system_count = len(contract["experiment_matrix"]["systems"])
    matrix = contract["experiment_matrix"]
    return {
        "main_e2e": dataset_count
        * len(matrix["main_e2e"]["algorithms"])
        * len(matrix["main_e2e"]["batch_sizes"])
        * system_count,
        "endpoint_scalability": len(matrix["endpoint_scalability"]["datasets"])
        * len(matrix["endpoint_scalability"]["algorithms"])
        * len(matrix["endpoint_scalability"]["batch_sizes"])
        * system_count,
        "update_performance": dataset_count
        * len(matrix["update_performance"]["scenarios"])
        * len(matrix["update_performance"]["batch_sizes"])
        * system_count,
        "update_triggered_compute": len(matrix["update_triggered_compute"]["datasets"])
        * len(matrix["update_triggered_compute"]["algorithms"])
        * len(matrix["update_triggered_compute"]["scenarios"])
        * len(matrix["update_triggered_compute"]["batch_sizes"])
        * system_count,
        "dense": len(matrix["dense"]["datasets"])
        * len(matrix["dense"]["algorithms"])
        * len(matrix["dense"]["batch_sizes"])
        * system_count,
        "mixed_supplement": len(matrix["mixed_supplement"]["datasets"])
        * len(matrix["mixed_supplement"]["algorithms"])
        * len(matrix["mixed_supplement"]["batch_sizes"])
        * system_count,
    }


def build_materialization_campaign_manifest(
    contract: Mapping[str, Any],
    *,
    output_root: Path,
    python: str,
    repository_root: Path = ROOT,
    include_r19: bool = False,
    sort_parallel: int = 8,
    sort_memory: str = "4G",
) -> dict[str, Any]:
    validate_large_graph_campaign_contract(contract)
    if sort_parallel <= 0:
        raise ValueError("materialization sort parallelism must be positive")
    root = repository_root.resolve()
    output = output_root.resolve()
    datasets = list(contract["datasets"])
    if include_r19:
        endpoint = contract["synthetic_endpoint"]
        datasets.append(
            {
                "dataset_id": endpoint["dataset_id"],
                "source": {"size_bytes": endpoint["source"]["size_bytes"]},
            }
        )
    jobs = []
    for priority, dataset in enumerate(datasets):
        dataset_id = str(dataset["dataset_id"])
        source_size = int(dataset["source"]["size_bytes"])
        large = source_size >= 128 * 1024 * 1024
        jobs.append(
            {
                "job_id": f"materialize.{dataset_id}",
                "command": [
                    python,
                    str(root / "scripts/materialize_publication_workload.py"),
                    "--dataset",
                    dataset_id,
                    "--out-dir",
                    str(output / "workloads" / dataset_id),
                    "--sort-parallel",
                    str(sort_parallel),
                    "--sort-memory",
                    sort_memory,
                ],
                "cwd": str(root),
                "dataset_id": dataset_id,
                "algorithm": "materialization",
                "system": "shared_workload",
                "tier": "preprocess",
                "resource_class": "large" if large else "small",
                "estimated_rss_gib": 6.0 if large else 3.0,
                "priority": priority,
                "dependencies": [],
                "environment": {},
            }
        )
    return {
        "schema_version": 1,
        "campaign_id": f"{contract['contract_id']}_materialization",
        "default_cwd": str(root),
        "contract_id": contract["contract_id"],
        "output_root": str(output),
        "jobs": jobs,
    }


def _publication_rss_gib(vertices: int, records: int) -> float:
    estimated_bytes = 1.0 * 2**30 + vertices * 64 + records * 96
    return round(min(48.0, max(1.5, estimated_bytes / 2**30)), 2)


def build_publication_experiment_campaign_manifest(
    contract: Mapping[str, Any],
    *,
    materialization_root: Path,
    output_root: Path,
    python: str,
    sst: Path,
    lib_dir: Path,
    capability_catalog: Path,
    contract_path: Path = DEFAULT_LARGE_GRAPH_CAMPAIGN_CONTRACT,
    repository_root: Path = ROOT,
    selected_tiers: set[str] | None = None,
    selected_datasets: set[str] | None = None,
    selected_algorithms: set[str] | None = None,
    selected_systems: set[str] | None = None,
    max_cycles: int = 10_000_000_000_000,
) -> dict[str, Any]:
    """Build the de-duplicated, correctness-gated publication run manifest."""

    validate_large_graph_campaign_contract(contract)
    if max_cycles <= 0:
        raise ValueError("publication max cycles must be positive")
    root = repository_root.resolve()
    materialized = materialization_root.resolve()
    output = output_root.resolve()
    requests = publication_case_requests(contract)
    known_tiers = {request.tier for request in requests}
    if selected_tiers is not None and not selected_tiers <= known_tiers:
        raise ValueError(
            f"unknown publication tiers: {sorted(selected_tiers - known_tiers)}"
        )
    known_datasets = {request.dataset_id for request in requests}
    if selected_datasets is not None and not selected_datasets <= known_datasets:
        raise ValueError(
            "unknown publication datasets: "
            f"{sorted(selected_datasets - known_datasets)}"
        )
    known_algorithms = {request.algorithm for request in requests}
    if (
        selected_algorithms is not None
        and not selected_algorithms <= known_algorithms
    ):
        raise ValueError(
            "unknown publication algorithms: "
            f"{sorted(selected_algorithms - known_algorithms)}"
        )
    known_systems = {request.system for request in requests}
    if selected_systems is not None and not selected_systems <= known_systems:
        raise ValueError(
            "unknown publication systems: "
            f"{sorted(selected_systems - known_systems)}"
        )
    requests = tuple(
        request
        for request in requests
        if (selected_tiers is None or request.tier in selected_tiers)
        and (
            selected_datasets is None
            or request.dataset_id in selected_datasets
        )
        and (
            selected_algorithms is None
            or request.algorithm in selected_algorithms
        )
        and (selected_systems is None or request.system in selected_systems)
    )
    if not requests:
        raise ValueError("publication campaign selection is empty")

    manifests: dict[str, tuple[Path, dict[str, Any]]] = {}
    requested_cases = []
    edge_cap = int(contract["workload_semantics"]["full_pagerank"]["edge_cap"])
    for request in requests:
        if request.dataset_id not in manifests:
            path = (
                materialized
                / "workloads"
                / request.dataset_id
                / "materialization_manifest.json"
            )
            manifests[request.dataset_id] = (
                path,
                load_materialization_manifest(path),
            )
        manifest = manifests[request.dataset_id][1]
        case = select_publication_case(
            manifest,
            system=request.system,
            algorithm=request.algorithm,
            scenario=request.scenario,
            batch_size=request.batch_size,
            full_pagerank_edge_cap=edge_cap,
            source_cohort=request.source_cohort,
        )
        requested_cases.append((request.tier, case))
    cases, views = deduplicate_publication_cases(requested_cases)

    tier_priority = {
        "main_e2e": 0,
        "endpoint_scalability": 50,
        "update_performance": 100,
        "update_triggered_compute": 200,
        "dense": 300,
        "mixed_supplement": 400,
    }
    jobs = []
    for case in cases:
        case_views = views[case.execution_id]
        runner = (
            "run_publication_cc_case.py"
            if case.algorithm == "connected_components"
            else "run_publication_case.py"
        )
        command = [
            python,
            str(root / "scripts" / runner),
            "--materialization-manifest",
            str(manifests[case.dataset_id][0]),
            "--system",
            case.system,
            "--algorithm",
            case.algorithm,
            "--scenario",
            case.scenario,
            "--batch-size",
            str(case.batch_size),
            "--out-dir",
            str(output / "runs" / case.execution_id),
            "--contract",
            str(contract_path.resolve()),
            "--sst",
            str(sst.resolve()),
            "--lib-dir",
            str(lib_dir.resolve()),
            "--capability-catalog",
            str(capability_catalog.resolve()),
            "--max-cycles",
            str(max_cycles),
        ]
        if case.algorithm != "connected_components":
            command.extend(
                (
                    "--source-cohort",
                    str(case.algorithm_parameters.get("source_cohort", "default")),
                    "--full-pagerank-edge-cap",
                    str(edge_cap),
                )
            )
        for view in case_views:
            command.extend(("--logical-view", view))
        vertices = int(case.graph["vertices"])
        records = int(case.graph["records"])
        rss_gib = _publication_rss_gib(vertices, records)
        base_priority = min(tier_priority[view] for view in case_views)
        jobs.append(
            {
                "job_id": (
                    f"run.{case.dataset_id}.{case.algorithm}.{case.scenario}."
                    f"u{case.batch_size}.{case.system}.{case.execution_id}"
                ),
                "command": command,
                "cwd": str(root),
                "dataset_id": case.dataset_id,
                "algorithm": case.algorithm,
                "system": case.system,
                "tier": "+".join(case_views),
                "resource_class": "large" if rss_gib >= 4.0 else "small",
                "estimated_rss_gib": rss_gib,
                "priority": base_priority + min(90, records // 1_000_000),
                "dependencies": [],
                "environment": {
                    "SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES": "1000000"
                },
            }
        )
    jobs.sort(key=lambda job: (job["priority"], job["job_id"]))
    return {
        "schema_version": 1,
        "campaign_id": f"{contract['contract_id']}_formal_execution",
        "default_cwd": str(root),
        "contract_id": contract["contract_id"],
        "contract_path": str(contract_path.resolve()),
        "contract_sha256": _sha256(contract_path.resolve()),
        "materialization_root": str(materialized),
        "output_root": str(output),
        "logical_view_count": len(requests),
        "physical_execution_count": len(cases),
        "selected_tiers": sorted(selected_tiers or known_tiers),
        "selected_datasets": sorted(selected_datasets or known_datasets),
        "selected_algorithms": sorted(selected_algorithms or known_algorithms),
        "selected_systems": sorted(selected_systems or known_systems),
        "execution_views": views,
        "materialization_manifests": {
            dataset_id: {
                "path": str(path),
                "sha256": _sha256(path),
            }
            for dataset_id, (path, _manifest) in sorted(manifests.items())
        },
        "jobs": jobs,
    }
