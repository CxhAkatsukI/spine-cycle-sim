import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.metadata_refresh import analysis, preparation, study
from spine_cycle_sim.experiments.evaluation_impact.common_g.native_board.analysis import ROLES


def fixture(board=False):
    setup = {"board": board, "shards": 5, "hbm_bytes": preparation.CASE["hbm_bytes"], "one_time_setup_ms": 1.0}
    if board:
        setup["device_bdf"] = "0000:41:00.1"
    records = [("METADATA_G_SETUP", setup)]
    for generation in range(2):
        def event(batch, shard, role, base):
            return {"generation": generation, "batch": batch, "shard": shard, "role": role,
                    "queued_ns": base, "submit_ns": base + 1, "start_ns": base + 10, "end_ns": base + 100}
        if board and generation:
            records += [("METADATA_G_EVENT", event(-1, shard, role, 4000000 + 1000 * shard))
                        for shard in range(5) for role in ("metadata_row_dma", "metadata_binary_dma")]
        records.append(("METADATA_G_GENERATION", {"generation": generation, "metadata_preparation_ms": 1.0,
                        "metadata_dma_ms": 1.0, "same_bos": True, "restored_pma": False}))
        for expected in preparation.CASE["batches"]:
            base = 1000000 * (1 + generation * 4 + expected["batch"])
            events = []
            if board:
                if expected["updates"]:
                    events += [event(expected["batch"], shard, "update_dma", base + 100) for shard in (0, 4) for _ in range(4)]
                events += [event(expected["batch"], shard, role, base + 10000 + 1000 * shard)
                           for shard in range(5) for role in sorted(ROLES)]
            row = {**expected, "generation": generation, "board": board,
                   "checked_words": preparation.CASE["checked_words"], **dict.fromkeys(analysis.TIMES, 0.0),
                   "host_preparation_ms": 0.2, "transfer_wall_ms": 1.0, "launch_wait_ms": 1.0,
                   "g_ready_wall_ms": 3.0, "complete_state_pass": True, "metadata_pass": True, "restored_pma": False}
            if board:
                row["kernel_busy_ms"], row["kernel_span_ms"] = analysis.window([e for e in events if e["role"] != "update_dma"])
            records += [("METADATA_G_EVENT", e) for e in events]
            records.append(("METADATA_G_ROW", row))
    return records


def transcript(records, board=False):
    return "\n".join([*(kind + " " + json.dumps(row) for kind, row in records),
                      analysis.BOARD_PASS if board else analysis.PASS]) + "\n"


