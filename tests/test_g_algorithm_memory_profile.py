"""Remote PageRank policies and return verification retain their exact boundary."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_g_algorithm_artifacts import fixture, write
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import (
    artifacts, memory,
)


class PolicyTests(unittest.TestCase):
    def test_defaults_remain_strict_and_independent(self):
        self.assertEqual(memory.select(), memory.LINK)
        self.assertEqual(memory.select(compile=True), memory.COMPILE)
        changed = memory.select()
        changed["reserve_gib"] = 1
        self.assertEqual(memory.select()["reserve_gib"], 32)

    def test_named_compile_uses_full_40g_lease_and_checks_host(self):
        with patch.object(memory.memory_profiles, "host") as host:
            for compile in (True, False):
                policy = memory.select(memory.memory_profiles.SEELE, compile=compile)
                self.assertEqual(policy["tree_memory_gib"], 40)
                self.assertEqual(policy["reserve_gib"], 128)
                host.assert_called_with(policy)
            with self.assertRaises(ValueError):
                memory.select("unknown")
        with patch.object(memory.memory_profiles, "host", side_effect=ValueError("wrong host")), \
                self.assertRaisesRegex(ValueError, "wrong host"):
            memory.select(memory.memory_profiles.SEELE)

    def route_fixture(self, root):
        _, route, _, _, _ = fixture(root)
        profile = memory.memory_profiles.SEELE
        policy = memory.select(profile, check_host=False)
        path = route / "route.resources.json"
        child = json.loads(path.read_text())
        child.update(reserve_gib=128, minimum_available_bytes=129 * 1024**3)
        write(path, child)
        path = route / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(policy=policy, memory_profile=profile)
        write(path, manifest)
        path = route / "execution.json"
        execution = json.loads(path.read_text())
        execution.update(route=child, policy=policy, memory_profile=profile, host="seele",
                         admission={"admitted": True, "policy": profile,
                             "observed_peer_host": {"host": "seele", "total_memory_bytes": 499 * 1024**3}})
        write(path, execution)
        return route, execution

    def test_return_replays_remote_host_not_current_local_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            route, _ = self.route_fixture(Path(temporary))
            with patch.object(memory.memory_profiles, "host", side_effect=AssertionError("local host queried")):
                artifacts.completed(route)

    def test_inadequate_watchdog_missing_admission_or_profile_mismatch_rejected(self):
        changes = (lambda row: row["route"].update(minimum_available_bytes=127 * 1024**3),
                   lambda row: row["admission"].update(admitted=False),
                   lambda row: row.update(memory_profile=None),
                   lambda row: row.update(host="trifoliate"),
                   lambda row: row["admission"]["observed_peer_host"].update(total_memory_bytes=479 * 1024**3))
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                route, row = self.route_fixture(Path(temporary))
                change(row)
                write(route / "execution.json", row)
                write(route / "route.resources.json", row["route"])
                with self.assertRaises(ValueError):
                    artifacts.completed(route)


if __name__ == "__main__":
    unittest.main()
