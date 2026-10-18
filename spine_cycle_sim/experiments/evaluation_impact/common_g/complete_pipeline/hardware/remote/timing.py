"""Explicit physical-only retry; never change clocks, kernels or connectivity."""

PROFILE = "aggressive-route-v1"
PROPERTIES = (
    "run.impl_1.STEPS.PLACE_DESIGN.ARGS.DIRECTIVE=AltSpreadLogic_high",
    "run.impl_1.STEPS.PHYS_OPT_DESIGN.ARGS.DIRECTIVE=AggressiveExplore",
    "run.impl_1.STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE=AggressiveExplore",
    "run.impl_1.STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED=true",
    "run.impl_1.STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE=AggressiveExplore",
)


def configure(contents, profile):
    if profile is None:
        return contents
    if profile != PROFILE:
        raise ValueError("unknown physical timing profile")
    if any(line.strip().lower() == "[vivado]" for line in contents.splitlines()):
        raise ValueError("timing retry cannot replace existing Vivado properties")
    return contents + "\n[vivado]\n" + "\n".join("prop=" + value for value in PROPERTIES) + "\n"
