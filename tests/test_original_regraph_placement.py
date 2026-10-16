from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import (
    configuration as config, execution, placement, preflight, snapshot, waiting,
)


AUTHOR = """# slr=kernelApply_1:SLR2
[connectivity]
nk=kernelApply:1
slr=kernelLittleGSMerger_1:SLR1
slr=kernelApply_1:SLR1
sp=kernelApply_1.outdegree:HBM[30]
sp=littleKernelScatterGather_1.part_edge_array:HBM[0]
stream_connect=kernelLittleGSMerger_1.l_write_burst_stm:kernelApply_1.l_merged_prop_stm:16
stream_connect=kernelApply_1.prop_write_burst_stm:kernelHBMWrapper_1.prop_write_burst_stm:16
slr=littleKernelScatterGather_1:SLR0
"""


class PlacementControlTests(unittest.TestCase):
    def test_only_apply_location_changes_and_repeated_keys_are_preserved(self):
        changed = placement.move_apply(AUTHOR)
        before, after = AUTHOR.splitlines(), changed.splitlines()
        differences = [(old, new) for old, new in zip(before, after) if old != new]
        self.assertEqual(len(before), len(after))
        self.assertEqual(differences, [("slr=kernelApply_1:SLR1", "slr=kernelApply_1:SLR0")])
        self.assertEqual(changed.count("sp="), 2)
        self.assertEqual(changed.count("stream_connect="), 2)

    def test_ambiguous_missing_or_drifted_author_placement_fails_closed(self):
        for contents in (AUTHOR.replace("slr=kernelApply_1:SLR1\n", ""),
                         AUTHOR + "slr=kernelApply_1:SLR1\n",
                         AUTHOR.replace("slr=kernelApply_1:SLR1", "slr=kernelApply_1:SLR2"),
                         AUTHOR.replace("[connectivity]", "[other]"),
                         AUTHOR.replace("[connectivity]", "[connectivity")):
            with self.assertRaises(ValueError):
                placement.move_apply(contents)

    def test_line_endings_and_missing_final_newline_are_not_required(self):
        for contents in (AUTHOR.replace("\n", "\r\n"), AUTHOR.rstrip("\n")):
            self.assertEqual(placement.move_apply(contents),
                             contents.replace("slr=kernelApply_1:SLR1", "slr=kernelApply_1:SLR0"))

    def test_preparation_pins_both_configs_without_editing_author_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author = root / "source/acc_template/connectivity.cfg"
            author.parent.mkdir(parents=True)
            author.write_text(AUTHOR)
            output = root / "attempt"
            output.mkdir()
            result = placement.prepare(root / "source", output, "a4", "apply_slr0")
            self.assertEqual(author.read_text(), AUTHOR)
            self.assertEqual(Path(result["config"]).read_text(), placement.move_apply(AUTHOR))
            self.assertFalse(result["device_algorithm_edits"])
            self.assertFalse(result["clock_or_timing_constraint_edits"])
            self.assertEqual(result["changes"], [{"instance": "kernelApply_1", "from": "SLR1", "to": "SLR0"}])
            snapshot.unchanged(result["pins"])
            Path(result["config"]).write_text("drift")
            with self.assertRaisesRegex(ValueError, "changed"):
                snapshot.unchanged(result["pins"])
            with self.assertRaises(FileExistsError):
                placement.prepare(root / "source", output, "a4", "apply_slr0")

    def test_author_default_keeps_identical_link_command_and_no_extra_files(self):
        source, output = Path("/original/source"), Path("/original/output")
        for topology in config.TOPOLOGIES:
            prepared = placement.prepare(source, output, topology)
            self.assertEqual(prepared["name"], "author")
            self.assertEqual(prepared["pins"], [])
            self.assertEqual(config.link_command(source, output, topology),
                             config.link_command(source, output, topology,
                                                 connectivity=Path(prepared["config"])))

    def test_new_link_only_selects_derived_config_without_clock_or_xo_changes(self):
        source, output = Path("/source"), Path("/run")
        author = config.link_command(source, output, "a4")
        derived = config.link_command(source, output, "a4", connectivity=output / "placement/connectivity.cfg")
        differences = [(old, new) for old, new in zip(author, derived) if old != new]
        self.assertEqual(differences, [("/source/acc_template/connectivity.cfg", "/run/placement/connectivity.cfg")])
        self.assertEqual(len(author), len(derived))
        self.assertEqual(derived[derived.index("--kernel_frequency") + 1], "150")

    def test_invalid_combination_stops_before_output_or_memory_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for runner, args, kwargs in (
                    (execution.run, [root] * 5 + [root / "new"], {}),
                    (waiting.run, [root] * 5 + [root / "new"], {"wait_seconds": 30}),
                    (preflight.run, [root] * 2 + [root / "new"], {})):
                with patch.object(execution, "Lease") as lease, self.assertRaises(ValueError):
                    runner(*args, topology="original_example", placement="apply_slr0", **kwargs)
                lease.assert_not_called()
                self.assertFalse((root / "new").exists())
            for invalid in (None, False, [], {}, "automatic"):
                with self.assertRaises(ValueError):
                    placement.validate("a4", invalid)


if __name__ == "__main__":
    unittest.main()
