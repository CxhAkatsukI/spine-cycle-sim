from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.bank_stream import runtime


class BankStreamRuntimeTests(unittest.TestCase):
    def select(self, cpus=(4, 5), sha="pinned"):
        return runtime.select(Path("/runtime/bin/sst"), Path("/plugin"), cpus,
                              Path("/runtime/dram"), sha)

    def setUp(self):
        binding = {"sst_element_path": "/runtime/lib/sst-elements-library"}
        for name, value in (("forced_sst_library_binding", binding),
                            ("sha256_file", "pinned"), ("identity", {"sha256": "file"})):
            patcher = patch.object(runtime, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(runtime.os, "sched_getaffinity", return_value={4, 5})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_explicit_host_cpu_and_dependencies(self):
        with patch.object(Path, "is_file", return_value=True):
            binding, record = self.select()
        self.assertEqual(record["cpus"], [4, 5])
        self.assertEqual(record["dramsim3_root"], "/runtime/dram")
        self.assertEqual(len(record["files"]), 4)
        self.assertTrue(record["host"])
        self.assertEqual(binding["sst_element_path"], "/runtime/lib/sst-elements-library")
        self.assertEqual(record["sst_options"], [])

    def test_relocated_engine_mode_is_explicit_and_recorded(self):
        with patch.object(Path, "is_file", return_value=True):
            _, record = runtime.select(Path("/runtime/libexec/sstsim.x"), Path("/plugin"),
                                       (4, 5), Path("/runtime/dram"), "pinned",
                                       no_env_config=True)
        self.assertEqual(record["sst_options"], ["--no-env-config"])
        self.assertEqual(len(record["files"]), 3)

    def test_rejects_missing_duplicate_and_unavailable_cpu(self):
        for cpus in ((), (4, 4), (7,), (-1,)):
            with self.subTest(cpus=cpus), self.assertRaisesRegex(ValueError, "CPU selection"):
                self.select(cpus)

    def test_rejects_different_dram_dependency(self):
        with self.assertRaisesRegex(ValueError, "DRAMSim3 differs"):
            self.select(sha="different")


if __name__ == "__main__":
    unittest.main()
