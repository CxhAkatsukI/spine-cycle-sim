"""Single-component relinks must keep production inputs and reject stale gates."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.component import command
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
        paths = [production / adapter] + [production / f"other_{i}.hw.xo" for i in range(11)]
        candidate = packet / "build" / adapter
        for path in (paths[0], candidate):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("kernel/kernel.xml", '<root><kernel name="pma_to_regraph_adapter" '
                                 'compileOptions="-DGRASU_REGRAPH_PREFETCH_COMPACT=1"/></root>')
        for path in paths[1:]:
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
                command(packet, "k")
            binary.parent.mkdir()
            binary.touch()
            script.write_text(f"v++ --target hw --compile -o {binary}\n")
            with self.assertRaisesRegex(ValueError, "fresh component"):
                command(packet, "k")


if __name__ == "__main__":
    unittest.main()
