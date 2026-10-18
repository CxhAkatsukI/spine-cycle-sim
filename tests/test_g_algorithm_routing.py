"""Explicit placement/configuration invariants, not execution of FPGA tools."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_g_algorithm_review import compile_fixture, write
from test_g_algorithm_inspection import CAPACITY
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import route_study, routing
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import timing

CONFIG = ("platform=/old/platform.xpfm\nmessageDb=/old/a\ntemp_dir=/old/b\nreport_dir=/old/c\n"
          "log_dir=/old/d\nremote_ip_cache=/old/e\n[connectivity]\n"
          "nk=lksg_stream:4:lksg_stream_1.lksg_stream_2.lksg_stream_3.lksg_stream_4\n"
          "slr=lksg_stream_1:SLR2\nslr=lksg_stream_2:SLR2\nslr=lksg_stream_3:SLR2\n"
          "slr=lksg_stream_4:SLR0\nsp=lksg_stream_1.a:HBM[0:22]\n"
          "sp=lksg_stream_2.a:HBM[0:22]\n")


class PlacementTests(unittest.TestCase):
    def test_only_fourth_little_slr_changes_and_repeated_keys_survive(self):
        result = routing.relocate_little(CONFIG)
        self.assertEqual(result, CONFIG.replace("slr=lksg_stream_4:SLR0", "slr=lksg_stream_4:SLR1"))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            config = routing.configuration(result, output, output / "new.xpfm")
            self.assertIn("platform=" + str(output / "new.xpfm"), config)
            self.assertIn("temp_dir=" + str(output / "link"), config)
            self.assertEqual(config.count("sp="), 2)

    def test_wrong_missing_duplicate_or_already_changed_placement_fails(self):
        for config in (CONFIG.replace("slr=lksg_stream_4:SLR0", "slr=lksg_stream_4:SLR1"),
                       CONFIG.replace("slr=lksg_stream_4:SLR0\n", ""),
                       CONFIG + "slr=lksg_stream_4:SLR0\n",
                       CONFIG.replace("nk=lksg_stream:4", "nk=lksg_stream:3")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                routing.relocate_little(config)

    def test_physical_retry_changes_only_the_five_declared_properties(self):
        contents = timing.configure(CONFIG, timing.PROFILE)
        routing.validate_timing_profile(contents, timing.PROFILE)
        routing.validate_timing_profile(CONFIG, None)
        self.assertEqual(contents.removesuffix("\n[vivado]\n" + "\n".join(
            "prop=" + value for value in timing.PROPERTIES) + "\n"), CONFIG)
        for altered, profile in ((contents, None), (CONFIG, timing.PROFILE), (contents, "unknown"),
                                 (contents + "prop=run.impl_1.OTHER=true\n", timing.PROFILE),
                                 (contents + "[vivado]\n", timing.PROFILE), (CONFIG + "[vivado]\n", None),
                                 (contents.replace("AggressiveExplore", "Explore", 1), timing.PROFILE)):
            with self.subTest(profile=profile, contents=altered), self.assertRaises(ValueError):
                routing.validate_timing_profile(altered, profile)

    def prepare_fixture(self, root, original_status, candidate_status, automatic=None):
        compilation, rows = compile_fixture(root)
        config = compilation / "packet/config/link.cfg"
        config.write_text(CONFIG)
        output = root / "route"
        output.mkdir()
        original = {"status": original_status, "inputs": []}
        (output / "original-review").mkdir()
        write(output / "original-review/results.json", original)
        candidate = {"status": candidate_status, "pins": [],
                     "connections": {"automatic_memory_masters": automatic or []}}
        return compilation, rows, output, original, candidate

    def test_all_xos_and_scope_preserved_after_independent_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            comp, rows, output, original, candidate = self.prepare_fixture(
                root, "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW", routing.PASS)
            with patch.object(routing.review, "run", return_value=original), \
                    patch.object(routing.review, "capacities", return_value=({"physical": CAPACITY, "platform": CAPACITY}, [])), \
                    patch.object(routing.inspection, "inspect", return_value=copy.deepcopy(candidate)), \
                    patch.object(routing.commands, "PURE", {row["kernel"] for row in rows}):
                result = routing.prepare(comp, root / "storage", output, root / "platform", "/fixed/v++")
            self.assertEqual([a for a in result["command"] if a.endswith(".xo")], [r["xo"] for r in rows])
            self.assertEqual(result["command"][0], "/fixed/v++")
            self.assertEqual(result["clock_mhz"], 150)
            self.assertFalse(result["rtl_admitted"])
            self.assertFalse(result["board_admitted"])
            self.assertIn("experimental", result["scope"])
            self.assertEqual(result["placement_change"]["instance"], "lksg_stream_4")
            self.assertIsNone(result["timing_profile"])

    def test_profile_is_frozen_in_the_manifest_and_does_not_change_xos(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            comp, rows, output, original, candidate = self.prepare_fixture(root, routing.PASS, routing.PASS)
            with patch.object(routing.review, "run", return_value=original), \
                    patch.object(routing.review, "capacities", return_value=({"physical": CAPACITY, "platform": CAPACITY}, [])), \
                    patch.object(routing.inspection, "inspect", return_value=copy.deepcopy(candidate)), \
                    patch.object(routing.commands, "PURE", {row["kernel"] for row in rows}):
                result = routing.prepare(comp, root / "storage", output, root / "platform", "/fixed/v++",
                                         timing_profile=timing.PROFILE)
            self.assertEqual(result["timing_profile"], timing.PROFILE)
            self.assertEqual([a for a in result["command"] if a.endswith(".xo")], [r["xo"] for r in rows])
            routing.validate_timing_profile((output / "link.cfg").read_text(), timing.PROFILE)

    def test_nonplacement_conflicts_or_remaining_conflicts_or_implicit_ports_block_route(self):
        for original_status, candidate_status, automatic in (
            ("RESOURCE_ESTIMATE_CONFLICT_REQUIRES_IMPLEMENTATION_REVIEW", routing.PASS, []),
            (routing.PASS, "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW", []),
            (routing.PASS, routing.PASS, [{"instance": "unknown", "port": "gmem"}])):
            with self.subTest(original=original_status, candidate=candidate_status, automatic=automatic), \
                    tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                comp, rows, output, original, candidate = self.prepare_fixture(root, original_status, candidate_status, automatic)
                with patch.object(routing.review, "run", return_value=original), \
                        patch.object(routing.review, "capacities", return_value=({"physical": CAPACITY, "platform": CAPACITY}, [])), \
                        patch.object(routing.inspection, "inspect", return_value=candidate), self.assertRaises(ValueError):
                    routing.prepare(comp, root / "storage", output, root / "platform", "/fixed/v++")

    def test_uncontained_experimental_route_fails_before_vendor_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            group = root / "cgroup"
            group.mkdir()
            (group / "memory.events").write_text("oom 0\noom_kill 0\n")
            with patch.object(route_study, "current", return_value=group), \
                    patch.object(route_study, "Lease"), \
                    patch.object(route_study, "verify", side_effect=ValueError("unbounded")), \
                    patch.object(route_study.environment, "capture") as capture, self.assertRaisesRegex(ValueError, "unbounded"):
                route_study.run(root, root, root / "output", root, root, root, root)
            capture.assert_not_called()
            import json
            result = json.loads((root / "output/execution.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertFalse(result["board_admitted"])


if __name__ == "__main__":
    unittest.main()
