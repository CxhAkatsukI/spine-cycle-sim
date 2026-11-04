import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import active_min_resident as resident
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import active_min_resident_follow as follow
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class ActiveMinResidentTest(unittest.TestCase):
    def test_so_memory_profile_only_accepts_the_pinned_matching_unthrottled_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            case = dict(dataset="SO", logical="weighted_sssp", memory_gib=32, source=0, graph="graph",
                        spine_host="host", spine_binary="image")
            receipt = dict(status="RESIDENT_PAIR_PASS", boundary=resident.BOUNDARY, config=case,
                           memory_events_after="high 0\nmax 0\noom 0\noom_kill 0\n",
                           samples=[dict(warmup=False, resources={"spine": {"peak_tree_rss_kib": 4 * 2**20},
                                                                  "gr": {"peak_tree_rss_kib": 19 * 2**20}})])
            path.write_text(json.dumps(receipt))
            pin = identity(path)
            profile = resident.so_memory_profile(case, path, pin["sha256"])
            self.assertEqual(profile["memory_gib"], 24)
            self.assertEqual(profile["receipt"], pin)
            with self.assertRaisesRegex(ValueError, "pinned"):
                resident.so_memory_profile(dict(case, source=1), path, pin["sha256"])
            receipt["samples"][0]["resources"]["gr"]["peak_tree_rss_kib"] = 21 * 2**20
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "pinned"):
                resident.so_memory_profile(case, path, pin["sha256"])
            with self.assertRaisesRegex(ValueError, "4 GiB"):
                resident.so_memory_profile(case, path, identity(path)["sha256"])
            with self.assertRaisesRegex(MemoryError, "throttled"):
                resident.require_unthrottled("high 1\nmax 0\noom 0\noom_kill 0\n")

    def test_freezes_old_batch_but_not_old_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph, spine_host, spine_image = [root / name for name in ("graph", "spine", "image")]
            for path in (graph, spine_host, spine_image):
                path.write_text("100 200 8\n")
            pins = [identity(path) for path in (graph, spine_host, spine_image)]
            config = dict(dataset="AU", logical="weighted_sssp", source=11, graph=str(graph),
                          spine_host=str(spine_host), spine_binary=str(spine_image), memory_gib=16,
                          expected_pins=pins, gr_host="old-host", gr_binary="old-image")
            config_path = root / "sssp-au.json"
            config_path.write_text(json.dumps(config))
            manifest = root / "sssp-au/manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(json.dumps(dict(boundary=resident.BOUNDARY, config=config, pins=pins)))

            case, frozen = resident.frozen_case(root, "weighted_sssp", "AU")
            self.assertEqual((case["vertices"], case["edges"], case["updates"]), (100, 200, 8))
            self.assertEqual(len(frozen), 5)
            gate = {"host": {"path": "screened-host"}, "image": {"path": "screened-image"}}
            commands = resident.commands(case, gate, root)
            self.assertEqual(commands["gr"][:3], ["screened-host", "screened-image", str(graph)])
            self.assertEqual(commands["gr"][-2:], ["11", "256"])
            self.assertEqual(commands["spine"][-2:], ["11", "--resident-benchmark"])
            config_path.write_text(json.dumps(dict(config, source=12)))
            with self.assertRaisesRegex(ValueError, "disagree"):
                resident.frozen_case(root, "weighted_sssp", "AU")
            config_path.write_text(json.dumps(config))
            graph.write_text("100 200 8\nchanged edges\n")
            with self.assertRaisesRegex(ValueError, "missing or changed: graph"):
                resident.frozen_case(root, "weighted_sssp", "AU")

    def test_failed_gate_retains_no_board_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            args = SimpleNamespace(output=output, dataset="AU", algorithm="cc", route=None, host=None,
                                   r_report=None, r_inputs=None, g_report=None, g_reference=None, wait_seconds=0)
            with patch.object(resident.active_min_admission, "admit", side_effect=ValueError("R over budget")), \
                    patch.object(resident, "lease") as lease:
                with self.assertRaisesRegex(ValueError, "R over budget"):
                    resident.run(args)
                lease.assert_not_called()
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(report["attempts"], [])
            self.assertEqual(report["status"], "FAILED_RETAINED")
            with self.assertRaises(FileExistsError):
                resident.run(args)

    def test_cc_wall_pins_match_the_frozen_input_and_admitted_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wall = resident.cc_resident_wall
            files = {name: root / name for name in ("spine_host", "spine_binary", "gr_host", "inputs")}
            for name, path in files.items():
                path.write_text(name)
            source, graph_slice, update_slice = [root / name for name in ("raw", "old", "batch")]
            for path in (source, graph_slice, update_slice):
                path.write_text(path.name)
            case = dict(graph=str(source), source=0, vertices=10, edges=20, updates=4)
            source_pin = identity(source)
            files["inputs"].write_text(json.dumps(dict(case, source=source_pin, graph=identity(graph_slice),
                                                        update=identity(update_slice))))
            packet = root / "packet.json"
            packet.write_text(json.dumps({name: str(path) for name, path in files.items()}))
            args = SimpleNamespace(algorithm="cc", cc_wall_packet=packet)
            with patch.multiple(wall, IMAGE=identity(files["spine_binary"])["sha256"],
                                SPINE_HOST=identity(files["spine_host"])["sha256"],
                                GR_HOST=identity(files["gr_host"])["sha256"]):
                configured, pins = wall.configure(args, case, [source_pin])
                self.assertIn(identity(packet), pins)
                self.assertEqual(configured["memory_gib"], 32)
                commands = wall.commands(configured, {"image": {"path": "admitted"}}, root)
                self.assertEqual(commands["gr"][:3], [str(files["gr_host"]), "admitted", str(source)])
                self.assertEqual(commands["spine"][-8:], ["--mode", "partial", "--samples", "1",
                                                          "--slice", str(graph_slice), "--update", str(update_slice)])
                with self.assertRaisesRegex(ValueError, "frozen workload"):
                    wall.configure(args, dict(case, updates=5), [source_pin])
                update_slice.write_text("wrong update")
                with self.assertRaisesRegex(ValueError, "changed"):
                    wall.configure(args, case, [source_pin])

    def test_comparison_rejects_wrong_dimensions_and_changed_raw_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            logs = {name: output / name for name in ("gr", "spine")}
            for path in logs.values():
                path.write_text("raw")
            arms = {name: {"stdout": identity(path)} for name, path in logs.items()}
            case = dict(logical="connected_components", source=0, vertices=10, updates=16)

            def wrong_dimensions(*args, **kwargs):
                (output / "pair.json").write_text(json.dumps({"vertices": 9, "logical_updates": 16,
                                                               "boundary": resident.BOUNDARY}))

            with patch.object(resident.subprocess, "run", side_effect=wrong_dimensions):
                with self.assertRaisesRegex(ValueError, "dimensions"):
                    resident.compare(case, arms, "comparator", output)
            logs["gr"].write_text("edited")
            with patch.object(resident.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "changed"):
                    resident.compare(case, arms, "comparator", output)
                run.assert_not_called()


