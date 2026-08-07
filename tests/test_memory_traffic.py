from __future__ import annotations

import copy
import unittest

from spine_cycle_sim.experiments.memory_traffic import (
    backpressure_metrics,
    memory_traffic_metrics,
    phase_memory_is_valid,
    phase_memory_metrics,
)


def _group(
    *,
    first: tuple[int, int] = (0, 0),
    contiguous: tuple[int, int] = (0, 0),
    repeated: tuple[int, int] = (0, 0),
    discontinuous: tuple[int, int] = (0, 0),
) -> dict[str, int]:
    categories = (first, contiguous, repeated, discontinuous)
    return {
        "requests": sum(item[0] for item in categories),
        "bytes": sum(item[1] for item in categories),
        "first_requests": first[0],
        "first_bytes": first[1],
        "contiguous_requests": contiguous[0],
        "contiguous_bytes": contiguous[1],
        "repeated_requests": repeated[0],
        "repeated_bytes": repeated[1],
        "discontinuous_requests": discontinuous[0],
        "discontinuous_bytes": discontinuous[1],
    }


def _sum_group(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {field: left[field] + right[field] for field in left}


def _traffic(
    reads: dict[str, int], writes: dict[str, int]
) -> dict[str, object]:
    return {
        "classification": (
            "per_initiator_and_operation_accepted_backend_request"
        ),
        "address_basis": "logical_channel_and_byte_address",
        "reads": reads,
        "writes": writes,
        "combined": _sum_group(reads, writes),
    }


class MemoryTrafficTests(unittest.TestCase):
    def setUp(self) -> None:
        self.update = _traffic(
            _group(first=(1, 8), contiguous=(2, 16), discontinuous=(1, 4)),
            _group(first=(1, 4), repeated=(1, 4)),
        )
        self.compute = _traffic(
            _group(first=(1, 64), contiguous=(3, 192)),
            _group(),
        )
        update_combined = self.update["combined"]
        compute_combined = self.compute["combined"]
        assert isinstance(update_combined, dict)
        assert isinstance(compute_combined, dict)
        self.total = _traffic(
            _sum_group(self.update["reads"], self.compute["reads"]),  # type: ignore[arg-type]
            _sum_group(self.update["writes"], self.compute["writes"]),  # type: ignore[arg-type]
        )
        self.result = {
            "backend_traffic": self.total,
            "update_backend_traffic": self.update,
            "compute_backend_traffic": self.compute,
        }

    def test_reports_actual_bytes_and_nominal_upper_bound_separately(self) -> None:
        metrics = phase_memory_metrics(
            self.result,
            update_key="update_backend_traffic",
            backend_requests=10,
            update_requests=6,
            compute_requests=4,
        )
        self.assertEqual(metrics["backend_bytes"], 292)
        self.assertEqual(metrics["backend_nominal_64b_bytes"], 640)
        self.assertEqual(metrics["backend_read_bytes"], 284)
        self.assertEqual(metrics["backend_write_bytes"], 8)
        self.assertAlmostEqual(metrics["backend_contiguous_byte_ratio"], 208 / 216)

    def test_rejects_unknown_classification_contract(self) -> None:
        malformed = copy.deepcopy(self.total)
        malformed["classification"] = "global_address_delta"
        with self.assertRaisesRegex(ValueError, "unsupported classification"):
            memory_traffic_metrics(
                malformed, expected_requests=10, prefix="backend"
            )

    def test_rejects_category_and_read_write_nonclosure(self) -> None:
        category_broken = copy.deepcopy(self.total)
        category_broken["reads"]["contiguous_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "does not close"):
            memory_traffic_metrics(
                category_broken, expected_requests=10, prefix="backend"
            )

        direction_broken = copy.deepcopy(self.total)
        direction_broken["combined"]["bytes"] += 1
        direction_broken["combined"]["discontinuous_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "read/write sum"):
            memory_traffic_metrics(
                direction_broken, expected_requests=10, prefix="backend"
            )

    def test_rejects_request_ledger_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "request count"):
            memory_traffic_metrics(
                self.total, expected_requests=11, prefix="backend"
            )

    def test_rejects_phase_nonclosure(self) -> None:
        malformed = copy.deepcopy(self.result)
        malformed["backend_traffic"]["reads"]["first_bytes"] += 4
        malformed["backend_traffic"]["reads"]["bytes"] += 4
        malformed["backend_traffic"]["combined"]["first_bytes"] += 4
        malformed["backend_traffic"]["combined"]["bytes"] += 4
        with self.assertRaisesRegex(ValueError, "phase traffic does not close"):
            phase_memory_metrics(
                malformed,
                update_key="update_backend_traffic",
                backend_requests=10,
                update_requests=6,
                compute_requests=4,
            )
        self.assertFalse(
            phase_memory_is_valid(
                malformed,
                update_key="update_backend_traffic",
                backend_requests=10,
                update_requests=6,
                compute_requests=4,
            )
        )

    def test_reports_complete_three_layer_backpressure_contract(self) -> None:
        metrics = backpressure_metrics(
            {
                "axis_push_stalls": 2,
                "axi_issue_stalls": 3,
                "hbm_queue_stalls": 5,
                "hbm_response_queue_stalls": 7,
            },
            axis_push_stalls=2,
        )
        self.assertTrue(metrics["stall_metrics_complete"])
        self.assertEqual(metrics["axis_push_stalls"], 2)
        self.assertEqual(metrics["axi_issue_stalls"], 3)
        self.assertEqual(metrics["hbm_queue_stalls"], 5)

    def test_legacy_backpressure_cannot_close_complete_gate(self) -> None:
        metrics = backpressure_metrics(
            {"backend_submit_stalls": 5, "backend_response_queue_stalls": 7},
            axis_push_stalls=2,
        )
        self.assertFalse(metrics["stall_metrics_complete"])
        self.assertEqual(metrics["axi_issue_stalls"], "")
        self.assertEqual(metrics["hbm_queue_stalls"], 5)


if __name__ == "__main__":
    unittest.main()
