import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board import analysis
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import events, route, runtime, study

BDF = "0000:82:00.1"


def case():
    return {"case": "AU-mixed-512", "input": "input.txt", "shards": 1, "partition_vertices": 65536,
            "batches": [{"batch": 0, "updates": 0, "edges": 8192},
                        {"batch": 1, "updates": 256, "edges": 8104},
                        {"batch": 2, "updates": 256, "edges": 8192}]}


def output():
    setup = {"board": True, "device_bdf": BDF, "shards": 1, "hbm_bytes": 16777344, "one_time_setup_ms": 1.0}
    lines = ["CONTINUOUS_G_SETUP " + json.dumps(setup)]
    for batch in case()["batches"]:
        base = (batch["batch"] + 1) * 1000000
        for i in range(min(4, batch["updates"])):
            lines.append("CONTINUOUS_G_EVENT " + json.dumps({"batch": batch["batch"], "shard": 0,
                "role": "update_dma", "queued_ns": base, "submit_ns": base + 10,
                "start_ns": base + 20 + i, "end_ns": base + 100 + i}))
        for i, role in enumerate(sorted(events.ROLES)):
            lines.append("CONTINUOUS_G_EVENT " + json.dumps({"batch": batch["batch"], "shard": 0,
                "role": role, "queued_ns": base + 200, "submit_ns": base + 210,
                "start_ns": base + 300 + i * 10, "end_ns": base + 800 + i * 10}))
        row = {**batch, "board": True, "checked_words": 2 * 131072 * 16 + 32,
               **dict.fromkeys(analysis.TIMES, 1.0), "g_ready_wall_ms": 3.1,
               "kernel_busy_ms": 590 / 1e6, "kernel_span_ms": 590 / 1e6,
               "complete_state_pass": True, "metadata_pass": True, "restored_pma": False}
        lines.append("CONTINUOUS_G_ROW " + json.dumps(row))
    return "\n".join([*lines, analysis.BOARD_PASS])


def mutate(text, prefix, index, key, value):
    lines = text.splitlines()
    selected = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    row = json.loads(lines[selected[index]].removeprefix(prefix))
    row[key] = value
    lines[selected[index]] = prefix + json.dumps(row)
    return "\n".join(lines)


