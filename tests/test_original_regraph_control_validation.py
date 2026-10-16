import array
import copy
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import Mock, patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_analysis as analysis
from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_delivery as delivery
from spine_cycle_sim.experiments.original_regraph_execution.hardware import (
    artifact, control_inputs, control_validation, oracle, study,
)


class ControlValidationTests(unittest.TestCase):
    def fixture(self, output, published=6):
        words = array.array("I", [108, 0, 0, 0, 0, 0])
        words[published:] = array.array("I", [analysis.GUARD]) * (6 - published)
        words.extend([analysis.GUARD] * 16)
        with (output / "expected.u32le").open("wb") as stream:
            payload = array.array("I", words)
            import sys
            if sys.byteorder != "little":
                payload.byteswap()
            payload.tofile(stream)
        report = {"status": "ORIGINAL_R_CONTROL_OFFLINE_PASS_NOT_FPGA",
                  "board_programmed": False, "hardware_timing_measured": False, "publication_match": False,
                  "events": [], "bdf": "", "enqueue_to_completion_ms": None, "event_union_ns": None,
                  "event_span_ns": None, "binding": "csr_degree", "iterations": 1, "argument": 0,
                  "guard_words": 16, "vertices": 3, "aligned_vertices": 4, "published_vertices": published,
                  "allocation_vertices": 6, "extra_padding_vertices": 2, "logical_edges": 2,
                  "physical_edges": 8, "dummy_edges": 6}
        reference = {"vertices": 3, "original_allocation_words": 4, "device_publication_words": published,
                     "logical_edges": 2, "physical_edges": 8, "one_superstep_comparison":
                         {"csr_degree_result_sha256": oracle.digest(array.array("I", [108, 0, 0, 0]))}}
        return report, reference, words

    def test_guarded_publication_matches_independent_csr_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for published in (2, 6):
                report, reference, words = self.fixture(output, published)
                observed = analysis.inspect(report, output, reference)
                self.assertEqual(observed["expected_sha256"], oracle.digest(words))
                self.assertTrue(observed["complete_guard_and_tail_checked"])

    def test_promoted_hardware_claims_and_implicit_bindings_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, reference, _ = self.fixture(output)
            for name in ("board_programmed", "hardware_timing_measured", "publication_match"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    analysis.inspect({**report, name: True}, output, reference)
            for changes in ({"binding": "implicit"}, {"iterations": 2}, {"guard_words": 1},
                            {"event_span_ns": 42}, {"events": [{}]}, {"bdf": "82:00.1"}):
                with self.assertRaises(ValueError):
                    analysis.inspect({**report, **changes}, output, reference)

    def test_guard_padding_or_oracle_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for index in (0, 4, 6, 21):
                report, reference, words = self.fixture(output)
                with (output / "expected.u32le").open("r+b") as stream:
                    stream.seek(index * 4)
                    stream.write((int(words[index]) ^ 1).to_bytes(4, "little"))
                with self.subTest(index=index), self.assertRaises(ValueError):
                    analysis.inspect(report, output, reference)

    def test_geometry_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, reference, _ = self.fixture(output)
            for changes in ({"allocation_vertices": 3}, {"vertices": True}, {"dummy_edges": 0},
                            {"extra_padding_vertices": 0}, {"published_vertices": 7}):
                with self.assertRaises(ValueError):
                    analysis.inspect({**report, **changes}, output, reference)
            with (output / "expected.u32le").open("r+b") as stream:
                stream.truncate(4)
            with self.assertRaises(ValueError):
                analysis.inspect(report, output, reference)

    def rows(self):
        return [{"build": build, "repetition": repetition, "topology": topology, "graph": graph,
                 "binding": binding, "analysis": {"expected_sha256": "guarded", "logical_sha256": "logical"}}
                for build in ("release", "ubsan") for repetition in range(2)
                for topology, graph, binding in sorted(analysis.EXPECTED)]

    def test_complete_matrix_repeats_and_topologies_required(self):
        rows = self.rows()
        analysis.matrix(rows)
        for bad in (rows[:-1], rows[1:] + [rows[1]]):
            with self.assertRaises(ValueError):
                analysis.matrix(bad)
        for key in ("expected_sha256", "logical_sha256"):
            bad = copy.deepcopy(rows)
            bad[0]["analysis"][key] = "changed"
            with self.assertRaises(ValueError):
                analysis.matrix(bad)

    def test_unpinned_input_report_is_not_accepted_as_a_source_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            report.write_text("{}")
            reference = {"status": study.STATUS, "errors": [], "pins": []}
            with self.assertRaisesRegex(ValueError, "pinned"):
                control_inputs.admit(report, reference, root / "inputs")


class ControlDeliveryTests(unittest.TestCase):
    def report(self):
        return {"status": analysis.STATUS, "errors": [], "rows": ControlValidationTests().rows(),
                "negative_controls": ["missing_lease", "unknown_binding", "a4_board_abi", "symlink_input"],
                **dict.fromkeys(delivery.CLAIMS, False)}

    def test_delivery_rejects_incomplete_or_promoted_results(self):
        delivery.terminal(self.report())
        for key in delivery.CLAIMS:
            with self.assertRaises(ValueError):
                delivery.terminal({**self.report(), key: True})
        for changes in ({"rows": []}, {"errors": ["failed"]}, {"negative_controls": []},
                        {"status": "PREPARED"}):
            with self.assertRaises(ValueError):
                delivery.terminal({**self.report(), **changes})

    def test_a4_capable_host_requires_new_negative_controls_without_promoting_legacy(self):
        report = {**self.report(), "board_abis": ["original_example", "a4"],
                  "negative_controls": ["missing_lease", "unknown_binding", "missing_lease_a4", "symlink_input"]}
        delivery.terminal(report)
        for changes in ({"board_abis": ["a4"]}, {"board_abis": []},
                        {"negative_controls": self.report()["negative_controls"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                delivery.terminal({**report, **changes})

    def test_portable_capsule_rejects_archive_and_claim_tampering(self):
        import json
        from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
        from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "results.json"
            atomic_write_json(report, self.report())
            archive = root / "control.tar.gz"
            index = {"status": analysis.STATUS, "archive": archive.name, "rows": 48,
                     "files": seal([(report, "run/results.json")], archive),
                     "sha256": sha256_file(archive), **dict.fromkeys(delivery.CLAIMS, False)}
            atomic_write_json(root / "index.json", index)
            self.assertEqual(delivery.verify(root), index)
            with tarfile.open(archive) as bundle:
                self.assertEqual(json.load(bundle.extractfile("run/results.json")), self.report())
            atomic_write_json(root / "index.json", {**index, "hardware_timing_measured": True})
            with self.assertRaises(ValueError):
                delivery.verify(root)
            atomic_write_json(root / "index.json", index)
            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "archive changed"):
                delivery.verify(root)


class ControlMemoryWaitTests(unittest.TestCase):
    def invoke(self, report, sample, *, wait_seconds=0):
        lease, save = Mock(), Mock()
        lease.sample.side_effect = sample
        peers = [{"pid": 42, "memory_max_bytes": 40 * 1024**3}]
        with patch.object(control_validation, "available_memory_bytes", return_value=160 * 1024**3), \
                patch.object(control_validation, "other_builds", return_value=peers), \
                patch.object(control_validation.time, "sleep") as sleep, \
                patch.object(control_validation.time, "monotonic", side_effect=[0, 0, 1]):
            control_validation.wait_for_memory(lease, report, save, wait_seconds=wait_seconds, poll_seconds=0.1)
        return lease, save, sleep, peers

    def test_fitting_budgets_start_even_when_another_fpga_build_is_running(self):
        report = {"pins": []}
        lease, save, sleep, peers = self.invoke(report, [{"admitted": True}])
        lease.sample.assert_called_once_with(160 * 1024**3, peers, control_validation.POLICY, commit=True)
        save.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(report["status"], "MEMORY_ADMITTED")

    def test_wait_rechecks_budget_until_admitted_and_zero_wait_fails_closed(self):
        report = {"pins": []}
        lease, save, sleep, _ = self.invoke(report, [{"admitted": False}, {"admitted": True}], wait_seconds=10)
        self.assertEqual(lease.sample.call_count, 2)
        self.assertEqual(save.call_count, 2)
        sleep.assert_called_once_with(0.1)
        with self.assertRaisesRegex(TimeoutError, "no compiler launched"):
            self.invoke({"pins": []}, [{"admitted": False}])

    def test_wait_rejects_source_drift_before_budget_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.write_text("frozen")
            report = {"pins": [artifact.identity(source)]}
            source.write_text("changed")
            lease = Mock()
            with self.assertRaisesRegex(ValueError, "changed while waiting"):
                control_validation.wait_for_memory(lease, report, Mock(), wait_seconds=10, poll_seconds=1)
            lease.sample.assert_not_called()

    def test_wait_bounds_must_be_finite(self):
        for wait, poll in ((True, 1), (-1, 1), (float("inf"), 1), (1, 0), (1, float("nan"))):
            with self.subTest(wait=wait, poll=poll), self.assertRaises(ValueError):
                control_validation.wait_for_memory(Mock(), {"pins": []}, Mock(), wait_seconds=wait,
                                                   poll_seconds=poll)


if __name__ == "__main__":
    unittest.main()
