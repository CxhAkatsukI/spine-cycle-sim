"""Wait for one exact external-port BD invocation, then link unchanged author XOs."""

import argparse
import math
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from .. import configuration as config
from . import probe, route_inputs


def run(packet, attempt, bd, output, environment_root, xilinx, platform, compatibility, *,
        unit, invocation, maximum_wait=86400, poll_seconds=10):
    route_inputs.service_identity(unit, invocation)
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
           for value in (maximum_wait, poll_seconds)):
        raise ValueError("positive finite BD-wait bounds required")
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "WAITING_FOR_EXACT_EXTERNAL_PORT_BD", "errors": [],
              "bd_unit": unit, "bd_invocation": invocation, "profile": route_inputs.PROFILE,
              "physical_interconnect_changed": True, **dict.fromkeys(config.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", result)
    save()
    try:
        result["containment"] = probe.verify(probe.current())
        pins, _ = probe.inputs(packet, attempt)
        pins += runner_pins()
        result["pins"] = pins
        deadline = time.monotonic() + maximum_wait
        while True:
            probe.unchanged(pins)
            state = route_inputs.service_state(unit)
            result["bd_service"] = state
            save()
            if route_inputs.route_finished(state, invocation):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("external-port BD wait expired; no full link started")
            time.sleep(min(poll_seconds, remaining))
        parent = route_inputs.admit(packet, attempt, bd, unit=unit, invocation=invocation)
        result.update(status="STARTING_FULL_LINK_NOT_BOARD_ADMISSION", bd_parent=parent)
        save()
        child = probe.run(packet, attempt, output / "link_attempt", environment_root,
                          xilinx, platform, compatibility, bd_parent=parent)
        probe.unchanged(pins)
        if child["status"] != "EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD":
            raise ValueError("external-port full link did not complete")
        result.update(status=child["status"], child_report=probe.identity(output / "link_attempt/results.json"))
    except BaseException as error:
        result.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("packet", "attempt", "bd", "output", "environment-root", "xilinx", "platform", "compatibility"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--invocation", required=True)
    parser.add_argument("--maximum-wait", type=float, default=86400)
    run(**vars(parser.parse_args()))
