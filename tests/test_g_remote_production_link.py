import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import capsule
import test_g_production_board_route as production_tests


def fixture(root):
    parent = root / "parent"
    parent.mkdir()
    manifest, _, exports = production_tests.fixture(parent)
    config = parent / "link.cfg"
    config.write_text("platform=/old/platform.xpfm\n[connectivity]\nnk=search:4\n"
                      "sp=search_1.pma:HBM[0]\nsp=search_2.pma:HBM[1]\n"
                      "[advanced]\nmisc=solution_name=link\n[param]\n"
                      "compiler.userPostSysLinkTcl=/unchanged.tcl\n")
    shim = parent / "gcc_compat/bits/gthr-default.h"
    shim.parent.mkdir(parents=True)
    shim.write_text("reviewed thread shim")
    manifest["pins"].extend([identity(config), identity(shim)])
    manifest["command"] = ["/old/v++", "--target", "hw", "--link", "--kernel_frequency", "150",
        "--config", str(config), "-I/unchanged/include", "-o", str(parent / "candidate.hw.xclbin"),
        *[row["frozen"]["path"] for row in manifest["kernel_inputs"].values()],
        "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    production_tests.save(parent, manifest)
    (parent / "environment.json").write_text(json.dumps({"effective": {"values": {
        "CPLUS_INCLUDE_PATH": str(shim.parents[1])}}}))
    return parent, exports


class RemoteProductionCapsuleTests(unittest.TestCase):
    def prepare(self, root):
        parent, exports = fixture(root)
        output = root / "capsule"
        with patch.object(capsule.production, "EXPORTS", exports):
            packet = capsule.prepare(parent, output)
        return parent, output, packet

    def test_export_freezes_exact_parent_and_survives_relocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, output, packet = self.prepare(root)
            before = (parent / "manifest.json").read_bytes()
            moved = root / "moved"
            output.rename(moved)
            checked, manifest = capsule.verify(moved)
            self.assertEqual(packet, checked)
            self.assertEqual(len(checked["xo_replacements"]), 11)
            self.assertEqual((moved / "parent/manifest.json").read_bytes(), before)
            self.assertEqual(manifest["clock_mhz"], 150)
            self.assertTrue(all(checked[key] is False for key in capsule.FLAGS))

    def test_command_changes_only_compiler_config_output_and_xo_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            _, root, packet = self.prepare(Path(directory))
            _, parent = capsule.verify(root)
            output = root.parent / "route"
            command = capsule.command(packet, parent, root, output, Path("/new/v++"))
            expected = parent["command"].copy()
            expected[0] = "/new/v++"
            expected[expected.index("--config") + 1] = str(output / "link.cfg")
            expected[expected.index("-o") + 1] = str(output / "candidate.hw.xclbin")
            expected = [str(root / packet["xo_replacements"][arg])
                        if arg in packet["xo_replacements"] else arg for arg in expected]
            self.assertEqual(command, expected)

    def test_changed_input_or_index_cannot_pass_verification(self):
        changes = [lambda p: p.update(FPGA_timing_admitted=True),
                   lambda p: p["policy"].update(tree_memory_gib=400),
                   lambda p: p["files"].append(p["files"][0]),
                   lambda p: p["files"][0].update(member="../escape"),
                   lambda p: p["files"][1]["source"].update(path="/not-the-parent-config"),
                   lambda p: p["files"].pop(),
                   lambda p: p.update(checked_parent_pin_count=0),
                   lambda p: p["xo_replacements"].popitem()]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                _, root, packet = self.prepare(Path(directory))
                change(packet)
                (root / "capsule.json").write_text(json.dumps(packet))
                with self.assertRaises(ValueError):
                    capsule.verify(root)
        with tempfile.TemporaryDirectory() as directory:
            _, root, _ = self.prepare(Path(directory))
            (root / "parent/link.cfg").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                capsule.verify(root)

    def test_changed_parent_source_or_ambiguous_command_cannot_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent, exports = fixture(root)
            manifest = json.loads((parent / "manifest.json").read_text())
            for change in (lambda m: m["command"].extend(["--target", "hw"]),
                           lambda m: m["command"].__setitem__(m["command"].index("150"), "200"),
                           lambda m: m["command"].remove("--link")):
                modified = copy.deepcopy(manifest)
                change(modified)
                with self.assertRaises(ValueError):
                    capsule.validate_command(modified)
            Path(manifest["kernel_inputs"]["process_cache"]["frozen"]["path"]).write_text("changed")
            with patch.object(capsule.production, "EXPORTS", exports), self.assertRaises(ValueError):
                capsule.prepare(parent, root / "capsule")

    def test_config_preserves_repeated_ports_and_topology(self):
        paths = ("messageDb=/old/route.mdb\ntemp_dir=/old/link\nreport_dir=/old/reports\n"
                 "log_dir=/old/logs\nremote_ip_cache=/old/ip_cache\n")
        text = ("platform=/old/platform\n" + paths + "[connectivity]\nnk=search:4\n"
                "sp=search_1.pma:HBM[0]\nsp=search_2.pma:HBM[1]\n"
                "slr=search_1:SLR0\nstream_connect=a.out:b.in\n"
                "[advanced]\nmisc=solution_name=link\n[profile]\n"
                "[param]\ncompiler.userPostSysLinkTcl=/unchanged.tcl\n")
        result = capsule.configuration(text, Path("/new/output"), Path("/new/platform"))
        self.assertEqual(result, text.replace("platform=/old/platform", "platform=/new/platform")
                         .replace("/old/", "/new/output/"))
        for invalid in (text.replace("platform=/old/platform\n", ""), text + "platform=duplicate\n"):
            with self.assertRaises(ValueError):
                capsule.configuration(invalid, Path("/new/output"), Path("/new/platform"))


if __name__ == "__main__":
    unittest.main()
