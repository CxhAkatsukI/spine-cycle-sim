"""Keep weighted and destination-only adapter evidence separate."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_adapter_component_replacement as fixture
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    algorithm_components as components, algorithm_routes as routes,
)


class DirectorySpanAlgorithmsTest(unittest.TestCase):
    def gates(self, packet, algorithm):
        mode, flag = components.MODES[algorithm]
        (packet / "manifest.env").write_text(
            f"ALGORITHM={algorithm}\nADAPTER_MODE_DEFINE={flag}\n"
            f"GRI_ROOT={packet}\nHLS_INCLUDE=/vitis/include\n"
            "PIPELINE_MODE=sharded-k4\nPHYSICAL_PORT_POLICY=shared-ingress\n")
        candidate = packet / "build/pma_to_regraph_adapter.hw.xo"
        command = ["v++", flag, "-DGRI_HMSS_SHARED_INGRESS=1",
                   "-DGRASU_REGRAPH_SHARDED_PMA=1", "-DGRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS=1",
                   "-o", str(candidate), str(packet / "kernels/pma_prefetch_compact/top.cpp")]
        evidence = packet / "evidence"
        path = packet / "source.hpp"
        pins = [identity(path), identity(packet / "manifest.env")]
        fixture.save(evidence / "execution.json", {"status": "COMPONENT_GATES_PASS_NOT_ROUTED", "mode": mode})
        fixture.save(evidence / "adapter/manifest.json", {"command": command, "pins": pins})
        fixture.save(evidence / ("rtl-" + mode) / "manifest.json", {"pins": pins})
        fixture.save(evidence / ("rtl-" + mode) / "execution.json",
             {"status": "FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD"})
        return command

    def test_mode_flags_cannot_be_mixed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, packet, _ = fixture.AdapterReplacementTest().fixture(Path(directory))
            command = self.gates(packet, "connected_components")
            self.assertEqual(components.mode_for(packet, command)[0], "destination")
            with self.assertRaisesRegex(ValueError, "same sharded shared-ingress mode"):
                components.mode_for(packet, command + [components.MODES["weighted_sssp"][1]])

    def test_abi_relink_preserves_ten_xos_and_rejects_a_rewritten_input(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = fixture.AdapterReplacementTest().fixture(Path(directory))
            self.gates(packet, "weighted_sssp")
            manifest = production / "manifest.json"
            content = json.loads(manifest.read_text())
            content["command"].pop()
            for pin in content["pins"]:
                pin.pop("bytes", None)
            fixture.save(manifest, content)
            plan = routes.prepare(production, packet, output)
            self.assertEqual(plan["mode"], "weighted")
            xos = [arg for arg in plan["command"] if arg.endswith(".xo")]
            self.assertEqual(len(xos), 11)
            self.assertEqual(xos[1:], [arg for arg in content["command"] if arg.endswith(".xo")][1:])
            self.assertTrue((output / "link.cfg").read_text().endswith("nk=a:4\nnk=b:1\n"))
            (packet / "source.hpp").write_text("changed after the RTL gate")
            with self.assertRaisesRegex(ValueError, "pinned build input changed"):
                routes.prepare(production, packet, output.with_name("stale"))

    def test_zero_exit_without_rtl_marker_does_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "stage"

            def fake_run(_, output, prefix, **kwargs):
                (output / "job.stdout.txt").write_text("did not compare output\n")
                self.assertEqual(kwargs["tree_memory_gib"], 8)
                self.assertEqual(kwargs["reserve_gib"], 40)
                return {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}

            with patch.object(components, "run_link", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "finite RTL did not complete"):
                    components.stage(stage, ["fake-tool"], {}, [])
            self.assertEqual(json.loads((stage / "execution.json").read_text())["status"], "FAILED_RETAINED")


if __name__ == "__main__":
    unittest.main()
