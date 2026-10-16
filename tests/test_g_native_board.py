import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.native_board import analysis, preparation, study


def fixture(board=False):
    setup = {"board": board, "shards": 5, "hbm_bytes": preparation.CASE["hbm_bytes"], "one_time_setup_ms": 1.0}
    if board:
        setup["device_bdf"] = "0000:41:00.1"
    batches = []
    for expected in preparation.CASE["batches"]:
        events = []
        base = 1000000 * (expected["batch"] + 1)
        def event(shard, role, begin, start, end):
            return {"batch": expected["batch"], "shard": shard, "role": role,
                    "queued_ns": begin, "submit_ns": begin + 1, "start_ns": start, "end_ns": end}
        if board:
            if expected["updates"]:
                for shard in (0, 4):
                    events += [event(shard, "update_dma", base + 100, base + 200, base + 400)] * 4
            for shard in range(5):
                first = base + 10000 + shard * 100000
                events += [event(shard, role, first, first + 10000, first + 50000)
                           for role in sorted(analysis.ROLES)]
        row = {**expected, "board": board, "checked_words": preparation.CASE["checked_words"],
               **dict.fromkeys(analysis.TIMES, 0.0), "host_preparation_ms": 0.2,
               "transfer_wall_ms": 1.0, "launch_wait_ms": 1.0, "g_ready_wall_ms": 3.0,
               "complete_state_pass": True, "metadata_pass": True, "restored_pma": False}
        if board:
            row["kernel_busy_ms"], row["kernel_span_ms"] = analysis.window(
                [event for event in events if event["role"] != "update_dma"])
        batches.append({"events": events, "row": row})
    return setup, batches


def transcript(setup, batches):
    lines = ["CONTINUOUS_G_SETUP " + json.dumps(setup)]
    for batch in batches:
        lines += ["CONTINUOUS_G_EVENT " + json.dumps(event) for event in batch["events"]]
        lines.append("CONTINUOUS_G_ROW " + json.dumps(batch["row"]))
    lines.append(analysis.BOARD_PASS if setup["board"] else analysis.PASS)
    return "\n".join(lines) + "\n"