class ContinuousEventTests(unittest.TestCase):
    def test_raw_event_union_is_not_the_sum_of_concurrent_kernels(self):
        result = events.analyze(case(), output(), "", bdf=BDF)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(len(result["events"]), 38)
        self.assertLess(result["rows"][0]["kernel_busy_ms"], sum(
            (row["end_ns"] - row["start_ns"]) / 1e6 for row in result["events"] if row["batch"] == 0))
        self.assertEqual(events.window([]), (0, 0))
        self.assertEqual(events.window([{"start_ns": 0, "end_ns": 10},
                                        {"start_ns": 20, "end_ns": 30}]), (20e-6, 30e-6))

    def test_missing_duplicate_and_wrong_shard_events_rejected(self):
        lines = output().splitlines()
        for text in ("\n".join(lines[:1] + lines[2:]), "\n".join(lines[:2] + lines[1:]),
                     mutate(output(), "CONTINUOUS_G_EVENT ", 0, "shard", 1),
                     mutate(output(), "CONTINUOUS_G_EVENT ", 0, "batch", True),
                     mutate(output(), "CONTINUOUS_G_EVENT ", 0, "role", "unlisted_kernel")):
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                events.analyze(case(), text, "", bdf=BDF)

    def test_invalid_times_and_reported_union_rejected(self):
        for prefix, key, value in (("CONTINUOUS_G_EVENT ", "end_ns", 0),
                                   ("CONTINUOUS_G_EVENT ", "queued_ns", -1),
                                   ("CONTINUOUS_G_EVENT ", "start_ns", True),
                                   ("CONTINUOUS_G_ROW ", "kernel_busy_ms", 1.0),
                                   ("CONTINUOUS_G_ROW ", "kernel_span_ms", float("nan")),
                                   ("CONTINUOUS_G_ROW ", "g_ready_wall_ms", 1.0),
                                   ("CONTINUOUS_G_ROW ", "oracle_ms", True),
                                   ("CONTINUOUS_G_ROW ", "complete_state_pass", False)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                events.analyze(case(), mutate(output(), prefix, 0, key, value), "", bdf=BDF)

    def test_dma_and_cross_batch_order_rejected(self):
        text = mutate(output(), "CONTINUOUS_G_EVENT ", 10, "end_ns", 2000250)
        with self.assertRaisesRegex(ValueError, "DMA"):
            events.analyze(case(), text, "", bdf=BDF)
        text = mutate(output(), "CONTINUOUS_G_EVENT ", 10, "queued_ns", 1)
        with self.assertRaisesRegex(ValueError, "cross-batch"):
            events.analyze(case(), text, "", bdf=BDF)

    def test_model_marker_device_disagreement_and_scope_rejected(self):
        for text, diagnostic, bdf in ((output(), "unclassified warning", BDF),
                                     (output(), "", "0000:c1:00.1"),
                                     (output().replace(analysis.BOARD_PASS, analysis.PASS), "", BDF),
                                     (output() + "\nCONTINUOUS_G_ROW {}", "", BDF)):
            with self.subTest(diagnostic=diagnostic, bdf=bdf), self.assertRaises(ValueError):
                events.analyze(case(), text, diagnostic, bdf=bdf)
        with self.assertRaisesRegex(ValueError, "multi-shard"):
            events.analyze({**case(), "shards": 2}, output(), "", bdf=BDF)


class ContinuousRouteTests(unittest.TestCase):
    def fixture(self, root):
        kernels = {}
        for name in route.COUNTS:
            path = root / (name + ".xo")
            path.write_text(name)
            kernels[name] = {"source": identity(path), "frozen": identity(path),
                             "replaced": name in ("bin_search", "process_cache")}
        manifest = {"status": "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION", "clock_mhz": 150,
                    "core_identity": {"synthesizable_core_identical": True}, "kernel_inputs": kernels,
                    "pins": [value["source"] for value in kernels.values()]}
        self.save(root, "manifest", manifest)
        resources = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}
        result = {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "resources": resources,
                  "inputs_unchanged": True, "xclbin": {"path": "candidate", "sha256": "hash"}}
        self.save(root, "summary", result)
        self.save(root, "execution", result)
        checked = {"topology": {"kernels": [[f"{name}:{name}_{i + 1}", "AP_CTRL_CHAIN"]
                    for name, count in route.COUNTS.items() for i in range(count)]}, "pins": []}
        return manifest, result, checked

    def save(self, root, name, value):
        (root / (name + ".json")).write_text(json.dumps(value))

    def test_completed_new_g_route_requires_final_timing_and_topology(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, checked = self.fixture(root)
            with patch.object(route, "admit_bitstream", return_value=checked) as gate:
                self.assertEqual(len(route.review(root, root / "old", root / "review")["pins"]), 2)
                gate.assert_called_once()
            with patch.object(route, "admit_bitstream", side_effect=ValueError("timing failed")):
                with self.assertRaisesRegex(ValueError, "timing failed"):
                    route.review(root, root / "old", root / "review")

    def test_live_route_old_cache_and_changed_xo_cannot_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, result, _ = self.fixture(root)
            (root / "summary.json").unlink()
            with self.assertRaisesRegex(ValueError, "unfinished"):
                route.review(root, root / "old", root / "review")
            self.save(root, "summary", result)
            original = copy.deepcopy(manifest)
            manifest["kernel_inputs"]["process_cache"]["replaced"] = False
            self.save(root, "manifest", manifest)
            with self.assertRaisesRegex(ValueError, "both new"):
                route.review(root, root / "old", root / "review")
            self.save(root, "manifest", original)
            (root / "bin_search.xo").write_text("changed")
            with self.assertRaises(ValueError):
                route.review(root, root / "old", root / "review")

    def test_link_failure_and_incomplete_cu_budget_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, result, checked = self.fixture(root)
            self.save(root, "execution", {**result, "status": "LINK_FAILED"})
            with self.assertRaisesRegex(ValueError, "final route"):
                route.review(root, root / "old", root / "review")
            self.save(root, "execution", result)
            checked["topology"]["kernels"].pop()
            with patch.object(route, "admit_bitstream", return_value=checked), self.assertRaisesRegex(ValueError, "budget"):
                route.review(root, root / "old", root / "review")

    def test_missing_cleanup_record_and_boolean_exit_code_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, result, _ = self.fixture(root)
            for resources in ({"exit_code": 0, "stop_reason": "process_exit"},
                              {**result["resources"], "exit_code": False}):
                changed = {**result, "resources": resources}
                self.save(root, "summary", changed)
                self.save(root, "execution", changed)
                with self.assertRaisesRegex(ValueError, "final route"):
                    route.review(root, root / "old", root / "review")


class ContinuousRuntimeTests(unittest.TestCase):
    def test_inherited_runtime_knobs_and_default_ini_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {}, clear=True):
                runtime.require_clean_environment(root / "host", root)
                for name in runtime.FORBIDDEN:
                    with patch.dict(os.environ, {name: "value"}), self.assertRaises(ValueError):
                        runtime.require_clean_environment(root / "host", root)
                (root / "xrt.ini").write_text("[Debug]")
                with self.assertRaises(ValueError):
                    runtime.require_clean_environment(root / "host", root)

    def test_actual_loader_paths_not_library_aliases_are_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "libxilinxopencl.so.2.18.179"
            library.write_text("library")
            alias = root / "libxilinxopencl.so.2"
            alias.symlink_to(library)
            self.assertEqual(runtime.library_paths(f"libxilinxopencl.so.2 => {alias} (0x1)\n"), [library])
            for output in ("lib => not found", "linux-vdso.so.1 (0x1)"):
                with self.assertRaises(ValueError):
                    runtime.library_paths(output)

    def test_platform_health_mig_and_bdf_checked(self):
        document = {"devices": [{"device_id": BDF, "device_status": "HEALTHY", "platforms": [{
            "static_region": {"vbnv": "xilinx_u55c_base_3"}, "status": {"mig_calibrated": "true"}, "controller": {}}]}]}
        runtime.platform(document, BDF)
        for field, value in (("device_id", "0000:c1:00.1"), ("device_status", "ERROR")):
            changed = copy.deepcopy(document)
            changed["devices"][0][field] = value
            with self.assertRaises(ValueError):
                runtime.platform(changed, BDF)
        document["devices"][0]["platforms"][0]["status"]["mig_calibrated"] = "false"
        with self.assertRaises(ValueError):
            runtime.platform(document, BDF)

    def test_changed_runtime_or_driver_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.so"
            path.write_text("runtime")
            captured = {"device": {"driver": "old"}, "pins": [identity(path)]}
            with patch.object(runtime, "device_identity", return_value=captured["device"]):
                runtime.unchanged(captured, Path("render"))
                path.write_text("changed")
                with self.assertRaises(ValueError):
                    runtime.unchanged(captured, Path("render"))
            with patch.object(runtime, "device_identity", return_value={"driver": "new"}), self.assertRaises(ValueError):
                runtime.unchanged(captured, Path("render"))


