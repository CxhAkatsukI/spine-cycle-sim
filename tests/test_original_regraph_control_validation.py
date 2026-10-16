import array
import copy
from pathlib import Path
import tempfile
import tarfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_analysis as analysis
from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_delivery as delivery
from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_inputs, oracle, study


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


if __name__ == "__main__":
    unittest.main()
