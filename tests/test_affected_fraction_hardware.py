"""Keep each frozen host's CLI distinct from the other algorithms."""

from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction import hardware


class HardwareCommandsTest(unittest.TestCase):
    def setUp(self):
        self.binding = {key: dict(path=key) for key in (
            "spine_host", "spine_image", "gr_host", "gr_image")}
        self.point = dict(graph=dict(path="dynamic.graph"))

    def test_pagerank_has_no_source_or_round_cli_arguments(self):
        commands, _ = hardware.commands(self.binding, dict(algorithm="residual_pagerank", source=0),
                                        self.point, Path("output"))
        self.assertEqual(commands["gr"], ["gr_host", "gr_image", "dynamic.graph", "output/gr-state.txt"])

    def test_sssp_keeps_source_and_round_arguments(self):
        commands, _ = hardware.commands(self.binding, dict(algorithm="weighted_sssp", source=11),
                                        self.point, Path("output"))
        self.assertEqual(commands["gr"][-2:], ["11", "256"])

    @patch.object(hardware.spine_cc_input, "prepare")
    def test_cc_keeps_split_input_and_its_own_gr_cli(self, prepare):
        prepare.return_value = dict(graph=dict(path="old.slice"), update=dict(path="update.slice"))
        commands, inputs = hardware.commands(self.binding, dict(algorithm="connected_components", source=0),
                                             self.point, Path("output"))
        self.assertEqual(commands["gr"][-2:], ["0", "256"])
        self.assertEqual(commands["spine"][-4:], ["--slice", "old.slice", "--update", "update.slice"])
        self.assertEqual(inputs, prepare.return_value)


if __name__ == "__main__":
    unittest.main()
