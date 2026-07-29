"""Frozen contract helpers for the publication-scale graph campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


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
    if matrix["update_performance"].get("batch_sizes") != [1, 8, 64]:
        raise ValueError("large-graph campaign small-batch set changed")
    if set(matrix["update_performance"].get("scenarios", ())) != {
        "insert",
        "delete",
        "weight_change",
    }:
        raise ValueError("large-graph campaign update scenarios changed")
    if matrix["dense"].get("batch_sizes") != [64, 512, 4096]:
        raise ValueError("large-graph campaign dense batches changed")

    semantics = contract.get("workload_semantics", {})
    full_pr = semantics.get("full_pagerank", {})
    if full_pr.get("edge_cap") != 4_000_000:
        raise ValueError("Full PageRank edge cap must remain 4M")
    residual = semantics.get("thresholded_residual_pagerank", {})
    if residual.get("per_vertex_threshold") != 1.0e-6:
        raise ValueError("Residual PageRank threshold must remain per-vertex 1e-6")
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
