"""Opt-in remote admission, separate from hash-pinned strict legacy runners."""

import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from . import admission, concurrent, memory_profiles
from .containment import GIB, verify


def required_bytes(policy, peers):
    memory_profiles.observed(policy)
    return admission.required_bytes(policy, peers)


def eligible(available, peers, policy):
    return (all(memory_profiles.compatible(row, policy) for row in peers) and
            available >= required_bytes(policy, peers))


class ObservedLease(concurrent.Lease):
    def sample(self, available, active, policy, *, commit=False):
        with self.locked():
            host = memory_profiles.host(policy)
            if host is None:
                raise ValueError("observed lease requires the named high-memory profile")
            guard = verify(self.own)
            peers = concurrent.merge(admission.reservations(active, self.own,
                proc=self.proc, root=self.root), self.peers())
            admitted = eligible(available, peers, policy)
            result = {"admitted": admitted, "available_bytes": available,
                "required_bytes": required_bytes(policy, peers), "reservations": peers,
                "cgroup": guard, "policy": memory_profiles.SEELE, "observed_peer_host": host}
            if commit and admitted:
                amount = int(guard["limits"]["memory.max"])
                if amount != policy["tree_memory_gib"] * GIB:
                    raise ValueError("lease must reserve the actual complete compiler cgroup limit")
                atomic_write_json(self.path, {"cgroup": str(self.own), "memory_max_bytes": amount,
                    "bounded": True, "pid": os.getpid(), "start_time": concurrent.start_time(os.getpid(), self.proc)})
                self.held = True
            return result


def lease(directory: Path, own: Path, policy: dict):
    owner = ObservedLease if memory_profiles.observed(policy) else concurrent.Lease
    return owner(directory, own)
