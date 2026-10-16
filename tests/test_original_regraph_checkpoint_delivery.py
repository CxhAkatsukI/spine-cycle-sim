import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import checkpoint, checkpoint_delivery as delivery


class CheckpointDeliveryTests(unittest.TestCase):
    def test_full_timing_report_has_a_separate_bounded_extent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "query").mkdir()
            timing = root / "query/timing.rpt"
            with timing.open("wb") as stream:
                stream.truncate(32 * 1024**2)
            self.assertEqual(delivery.metadata_file(root, "query/timing.rpt"), timing)
            with timing.open("wb") as stream:
                stream.truncate(64 * 1024**2 + 1)
            with self.assertRaisesRegex(ValueError, "query/timing.rpt"):
                delivery.metadata_file(root, "query/timing.rpt")
            log = root / "vivado.log"
            with log.open("wb") as stream:
                stream.truncate(16 * 1024**2 + 1)
            with self.assertRaisesRegex(ValueError, "vivado.log"):
                delivery.metadata_file(root, "vivado.log")
            log.unlink()
            log.symlink_to(timing)
            with self.assertRaisesRegex(ValueError, "vivado.log"):
                delivery.metadata_file(root, "vivado.log")

    def report(self):
        analysis = {"status": checkpoint.STATUS, "constraints_modified": False,
                    "implementation_or_bitstream_rewritten": False, **dict.fromkeys(checkpoint.CLAIMS, False)}
        return {"status": checkpoint.STATUS, "errors": [], "pins": [], "analysis": analysis,
                **dict.fromkeys(checkpoint.CLAIMS, False)}

    def test_each_promoted_top_level_or_analysis_claim_rejected(self):
        for key in checkpoint.CLAIMS:
            for location in ("top", "analysis"):
                report = self.report()
                (report if location == "top" else report["analysis"])[key] = True
                with self.subTest(key=key, location=location), self.assertRaises(ValueError):
                    delivery.terminal(report)

    def test_nonterminal_failed_or_constraint_rewritten_results_rejected(self):
        for changes in ({"status": "READ_ONLY_QUERY_RUNNING"}, {"errors": ["failed"]}):
            with self.assertRaises(ValueError):
                delivery.terminal({**self.report(), **changes})
        for key in ("constraints_modified", "implementation_or_bitstream_rewritten"):
            report = self.report()
            report["analysis"][key] = True
            with self.assertRaises(ValueError):
                delivery.terminal(report)

    def test_capsule_roundtrip_tamper_and_result_disagreement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, prebuilt, audit, output = [root / name for name in ("attempt", "prebuilt", "audit", "output")]
            for name in delivery.FILES:
                path = attempt / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("metadata")
            (attempt / "results.json").write_text(json.dumps(self.report()))
            audit.mkdir()
            (audit / "results.json").write_text("{}")
            (prebuilt / checkpoint.IMPL).mkdir(parents=True)
            (prebuilt / checkpoint.IMPL / "_new_clk_freq").write_text("clock")
            with patch.object(delivery, "recheck"):
                result = delivery.package(attempt, prebuilt, audit, output)
            self.assertEqual(result, delivery.verify(output))
            altered = {**result, "analysis": {**result["analysis"], "changed": True}}
            (output / "index.json").write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "disagrees"):
                delivery.verify(output)
            (output / "index.json").write_text(json.dumps(result))
            (output / result["archive"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "archive changed"):
                delivery.verify(output)


if __name__ == "__main__":
    unittest.main()
