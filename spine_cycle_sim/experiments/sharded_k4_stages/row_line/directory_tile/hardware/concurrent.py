"""Atomic memory reservations; independent builds do not share a lifetime lock."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .admission import eligible, required_bytes, reservations
from .containment import GIB, verify


def start_time(pid, proc=Path("/proc")):
    # comm may contain spaces and parentheses; fields after its final ')' are fixed.
    return (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


def merge(builds, leases):
    groups, rejected = {}, []
    for row in [*builds, *leases]:
        if row.get("bounded") is not True or row.get("memory_max_bytes", 0) <= 0:
            rejected.append(row)
            continue
        key = row["cgroup"]
        if key in groups and groups[key]["memory_max_bytes"] != row["memory_max_bytes"]:
            rejected.append({"bounded": False, "reason": "inconsistent cgroup reservation", "cgroup": key})
        groups[key] = row
    return [*groups.values(), *rejected]


def verify_peer(group, maximum):
    # A peer retains its declared full budget, not this runner's 40/36-GiB cap.
    limits = {key: (group / key).read_text().strip() for key in
              ("memory.max", "memory.high", "memory.swap.max", "memory.oom.group")}
    if (type(maximum) is not int or maximum <= 0 or limits["memory.max"] != str(maximum)):
        raise ValueError("reserved compiler cgroup limit changed")
    if (limits["memory.high"] == "max" or not 0 < int(limits["memory.high"]) <= maximum
            or limits["memory.swap.max"] != "0" or limits["memory.oom.group"] != "1"):
        raise ValueError("finite peer high/max, zero swap and group OOM kill required")


class Lease:
    def __init__(self, directory, own, *, proc=Path("/proc"), root=Path("/sys/fs/cgroup"),
                 host_swap_disabled=False, own_limits=None):
        self.directory, self.own, self.proc, self.root = directory, own, proc, root
        self.host_swap_disabled = host_swap_disabled
        self.own_limits = dict(own_limits or {})
        self.path = directory / (hashlib.sha256(str(own).encode()).hexdigest() + ".json")
        self.held = False

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "admission.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def peers(self):
        peers = []
        for path in sorted(self.directory.glob("*.json")):
            row = json.loads(path.read_text())
            group = Path(row["cgroup"])
            if not group.is_relative_to(self.root) or ".." in group.parts:
                raise ValueError("unsafe compiler lease cgroup")
            populated = group.exists() and "populated 1" in (group / "cgroup.events").read_text().splitlines()
            try:
                live = start_time(row["pid"], self.proc) == row["start_time"]
            except FileNotFoundError:
                live = False
            if not live and not populated:
                path.unlink()
                continue
            if group == self.own:
                raise ValueError("another supervisor already reserved this compiler cgroup")
            verify_peer(group, row["memory_max_bytes"])
            peers.append(row)
        return peers

    def sample(self, available, active, manifest, *, commit=False):
        with self.locked():
            guard = verify(self.own, **self.own_limits)
            if self.host_swap_disabled:
                fields = dict(line.split(":", 1) for line in (self.proc / "meminfo").read_text().splitlines())
                if fields.get("SwapTotal", "").split() != ["0", "kB"]:
                    raise ValueError("CPU-only admission requires host SwapTotal=0")
            budgets = merge(reservations(active, self.own, proc=self.proc, root=self.root,
                host_swap_disabled=self.host_swap_disabled), self.peers())
            admitted = eligible(available, budgets, manifest)
            state = {"admitted": admitted, "available_bytes": available,
                     "required_bytes": required_bytes(manifest, budgets), "reservations": budgets,
                     "cgroup": guard, "policy": "full_finite_budgets_plus_reserve_atomic_lease",
                     "host_swap_disabled_verified": self.host_swap_disabled}
            if commit and admitted:
                amount = int(guard["limits"]["memory.max"])
                if amount != manifest["tree_memory_gib"] * GIB:
                    raise ValueError("lease must reserve the actual complete compiler cgroup limit")
                atomic_write_json(self.path, {"cgroup": str(self.own), "memory_max_bytes": amount,
                    "bounded": True, "pid": os.getpid(), "start_time": start_time(os.getpid(), self.proc)})
                self.held = True
            return state

    def release(self):
        if self.held:
            with self.locked():
                self.path.unlink()
                self.held = False
