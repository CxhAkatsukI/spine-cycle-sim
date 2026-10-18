"""Accept one exact terminal algorithm link and retain its unchanged checkpoint."""

import re

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....continuous_board.execution.supervisor import route_finished, service_state
from ....search_pipeline.synthesis import unchanged
from ..algorithm_build import artifacts


def admit(route, unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact terminal service invocation required")
    state = service_state(unit)
    if not route_finished(state, invocation):
        raise ValueError("checkpoint producer is still running or failed")
    execution, manifest = artifacts.completed(route)
    pins = list(manifest["pins"])
    unchanged(pins)
    if execution.get("manifest") != identity(route / "manifest.json") or \
            execution.get("xclbin") != identity(route / "candidate.hw.xclbin"):
        raise ValueError("terminal route identities differ")
    checkpoints = list((route / "link").glob("**/impl_1/level0_wrapper_routed.dcp"))
    reports = list((route / "reports").glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(checkpoints) != 1 or len(reports) != 1:
        raise ValueError("one final routed checkpoint and timing report required")
    pins += [identity(route / name) for name in ("manifest.json", "execution.json", "candidate.hw.xclbin")]
    pins += [identity(checkpoints[0]), identity(reports[0])]
    return {"route": str(route), "unit": unit, "invocation": invocation, "service": state,
            "algorithm": manifest["algorithm"], "pins": pins, "checkpoint": str(checkpoints[0]),
            "original_timing": str(reports[0])}