class MetadataRefreshTests(unittest.TestCase):
    def parse(self, records, board=False):
        return analysis.analyze(transcript(records, board), "", bdf="0000:41:00.1" if board else None)

    def test_two_generations_six_complete_host_rows_not_board(self):
        result = self.parse(fixture())
        self.assertEqual(len(result["rows"]), 6)
        self.assertEqual(len(result["generations"]), 2)
        self.assertEqual(result["events"], [])
        self.assertEqual(preparation.CASE["ports_nonempty_batch"], [4, 2, 4, 2])

    def test_board_checks_same_bos_and_all_metadata_dma_and_kernel_events(self):
        result = self.parse(fixture(True), True)
        self.assertEqual(len(result["events"]), 342)
        self.assertEqual(sum(e["batch"] == -1 for e in result["events"]), 10)
        self.assertEqual(sum(e["role"] == "update_dma" for e in result["events"]), 32)

    def test_missing_duplicate_reset_or_unclassified_records_rejected(self):
        for fault in ("missing_generation", "duplicate_row", "reset", "new_bos", "metadata", "geometry", "unknown"):
            records = fixture()
            if fault == "missing_generation": records.pop(5)
            elif fault == "duplicate_row": records.append(copy.deepcopy(records[-1]))
            elif fault == "reset": records[5][1]["restored_pma"] = True
            elif fault == "new_bos": records[5][1]["same_bos"] = False
            elif fault == "metadata": records[-1][1]["metadata_pass"] = False
            elif fault == "geometry": records[0][1]["shards"] = True
            elif fault == "unknown": records.append(("UNCLASSIFIED", {}))
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.parse(records)

    def test_board_missing_refresh_wrong_transaction_or_overlap_rejected(self):
        for fault in ("missing", "duplicate", "wrong_generation", "wrong_role", "late", "span", "bdf"):
            records = fixture(True)
            index = next(i for i, (kind, row) in enumerate(records) if kind == "METADATA_G_EVENT" and row["batch"] == -1)
            if fault == "missing": records.pop(index)
            elif fault == "duplicate": records.insert(index, copy.deepcopy(records[index]))
            elif fault == "wrong_generation": records[index][1]["generation"] = 0
            elif fault == "wrong_role": records[index][1]["role"] = "update_dma"
            elif fault == "late": records[index][1].update(queued_ns=6000000, submit_ns=6000001, start_ns=6000010, end_ns=6000100)
            elif fault == "span":
                next(row for kind, row in records if kind == "METADATA_G_GENERATION" and row["generation"] == 1)["metadata_dma_ms"] = 0
            else: records[0][1]["device_bdf"] = "wrong"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.parse(records, True)

    def test_stale_negative_requires_exact_failed_transaction_and_reason(self):
        records = fixture()[:7]
        text = "\n".join(kind + " " + json.dumps(row) for kind, row in records) + "\n"
        error = "complete resident PMA/padding mismatch\n"
        self.assertEqual(analysis.stale_rejection(text, error)["batch"], 1)
        for changed, diagnostic in (("", error), (text, "other error"), (text + analysis.PASS, error),
                                    (text.rsplit("\n", 2)[0], error)):
            with self.assertRaises(ValueError):
                analysis.stale_rejection(changed, diagnostic)

    def test_host_cannot_be_promoted_to_fpga_timing(self):
        records = fixture()
        with self.assertRaises(ValueError):
            analysis.analyze(transcript(records), "", bdf="0000:41:00.1")
        records[-1][1]["kernel_busy_ms"] = 1
        with self.assertRaises(ValueError):
            self.parse(records)

    def test_command_uses_shared_xrt_host_without_hls_or_reduced_cache(self):
        argv = preparation.command(Path("/source"), Path("/xrt"), "g++", Path("/probe"))
        self.assertIn("/source/metadata_refresh/control.cpp", argv)
        self.assertNotIn("/source/continuous_board/control.cpp", argv)
        self.assertIn("-Werror", argv)
        self.assertIn("-MD", argv)
        self.assertFalse(any("Vitis_HLS" in arg or "MAX_CACHE_SEGMENT" in arg for arg in argv))

    def test_freeze_keeps_original_files_and_declares_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            integration = Path(__file__).resolve().parents[1] / "../grasu-integration-missing"
            with patch.object(preparation.shutil, "copy2", side_effect=lambda source, target: target.touch()), \
                    patch.object(preparation, "sha256_file", return_value="a" * 64):
                pins, contract = preparation.prepare(output, integration)
            self.assertEqual(contract["generations"], 2)
            self.assertFalse(contract["restored_pma"])
            self.assertIn("original-G speed", contract["not_claimed"])
            names = [pin["path"] for pin in pins]
            self.assertTrue(any("metadata_refresh/control.cpp" in name for name in names))
            self.assertTrue(any("continuous_board/device.hpp" in name for name in names))

    def test_invalid_wait_existing_output_or_missing_containment_cannot_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(FileExistsError): study.run(root, root, root)
            for wait in (0, -1, True, 1.5, 86401):
                with self.assertRaises(ValueError): study.run(root / "missing", root, root, wait_seconds=wait)
            with patch.object(study, "current", return_value=root), patch.object(study, "verify", return_value={
                    "limits": {"memory.max": str(2 * 1024**3), "memory.high": str(2 * 1024**3)}}), \
                    patch.object(study, "run_link") as launch:
                with self.assertRaises(ValueError): study.run(root / "missing", root, root)
                launch.assert_not_called()

    def test_memory_deadline_retains_failure_without_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").write_text("oom 0\noom_kill 0\noom_group_kill 0\n")
            (root / "include/CL").mkdir(parents=True)
            (root / "include/CL/cl_ext_xilinx.h").touch()
            lease = MagicMock()
            lease.sample.return_value = {"admitted": False}
            def prepare(output, *_):
                output.mkdir()
                return [], {"case": preparation.CASE}
            with patch.object(study, "current", return_value=root), patch.object(study, "verify", return_value={
                    "limits": {"memory.max": str(2 * 1024**3), "memory.high": str(1536 * 1024**2)}}), \
                    patch.object(preparation, "prepare", side_effect=prepare), \
                    patch.object(study, "Lease", return_value=lease), patch.object(study, "available_memory_bytes", return_value=1), \
                    patch.object(study, "other_builds", return_value=[]), \
                    patch.object(study.time, "monotonic", side_effect=[0, 2]), patch.object(study, "run_link") as launch:
                with self.assertRaises(TimeoutError): study.run(root / "attempt", root, root, wait_seconds=1)
            launch.assert_not_called()
            lease.release.assert_called_once()
            report = json.loads((root / "attempt/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertEqual(report["steps"], [])


if __name__ == "__main__":
    unittest.main()
