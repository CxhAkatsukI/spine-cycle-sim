"""The exceptional remote profile never changes numerical or timing admission."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    admission, high_memory, memory_profiles,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    capsule, delivery,
)


class HighMemoryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.policy = memory_profiles.select(capsule.POLICY, memory_profiles.SEELE)
        self.unbounded = {"pid": 123, "bounded": False, "reason": memory_profiles.UNBOUNDED}
        self.bounded = {"bounded": True, "cgroup": "/peer", "memory_max_bytes": 40 * 1024**3}

    def test_default_stays_strict_and_named_profile_requires_complete_budgets(self):
        self.assertFalse(admission.eligible(499 * 1024**3, [self.unbounded], capsule.POLICY))
        peers = [self.unbounded, self.bounded]
        self.assertEqual(high_memory.required_bytes(self.policy, peers), 216 * 1024**3)
        self.assertFalse(high_memory.eligible(215 * 1024**3, peers, self.policy))
        self.assertTrue(high_memory.eligible(216 * 1024**3, peers, self.policy))

    def test_invalid_peers_and_conflicting_leases_remain_blocked(self):
        for row in ({"pid": 123, "bounded": False},
                    {**self.unbounded, "reason": "missing cgroup limit"},
                    {**self.unbounded, "reason": "positive finite compiler limit and zero swap required"},
                    {**self.unbounded, "cgroup": "/conflicting"},
                    {**self.unbounded, "pid": True}):
            with self.subTest(row=row):
                self.assertFalse(high_memory.eligible(499 * 1024**3, [row], self.policy))

    def test_profile_cannot_reduce_limits_reserve_or_background(self):
        for key, value in (("tree_memory_gib", 80), ("reserve_gib", 127),
                           ("background_memory_gib", 0), (memory_profiles.KEY, "anything")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                high_memory.eligible(499 * 1024**3, [], {**self.policy, key: value})
        with self.assertRaises(ValueError):
            memory_profiles.select(capsule.POLICY, "unbounded")

    def test_host_is_explicit_and_cannot_run_on_local_smaller_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            meminfo = Path(directory) / "meminfo"
            meminfo.write_text(f"MemTotal: {499 * 1024**2} kB\nMemAvailable: 1 kB\n")
            result = memory_profiles.host(self.policy, name="seele", meminfo=meminfo)
            self.assertEqual(result["total_memory_bytes"], 499 * 1024**3)
            with self.assertRaises(ValueError):
                memory_profiles.host(self.policy, name="trifoliate", meminfo=meminfo)
            meminfo.write_text(f"MemTotal: {251 * 1024**2} kB\n")
            with self.assertRaises(ValueError):
                memory_profiles.host(self.policy, name="seele", meminfo=meminfo)

    def test_return_requires_named_profile_and_live_reserve(self):
        manifest = {"policy": self.policy, "memory_profile": memory_profiles.SEELE}
        execution = {"host": "seele", **manifest, "route": {"tree_memory_gib": 40,
            "reserve_gib": 128, "minimum_available_bytes": 200 * 1024**3},
            "admission": {"admitted": True, "policy": memory_profiles.SEELE,
                "observed_peer_host": {"host": "seele", "total_memory_bytes": 499 * 1024**3}}}
        self.assertEqual(delivery.resource_policy(execution, manifest), self.policy)
        with self.assertRaises(ValueError):
            delivery.resource_policy(execution, {"policy": self.policy})
        for key, value in (("reserve_gib", 32), ("tree_memory_gib", 41),
                           ("minimum_available_bytes", 127 * 1024**3)):
            bad = {**execution, "route": {**execution["route"], key: value}}
            with self.subTest(key=key), self.assertRaises(ValueError):
                delivery.resource_policy(bad, manifest)

    def test_observed_lease_keeps_atomic_reservation_and_releases_only_own_file(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = high_memory.ObservedLease(Path(directory), Path("/owned/group"))
            guard = {"limits": {"memory.max": str(40 * 1024**3)}}
            observed = {"host": "seele", "total_memory_bytes": 499 * 1024**3}
            with patch.object(memory_profiles, "host", return_value=observed), \
                    patch.object(high_memory, "verify", return_value=guard), \
                    patch.object(admission, "reservations", return_value=[self.unbounded]), \
                    patch.object(owner, "peers", return_value=[self.bounded]), \
                    patch.object(high_memory.concurrent, "start_time", return_value="42"):
                state = owner.sample(215 * 1024**3, [], self.policy, commit=True)
                self.assertFalse(state["admitted"])
                self.assertFalse(owner.path.exists())
                state = owner.sample(216 * 1024**3, [], self.policy, commit=True)
                self.assertTrue(state["admitted"])
                self.assertIn(self.unbounded, state["reservations"])
                self.assertEqual(state["observed_peer_host"], observed)
                self.assertEqual(json.loads(owner.path.read_text())["memory_max_bytes"], 40 * 1024**3)
                foreign = Path(directory) / "foreign.json"
                foreign.write_text("retained")
                owner.release()
                self.assertFalse(owner.held)
                self.assertFalse(owner.path.exists())
                self.assertEqual(foreign.read_text(), "retained")

    def test_factory_keeps_unselected_legacy_lease(self):
        self.assertIs(type(high_memory.lease(Path("/leases"), Path("/own"), capsule.POLICY)),
                      high_memory.concurrent.Lease)
        self.assertIs(type(high_memory.lease(Path("/leases"), Path("/own"), self.policy)),
                      high_memory.ObservedLease)


if __name__ == "__main__":
    unittest.main()