class ResidentStageFollowerTest(unittest.TestCase):
    INVOCATION = "a" * 32

    def state(self, phase):
        return {"LoadState": "not-found" if phase == "collected" else "loaded",
                "InvocationID": "" if phase == "collected" else self.INVOCATION,
                "ActiveState": {"running": "active", "collected": "inactive", "failed": "failed"}[phase],
                "SubState": {"running": "running", "collected": "dead", "failed": "failed"}[phase],
                "MainPID": "17" if phase == "running" else "0",
                "Result": "exit-code" if phase == "failed" else "success",
                "ExecMainStatus": "1" if phase == "failed" else "0"}

    def test_receipts_from_observed_producers_request_exactly_one_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(output=root / "output", dataset="AU", algorithm="weighted_sssp",
                                   stage_wait_seconds=60)
            for stage in ("r", "g"):
                setattr(args, stage + "_unit", stage + ".service")
                setattr(args, stage + "_invocation", self.INVOCATION)
                setattr(args, stage + "_report", root / (stage + ".json"))
            args.g_report.write_text(json.dumps(dict(status="WAITING_FOR_ROUTE")))

            def produce():
                for stage, status in follow.STAGE_PASS.items():
                    getattr(args, stage + "_report").write_text(
                        json.dumps(dict(status=status, algorithm=args.algorithm)))

            def resident_once(child):
                self.assertEqual(child.stage_receipts, {"r": identity(args.r_report), "g": identity(args.g_report)})
                child.output.mkdir()
                result = dict(status="MEASURED_RESIDENT_PAIR")
                (child.output / "results.json").write_text(json.dumps(result))
                return result

            with patch.object(follow, "service_state", side_effect=[self.state("running")] * 4 +
                              [self.state("collected")] * 2), patch.object(follow, "runner_pins", return_value=[]), \
                    patch.object(follow.time, "sleep", side_effect=lambda _: produce()), \
                    patch.object(resident, "run", side_effect=resident_once) as board:
                result = follow.run(args)
                board.assert_called_once()
            self.assertEqual(result["status"], "MEASURED_RESIDENT_PAIR")
            self.assertTrue(result["requested_pair"])

    def test_refuses_unseen_invocation_and_failed_stage_even_with_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(dict(status=follow.STAGE_PASS["r"], algorithm="cc")))
            row = dict(unit="r.service", invocation=self.INVOCATION, report_path=str(path), observed=False)
            with self.assertRaisesRegex(ValueError, "lost its pinned invocation"):
                follow.ready(row, self.state("collected"), follow.STAGE_PASS["r"], "cc")
            with self.assertRaisesRegex(ValueError, "did not complete successfully"):
                follow.ready(row, self.state("failed"), follow.STAGE_PASS["r"], "cc")
            self.assertIn("failed_receipt", row)
            path.write_text(json.dumps(dict(status="R_GATE_FAILED", algorithm="cc")))
            with self.assertRaisesRegex(ValueError, "R_GATE_FAILED"):
                follow.ready(row, self.state("collected"), follow.STAGE_PASS["r"], "cc")
