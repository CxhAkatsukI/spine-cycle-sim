from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.alignment_contract import (
    AlignmentContractError,
    load_alignment_contract,
    render_hls_contract_header,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/contracts/spine_paper_architecture_alignment_v1.json"


class AlignmentContractTests(unittest.TestCase):
    def test_frozen_contract_loads_and_pins_the_agreed_architecture(self) -> None:
        contract = load_alignment_contract(CONTRACT_PATH)
        self.assertEqual(contract.contract_id, "spine_paper_architecture_alignment_v1")
        self.assertEqual(len(contract.sha256), 64)
        self.assertEqual(contract.payload["organization"]["families"], 32)
        self.assertEqual(contract.payload["organization"]["levels"], 11)
        self.assertEqual(contract.payload["organization"]["compute_lanes"], 4)
        self.assertTrue(contract.payload["scheduler"]["no_lost_reactivation"])
        self.assertFalse(
            contract.payload["scheduler"]["host_may_recompute_active_membership"]
        )
        self.assertEqual(
            set(contract.payload["algorithms"]["required"]),
            {
                "weighted_sssp",
                "connected_components",
                "thresholded_residual_pagerank",
                "full_pagerank",
            },
        )

    def test_hls_header_is_deterministic_and_hash_bound(self) -> None:
        contract = load_alignment_contract(CONTRACT_PATH)
        first = render_hls_contract_header(contract)
        second = render_hls_contract_header(contract)
        self.assertEqual(first, second)
        self.assertIn(contract.sha256, first)
        self.assertIn("SPINE_ALIGNMENT_OWNER_FIFO_DEPTH 256", first)
        self.assertIn("SPINE_ALIGNMENT_REACTIVATION_FIFO_DEPTH 256", first)

    def test_contract_rejects_host_active_membership(self) -> None:
        payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload["scheduler"]["host_may_recompute_active_membership"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(AlignmentContractError, "host may not"):
                load_alignment_contract(path)

    def test_contract_rejects_unversioned_parallel_edge_change(self) -> None:
        payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        payload["graph_semantics"]["payload_distinct_parallel_edges"] = "enabled"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(AlignmentContractError, "separately versioned"):
                load_alignment_contract(path)


if __name__ == "__main__":
    unittest.main()
