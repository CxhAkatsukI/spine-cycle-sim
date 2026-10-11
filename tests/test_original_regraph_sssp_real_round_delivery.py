"""Reject incomplete resource evidence and unsafe or altered delivery contents."""

import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.analysis import LATENCIES, MODES
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import members, seal
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.recheck import identity, steps
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.study import SSSP_TARGETS


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def report(self):
        names = ["configure", "compiler", "build", *SSSP_TARGETS,
                 "legacy_gather_tests", "legacy_frontend_tests", "legacy_state_tests", "legacy_iteration_tests",
                 "old_source_comparison", "legacy_source_comparison", "old_state_comparison", "legacy_state_comparison",
                 "whole_skewed_sources", "whole_boundary_ring", "whole_amazon", "author_layout", "pr_arithmetic_rejection",
                 *(f"{mode}_lat{latency}_reverse{reverse}" for mode in MODES for latency in LATENCIES for reverse in (0, 1))]
        runs = []
        for name in names:
            row = {"stdout": str(self.root / (name + ".stdout.txt")),
                   "exit_code": int(name == "pr_arithmetic_rejection"), "timed_out": False,
                   "memory_limit_gib": 8, "reserve_gib": 16, "available_before_bytes": 25 * 1024**3}
            atomic_write_json(self.root / (name + ".resources.json"), row)
            runs.append(row)
        return {"runs": runs}

    def test_complete_step_matrix_retains_expected_negative(self):
        observed = steps(self.report())
        self.assertEqual(len(observed), 33)
        self.assertEqual(observed["pr_arithmetic_rejection"]["exit_code"], 1)

    def test_missing_duplicate_or_reordered_steps_rejected(self):
        report = self.report()
        for runs in (report["runs"][:-1], report["runs"] + report["runs"][:1], list(reversed(report["runs"]))):
            with self.assertRaises(ValueError):
                steps({"runs": runs})

    def test_failure_timeout_or_changed_resource_record_rejected(self):
        original = self.report()
        for key, value in (("exit_code", 1), ("timed_out", True), ("reserve_gib", 0),
                           ("available_before_bytes", 23 * 1024**3), ("exit_code", False)):
            report = copy.deepcopy(original)
            report["runs"][0][key] = value
            with self.assertRaises(ValueError):
                steps(report)
        path = self.root / "configure.resources.json"
        row = json.loads(path.read_text())
        row["extra"] = True
        atomic_write_json(path, row)
        with self.assertRaises(ValueError):
            steps(original)

    def test_hash_and_symlink_identity_are_strict(self):
        path = self.root / "state.u32le"
        path.write_bytes(b"\x00" * 4)
        item = {"path": str(path), "sha256": sha256_file(path)}
        identity(item)
        link = self.root / "link.u32le"
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            identity({**item, "path": str(link)})
        path.write_bytes(b"\x01" * 4)
        with self.assertRaises(ValueError):
            identity(item)

    def test_archive_preserves_full_member_bytes_and_refuses_overwrite(self):
        directory = self.root / "evidence"
        directory.mkdir()
        (directory / "state.u32le").write_bytes(bytes(range(64)))
        (directory / "results.json").write_text("{}\n")
        files = members(directory, "run")
        archive = self.root / "raw.tar.gz"
        index = seal(files, archive)
        self.assertEqual(len(index), 2)
        with tarfile.open(archive, "r:gz") as bundle:
            self.assertEqual(bundle.extractfile("run/state.u32le").read(), bytes(range(64)))
        with self.assertRaises(ValueError):
            seal(files, archive)

    def test_symlink_binary_and_unsafe_archive_members_rejected(self):
        directory = self.root / "evidence"
        directory.mkdir()
        path = directory / "raw.txt"
        path.write_text("raw")
        for name in ("../escape", "/absolute"):
            with self.assertRaises(ValueError):
                seal([(path, name)], self.root / "raw.tar.gz")
        with self.assertRaises(ValueError):
            seal([(path, "run/raw"), (path, "run/raw")], self.root / "raw.tar.gz")
        link = directory / "link.txt"
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            members(directory, "run")
        link.unlink()
        (directory / "binary").write_bytes(b"not evidence")
        with self.assertRaises(ValueError):
            members(directory, "run")


if __name__ == "__main__":
    unittest.main()
