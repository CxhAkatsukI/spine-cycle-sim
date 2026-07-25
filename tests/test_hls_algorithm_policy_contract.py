import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "configs/contracts/hls_algorithm_policy_evidence_v1.json"
INTEGRATION = Path("/home/chuxiao/grasu-regraph-integration")


class HlsAlgorithmPolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_contract_is_pinned_to_current_integration_commit(self) -> None:
        repository = self.contract["integration_repository"]
        self.assertEqual(repository["branch"], "codex/map-reduce-algorithm-hls")
        self.assertEqual(
            repository["commit"],
            "15b92edfef006ff8d5c6097ae2dbabd4522156a9",
        )
        self.assertFalse(repository["tracked_dirty"])

    def test_policy_and_adapter_sources_match_pinned_hashes(self) -> None:
        for section in ("policy_core", "pma_adapter"):
            record = self.contract[section]
            source = INTEGRATION / record["source"]
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(digest, record["source_sha256"])

    def test_all_required_algorithms_have_policy_compile_evidence(self) -> None:
        algorithms = self.contract["algorithms"]
        self.assertEqual(
            set(algorithms),
            {"weighted_sssp", "full_pagerank", "thresholded_residual_pagerank"},
        )
        for algorithm in algorithms.values():
            self.assertEqual(algorithm["policy_sw_emu_compile"], "passed")
            self.assertEqual(
                algorithm["normalized_execution_driven_simulator"], "passed"
            )

    def test_native_claims_fail_closed(self) -> None:
        algorithms = self.contract["algorithms"]
        self.assertEqual(
            algorithms["weighted_sssp"]["native_claim_allowed"],
            "sw_emu_correctness_only",
        )
        for name in ("full_pagerank", "thresholded_residual_pagerank"):
            algorithm = algorithms[name]
            self.assertEqual(algorithm["native_claim_allowed"], "no")
            self.assertEqual(algorithm["full_system_hls_sw_emu"], "not_integrated")
            self.assertGreaterEqual(len(algorithm["remaining_full_system_components"]), 6)

    def test_policy_core_is_not_mislabeled_as_full_system_ppa(self) -> None:
        core = self.contract["policy_core"]
        self.assertEqual(core["lanes"], 8)
        self.assertEqual(core["requested_clock_mhz"], 200)
        self.assertEqual(
            core["claim_class"],
            "synthesizable_policy_core_not_full_system_native",
        )
        self.assertEqual(core["hw_synthesis"], "pending")


if __name__ == "__main__":
    unittest.main()