class ContinuousRunnerTests(unittest.TestCase):
    def test_unfinished_route_is_retained_without_acquiring_or_programming_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(study, "host_identity", return_value=({}, [])), \
                    patch.object(runtime, "require_clean_environment"), \
                    patch.object(route, "review", side_effect=ValueError("route unfinished")), \
                    patch.object(study, "board_lease") as lease:
                with self.assertRaisesRegex(ValueError, "unfinished"):
                    study.run(root, root, root, root / "attempt", execute=True)
                lease.assert_not_called()
            result = json.loads((root / "attempt/results.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertFalse(result["board_started"])
            self.assertTrue(all(result[key] is False for key in analysis.CLAIMS))

    def test_board_occupancy_is_checked_before_runtime_query_or_programming(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checked = {"pins": [], "candidate": {"path": "candidate", "sha256": "hash"},
                       "timing": {"report": {"path": "timing", "sha256": "hash"}}}
            with patch.object(study, "host_identity", return_value=({"contract": {}}, [])), \
                    patch.object(runtime, "require_clean_environment"), patch.object(route, "review", return_value=checked), \
                    patch.object(study, "unchanged"), patch.object(study, "containment", return_value={}), \
                    patch.object(study, "board_lease", return_value=nullcontext(Path("render"))), \
                    patch.object(study, "require_idle_board", side_effect=RuntimeError("occupied")), \
                    patch.object(runtime, "capture") as capture, patch.object(study, "run_link") as launch:
                with self.assertRaisesRegex(RuntimeError, "occupied"):
                    study.run(root, root, root, root / "attempt", execute=True)
                capture.assert_not_called()
                launch.assert_not_called()
            result = json.loads((root / "attempt/results.json").read_text())
            self.assertFalse(result["board_started"])

    def test_invalid_device_repetition_and_existing_output_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kwargs in ({"device": 2}, {"device": False}, {"repeats": 1}, {"repeats": True}):
                with self.assertRaises(ValueError):
                    study.run(root, root, root, root / "attempt", **kwargs)
            with self.assertRaises(FileExistsError):
                study.run(root, root, root, root)

    def test_declared_high_memory_limit_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {"memory.max": str(8 * 1024**3), "memory.high": str(7 * 1024**3),
                      "memory.swap.max": "0", "memory.oom.group": "1"}
            for key, value in values.items():
                (root / key).write_text(value)
            with patch.object(study, "current", return_value=root):
                self.assertEqual(study.containment()["limits"], values)
                (root / "memory.high").write_text(str(8 * 1024**3))
                with self.assertRaisesRegex(ValueError, "memory.high"):
                    study.containment()


if __name__ == "__main__":
    unittest.main()
