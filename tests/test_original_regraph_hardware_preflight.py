import array
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact, delivery, oracle, sources, study


class BindingAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.words = {
            "csr_offsets.u32le": [0, 1, 2, 2], "csr_destinations.u32le": [1, 2],
            "initial.u32le": [1000, 500, 0] + [0] * 65533,
            "degrees.u32le": [1, 1, 0] + [0] * 65533,
            "tasks.u32le": [0, 1, 1, 2] + [0, 0xffffffff] * 6,
            "original_to_reordered.u32le": [0, 1, 2], "partitions.u32le": [0] * 16}
        self.layout = {"summary": {"vertices": 3, "aligned_vertices": 65536,
            "logical_edges": 2, "task_physical_edges": 8, "dense_partitions": 1, "sparse_groups": 0},
            "partitions": [{"words": 16}],
            "tasks": [{"words": 16, "offset_words": 0, "dst_offset": 0, "dst_len": 65536}], "files": []}
        self.write()

    def write(self):
        self.layout["files"] = []
        for name, words in self.words.items():
            values = array.array("I", words)
            if sys.byteorder != "little":
                values.byteswap()
            path = self.directory / name
            path.write_bytes(values.tobytes())
            self.layout["files"].append({"path": name, "words": len(words), "bytes": len(words) * 4,
                                         "format": "u32le", "sha256": sha256_file(path)})

    def test_same_gather_different_explicit_divisors_without_hardware_claim(self):
        result = oracle.audit(self.directory, self.layout)
        self.assertTrue(result["csr_task_gather_equal"])
        self.assertEqual(result["different_logical_divisors"], 2)
        self.assertEqual(result["one_superstep_comparison"]["different_logical_vertices"], 1)
        self.assertNotEqual(result["one_superstep_comparison"]["original_host_result_sha256"],
                            result["one_superstep_comparison"]["csr_degree_result_sha256"])
        self.assertEqual(result["publication_excess_words"], 0)
        self.assertFalse(result["padding_control_applied"])

    def test_mixed_publication_excess_is_reported_not_silently_padded(self):
        self.layout["summary"]["sparse_groups"] = 1
        result = oracle.audit(self.directory, self.layout)
        self.assertEqual(result["publication_excess_words"], 8 * 65536)
        self.assertFalse(result["original_output_allocation_covers_publication"])
        self.assertFalse(result["padding_control_applied"])

    def test_signed_overflow_is_not_wrapped_into_an_oracle(self):
        self.words["initial.u32le"][0] = 20_000_000
        self.write()
        result = oracle.audit(self.directory, self.layout)
        self.assertEqual(result["original_host_signed_overflow_vertices"], 1)
        self.assertEqual(result["csr_degree_signed_overflow_vertices"], 1)
        self.assertIsNone(result["one_superstep_comparison"])

    def test_degree_and_task_csr_mismatch_rejected_even_when_hashes_refreshed(self):
        for name, index, value in (("degrees.u32le", 0, 2), ("tasks.u32le", 1, 2),
                                   ("tasks.u32le", 5, 3), ("csr_offsets.u32le", 0, 1),
                                   ("initial.u32le", 4, 1)):
            before = copy.deepcopy(self.words)
            self.words[name][index] = value
            self.write()
            with self.subTest(name=name, index=index), self.assertRaises(ValueError):
                oracle.audit(self.directory, self.layout)
            self.words = before

    def test_capture_change_truncation_duplicate_and_symlink_rejected(self):
        path = self.directory / "csr_destinations.u32le"
        path.write_bytes(b"changed!")
        with self.assertRaisesRegex(ValueError, "identity"):
            oracle.audit(self.directory, self.layout)
        self.write()
        duplicate = copy.deepcopy(self.layout)
        duplicate["files"][-1] = duplicate["files"][0]
        with self.assertRaisesRegex(ValueError, "seven"):
            oracle.audit(self.directory, duplicate)
        target = self.directory / "backing"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "extent or type"):
            oracle.audit(self.directory, self.layout)
        target.write_bytes(b"short")
        with self.assertRaises(ValueError):
            oracle.read_words(target, 2)

    def test_apply_integer_arithmetic_domain_and_zero_divisor(self):
        result, overflow = oracle.apply([128, 128], [1, 0])
        self.assertEqual(list(result), [108, 0])
        self.assertEqual(overflow, 0)
        for totals, divisors in (([1], []), ([-1], [1]), ([1], [-1]), ([1], [2**31])):
            with self.assertRaises(ValueError):
                oracle.apply(totals, divisors)


class SourceReviewTests(unittest.TestCase):
    def test_exact_revision_unique_anchors_and_clock_order_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for _, relative, needle in sources.ANCHORS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as stream:
                    stream.write(needle + "\n")
            host = root / "host/host.cpp"
            lines = host.read_text().splitlines()
            start = next(line for line in lines if "auto kernel_start" in line)
            host.write_text("\n".join([line for line in lines if line != start] + [start]))
            with patch.object(sources, "verify_snapshot", return_value={"revision": sources.REVISION}):
                report = sources.review(root, {"revision": sources.REVISION})
                self.assertFalse(report["device_source_modified"])
                with self.assertRaisesRegex(ValueError, "explicitly reviewed"):
                    sources.review(root, {"revision": "new"})
                host.write_text(start + "\n" + host.read_text())
                with self.assertRaisesRegex(ValueError, "anchor changed"):
                    sources.review(root, {"revision": sources.REVISION})
                host.write_text(start + "\n" + "\n".join(line for line in lines if line != start))
                with self.assertRaisesRegex(ValueError, "wall-clock"):
                    sources.review(root, {"revision": sources.REVISION})


