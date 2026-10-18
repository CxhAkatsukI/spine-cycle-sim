"""Named remote policy without relaxing the default compile or link budgets."""

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import memory_profiles

LINK = {"tree_memory_gib": 40, "reserve_gib": 32, "background_memory_gib": 8,
        "allow_bounded_builds": True}
COMPILE = {**LINK, "tree_memory_gib": 16}


def select(profile=None, *, compile=False, check_host=True):
    if profile is None:
        return dict(COMPILE if compile else LINK)
    # The remote exception has one exact cgroup contract, including during synthesis.
    policy = memory_profiles.select(LINK, profile)
    if check_host:
        memory_profiles.host(policy)
    return policy
