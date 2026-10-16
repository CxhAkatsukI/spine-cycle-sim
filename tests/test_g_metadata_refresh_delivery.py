import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_refresh import analysis, delivery, preparation, study
from test_g_metadata_refresh import fixture, transcript


def materialize(root):
    root.mkdir()
    contract = {"case": preparation.CASE}
    (root / "contract.json").write_text(json.dumps(contract))
    (root / "probe").write_text("synthetic binary identity, never executed")
    model = transcript(fixture())
    stale = "\n".join(kind + " " + json.dumps(row) for kind, row in fixture()[:7]) + "\n"
    diagnostic = "complete resident PMA/padding mismatch\n"
    report = {"status": analysis.PASS, "errors": [], "contract": contract, "policy": study.POLICY,
              **dict.fromkeys(preparation.CLAIMS, False),
              "pins": [{"path": str(root / "contract.json"), "sha256": sha256_file(root / "contract.json")}],
              "binary_sha256": sha256_file(root / "probe"), "model": analysis.analyze(model, ""),
              "negative": analysis.stale_rejection(stale, diagnostic),
              "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
              "admission": {"admitted": True, "policy": "full_finite_budgets_plus_reserve_atomic_lease"}, "steps": []}
    (root / "raw").mkdir()
    for label, stdout, stderr in (("compile", "", ""), ("model", model, ""), ("stale", stale, diagnostic)):
        step = {"exit_code": 1 if label == "stale" else 0, "stop_reason": "process_exit",
                "cleanup_snapshot_error": None, "tree_memory_gib": 2, "reserve_gib": 24}
        report["steps"].append({"label": label, **step})
        (root / "raw" / (label + ".resources.json")).write_text(json.dumps(step))
        (root / "raw" / (label + ".stdout.txt")).write_text(stdout)
        (root / "raw" / (label + ".stderr.txt")).write_text(stderr)
    (root / "results.json").write_text(json.dumps(report))
    return report


class MetadataRefreshDeliveryTests(unittest.TestCase):
    def test_raw_host_rows_negative_and_resources_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "attempt"
            report = materialize(root)
            self.assertEqual(delivery.validate(root), report)

    def test_claim_promotion_bad_budget_oom_or_incomplete_rows_rejected(self):
        changes = [lambda r: r.update(fpga_measured=True), lambda r: r.update(device_metadata_refresh_verified=True),
                   lambda r: r["policy"].update(reserve_gib=0), lambda r: r["admission"].update(admitted=False),
                   lambda r: r.update(memory_events_after="oom 1\noom_kill 0\noom_group_kill 0\n"),
                   lambda r: r["model"]["rows"].pop(), lambda r: r["steps"].reverse(),
                   lambda r: r["negative"].update(batch=2)]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "attempt"
                report = materialize(root)
                # Avoid mutating the shared admission policy used by other tests.
                report = json.loads(json.dumps(report))
                change(report)
                (root / "results.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError): delivery.validate(root)

    def test_changed_sources_binary_raw_or_diagnostics_rejected(self):
        for name in ("contract.json", "probe", "raw/model.stdout.txt", "raw/stale.stderr.txt", "raw/compile.resources.json",
                     "raw/compile.stderr.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "attempt"
                materialize(root)
                path = root / name
                path.write_text(path.read_text() + " changed")
                with self.assertRaises(ValueError): delivery.validate(root)


if __name__ == "__main__":
    unittest.main()