class ArtifactAuditTests(unittest.TestCase):
    def topology(self):
        names = [f"littleKernelScatterGather:littleKernelScatterGather_{i}" for i in range(1, 12)]
        names += [f"bigKernelScatterGather:bigKernelScatterGather_{i}" for i in range(1, 4)]
        names += [f"{name}:{name}_1" for name in ("kernelLittleGSMerger", "kernelBigGSMerger",
                                                  "kernelApply", "kernelHBMWrapper")]
        return {"clock": [("DATA", "DATA_CLK", 215)], "kernels": [(name, "AP_CTRL_HS") for name in names]}

    def test_clock_report_and_source_pairing_never_inferred_from_a_prebuilt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (*artifact.SECTIONS.values(), "system"):
                (root / (name + ".json")).write_text("{}")
            timing = root / "timing.rpt"
            timing.write_text("failed old requested-clock timing")
            with patch.object(artifact, "normalized_topology", return_value=self.topology()):
                report = artifact.inspect(root, timing)
                self.assertEqual(report["data_clock_mhz_from_xclbin"], 215)
                self.assertFalse(report["saved_timing"]["saved_report_passed"])
                self.assertFalse(report["board_admitted"])
                self.assertFalse(report["publication_match"])
                with patch.object(artifact, "parse_routed_timing", return_value={"wns_ns": 0.1}):
                    self.assertFalse(artifact.inspect(root, timing)["checkpoint_bitstream_timing_clock_pairing_verified"])
            for field, replacement in (("clock", []), ("kernels", [])):
                topology = self.topology()
                topology[field] = replacement
                with patch.object(artifact, "normalized_topology", return_value=topology):
                    with self.assertRaises(ValueError):
                        artifact.inspect(root, timing)

    def test_dump_is_read_only_and_includes_system_metadata(self):
        command = artifact.dump_command(Path("binary"), Path("directory"), Path("utility"))
        self.assertNotIn("--force", command)
        self.assertIn("SYSTEM_METADATA:RAW:directory/system.json", command)
        self.assertEqual(command.count("--dump-section"), 5)

    def test_complete_unique_input_matrix_and_runner_dependencies_required(self):
        report = {"status": study.INPUT_PASS, "cases": [{"id": name} for name in study.EXPECTED]}
        study.validate_matrix(report)
        for cases in (report["cases"][:-1], report["cases"][:-1] + report["cases"][:1]):
            with self.assertRaises(ValueError):
                study.validate_matrix({**report, "cases": cases})
        paths = {pin["path"] for pin in study.runner_pins()}
        self.assertIn(str(Path(artifact.__file__).resolve()), paths)
        self.assertTrue(any(path.endswith("upstream_controls/execution.py") for path in paths))


class DeliveryTests(unittest.TestCase):
    def report(self):
        return {"status": study.STATUS, "cases": [{"id": name} for name in sorted(study.EXPECTED)],
                "errors": [], **dict.fromkeys(delivery.CLAIMS, False)}

    def test_no_promoted_claims_missing_rows_or_hidden_failures(self):
        delivery.terminal(self.report())
        for claim in delivery.CLAIMS:
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                delivery.terminal({**self.report(), claim: True})
        for changes in ({"cases": []}, {"errors": ["failed"]}, {"status": "RUNNING"}):
            with self.assertRaises(ValueError):
                delivery.terminal({**self.report(), **changes})
        delivery.terminal({**self.report(), "status": "FAILED_RETAINED", "errors": ["failed"], "cases": []})

    def test_archive_roundtrip_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, output = root / "attempt", root / "evidence"
            attempt.mkdir()
            (attempt / "results.json").write_text(json.dumps(self.report()))
            with patch.object(delivery, "recheck"):
                report = self.report()
                report.update(pins=[], source_review={"identities": []})
                (attempt / "results.json").write_text(json.dumps(report))
                result = delivery.package(attempt, [], output)
            self.assertFalse(result["board_programmed"])
            self.assertEqual(result, delivery.verify(output))
            (output / result["archive"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "archive changed"):
                delivery.verify(output)

    def test_recheck_preserves_json_topology_and_rejects_raw_result_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs.json"
            extraction = {"exit_code": 0, "timed_out": False}
            (root / "extract.resources.json").write_text(json.dumps(extraction))
            observed = {"topology": {"clock": [("DATA", "DATA_CLK", 215)]},
                        "saved_timing": {"report": {"path": str(root / "timing.rpt")}}}
            matrix = {"cases": [{"id": name, "runs": [{"directory": str(root), "analysis": {}}]}
                                for name in sorted(study.EXPECTED)]}
            inputs.write_text(json.dumps(matrix))
            report = {**self.report(), "pins": [artifact.identity(inputs)],
                      "source_review": {"identities": []}, "extraction": extraction,
                      "artifact": json.loads(json.dumps(observed))}
            with patch.object(delivery.study, "validate_matrix"), \
                    patch.object(delivery.artifact, "inspect", return_value=observed), \
                    patch.object(delivery.oracle, "audit", side_effect=lambda *args: {"pins": []}) as audit:
                delivery.recheck(root, report)
                audit.side_effect = lambda *args: {"pins": [], "changed": True}
                with self.assertRaisesRegex(ValueError, "raw CSR/task"):
                    delivery.recheck(root, report)


if __name__ == "__main__":
    unittest.main()
