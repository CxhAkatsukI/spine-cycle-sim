"""One memory policy for resident-G admission and the live case watchdog."""

POLICY = {"tree_memory_gib": 8, "reserve_gib": 32, "allow_bounded_builds": True}
MINIMUM_AVAILABLE_BYTES = (POLICY["tree_memory_gib"] + POLICY["reserve_gib"]) * 1024**3
