"""Single-component relinks must keep production inputs and reject stale gates."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import component
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.replacement import prepare


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class AdapterReplacementTest(unittest.TestCase):
    def fixture(self, root):
        production, packet = root / "production", root / "packet"
        production.mkdir()
        (packet / "build").mkdir(parents=True)
        adapter = "pma_to_regraph_adapter.hw.xo"
        wrapper = "kernelHBMWrapper.hw.xo"
        paths = [production / adapter, production / wrapper] + [
            production / f"other_{i}.hw.xo" for i in range(10)]
        candidate = packet / "build" / adapter
        for path in (paths[0], candidate):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("kernel/kernel.xml", '<root><kernel name="pma_to_regraph_adapter" '
                                 'compileOptions="-DGRASU_REGRAPH_PREFETCH_COMPACT=1"/></root>')
        self.wrapper(paths[1])
        for path in paths[2:]:
            path.write_bytes(b"unchanged")
        config = production / "link.cfg"
        config.write_text("".join(f"{key}={production / key}\n" for key in (
            "messageDb", "temp_dir", "report_dir", "log_dir", "remote_ip_cache")) +
            "[connectivity]\nnk=a:4\nnk=b:1\n")
        argv = ["v++", "--target", "hw", "--link", "--kernel_frequency", "150", "--config",
                str(config), "-o", str(production / "original.hw.xclbin"), *map(str, paths)]
        save(production / "manifest.json", {"command": argv, "pins": list(map(identity, [*paths, config]))})
        source = packet / "source.hpp"
        source.write_text("fixed hardware source")
        for name, status in (("adapter", "COMPONENT_XO_PASS_NOT_ROUTED"),
                             ("rtl-destination", "FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD")):
            gate = packet / "evidence" / name
            save(gate / "execution.json", {"status": status, "xo": identity(candidate)})
            save(gate / "manifest.json", {"pins": [identity(source)]})
        return production, packet, root / "route"

    @staticmethod
    def wrapper(path, compile_value=4, rtl=b"original"):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("kernel/kernel.xml", '<root><kernel name="kernelHBMWrapper" '
                             f'compileOptions="-DLITTLE_KERNEL_NUM={compile_value}"/></root>')
            archive.writestr("kernel/wrapper.v", rtl)

    def test_source_wrapper_replacement_is_pinned_without_touching_other_xos(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            wrapper = packet / "build/kernelHBMWrapper.hw.xo"
            self.wrapper(wrapper, rtl=b"new")
            result = prepare(production, packet, output, source_wrapper=wrapper)
            before = json.loads((production / "manifest.json").read_text())["command"]
            old_xos = [a for a in before if a.endswith(".xo")]
            new_xos = [a for a in result["command"] if a.endswith(".xo")]
            self.assertEqual(new_xos[1], str(wrapper))
            self.assertEqual(new_xos[2:], old_xos[2:])
            self.assertIn(identity(wrapper), result["pins"])

    def test_source_wrapper_compile_option_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            wrapper = packet / "build/kernelHBMWrapper.hw.xo"
            self.wrapper(wrapper, compile_value=2)
            with self.assertRaisesRegex(ValueError, "source wrapper ABI or compile-time"):
                prepare(production, packet, output, source_wrapper=wrapper)
            self.assertFalse(output.exists())

    def test_replaces_only_one_xo_and_retains_repeated_connectivity(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            result = prepare(production, packet, output)
            before = json.loads((production / "manifest.json").read_text())["command"]
            old_xos = [a for a in before if a.endswith(".xo")]
            new_xos = [a for a in result["command"] if a.endswith(".xo")]
            self.assertEqual(old_xos[1:], new_xos[1:])
            self.assertEqual(new_xos[0], str(packet / "build/pma_to_regraph_adapter.hw.xo"))
            self.assertTrue((output / "link.cfg").read_text().endswith("nk=a:4\nnk=b:1\n"))

    def test_changed_production_xo_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            (production / "other_3.hw.xo").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "frozen route"):
                prepare(production, packet, output)
            self.assertFalse(output.exists())

    def test_source_change_after_rtl_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            (packet / "source.hpp").write_text("new hardware")
            with self.assertRaisesRegex(ValueError, "pinned build input"):
                prepare(production, packet, output)

    def test_failed_rtl_is_not_route_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            save(packet / "evidence/rtl-destination/execution.json", {"status": "FAILED_RETAINED"})
            with self.assertRaisesRegex(ValueError, "finite RTL"):
                prepare(production, packet, output)

    def test_abi_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            production, packet, output = self.fixture(Path(directory))
            original = production / "pma_to_regraph_adapter.hw.xo"
            with zipfile.ZipFile(original, "w") as archive:
                archive.writestr("kernel/kernel.xml", '<root><kernel name="pma_to_regraph_adapter" '
                                 'compileOptions="-DGRASU_REGRAPH_PREFETCH_COMPACT=0"/></root>')
            manifest = production / "manifest.json"
            content = json.loads(manifest.read_text())
            content["pins"][0] = identity(original)
            save(manifest, content)
            with self.assertRaisesRegex(ValueError, "ABI or compile-time"):
                prepare(production, packet, output)

    def test_component_rejects_link_or_reused_output(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory)
            script = packet / "compile_commands.sh"
            binary = packet / "build/k.hw.xo"
            script.write_text(f"v++ --target hw --link -o {binary}\n")
            with self.assertRaisesRegex(ValueError, "component compile"):
                component.command(packet, "k")
            binary.parent.mkdir()
            binary.touch()
            script.write_text(f"v++ --target hw --compile -o {binary}\n")
            with self.assertRaisesRegex(ValueError, "fresh component"):
                component.command(packet, "k")

    def test_component_accepts_only_the_generated_platform_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory)
            script = packet / "compile_commands.sh"
            (packet / "manifest.env").write_text("PLATFORM=xilinx_u55c\n")
            binary = packet / "build/kernelHBMWrapper.hw.xilinx_u55c.xo"
            line = f"v++ --target hw --compile -o {binary}\n"
            script.write_text(line.replace("xilinx_u55c", "other"))
            with self.assertRaisesRegex(ValueError, "exactly one generated component"):
                component.command(packet, "kernelHBMWrapper")
            script.write_text(line)
            with patch.object(component, "environment", return_value={}):
                self.assertEqual(component.command(packet, "kernelHBMWrapper")[1], binary)
            script.write_text(line + line.replace(".hw.xilinx_u55c.xo", ".hw.xo"))
            with self.assertRaisesRegex(ValueError, "exactly one generated component"):
                component.command(packet, "kernelHBMWrapper")

    def test_memory_queue_can_exceed_six_hours_without_changing_link_watchdog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").touch()
            binary = root / "candidate.hw.xclbin"
            binary.touch()
            with (patch.object(component, "current", return_value=root),
                  patch.object(component, "verify", return_value={}),
                  patch.object(component, "Lease") as lease,
                  patch.object(component, "available_memory_bytes", return_value=1),
                  patch.object(component, "other_builds", return_value=[]),
                  patch.object(component, "runner_pins", return_value=[]),
                  patch.object(component.time, "monotonic", side_effect=[0, 25200, 25215]),
                  patch.object(component.time, "sleep") as sleep,
                  patch.object(component, "run_link", return_value={
                      "exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}) as link):
                lease.return_value.sample.side_effect = [{"admitted": False}, {"admitted": True}]
                result = component.execute(root / "run", ["v++"], {}, [], kind="LINK", binary=binary,
                                           timeout=21600, admission_wait=86400)
                sleep.assert_called_once_with(15)
                self.assertEqual(link.call_args.kwargs["timeout"], 21600)
                self.assertEqual(link.call_args.kwargs["tree_memory_gib"], 40)
                lease.return_value.release.assert_called_once()
            self.assertEqual(result["admission_waited_seconds"], 25215)
            self.assertTrue(result["tool_launch_requested"])

    def test_memory_queue_expiry_retains_no_launch_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").touch()
            output = root / "run"
            with (patch.object(component, "current", return_value=root),
                  patch.object(component, "verify", return_value={}),
                  patch.object(component, "Lease") as lease,
                  patch.object(component, "available_memory_bytes", return_value=1),
                  patch.object(component, "other_builds", return_value=[]),
                  patch.object(component, "runner_pins", return_value=[]),
                  patch.object(component.time, "monotonic", side_effect=[0, 86400]),
                  patch.object(component, "run_link") as link):
                lease.return_value.sample.return_value = {"admitted": False}
                with self.assertRaisesRegex(RuntimeError, "compiler budget"):
                    component.execute(output, ["v++"], {}, [], kind="LINK",
                                      timeout=21600, admission_wait=86400)
                link.assert_not_called()
                lease.return_value.release.assert_called_once()
            result = json.loads((output / "execution.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertFalse(result["tool_launch_requested"])


if __name__ == "__main__":
    unittest.main()
