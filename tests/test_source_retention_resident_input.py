from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_input import (
    prepare,
)


FIXTURES = Path(__file__).parent / "data" / "deltahls_real"
FLICKR = FIXTURES / "real_soc_flickr_und_reciprocal_sinkfree.slice"
UPDATES = FIXTURES / "real_soc_flickr_und_insert_u8.slice"


class ResidentInputTest(unittest.TestCase):
    def test_flickr_retains_all_rows(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "flickr.graph"
            prepare(FLICKR, UPDATES, output)
            initial = [line.rsplit(" ", 1)[0] for line in FLICKR.read_text().splitlines()
                       if not line.startswith("#")]
            updates = [line for line in UPDATES.read_text().splitlines()
                       if not line.startswith("#")]
            self.assertEqual(len(updates), 16)
            self.assertEqual(output.read_text().splitlines(), [
                f"2552 {len(initial)} 16", *initial, *updates,
            ])
            with self.assertRaises(FileExistsError):
                prepare(FLICKR, UPDATES, output)

    def test_invalid_input_is_not_written(self):
        reciprocal = "0 1 1 1\n1 0 1 1\n"
        with TemporaryDirectory() as directory:
            initial, batch, output = [
                Path(directory) / name for name in ("initial", "batch", "result")
            ]
            initial.write_text("# vertices=3\n" + reciprocal)
            for update, message in (
                ("0 2 1 1\n2 0 1 1\n", "sink-free"),
                (reciprocal, "only new edges"),
                ("0 2 1 1\n", "reciprocal"),
            ):
                with self.subTest(message=message):
                    batch.write_text("# vertices=3\n" + update)
                    with self.assertRaisesRegex(ValueError, message):
                        prepare(initial, batch, output)
                    self.assertFalse(output.exists())
