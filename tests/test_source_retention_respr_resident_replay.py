import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    respr_resident_replay as replay, resident_board as board, resident_results,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class ResidentReplayTest(unittest.TestCase):
    def test_stage_binding_rejects_another_host_or_clocks(self):
        report = {"pins": {"gr_host": {"path": "host"}}, "stage_gates": {"pins": [{"path": "r"}],
                  "resident_mhz": [150, 500, 450]}}
        stage = {"status": "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE",
                 "inputs": [{"path": "r"}, {"path": "host"}], "image": {"path": "image"},
                 "g": {"driver_mhz": {"current": [150, 500, 450]}}}
        with patch.object(replay, "unchanged") as verify:
            replay.stage_inputs(stage, report)
            verify.assert_called_once_with([*stage["inputs"], stage["image"]])
            for mutation in ({"inputs": [{"path": "r"}]}, {"status": "R_NOT_ADMITTED"},
                             {"g": {"driver_mhz": {"current": [140, 500, 450]}}}):
                with self.assertRaises(ValueError):
                    replay.stage_inputs(dict(stage, **mutation), report)

    def test_replays_original_pair_retains_no_propagation_and_rejects_changed_raw_logs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            def make(name, data=""):
                path = root / name
                path.write_text(data)
                return identity(path)

            graph = make("flickr", "2552 8192 16\n")
            pins = {"flickr": graph, **{key: make(key) for key in ("gr_host", "spine_host", "spine_image",
                                                                 "comparator")}}
            image, ranks = make("gr_image"), make("ranks")
            report = {"pins": pins, "bdf": board.BDF, "device": board.DEVICE,
                      "stage_gates": {"resident_mhz": [150, 500, 450]}}
            commands = {"spine": [pins["spine_host"]["path"], pins["spine_image"]["path"], "--dynamic-graph",
                                  graph["path"], "--source", "0", "--resident-benchmark"],
                        "gr": [pins["gr_host"]["path"], image["path"], graph["path"], ranks["path"]]}
            rows = {}
            for arm, command in commands.items():
                binary = image if arm == "gr" else pins["spine_image"]
                modes = ([f"SPINE_EXPECT_BDF={board.BDF}"] if arm == "spine" else
                         [f"GRASU_REGRAPH_EXPECT_BDF={board.BDF}", "GRASU_UPDATE_REPEATS=1",
                          "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
                          "GRASU_SHARDED_EVENT_TRACE=0"])
                clock = {"binary": binary, "bdf": board.BDF,
                         "driver_reported_mhz": [150 if arm == "gr" else 140, 500, 450]}
                rows[arm] = {"stdout": make(arm + ".stdout"), "stderr": make(arm + ".stderr"),
                             "clock": clock, "clock_evidence": clock,
                             "command": ["/usr/bin/taskset", "-c", "124,125", "/usr/bin/env",
                                         f"XCL_DEVICE_INDEX={board.DEVICE}", *modes, *command]}
            rows["gr"]["ranks"] = ranks
            case = {"dataset": "Flickr", "source": 0, "requires_propagation": True}
            pair = {"positive_propagation_on_both": False, "gr_wall_ms": 4.0, "spine_wall_ms": 5.0}
            log = make("pair.json", json.dumps({"gr_wall_ms": 4.0, "spine_wall_ms": 5.0}))
            record = {"case": case, "pair": pair, "comparison_log": log, "rows": rows,
                      "attempts": [{"arm": arm, "argv": rows[arm]["command"][3:]} for arm in ("spine", "gr")]}
            stage = {"image": image}
            with (patch.object(board, "frozen_case", return_value=case),
                  patch.object(replay.clocks, "replay", side_effect=lambda evidence: evidence),
                  patch.object(resident_results, "analyze", return_value=dict(pair)) as analyze):
                result = replay.replay_case(record, report, stage)
                self.assertEqual(result["scope"], "RETAINED_WITHOUT_REQUIRED_PROPAGATION")
                self.assertFalse(result["same_reported_clocks"])
                self.assertNotEqual(analyze.call_args.args[-2], root)
                record["attempts"].append(record["attempts"][0])
                with self.assertRaisesRegex(ValueError, "one measured command"):
                    replay.replay_case(record, report, stage)
                record["attempts"].pop()
                with self.assertRaisesRegex(ValueError, "frozen arm"):
                    replay.replay_case(record, report, {"image": make("other-image")})
                command = rows["gr"]["command"]
                repeat = command.index("GRASU_UPDATE_REPEATS=1")
                command[repeat] = "GRASU_UPDATE_REPEATS=3"
                record["attempts"][1]["argv"] = command[3:]
                with self.assertRaisesRegex(ValueError, "frozen arm"):
                    replay.replay_case(record, report, stage)
                command[repeat] = "GRASU_UPDATE_REPEATS=1"
                record["attempts"][1]["argv"] = command[3:]
                Path(rows["gr"]["stdout"]["path"]).write_text("changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    replay.replay_case(record, report, stage)
