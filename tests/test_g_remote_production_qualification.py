from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import qualification as job
from spine_cycle_sim.experiments.evaluation_impact.common_g.production_board import experiments


class RemoteQualificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.original = self.root / "original.xclbin"
        self.original.write_text("synthetic identity, never programmed")
        self.output = self.root / "output"
        self.mock(job.board, "containment", return_value={})
        pin = job.identity(self.original)
        self.review = self.mock(job.admission, "review", return_value={"pins": [], "candidate": pin,
                                                                       "timing": {"report": pin}})
        self.mock(experiments.native, "host_identity", return_value=({"contract": {"cases": [{}]}}, []))
        self.metadata = self.mock(experiments, "metadata_identity", return_value=({"contract": {"cases": [{}]}}, []))
        self.mock(experiments.handoff, "host_identity", return_value=({"contract": {"cases": [{}] * 9}}, []))
        self.mock(job, "current", return_value=self.root)
        self.mock(job, "other_builds", return_value=["bounded peer"])
        self.available = self.mock(job, "available_memory_bytes", return_value=120 * 1024**3)
        self.lease = self.mock(job, "Lease").return_value
        self.lease.held = False

        def reserve(available, peers, policy, *, commit):
            self.assertEqual(peers, ["bounded peer"])
            self.assertEqual(policy["tree_memory_gib"], 8)
            self.assertEqual(policy["reserve_gib"], 32)
            self.lease.held = commit
            return {"admitted": commit}

        self.lease.sample.side_effect = reserve
        self.launch = self.mock(job.board, "run", side_effect=self.matrix)
        self.sleep = self.mock(job.time, "sleep")

    def mock(self, owner, name, **options):
        return self.stack.enter_context(patch.object(owner, name, **options))

    def matrix(self, preflight, returned, original, output, **options):
        self.assertTrue(self.lease.held)
        self.assertTrue(options["execute"])
        spec = options["experiment"]
        self.assertIs(spec.route_review.func, self.review)
        self.assertEqual(spec.route_review.keywords["receipt_sha256"], "a" * 64)
        count = 9 if output.name == "resident_gr" else 1
        output.mkdir()
        result = {"status": spec.pass_status, "board_started": True, "board_correctness_measured": True,
                  "attempts": [{}] * (3 * count), **dict.fromkeys(job.board.CLAIMS, False)}
        (output / "results.json").write_text(json.dumps(result))
        return result

    def run_job(self, **options):
        return job.run(self.root, self.root, self.root, self.root, self.original, self.output,
                       parent_directory=self.root, receipt_sha256="a" * 64, **options)

    def saved(self):
        return json.loads((self.output / "results.json").read_text())

    def test_three_matrices_use_explicit_remote_gate_and_unpromoted_claims(self):
        result = self.run_job()
        self.assertEqual(result["status"], job.PASS)
        self.assertEqual([row["name"] for row in result["matrices"]], ["native_g", "metadata_refresh", "resident_gr"])
        self.assertEqual(self.launch.call_count, 3)
        self.assertTrue(result["board_correctness_measured"])
        self.assertTrue(all(result[key] is False for key in job.board.CLAIMS))
        self.lease.release.assert_called_once()

    def test_host_and_route_rejection_cannot_program_a_board(self):
        self.metadata.side_effect = ValueError("metadata rejected")
        with self.assertRaisesRegex(ValueError, "metadata rejected"):
            self.run_job()
        self.review.assert_not_called()
        self.launch.assert_not_called()
        self.metadata.side_effect = None
        self.output = self.root / "route-rejection"
        self.review.side_effect = ValueError("timing rejected")
        with self.assertRaisesRegex(ValueError, "timing rejected"):
            self.run_job()
        self.launch.assert_not_called()

    def test_watchdog_reserve_and_full_peer_budget_are_required(self):
        self.available.return_value = 39 * 1024**3
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), \
                self.assertRaisesRegex(TimeoutError, "watchdog reserve"):
            self.run_job(maximum_wait=1)
        self.launch.assert_not_called()
        self.assertFalse(self.saved()["board_started"])
        self.lease.release.assert_called_once()

    def test_safe_memory_admits_without_waiting_for_bounded_peer_exit(self):
        self.available.side_effect = [39 * 1024**3, 80 * 1024**3]
        self.run_job()
        self.assertEqual([call.kwargs["commit"] for call in self.lease.sample.call_args_list], [False, True])
        self.sleep.assert_called_once()

    def test_peer_budget_rejection_still_blocks_above_the_watchdog_floor(self):
        self.available.return_value = 80 * 1024**3
        self.lease.sample.side_effect = lambda *args, **kwargs: {"admitted": False}
        with patch.object(job.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            self.run_job(maximum_wait=1)
        self.assertTrue(self.lease.sample.call_args.kwargs["commit"])
        self.launch.assert_not_called()

    def test_incomplete_or_promoted_matrix_cannot_complete_qualification(self):
        for change in (lambda result: result["attempts"].pop(),
                       lambda result: result.update(publication_match_admitted=True)):
            with self.subTest(change=change):
                self.output = self.root / str(len(list(self.root.iterdir())))

                def partial(*args, **kwargs):
                    result = self.matrix(*args, **kwargs)
                    change(result)
                    return result

                self.launch.side_effect = partial
                with self.assertRaisesRegex(ValueError, "incomplete production"):
                    self.run_job()
                self.assertFalse(self.saved()["board_correctness_measured"])

    def test_child_failure_retained_and_corrupt_report_does_not_mask_reason(self):
        for data in (json.dumps({"status": "FAILED_RETAINED", "board_started": True}), "not JSON"):
            with self.subTest(data=data):
                self.output = self.root / str(len(list(self.root.iterdir())))

                def fail(*args, **kwargs):
                    output = args[3]
                    output.mkdir()
                    (output / "results.json").write_text(data)
                    raise ValueError("PMA mismatch")

                self.launch.side_effect = fail
                with self.assertRaisesRegex(ValueError, "PMA mismatch"):
                    self.run_job()
                report = self.saved()
                self.assertEqual(report["status"], "FAILED_RETAINED")
                self.assertIn("PMA mismatch", report["errors"][-1])
                if data.startswith("{"):
                    self.assertTrue(report["board_started"])
                else:
                    self.assertIn("child report unreadable", report["errors"][0])

    def test_legacy_plan_default_and_explicit_review_are_separate(self):
        for _, _, spec, _ in experiments.plans(self.root, self.root, self.root):
            self.assertIs(spec.route_review, experiments.route.review)
        for options in ({"device": True}, {"device": 2}, {"repeats": 2}, {"repeats": 11}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_job(**options)
        self.launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
