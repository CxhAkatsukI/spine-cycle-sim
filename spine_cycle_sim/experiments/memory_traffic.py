"""Shared accepted-backend traffic and locality contracts."""

from __future__ import annotations

from typing import Mapping


BACKEND_LINE_BYTES = 64
LOCALITY_FIELDS = (
    "requests",
    "bytes",
    "first_requests",
    "first_bytes",
    "contiguous_requests",
    "contiguous_bytes",
    "repeated_requests",
    "repeated_bytes",
    "discontinuous_requests",
    "discontinuous_bytes",
)
ADDITIVE_TRAFFIC_FIELDS = (
    "requests",
    "bytes",
    "read_requests",
    "read_bytes",
    "write_requests",
    "write_bytes",
    "first_requests",
    "first_bytes",
    "contiguous_requests",
    "contiguous_bytes",
    "repeated_requests",
    "repeated_bytes",
    "discontinuous_requests",
    "discontinuous_bytes",
    "classified_requests",
    "classified_bytes",
)


def backpressure_metrics(
    result: Mapping[str, object], *, axis_push_stalls: int
) -> dict[str, int | str | bool]:
    """Normalize FIFO, AXI-request, and HBM-backend stall observations.

    Legacy results intentionally leave the new AXI metric blank. This keeps
    old evidence useful without allowing it to satisfy the complete physical
    memory gate retroactively.
    """

    if axis_push_stalls < 0:
        raise ValueError("axis_push_stalls must be non-negative")
    required = (
        "axi_issue_stalls",
        "hbm_queue_stalls",
        "hbm_response_queue_stalls",
    )
    complete = all(
        isinstance(result.get(field), int)
        and not isinstance(result.get(field), bool)
        and int(result[field]) >= 0
        for field in required
    )
    if not complete:
        return {
            "axis_push_stalls": axis_push_stalls,
            "axi_issue_stalls": "",
            "hbm_queue_stalls": int(result.get("backend_submit_stalls", 0)),
            "hbm_response_queue_stalls": int(
                result.get("backend_response_queue_stalls", 0)
            ),
            "stall_metrics_complete": False,
            "stall_metric_contract": "legacy_missing_axi_issue",
        }
    return {
        "axis_push_stalls": axis_push_stalls,
        "axi_issue_stalls": int(result["axi_issue_stalls"]),
        "hbm_queue_stalls": int(result["hbm_queue_stalls"]),
        "hbm_response_queue_stalls": int(result["hbm_response_queue_stalls"]),
        "stall_metrics_complete": True,
        "stall_metric_contract": "axis_axi_request_fifo_hbm_backend_v1",
    }


