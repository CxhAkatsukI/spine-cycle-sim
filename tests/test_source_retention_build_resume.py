from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

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
        for profile, maximum, high in [('192g-v1', 192, 184), ('320g-v1', 320, 304)]:
            with self.subTest(profile=profile):
                self.check_larger_profile(profile, maximum, high)

    def check_larger_profile(self, profile, maximum, high):
        policy = resume.MEMORY_PROFILES[profile]
        self.assertEqual(resume.POLICY['tree_memory_gib'], 104)
        self.assertEqual(policy['reserve_gib'], 128)
        self.assertIn(f'MemoryMax={maximum}G', resume.properties(policy))
        self.assertIn(f'MemoryHigh={high}G', resume.properties(policy))
        self.assertIn('MemorySwapMax=0', resume.properties(policy))
        required = (maximum + 128 + 8 + 40) * 2**30
        peer = dict(bounded=True, cgroup='/peer', memory_max_bytes=40 * 2**30)
        self.assertEqual(admission.required_bytes(policy, [peer]), required)
        self.assertFalse(admission.eligible(required - 1, [peer], policy))
        self.assertTrue(admission.eligible(required, [peer], policy))
        with TemporaryDirectory() as temporary:
            group = Path(temporary)
            for name, value in {'memory.max': maximum * 2**30, 'memory.high': high * 2**30,
                                'memory.swap.max': 0, 'memory.oom.group': 1}.items():
                (group / name).write_text(str(value))
            self.assertEqual(resume.verify(group, policy)['memory.max'], str(maximum * 2**30))
            with self.assertRaises(MemoryError):
                resume.verify(group)


class ResumeAdmissionWaitTests(unittest.TestCase):
    def exercise(self, peers, wait=10, amount=500 * 2**30):
        lease = MagicMock(path=Path('/lease.json'))
        lease.peers.return_value = []
        lease.held = False
        clock = [0]

        def sleep(seconds):
            self.assertFalse(lease.held)
            clock[0] += seconds

        report = {}
        with patch.object(resume, 'verify'), patch.object(resume, 'other_builds', return_value=[]), \
                patch.object(resume.admission, 'reservations', side_effect=peers), \
                patch.object(resume, 'available', return_value=amount), \
                patch.object(resume, 'start_time', return_value='start'), \
                patch.object(resume, 'save') as save, \
                patch.object(resume.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(resume.time, 'sleep', side_effect=sleep):
            resume.reserve(Path('/group'), resume.MEMORY_PROFILES['320g-v1'],
                           lease, report, Path('/output'), wait)
        return lease, report, save

    def test_waits_without_a_lease_then_atomically_reserves_the_full_budget(self):
        lease, report, save = self.exercise([[dict(bounded=False)], []])
        self.assertTrue(lease.held)
        self.assertEqual(report['admission_waited_seconds'], 5)
        self.assertEqual(report['admission']['required_bytes'], 456 * 2**30)
        self.assertEqual(save.call_args_list[0].args[0], Path('/output/execution.json'))
        self.assertEqual(save.call_args_list[-1].args[1]['memory_max_bytes'], 320 * 2**30)

    def test_unbounded_peer_times_out_without_a_reservation(self):
        with self.assertRaisesRegex(TimeoutError, 'without starting tools'):
            self.exercise([[dict(bounded=False)]] * 3)

    def test_insufficient_available_memory_times_out_without_bypassing_reserve(self):
        with self.assertRaisesRegex(TimeoutError, 'without starting tools'):
            self.exercise([[]] * 3, amount=455 * 2**30)

    def test_default_zero_wait_keeps_fail_closed_behavior(self):
        with self.assertRaisesRegex(MemoryError, 'full compiler budgets'):
            self.exercise([[dict(bounded=False)]], wait=0)

    def test_changed_containment_is_not_retried(self):
        with patch.object(resume, 'verify', side_effect=MemoryError('limits changed')), \
                patch.object(resume.time, 'sleep') as sleep:
            with self.assertRaisesRegex(MemoryError, 'limits changed'):
                resume.reserve(Path('/group'), resume.POLICY, MagicMock(), {}, Path('/out'), 10)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
