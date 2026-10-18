"""Mocked continuation tests; no route, FPGA or calibration claim."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident import continuation as owner


class FullPRContinuationTests(unittest.TestCase):
    def invoke(self, root, *, returned=None, terminal=True, failed=False, drift=False, wrong_pin=False):
        preflight, producer = root / "offline", root / "return"
        preflight.mkdir()
        (producer / "admission").mkdir(parents=True)
        (preflight / "results.json").write_text(json.dumps({"pins": []}))
        admission = producer / "admission/summary.json"
        admission.write_text("{}")
        record = {"status": owner.follow.PASS, "algorithm": owner.inputs.ALGORITHM,
                  "errors": [], "board_requested": False, "admission": owner.preparation.identity(admission)}
        record.update(returned or {})
        (producer / "results.json").write_text(json.dumps(record))
        output = root / "attempt"

        def board(*args, **kwargs):
            child = output / "board"
            child.mkdir()
            result = {"status": "FAILED_RETAINED" if failed else owner.gr.PASS,
                      "hardware_convergence_measured": not failed}
            (child / "results.json").write_text(json.dumps(result))
            if drift:
                admission.write_text("{\"changed\": true}")
            return result

        with ExitStack() as stack:
            stack.enter_context(patch.object(owner.gr_preparation, "replay", return_value={"replayed": True}))
            stack.enter_context(patch.object(owner, "runner_pins", return_value=[]))
            stack.enter_context(patch.object(owner, "service_state", return_value={"exact": True}))
            finish = stack.enter_context(patch.object(owner, "route_finished", return_value=terminal))
            stack.enter_context(patch.object(owner.time, "monotonic", side_effect=[0, 2]))
            run = stack.enter_context(patch.object(owner.board_study, "run", side_effect=board))
            pin = owner.preparation.identity(preflight / "results.json")["sha256"]
            try:
                result = owner.run(preflight, producer, admission, output, unit="fullpr-return.service",
                    invocation="a" * 32, preflight_sha256="0" * 64 if wrong_pin else pin, maximum_wait=1)
            except (ValueError, TimeoutError):
                result = json.loads((output / "results.json").read_text())
        return result, run, finish

    def test_exact_return_selects_only_resident_fullpr_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            result, run, finish = self.invoke(Path(directory))
            self.assertEqual(result["status"], owner.gr.PASS)
            self.assertTrue(result["hardware_convergence_measured"])
            self.assertFalse(result["spine_comparison"])
            self.assertFalse(result["publication_match"])
            self.assertEqual(finish.call_args.args[1], "a" * 32)
            self.assertEqual(run.call_args.args[2], owner.inputs.ALGORITHM)
            self.assertEqual(run.call_args.kwargs["repeats"], 3)
            self.assertTrue(run.call_args.kwargs["execute"])
            self.assertEqual(run.call_args.kwargs["experiment"].name, "new_production_gr_fullpr_resident")

    def test_incomplete_wrong_or_unpinned_return_never_requests_board(self):
        for kwargs in ({"terminal": False}, {"wrong_pin": True},
                {"returned": {"algorithm": "residual_pagerank"}},
                {"returned": {"status": "FAILED_RETAINED"}},
                {"returned": {"errors": ["failed timing"]}},
                {"returned": {"admission": {}}}, {"returned": {"board_requested": True}}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                result, run, _ = self.invoke(Path(directory), **kwargs)
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertFalse(result["board_requested"])
                run.assert_not_called()

    def test_local_return_keeps_the_same_fullpr_admission_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            result, run, _ = self.invoke(Path(directory), returned={"status": owner.local_follow.PASS})
            self.assertEqual(result["status"], owner.gr.PASS)
            run.assert_called_once()
        for change in ({"algorithm": "residual_pagerank"}, {"admission": {}},
                       {"errors": ["timing failed"]}, {"board_requested": True}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                result, run, _ = self.invoke(Path(directory),
                    returned={"status": owner.local_follow.PASS, **change})
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertFalse(result["board_requested"])
                run.assert_not_called()

    def test_board_failure_or_changed_admission_is_retained_not_retried(self):
        for kwargs in ({"failed": True}, {"drift": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                result, run, _ = self.invoke(Path(directory), **kwargs)
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertFalse(result["hardware_convergence_measured"])
                self.assertIn("board_report", result)
                run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
