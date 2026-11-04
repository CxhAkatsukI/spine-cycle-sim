"""Explicit physical-only retry; never change clocks, kernels or connectivity."""

from pathlib import Path

PROFILE = "aggressive-route-v1"
ROUTED_REPORT = "impl_1_hw_bb_locked_timing_summary_routed.rpt"
PHYSOPT_REPORT = "impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt"
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


def report_name(profile):
    if profile is None:
        return ROUTED_REPORT
    if profile == PROFILE:
        return PHYSOPT_REPORT
    raise ValueError("unknown physical timing profile")


def final_report(reports, profile):
    # With post-route physopt enabled, write_bitstream consumes that checkpoint.
    matches = list(reports.rglob(report_name(profile)))
    if len(matches) != 1 or not matches[0].is_file() or matches[0].is_symlink():
        raise ValueError(f"one final locked timing report required: {report_name(profile)}")
    return matches[0]


def check_report_source(pin, remote_reports, profile):
    source = Path(pin["path"])
    if not source.is_relative_to(remote_reports) or ".." in source.parts or source.name != report_name(profile):
        raise ValueError("returned timing report does not match the bitstream implementation stage")
