"""Evidence gates for the Figure 7 handoff; no FPGA or plotting dependency."""
import json
from pathlib import Path
import tempfile
import unittest

from render_fig7 import BOUNDARY, collect


class CollectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, rows, boundary=BOUNDARY):
        directory = self.root / 'sssp'
        directory.mkdir(exist_ok=True)
        (directory / 'execution.json').write_text(json.dumps(dict(
            boundary=boundary, rows=rows, status='PERFORMANCE_MATRIX_RUNNING')))

    def row(self):
        return dict(dataset='AU', status='PASS', summary=dict(
            excluded_warmup_pairs=1, measured_pairs=3,
            walls={'gr': dict(median_ms=30, min_ms=29, max_ms=31),
                   'spine': dict(median_ms=100, min_ms=99, max_ms=101)},
            speedup_ratio_of_median_walls=0.3))

    def test_missing_and_failed_rows_are_not_estimated(self):
        self.write([self.row(), dict(dataset='SU', status='FAILED_RETAINED')])
        rows, reports, pins = collect(self.root)
        self.assertEqual([(row['dataset'], row['speedup']) for row in rows], [('AU', 0.3)])
        self.assertEqual(reports['cc']['status'], 'NOT_STARTED')
        self.assertEqual(len(pins), 1)

    def test_mixed_boundary_rejected(self):
        self.write([self.row()], boundary='kernel_only')
        with self.assertRaisesRegex(ValueError, 'boundaries'):
            collect(self.root)

    def test_duplicate_dataset_rejected(self):
        self.write([self.row(), self.row()])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            collect(self.root)

    def test_ratio_cannot_override_measured_walls(self):
        row = self.row()
        row['summary']['speedup_ratio_of_median_walls'] = 10
        self.write([row])
        with self.assertRaisesRegex(ValueError, 'wall times'):
            collect(self.root)

    def test_three_measured_pairs_required(self):
        row = self.row()
        row['summary']['measured_pairs'] = 1
        self.write([row])
        with self.assertRaisesRegex(ValueError, 'three measured'):
            collect(self.root)


if __name__ == '__main__':
    unittest.main()
