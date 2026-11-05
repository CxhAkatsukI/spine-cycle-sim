from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import build_resume as resume
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import admission


class ResumePolicyTests(unittest.TestCase):
    def test_properties_and_guard_have_identical_limits(self):
        with TemporaryDirectory() as temporary:
            group = Path(temporary)
            for name, value in {'memory.max': 104 * 2**30, 'memory.high': 100 * 2**30,
                                'memory.swap.max': 0, 'memory.oom.group': 1}.items():
                (group / name).write_text(str(value))
            self.assertEqual(resume.verify(group)['memory.high'], str(100 * 2**30))
            self.assertIn('MemoryHigh=100G', resume.properties())
            (group / 'memory.high').write_text(str(88 * 2**30))
            with self.assertRaises(MemoryError):
                resume.verify(group)

    def test_full_budgets_and_unbounded_peers(self):
        peer = dict(bounded=True, cgroup='/peer', memory_max_bytes=40 * 2**30)
        required = (104 + 128 + 8 + 40) * 2**30
        self.assertEqual(admission.required_bytes(resume.POLICY, [peer]), required)
        self.assertFalse(admission.eligible(required - 1, [peer], resume.POLICY))
        self.assertTrue(admission.eligible(required, [peer], resume.POLICY))
        self.assertFalse(admission.eligible(500 * 2**30, [dict(bounded=False)], resume.POLICY))


if __name__ == '__main__':
    unittest.main()