def memory_traffic_metrics(
    value: object, *, expected_requests: int, prefix: str
) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{prefix} traffic is missing")
    if value.get("classification") != (
        "per_initiator_and_operation_accepted_backend_request"
    ) or value.get("address_basis") != "logical_channel_and_byte_address":
        raise ValueError(f"{prefix} traffic has an unsupported classification")

    groups: dict[str, dict[str, int]] = {}
    for group_name in ("reads", "writes", "combined"):
        raw_group = value.get(group_name)
        if not isinstance(raw_group, Mapping):
            raise ValueError(f"{prefix}.{group_name} is missing")
        group: dict[str, int] = {}
        for field in LOCALITY_FIELDS:
            raw = raw_group.get(field)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
                raise ValueError(f"{prefix}.{group_name}.{field} is invalid")
            group[field] = raw
        if group["requests"] != (
            group["first_requests"]
            + group["contiguous_requests"]
            + group["repeated_requests"]
            + group["discontinuous_requests"]
        ) or group["bytes"] != (
            group["first_bytes"]
            + group["contiguous_bytes"]
            + group["repeated_bytes"]
            + group["discontinuous_bytes"]
        ):
            raise ValueError(f"{prefix}.{group_name} does not close")
        groups[group_name] = group

    for field in LOCALITY_FIELDS:
        if groups["combined"][field] != (
            groups["reads"][field] + groups["writes"][field]
        ):
            raise ValueError(f"{prefix}.{field} read/write sum does not close")
    combined = groups["combined"]
    if combined["requests"] != expected_requests:
        raise ValueError(f"{prefix} request count does not match its ledger")

    classified_requests = combined["requests"] - combined["first_requests"]
    classified_bytes = combined["bytes"] - combined["first_bytes"]
    request_denominator = max(classified_requests, 1)
    byte_denominator = max(classified_bytes, 1)
    return {
        f"{prefix}_requests": combined["requests"],
        f"{prefix}_bytes": combined["bytes"],
        f"{prefix}_read_requests": groups["reads"]["requests"],
        f"{prefix}_read_bytes": groups["reads"]["bytes"],
        f"{prefix}_write_requests": groups["writes"]["requests"],
        f"{prefix}_write_bytes": groups["writes"]["bytes"],
        f"{prefix}_first_requests": combined["first_requests"],
        f"{prefix}_first_bytes": combined["first_bytes"],
        f"{prefix}_contiguous_requests": combined["contiguous_requests"],
        f"{prefix}_contiguous_bytes": combined["contiguous_bytes"],
        f"{prefix}_repeated_requests": combined["repeated_requests"],
        f"{prefix}_repeated_bytes": combined["repeated_bytes"],
        f"{prefix}_discontinuous_requests": combined[
            "discontinuous_requests"
        ],
        f"{prefix}_discontinuous_bytes": combined["discontinuous_bytes"],
        f"{prefix}_classified_requests": classified_requests,
        f"{prefix}_classified_bytes": classified_bytes,
        f"{prefix}_contiguous_request_ratio": combined["contiguous_requests"]
        / request_denominator,
        f"{prefix}_repeated_request_ratio": combined["repeated_requests"]
        / request_denominator,
        f"{prefix}_discontinuous_request_ratio": combined[
            "discontinuous_requests"
        ]
        / request_denominator,
        f"{prefix}_contiguous_byte_ratio": combined["contiguous_bytes"]
        / byte_denominator,
        f"{prefix}_repeated_byte_ratio": combined["repeated_bytes"]
        / byte_denominator,
        f"{prefix}_discontinuous_byte_ratio": combined[
            "discontinuous_bytes"
        ]
        / byte_denominator,
    }


def split_memory_metrics(
    result: Mapping[str, object],
    *,
    first_key: str,
    first_prefix: str,
    second_key: str,
    second_prefix: str,
    backend_requests: int,
    first_requests: int,
    second_requests: int,
) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        "backend_nominal_64b_bytes": backend_requests * BACKEND_LINE_BYTES,
        f"{first_prefix}_nominal_64b_bytes": first_requests * BACKEND_LINE_BYTES,
        f"{second_prefix}_nominal_64b_bytes": second_requests
        * BACKEND_LINE_BYTES,
    }
    metrics.update(
        memory_traffic_metrics(
            result.get("backend_traffic"),
            expected_requests=backend_requests,
            prefix="backend",
        )
    )
    metrics.update(
        memory_traffic_metrics(
            result.get(first_key),
            expected_requests=first_requests,
            prefix=first_prefix,
        )
    )
    metrics.update(
        memory_traffic_metrics(
            result.get(second_key),
            expected_requests=second_requests,
            prefix=second_prefix,
        )
    )
    for field in ADDITIVE_TRAFFIC_FIELDS:
        if metrics[f"backend_{field}"] != (
            metrics[f"{first_prefix}_{field}"]
            + metrics[f"{second_prefix}_{field}"]
        ):
            raise ValueError(f"backend phase traffic does not close for {field}")
    return metrics


def phase_memory_metrics(
    result: Mapping[str, object],
    *,
    update_key: str,
    backend_requests: int,
    update_requests: int,
    compute_requests: int,
) -> dict[str, int | float]:
    return split_memory_metrics(
        result,
        first_key=update_key,
        first_prefix="update_backend",
        second_key="compute_backend_traffic",
        second_prefix="compute_backend",
        backend_requests=backend_requests,
        first_requests=update_requests,
        second_requests=compute_requests,
    )


def phase_memory_is_valid(
    result: Mapping[str, object],
    *,
    update_key: str,
    backend_requests: int,
    update_requests: int,
    compute_requests: int,
) -> bool:
    try:
        phase_memory_metrics(
            result,
            update_key=update_key,
            backend_requests=backend_requests,
            update_requests=update_requests,
            compute_requests=compute_requests,
        )
    except (TypeError, ValueError):
        return False
    return True
