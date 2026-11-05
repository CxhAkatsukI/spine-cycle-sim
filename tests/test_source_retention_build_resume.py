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

    def test_larger_profile_is_explicit_and_reserves_its_full_limit(self):
        policy = resume.MEMORY_PROFILES['192g-v1']
        self.assertEqual(resume.POLICY['tree_memory_gib'], 104)
        self.assertEqual(policy['reserve_gib'], 128)
        self.assertIn('MemoryMax=192G', resume.properties(policy))
        self.assertIn('MemoryHigh=184G', resume.properties(policy))
        self.assertIn('MemorySwapMax=0', resume.properties(policy))
        required = (192 + 128 + 8 + 40) * 2**30
        peer = dict(bounded=True, cgroup='/peer', memory_max_bytes=40 * 2**30)
        self.assertEqual(admission.required_bytes(policy, [peer]), required)
        self.assertFalse(admission.eligible(required - 1, [peer], policy))
        self.assertTrue(admission.eligible(required, [peer], policy))
        with TemporaryDirectory() as temporary:
            group = Path(temporary)
            for name, value in {'memory.max': 192 * 2**30, 'memory.high': 184 * 2**30,
                                'memory.swap.max': 0, 'memory.oom.group': 1}.items():
                (group / name).write_text(str(value))
            self.assertEqual(resume.verify(group, policy)['memory.max'], str(192 * 2**30))
            with self.assertRaises(MemoryError):
                resume.verify(group)


if __name__ == '__main__':
    unittest.main()