class NativeBoardTests(unittest.TestCase):
    def parse(self, setup, batches, **kwargs):
        return analysis.analyze(preparation.CASE, transcript(setup, batches), "",
                                bdf="0000:41:00.1" if setup["board"] else None, **kwargs)

    def test_native_host_is_not_board_measurement(self):
        setup, batches = fixture()
        result = self.parse(setup, batches)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["events"], [])
        self.assertIn("NOT_BOARD", analysis.PASS)

    def test_board_counts_all_five_shards_and_eight_update_dmas(self):
        setup, batches = fixture(True)
        result = self.parse(setup, batches)
        self.assertEqual(len(result["events"]), 166)
        self.assertEqual({event["shard"] for event in result["events"]}, set(range(5)))
        self.assertEqual(sum(event["role"] == "update_dma" for event in result["events"]), 16)

    def test_wrong_geometry_padding_state_metadata_or_scope_rejected(self):
        for key, value in (("updates", True), ("checked_words", 20971680), ("edges", 1),
                           ("board", True), ("complete_state_pass", False), ("metadata_pass", False),
                           ("restored_pma", True), ("kernel_span_ms", 1.0), ("oracle_ms", float("nan")),
                           ("g_ready_wall_ms", 0.0), ("extra", 1)):
            setup, batches = fixture()
            batches[0]["row"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.parse(setup, batches)
        for key, value in (("shards", 1), ("hbm_bytes", 1), ("board", True), ("one_time_setup_ms", True)):
            setup, batches = fixture()
            setup[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.parse(setup, batches)

    def test_missing_duplicate_out_of_scope_or_early_shard_events_rejected(self):
        for fault in ("missing", "duplicate", "early", "unknown", "boolean", "reorder", "dma_empty", "dma_late", "batch"):
            setup, batches = fixture(True)
            events = batches[0]["events"]
            if fault == "missing": events.pop()
            elif fault == "duplicate": events.append(copy.deepcopy(events[-1]))
            elif fault == "early": events[10]["queued_ns"] = events[0]["start_ns"]
            elif fault == "unknown": events[0]["shard"] = 5
            elif fault == "boolean": events[0]["batch"] = False
            elif fault == "reorder": events.reverse()
            elif fault == "dma_empty": events[0]["role"] = "update_dma"
            elif fault == "dma_late":
                batches[1]["events"][0]["end_ns"] += 100000
            elif fault == "batch": events[0]["batch"] = 1
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.parse(setup, batches)

    def test_wrong_bdf_wrong_union_or_false_timing_rejected(self):
        for fault in ("bdf", "busy", "span", "wall"):
            setup, batches = fixture(True)
            if fault == "bdf": setup["device_bdf"] = "wrong"
            elif fault == "busy": batches[0]["row"]["kernel_busy_ms"] *= 2
            elif fault == "span": batches[0]["row"]["kernel_span_ms"] *= 2
            else: batches[0]["row"]["launch_wait_ms"] = 0.001
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.parse(setup, batches)

    def test_host_output_cannot_be_analyzed_as_fpga_output(self):
        setup, batches = fixture()
        with self.assertRaises(ValueError):
            analysis.analyze(preparation.CASE, transcript(setup, batches), "", bdf="0000:41:00.1")
        with self.assertRaises(ValueError):
            analysis.analyze(preparation.CASE, transcript(setup, batches), "unclassified warning")
        with self.assertRaises(ValueError):
            analysis.analyze({**preparation.CASE, "shards": 1}, transcript(setup, batches), "")

    def test_truncated_or_extra_matrix_rejected(self):
        setup, batches = fixture()
        for changed in (batches[:-1], batches + [batches[-1]], batches[::-1]):
            with self.assertRaises(ValueError):
                self.parse(setup, changed)

    def test_compilation_keeps_xrt_but_no_vendor_hls_or_reduced_cache(self):
        argv = preparation.command(Path("/source"), Path("/xrt"), "g++", Path("/probe"))
        self.assertIn("/source/native_board/control.cpp", argv)
        for flag in ("-D_GLIBCXX_ASSERTIONS", "-Wall", "-Wextra", "-Werror", "-MD", "-lxilinxopencl"):
            self.assertIn(flag, argv)
        self.assertFalse(any("MAX_CACHE_SEGMENT" in flag or "Vitis_HLS" in flag for flag in argv))

    def test_deterministic_comparison_ignores_only_times(self):
        setup, batches = fixture()
        one = self.parse(setup, batches)
        batches[0]["row"]["oracle_ms"] = 100
        setup["one_time_setup_ms"] = 200
        two = self.parse(setup, batches)
        self.assertEqual(analysis.deterministic(one), analysis.deterministic(two))
        batches[0]["row"]["edges"] = 1
        two["rows"][0]["edges"] = 1
        self.assertNotEqual(analysis.deterministic(one), analysis.deterministic(two))

    def test_existing_attempt_and_invalid_wait_cannot_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileExistsError):
                study.run(root, root, root, root, root)
            for wait in (0, -1, True, 1.5, 86401):
                with self.assertRaises(ValueError):
                    study.run(root / "missing", root, root, root, root, wait_seconds=wait)

    def test_memory_deadline_retains_failure_without_launching_a_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "memory.events").write_text("oom 0\noom_kill 0\noom_group_kill 0\n")
            (root / "include/CL").mkdir(parents=True)
            (root / "include/CL/cl_ext_xilinx.h").touch()
            (root / "results.json").write_text(json.dumps({"status": study.old_analysis.PASS}))
            lease = MagicMock()
            lease.sample.return_value = {"admitted": False}
            def prepare(output, *_):
                output.mkdir()
                return [], {"regression_cases": [], "cases": [preparation.CASE]}
            with patch.object(study, "current", return_value=root), \
                    patch.object(study, "verify", return_value={"limits": {
                        "memory.max": str(4 * 1024**3), "memory.high": str(3 * 1024**3)}}), \
                    patch.object(study, "validate_old"), patch.object(preparation, "prepare", side_effect=prepare), \
                    patch.object(study, "Lease", return_value=lease), \
                    patch.object(study, "available_memory_bytes", return_value=1), \
                    patch.object(study, "other_builds", return_value=[]), \
                    patch.object(study.time, "monotonic", side_effect=[0, 2]), \
                    patch.object(study, "run_link") as launch:
                with self.assertRaises(TimeoutError):
                    study.run(root / "attempt", root, root, root, root, wait_seconds=1)
            launch.assert_not_called()
            lease.release.assert_called_once()
            report = json.loads((root / "attempt/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertEqual(report["steps"], [])
            self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
