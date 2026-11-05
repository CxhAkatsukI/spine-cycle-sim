import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    correction_retime, host_correction,
)


class CorrectionRetimeTest(unittest.TestCase):
    def test_cpu_qualification_requires_both_opt_in_tests(self):
        correction = "RESIDENT_CORRECTION_TEST_PASS cases=160 bit_exact_seed=1 scope=offboard_not_fpga"
        resident = ("RESIDENT_CORRECTION mode=old_incoming_fp32_replay\n"
                    "RESIDENT_BENCHMARK_HOST_TEST_PASS algorithm=2 scope=offboard_driver_only")
        host_correction.validate_test_logs(correction, resident)
        for a, b in ((correction.replace("160", "159"), resident),
                     (correction * 2, resident), (correction, resident.splitlines()[-1])):
            with self.subTest(a=a, b=b), self.assertRaises(ValueError):
                host_correction.validate_test_logs(a, b)

    def test_explicit_cache_setup_and_timed_update_are_required(self):
        text = ("RESIDENT_CORRECTION_CACHE scope=old_graph_only_single_batch bytes=1024 "
                "preparation_ms=2.5 included_in_dynamic_wall=0\n"
                "RESIDENT_CORRECTION mode=old_incoming_fp32_replay dense_dangling_fallback=0 "
                "host_update_and_state_upload_in_dynamic_wall=1\n")
        self.assertEqual(correction_retime.validate_correction_log(text), dict(
            resident_cache_bytes=1024, old_graph_cache_preparation_ms=2.5, dense_dangling_fallback=False))
        for changed in (text.replace("old_graph_only_single_batch", "new_graph"),
                        text.replace("state_upload_in_dynamic_wall=1", "state_upload_in_dynamic_wall=0"), text * 2):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                correction_retime.validate_correction_log(changed)


if __name__ == "__main__":
    unittest.main()
