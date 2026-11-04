from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure8_inputs import (
    prepare,
)


class Figure8InputsTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.initial, self.batch, self.output = (
            Path(directory.name) / name for name in ("old.slice", "batch.slice", "native.graph")
        )
        self.initial.write_text("# vertices=4\n3 0 8 1\n2 1 7 1\n", encoding="ascii")

    def convert(self, batch_rows):
        self.batch.write_text(batch_rows, encoding="ascii")
        prepare(self.initial, self.batch, self.output, vertices=4, edges=2, batch_size=1)

    def test_preserves_edge_order_weights_and_operation(self):
        batch = "# vertices=4\n3 2 4095 1\n"
        self.convert(batch)
        self.assertEqual(self.output.read_text(), "4 2 1\n3 0 8\n2 1 7\n3 2 4095 1\n")
        with self.assertRaises(FileExistsError):
            self.convert(batch)

    def test_rejects_unsupported_rows_and_does_not_publish_partial_output(self):
        for text in ("# vertices=3\n2 1 1 1\n", "# vertices=4\n1 2 1 -1\n",
                     "# vertices=4\n4 1 1 1\n", "# vertices=4\n2 1 4096 1\n",
                     "# vertices=4\n", "1 2 1 1\n",
                     "# vertices=4\n1 2 1 1\n3 2 1 1\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.convert(text)
            self.assertFalse(self.output.exists())
