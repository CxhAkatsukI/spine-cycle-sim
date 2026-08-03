"""Strict loader for the frozen Spine paper-architecture contract."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


class AlignmentContractError(ValueError):
    """Raised when the paper, simulator, and HLS contract is inconsistent."""


@dataclass(frozen=True)
class AlignmentContract:
    contract_id: str
    status: str
    payload: dict[str, Any]
    sha256: str


_ROOT_FIELDS = {
    "schema_version",
    "contract_id",
    "status",
    "authority",
    "platform",
    "organization",
    "scheduler",
    "execution_boundary",
    "graph_semantics",
    "algorithms",
    "validation",
    "provenance",
}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AlignmentContractError(f"{field} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], field: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise AlignmentContractError(f"{field} fields invalid ({'; '.join(details)})")


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AlignmentContractError(f"{field} must be a positive integer")
    return value


def _sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise AlignmentContractError(f"{field} must be a lowercase SHA-256")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise AlignmentContractError(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise AlignmentContractError(f"{field} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise AlignmentContractError(f"{field} contains duplicates")
    return value


def _validate_contract(root: dict[str, Any]) -> None:
    _exact_fields(root, _ROOT_FIELDS, "contract")
    if root["schema_version"] != 1:
        raise AlignmentContractError("only schema_version=1 is supported")
    if root["status"] != "frozen":
        raise AlignmentContractError("alignment contract must be frozen")

    authority = _mapping(root["authority"], "authority")
    _exact_fields(
        authority,
        {
            "paper_repository",
            "paper_revision",
            "paper_dirty",
            "paper_files",
        },
        "authority",
    )
    if authority["paper_dirty"] is not False:
        raise AlignmentContractError("paper authority must be a clean revision")
    revision = authority["paper_revision"]
    if not isinstance(revision, str) or len(revision) != 40:
        raise AlignmentContractError("authority.paper_revision must be a full git hash")
    paper_files = authority["paper_files"]
    if not isinstance(paper_files, list) or not paper_files:
        raise AlignmentContractError("authority.paper_files must be non-empty")
    paper_paths: set[str] = set()
    for index, item in enumerate(paper_files):
        entry = _mapping(item, f"authority.paper_files[{index}]")
        _exact_fields(entry, {"path", "sha256"}, f"authority.paper_files[{index}]")
        path = entry["path"]
        if not isinstance(path, str) or not path.startswith("sections/"):
            raise AlignmentContractError("paper authority paths must be section files")
        if path in paper_paths:
            raise AlignmentContractError(f"duplicate paper authority path {path}")
        paper_paths.add(path)
        _sha256(entry["sha256"], f"authority.paper_files[{index}].sha256")

    platform = _mapping(root["platform"], "platform")
    _exact_fields(
        platform,
        {
            "accelerator_clock_mhz",
            "hbm_clock_mhz",
            "hbm_pseudo_channels",
            "hbm_pseudo_channel_budget",
            "hbm_channel_capacity_bytes",
            "axi_data_width_bits",
            "axi_max_burst_bytes",
            "axi_max_outstanding_per_port",
        },
        "platform",
    )
    for field in platform:
        _positive_int(platform[field], f"platform.{field}")
    if platform["hbm_pseudo_channel_budget"] > platform["hbm_pseudo_channels"]:
        raise AlignmentContractError("HBM budget exceeds physical channel count")

    organization = _mapping(root["organization"], "organization")
    _exact_fields(
        organization,
        {
            "vertex_partitions",
            "cold_families",
            "hot_families",
            "families",
            "levels",
            "level_ratio",
            "compute_lanes",
            "tile_vertices",
            "max_vertices",
            "graph_hbm_channels",
            "control_hbm_channels",
            "finite_queues",
        },
        "organization",
    )
    for field in (
        "vertex_partitions",
        "cold_families",
        "hot_families",
        "families",
        "levels",
        "level_ratio",
        "compute_lanes",
        "tile_vertices",
        "max_vertices",
    ):
        _positive_int(organization[field], f"organization.{field}")
    if organization["families"] != (
        organization["cold_families"] + organization["hot_families"]
    ):
        raise AlignmentContractError("family total does not match hot/cold ownership")
    graph_channels = organization["graph_hbm_channels"]
    if graph_channels != list(range(organization["cold_families"])):
        raise AlignmentContractError("graph HBM channels must map one-to-one to cold families")
    control_channels = _mapping(
        organization["control_hbm_channels"], "organization.control_hbm_channels"
    )
    _exact_fields(
        control_channels,
        {
            "sorted_edges",
            "vertex_state",
            "active_bins",
            "active_out",
            "metadata",
            "result",
            "active_bitmap",
        },
        "organization.control_hbm_channels",
    )
    all_channels = graph_channels + list(control_channels.values())
    if len(set(all_channels)) != len(all_channels):
        raise AlignmentContractError("HBM channel mapping contains aliases")
    if max(all_channels) >= platform["hbm_pseudo_channels"]:
        raise AlignmentContractError("HBM channel mapping exceeds platform")
    if len(all_channels) != platform["hbm_pseudo_channel_budget"]:
        raise AlignmentContractError("HBM mapping does not consume the frozen budget")
    finite_queues = _mapping(
        organization["finite_queues"], "organization.finite_queues"
    )
    _exact_fields(
        finite_queues,
        {
            "edge_stream_depth",
            "value_stream_depth",
            "command_fifo_depth",
            "owner_fifo_depth_per_partition",
            "reactivation_fifo_depth_per_partition",
        },
        "organization.finite_queues",
    )
    for field, value in finite_queues.items():
        _positive_int(value, f"organization.finite_queues.{field}")

    scheduler = _mapping(root["scheduler"], "scheduler")
    _exact_fields(
        scheduler,
        {
            "owner_state_bits",
            "device_determines_active_membership",
            "host_may_rebin_device_ids",
            "host_may_recompute_active_membership",
            "no_lost_reactivation",
            "finite_fifo_backpressure",
            "work_credit_quiescence",
        },
        "scheduler",
    )
    if set(_string_list(scheduler["owner_state_bits"], "scheduler.owner_state_bits")) != {
        "queued",
        "in_flight",
        "dirty",
    }:
        raise AlignmentContractError("owner scheduler must expose queued/in_flight/dirty")
    required_true = (
        "device_determines_active_membership",
        "host_may_rebin_device_ids",
        "no_lost_reactivation",
        "finite_fifo_backpressure",
        "work_credit_quiescence",
    )
    if any(scheduler[field] is not True for field in required_true):
        raise AlignmentContractError("required scheduler behavior is disabled")
    if scheduler["host_may_recompute_active_membership"] is not False:
        raise AlignmentContractError("host may not recompute active membership")

    boundary = _mapping(root["execution_boundary"], "execution_boundary")
    _exact_fields(boundary, {"start", "stop", "included", "excluded"}, "execution_boundary")
    included = set(_string_list(boundary["included"], "execution_boundary.included"))
    excluded = set(_string_list(boundary["excluded"], "execution_boundary.excluded"))
    if included & excluded:
        raise AlignmentContractError("execution boundary includes and excludes the same work")
    for required in ("device_active_generation", "reactivation", "drain_and_sync"):
        if required not in included:
            raise AlignmentContractError(f"execution boundary omits {required}")

    semantics = _mapping(root["graph_semantics"], "graph_semantics")
    _exact_fields(
        semantics,
        {
            "edge_identity",
            "payload_distinct_parallel_edges",
            "fixed_vertex_capacity",
            "vertex_lifecycle",
            "vertex_delete_incident_edges",
            "pagerank_vertex_universe",
        },
        "graph_semantics",
    )
    if semantics["fixed_vertex_capacity"] is not True:
        raise AlignmentContractError("this contract requires bounded vertex IDs")
    if semantics["edge_identity"] != "endpoint_keyed_src_dst":
        raise AlignmentContractError("v1 must preserve the routed endpoint-keyed baseline")
    if semantics["payload_distinct_parallel_edges"] != "deferred_extension":
        raise AlignmentContractError("parallel-edge extension must remain separately versioned")

    algorithms = _mapping(root["algorithms"], "algorithms")
    _exact_fields(
        algorithms,
        {
            "required",
            "shared_shell",
            "specialized_policy_kernels",
            "residual_pagerank_threshold",
            "pagerank_damping",
        },
        "algorithms",
    )
    required_algorithms = {
        "weighted_sssp",
        "connected_components",
        "thresholded_residual_pagerank",
        "full_pagerank",
    }
    if set(_string_list(algorithms["required"], "algorithms.required")) != required_algorithms:
        raise AlignmentContractError("the four frozen algorithm policies are required")
    if algorithms["shared_shell"] is not True or algorithms["specialized_policy_kernels"] is not True:
        raise AlignmentContractError("algorithms must share a shell and specialize policy kernels")

    validation = _mapping(root["validation"], "validation")
    _exact_fields(
        validation,
        {
            "fpga_repeats_per_case",
            "non_tiny_total_cycle_median_error_percent_max",
            "non_tiny_total_cycle_error_percent_max",
            "component_cycle_median_error_percent_max",
            "workload_rank_spearman_min",
            "system_memory_reserve_gib",
            "calibration_edge_scales",
            "holdout_edge_scale_min",
            "holdout_edge_scale_max",
            "holdout_is_immutable",
        },
        "validation",
    )
    for field in (
        "fpga_repeats_per_case",
        "non_tiny_total_cycle_median_error_percent_max",
        "non_tiny_total_cycle_error_percent_max",
        "component_cycle_median_error_percent_max",
        "system_memory_reserve_gib",
        "holdout_edge_scale_min",
        "holdout_edge_scale_max",
    ):
        _positive_int(validation[field], f"validation.{field}")
    scales = validation["calibration_edge_scales"]
    if not isinstance(scales, list) or any(_positive_int(value, "calibration edge scale") <= 0 for value in scales):
        raise AlignmentContractError("calibration_edge_scales must be positive integers")
    if validation["holdout_edge_scale_min"] > validation["holdout_edge_scale_max"]:
        raise AlignmentContractError("holdout range is reversed")
    if validation["holdout_is_immutable"] is not True:
        raise AlignmentContractError("holdout must be immutable")
    spearman = validation["workload_rank_spearman_min"]
    if not isinstance(spearman, (int, float)) or not 0 < spearman <= 1:
        raise AlignmentContractError("Spearman gate must be in (0, 1]")

    provenance = _mapping(root["provenance"], "provenance")
    _exact_fields(
        provenance,
        {
            "refactor31_base_revision",
            "refactor31_source_diff_sha256",
            "refactor31_xclbin_sha256",
            "refactor31_clock_mhz",
            "simulator_branch",
            "hls_branch",
        },
        "provenance",
    )
    _sha256(provenance["refactor31_source_diff_sha256"], "provenance.refactor31_source_diff_sha256")
    _sha256(provenance["refactor31_xclbin_sha256"], "provenance.refactor31_xclbin_sha256")
    _positive_int(provenance["refactor31_clock_mhz"], "provenance.refactor31_clock_mhz")


def load_alignment_contract(path: str | Path) -> AlignmentContract:
    """Load and fail closed on any architecture-contract drift."""

    contract_path = Path(path)
    raw = contract_path.read_bytes()
    try:
        payload = _mapping(json.loads(raw), "contract")
    except json.JSONDecodeError as exc:
        raise AlignmentContractError(f"invalid JSON in {contract_path}: {exc}") from exc
    _validate_contract(payload)
    contract_id = payload["contract_id"]
    if not isinstance(contract_id, str) or not contract_id:
        raise AlignmentContractError("contract_id must be a non-empty string")
    return AlignmentContract(
        contract_id=contract_id,
        status=payload["status"],
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def render_hls_contract_header(contract: AlignmentContract) -> str:
    """Render the constants HLS must compile against, including the contract hash."""

    platform = contract.payload["platform"]
    organization = contract.payload["organization"]
    queues = organization["finite_queues"]
    lines = [
        "#ifndef SPINE_PAPER_ARCHITECTURE_CONTRACT_HPP",
        "#define SPINE_PAPER_ARCHITECTURE_CONTRACT_HPP",
        "",
        f'#define SPINE_ALIGNMENT_CONTRACT_ID "{contract.contract_id}"',
        f'#define SPINE_ALIGNMENT_CONTRACT_SHA256 "{contract.sha256}"',
        f"#define SPINE_ALIGNMENT_ACCELERATOR_MHZ {platform['accelerator_clock_mhz']}",
        f"#define SPINE_ALIGNMENT_HBM_MHZ {platform['hbm_clock_mhz']}",
        f"#define SPINE_ALIGNMENT_VERTEX_PARTITIONS {organization['vertex_partitions']}",
        f"#define SPINE_ALIGNMENT_FAMILIES {organization['families']}",
        f"#define SPINE_ALIGNMENT_LEVELS {organization['levels']}",
        f"#define SPINE_ALIGNMENT_LEVEL_RATIO {organization['level_ratio']}",
        f"#define SPINE_ALIGNMENT_COMPUTE_LANES {organization['compute_lanes']}",
        f"#define SPINE_ALIGNMENT_MAX_VERTICES {organization['max_vertices']}",
        f"#define SPINE_ALIGNMENT_EDGE_STREAM_DEPTH {queues['edge_stream_depth']}",
        f"#define SPINE_ALIGNMENT_VALUE_STREAM_DEPTH {queues['value_stream_depth']}",
        f"#define SPINE_ALIGNMENT_COMMAND_FIFO_DEPTH {queues['command_fifo_depth']}",
        f"#define SPINE_ALIGNMENT_OWNER_FIFO_DEPTH {queues['owner_fifo_depth_per_partition']}",
        f"#define SPINE_ALIGNMENT_REACTIVATION_FIFO_DEPTH {queues['reactivation_fifo_depth_per_partition']}",
        f"#define SPINE_ALIGNMENT_AXI_OUTSTANDING {platform['axi_max_outstanding_per_port']}",
        f"#define SPINE_ALIGNMENT_AXI_MAX_BURST_BYTES {platform['axi_max_burst_bytes']}",
        "",
        "#endif",
        "",
    ]
    return "\n".join(lines)
