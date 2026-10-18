"""Explicit high-memory admission; foreign jobs are observed, never modified."""

from pathlib import Path
import socket

from .containment import GIB

SEELE = "seele-reserve-128g-v1"
KEY = "unbounded_peer_policy"
UNBOUNDED = "competing compiler has no finite cgroup memory limit"


def select(default, profile=None):
    if profile is None:
        return dict(default)
    if profile != SEELE or default != {"tree_memory_gib": 40, "reserve_gib": 32,
            "background_memory_gib": 8, "allow_bounded_builds": True}:
        raise ValueError("unknown high-memory admission profile or base policy")
    return {**default, "reserve_gib": 128, KEY: SEELE}


def observed(policy):
    if KEY not in policy:
        return False
    expected = {"tree_memory_gib": 40, "reserve_gib": 128,
                "background_memory_gib": 8, "allow_bounded_builds": True, KEY: SEELE}
    if policy != expected:
        raise ValueError("high-memory profile requires exact bounded 40/128/8-GiB policy")
    return True


def host(policy, *, name=None, meminfo=Path("/proc/meminfo")):
    if not observed(policy):
        return None
    name = socket.gethostname() if name is None else name
    total = int(dict(line.split(":", 1) for line in meminfo.read_text().splitlines())[
        "MemTotal"].split()[0]) * 1024
    if name != "seele" or total < 480 * GIB:
        raise ValueError("observed-peer profile is restricted to seele with at least 480 GiB RAM")
    return {"host": name, "total_memory_bytes": total, "minimum_reserve_gib": 128,
            "foreign_jobs_bounded": False,
            "response_to_low_memory": "stop_only_owned_build_tree"}


def compatible(row, policy):
    if row.get("bounded") is True and row.get("memory_max_bytes", 0) > 0:
        return True
    # Missing limits, invalid swap configuration and conflicting leases still reject.
    return (observed(policy) and row.get("bounded") is False and
            type(row.get("pid")) is int and row["pid"] > 0 and
            row.get("reason") == UNBOUNDED and "cgroup" not in row)
