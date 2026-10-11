"""Portable production-XO identity and raw RTL evidence acceptance gates."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.delivery import recheck


EVIDENCE = (Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/"
            "grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/adapter_axi/evidence")


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        with tarfile.open(EVIDENCE / "raw_adapter_axi.tar.gz") as archive:
            archive.extractall(cls.directory, filter="data")
        cls.evidence_run = cls.directory / "accepted"

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @contextmanager
    def changed(self, relative, transform):
        path = self.evidence_run / relative
        original = path.read_bytes()
        try:
            path.write_bytes(transform(original))
            yield
        finally:
            path.write_bytes(original)

    def change_json(self, relative, transform):
        return self.changed(relative, lambda raw: json.dumps(transform(json.loads(raw))).encode())

    def test_archive_and_every_member_are_sealed(self):
        verification = json.loads((EVIDENCE / "verification.json").read_text())
        archive_path = EVIDENCE / "raw_adapter_axi.tar.gz"
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), verification["archive_sha256"])
        self.assertEqual(archive_path.stat().st_size, verification["archive_bytes"])
        with tarfile.open(archive_path) as archive:
            self.assertEqual(archive.getnames(), [row["path"] for row in verification["files"]])
            for row in verification["files"]:
                data = archive.extractfile(row["path"]).read()
                self.assertEqual(len(data), row["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
        self.assertEqual(hashlib.sha256((EVIDENCE / "results.json").read_bytes()).hexdigest(),
                         verification["results_sha256"])

    def test_portable_raw_recheck_matches_concise_results(self):
        self.assertEqual(recheck(self.evidence_run), json.loads((EVIDENCE / "results.json").read_text()))

    def test_XO_source_and_route_manifest_changes_are_rejected(self):
        manifest = json.loads((self.evidence_run / "manifest.json").read_text())
        for suffix in (".xo", "/analysis.py", "route_combined_sssp/manifest.json"):
            copy = next(pin["archive_path"] for pin in manifest["source_copies"]
                        if pin["path"].endswith(suffix))
            with self.subTest(suffix=suffix), self.changed(copy, lambda raw: raw + b"\n"), self.assertRaises(ValueError):
                recheck(self.evidence_run)

    def test_executed_RTL_and_testbench_changes_are_rejected(self):
        for name in ("pma_to_regraph_adapter.v", "adapter_axi_tb.sv", "run.tcl"):
            with self.subTest(name=name), self.changed("candidate/" + name, lambda raw: raw + b"\n"), self.assertRaises(ValueError):
                recheck(self.evidence_run)

    def test_raw_transcript_is_required_even_with_passing_summary(self):
        with self.changed("candidate/simulate.stdout.txt", lambda raw: raw.replace(b"ADAPTER_AXI_PASS cases=12", b"MISSING")):
            with self.assertRaises(ValueError):
                recheck(self.evidence_run)

    def test_report_cycles_cannot_be_changed_without_raw_evidence(self):
        def altered(report):
            report["arms"]["candidate"][5]["cycles"] += 1
            return report
        with self.change_json("summary.json", altered), self.assertRaises(ValueError):
            recheck(self.evidence_run)

    def test_watchdog_and_command_changes_are_rejected(self):
        for key, value in (("stop_reason", "timeout"), ("reserve_gib", 8),
                           ("command", ["fake", "--pass"]), ("cwd", "/different/run")):
            with self.subTest(key=key), self.change_json("candidate/simulate.resources.json", lambda row: row | {key: value}):
                with self.assertRaises(ValueError):
                    recheck(self.evidence_run)

    def test_development_runs_are_retained_but_not_admitted(self):
        self.assertTrue((self.directory / "development/attempt-v1/failure.json").is_file())
        for name in ("attempt-v2", "attempt-v3", "attempt-v4"):
            with self.subTest(name=name), self.assertRaises((KeyError, ValueError)):
                recheck(self.directory / "development" / name)
        manifest = json.loads((self.evidence_run / "manifest.json").read_text())
        self.assertEqual(manifest["xos"]["previous"]["sha256"],
                         "93aa6b76e441eda51ffc0a9bb25c1411cfab2be2bf18326371558a0cefb1863a")


if __name__ == "__main__":
    unittest.main()
