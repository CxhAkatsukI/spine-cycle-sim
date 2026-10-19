"""Finite host budgets and throttle-free timing admission for resident matrices."""

GIB = 1024**3
HIGH_GIB = {24: 22, 40: 36}


def policy(memory_gib=24):
    if type(memory_gib) is not int or memory_gib not in HIGH_GIB:
        raise ValueError("explicit 24- or 40-GiB resident board budget required")
    return {"tree_memory_gib": memory_gib, "reserve_gib": 32, "allow_bounded_builds": True}


def validate(limits, declared):
    amount = declared.get("tree_memory_gib")
    if declared != policy(amount) or int(limits["memory.max"]) != amount * GIB or \
            not 0 < int(limits["memory.high"]) <= HIGH_GIB[amount] * GIB or \
            limits["memory.swap.max"] != "0" or limits["memory.oom.group"] != "1":
        raise ValueError("declared resident budget must match bounded no-swap board containment")


def require_unthrottled(raw):
    events = dict(line.split() for line in raw.splitlines())
    if any(int(events[key]) != 0 for key in ("high", "max", "oom", "oom_kill", "oom_group_kill")):
        raise ValueError("memory throttling, limit or OOM events prevent timing acceptance")
