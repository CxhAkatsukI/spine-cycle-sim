import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.analysis import (
    analyze, diagnostics,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.delivery import (
    CLAIMS, PASS, package, verify,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.preparation import ADAPTERS
from tests.test_grasu_weighted_source_abi import stderr, stdout


class WeightedDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "attempt"
        source = attempt / "source"
        source.mkdir(parents=True)
        pin = source / "control.cpp"
        pin.write_text("frozen control\n")
        report = {"status": PASS, "source": [{"path": str(pin), "sha256": sha256_file(pin)}],
                  "declared_adapters": list(ADAPTERS), "adapters": [], "errors": [],
                  **dict.fromkeys(CLAIMS, False)}
        for adapter in ADAPTERS:
            folder = attempt / adapter
            folder.mkdir()
            binary = folder / "probe"
            binary.write_bytes(b"binary identity only\n")
            entry = {"adapter": adapter, "binary_sha256": sha256_file(binary),
                     "dependencies": report["source"], "rows": analyze(stdout(), stderr()),
                     "diagnostics": diagnostics(stderr())}
            for label in ("compile", "execute"):
                stage = {"exit_code": 0, "timed_out": False}
                for suffix, content in (("stdout", stdout()), ("stderr", stderr())):
                    log = folder / f"{label}.{suffix}.txt"
                    log.write_text(content if label == "execute" else "")
                    stage[suffix] = str(log)
                (folder / f"{label}.resources.json").write_text(json.dumps(stage))
                entry[label] = stage
            report["adapters"].append(entry)
        self.write_report(attempt, report)
        return attempt, report

    @staticmethod
    def write_report(attempt, report):
        (attempt / "results.json").write_text(json.dumps(report))

    def test_archive_is_verifiable_without_machine_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = self.fixture(root)
            index = package(root / "evidence", [attempt])
            self.assertEqual(index, verify(root / "evidence"))
            names = [row["path"] for row in index["attempts"][0]["files"]]
            self.assertIn("source/control.cpp", names)
            self.assertNotIn("resident/probe", names)
            archive = root / "evidence" / index["attempts"][0]["archive"]
            with archive.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                verify(root / "evidence")

    def test_active_incomplete_promoted_and_failed_pass_reports_rejected(self):
        for change in ({"status": "RUNNING"}, {"declared_adapters": ["resident"]},
                       {"hardware_timing_admitted": True}, {"errors": [{"error": "failure"}]},
                       {"status": "FAILED_RETAINED"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, report = self.fixture(root)
                report.update(change)
                self.write_report(attempt, report)
                with self.assertRaises(ValueError):
                    package(root / "evidence", [attempt])

    def test_changed_raw_source_binary_resources_and_diagnostics_rejected(self):
        for relative in ("source/control.cpp", "resident/probe", "resident/execute.stdout.txt",
                         "resident/execute.stderr.txt", "resident/execute.resources.json"):
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, _ = self.fixture(root)
                with (attempt / relative).open("a") as stream:
                    stream.write("changed\n")
                with self.assertRaises(ValueError):
                    package(root / "evidence", [attempt])

    def test_failed_attempt_is_retained_without_reinterpreting_old_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, report = self.fixture(root)
            report.update(status="FAILED_RETAINED", errors=[{"error": "old gate rejected diagnostics"}])
            for entry in report["adapters"]:
                entry.pop("rows")
                entry.pop("diagnostics")
                entry["error"] = "old gate rejected diagnostics"
            self.write_report(attempt, report)
            index = package(root / "evidence", [attempt])
            self.assertEqual(index["attempts"][0]["status"], "FAILED_RETAINED")
            self.assertNotIn("rows", index["attempts"][0]["adapters"][0])

    def test_committed_capsule_keeps_all_attempts_and_source_only_boundary(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/weighted_abi/evidence")
        index = verify(folder)
        self.assertEqual([row["status"] for row in index["attempts"]],
                         ["FAILED_RETAINED"] * 3 + [PASS])
        final = index["attempts"][-1]
        self.assertEqual([row["adapter"] for row in final["adapters"]], list(ADAPTERS))
        for entry in final["adapters"]:
            self.assertEqual(len(entry["rows"]), 8)
            self.assertEqual(sum(row["operations"] for row in entry["rows"]), 162)
            self.assertEqual(entry["diagnostics"]["retained_vendor_width_warning_pairs"], 40)
        self.assertTrue(all(index[field] is False for field in (*CLAIMS, "new_spine_comparison_executed")))


if __name__ == "__main__":
    unittest.main()
