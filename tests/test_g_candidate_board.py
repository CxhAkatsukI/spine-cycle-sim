import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import candidate_board as board
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.native_profile import (
    ALGORITHM, EVENTS, ROLES, update_only_profile,
)


ORACLE = "status=PASS touched_segments=9 checked_words=32 pma_mismatches=0 degree_sources=2 degree_mismatches=0"
CONFIG = {"vertices": 65539, "updates": 3, "shards": 2, "pma_slots": 32}


def log():
    rows = [
        f"GRASU_REGRAPH_DEVICE bdf={board.BDF}",
        "SHARDED_METADATA_POLICY replicas=4",
        "SHARDED_INPUT_RESIDENCY policy=premigrate",
        "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_degree=1",
        f"{ALGORITHM}_INPUT vertices=65539 destination_partitions=2 logical_updates=3 "
        "physical_updates=3 pma_slots_total=32",
    ]
    for shard, vertices, gap in ((0, 65536, "0.000000"), (1, 3, "0.000024")):
        rows.append(f"GRASU_SHARDED_UPDATE_LAYOUT shard={shard} destination_base={shard * 65536} "
                    f"destination_vertices={vertices} updates={shard + 1} pma_slots=16")
        rows.append(f"{EVENTS} shard={shard} gap_from_previous_ms={gap} union_ms=0.000010 "
                    + " ".join(f"{role}_ms=0.000005" for role in sorted(ROLES)))
        for role in sorted(ROLES):
            start, end = ("0.000005", "0.000010") if role == "degree" else ("0.000000", "0.000005")
            rows.append(f"{EVENTS}_PHASE shard={shard} cu={role} execute_ms=0.000005 "
                        f"start_offset_ms={start} end_offset_ms={end}")
    rows.extend((
        "GRASU_SHARDED_UPDATE_REPEAT repeat=0 final=1 update_ms=0.000044",
        f"GRASU_SHARDED_UPDATE_ONLY_RESULT {ORACLE} algorithm={ALGORITHM} update_ms=0.000044 "
        "repeats=1 measurement_window=same_process_update_events",
    ))
    return "\n".join(rows)


class NativeGProfileTests(unittest.TestCase):
    def profile(self, text, oracle=ORACLE):
        return update_only_profile(text, oracle, bdf=board.BDF, reference=CONFIG)

    def test_elapsed_includes_shard_gaps_and_degree_tail(self):
        result = self.profile(log())
        self.assertEqual(result["event_span_ns"], 44)
        self.assertEqual(result["busy_union_ns"], 20)
        self.assertEqual(result["inter_shard_gap_ns"], 24)
        self.assertEqual(result["cu_events"], 20)

    def test_bad_records_are_rejected(self):
        cases = (
            ("cu=degree", "cu=other"),
            ("update_ms=0.000044", "update_ms=0.000020"),
            ("execute_ms=0.000005", "execute_ms=0.000006"),
            ("physical_updates=3", "physical_updates=2"),
            ("destination_base=65536", "destination_base=65535"),
            ("pma_mismatches=0", "pma_mismatches=1"),
        )
        for old, new in cases:
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.profile(log().replace(old, new, 1))
        with self.assertRaises(ValueError):
            self.profile(log() + "\nGRASU_SHARDED_UPDATE_DIAGNOSTIC_EVENTS shard=0")
        with self.assertRaises(ValueError):
            self.profile(log(), ORACLE.replace("degree_mismatches=0", "degree_mismatches=1"))


class ExactRouteTests(unittest.TestCase):
    @patch.object(board, "check_memory")
    def test_only_completed_screen_of_exact_image_is_accepted(self, _check_memory):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = root / "route"
            (route / "execution").mkdir(parents=True)
            (route / "manifest.json").write_text('{"pins": []}')
            image = route / "candidate.hw.xclbin"
            image.write_bytes(b"candidate")
            pin = board.identity(image)
            route_pin = {key: pin[key] for key in ("path", "sha256")}
            execution = route / "execution/execution.json"
            execution.write_text(json.dumps({"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "xclbin": route_pin}))
            analysis = root / "analysis.json"
            analysis.write_text("{}")
            (root / "board-once").mkdir()
            board_report = root / "board-once/results.json"
            evidence = {"bdf": board.BDF, "device": board.DEVICE, "pins": {"r_current": pin}}
            board_report.write_text(json.dumps(evidence))
            report = root / "results.json"
            report.write_text(json.dumps({"status": "WAITING_FOR_EXACT_ROUTE"}))
            with self.assertRaises(TimeoutError):
                board.wait_for_image(route, report, 0)
            report.write_text(json.dumps({"status": "FAILED_RETAINED"}))
            with self.assertRaises(RuntimeError):
                board.wait_for_image(route, report, 0)
            report.write_text(json.dumps({"status": "R_PERFORMANCE_GATE_FAILED_RETAINED",
                                          "pins": [route_pin, board.identity(execution)],
                                          "analysis": board.identity(analysis)}))
            self.assertEqual(board.wait_for_image(route, report, 0)[0], image)
            board_report.write_text(json.dumps({**evidence, "pins": {"r_current": {**pin, "bytes": 0}}}))
            with self.assertRaises(ValueError):
                board.wait_for_image(route, report, 0)
            board_report.write_text(json.dumps(evidence))
            image.write_bytes(b"another build")
            with self.assertRaises(ValueError):
                board.wait_for_image(route, report, 0)
