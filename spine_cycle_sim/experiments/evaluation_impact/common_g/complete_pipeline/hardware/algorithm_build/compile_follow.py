"""Wait for one exact compile before the independently reviewed, bounded link."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from ....continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from ....search_pipeline.synthesis import unchanged
from ..remote.timing import PROFILE
from . import inputs, memory, route_study

PASS = "COMPILE_AND_LINK_PASS_AWAITING_TIMING_RTL_AND_BOARD"
LINK_PASS = "LINK_PASS_UNVERIFIED_RTL_AWAITING_TIMING_AND_BOARD"


def run(compilation, sources, storage, output, xilinx, platform, compatibility, shim, *,
        compile_unit, compile_invocation, algorithm, timing_profile=None,
        maximum_wait=133200, poll_seconds=30, memory_profile=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", compile_unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", compile_invocation):
        raise ValueError("exact compile service and invocation required")
    if algorithm not in inputs.ALGORITHMS or timing_profile not in (None, PROFILE):
        raise ValueError("declared algorithm and physical timing profile required")
    memory.select(memory_profile)
    if type(maximum_wait) is not int or not 1 <= maximum_wait <= 133200 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("positive bounded compile wait and poll required")
    compilation, sources, storage, output, xilinx, platform, compatibility, shim = (
        path.resolve() for path in (compilation, sources, storage, output, xilinx, platform, compatibility, shim))
    output.mkdir(parents=True, exist_ok=False)
    child = output / "route"
    report = {"status": "PREPARING", "errors": [], "algorithm": algorithm,
              "compile_unit": compile_unit, "compile_invocation": compile_invocation,
              "compile_states": [], "maximum_wait_seconds": maximum_wait,
              "poll_seconds": poll_seconds, "timing_profile": timing_profile,
              "memory_profile": memory_profile,
              "route_output": str(child), "link_completed": False,
              "rtl_admitted": False, "timing_admitted": False, **inputs.CLAIMS}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=40)
        source = inputs.verify(sources)
        manifest_file = compilation / "manifest.json"
        manifest_pin = identity(manifest_file)
        manifest = json.loads(manifest_file.read_text())
        if manifest["source_manifest"] != identity(sources / "sources.json") or \
                manifest["integration_revision"] != source["integration_revision"] or \
                manifest["algorithm"] != algorithm or manifest["clock_mhz"] != 150 or \
                any(manifest.get(key) is not False for key in inputs.CLAIMS):
            raise ValueError("requested sources/algorithm differ from the active compilation")
        report.update(integration_revision=source["integration_revision"],
                      pins=[manifest_pin, manifest["source_manifest"], *manifest["pins"],
                            *[identity(sources / row["member"]) for row in source["files"]],
                            *runner_pins()])
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = service_state(compile_unit)
            if not report["compile_states"] or report["compile_states"][-1] != state:
                report["compile_states"].append(state)
            report.update(status="WAITING_FOR_EXACT_COMPILATION", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, compile_invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("exact algorithm compilation did not finish")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        execution_file = compilation / "execution.json"
        execution = json.loads(execution_file.read_text())
        if execution["status"] != "COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE" or \
                execution["errors"] or execution["algorithm"] != algorithm or \
                execution["manifest"] != manifest_pin:
            raise ValueError("terminal service lacks the requested successful compilation")
        report["pins"].append(identity(execution_file))
        unchanged(report["pins"])
        report["status"] = "REVIEWING_AND_LINKING_NOT_BOARD_ADMISSION"
        save()
        # The route owner rechecks every XO, resource, ABI and finite memory budget.
        options = {} if memory_profile is None else {"memory_profile": memory_profile}
        result = route_study.run(compilation, storage, child, xilinx, platform, compatibility, shim,
                                 timing_profile=timing_profile, **options)
        saved = json.loads((child / "execution.json").read_text())
        if saved != result or saved["status"] != LINK_PASS or saved["errors"] or \
                saved["algorithm"] != algorithm or \
                saved["integration_revision"] != source["integration_revision"] or \
                any(saved.get(key) is not False for key in ("rtl_admitted", "board_admitted", "publication_match")):
            raise ValueError("experimental link did not complete its declared source/algorithm scope")
        if saved["xclbin"] != identity(child / "candidate.hw.xclbin"):
            raise ValueError("experimental link binary identity changed")
        unchanged(report["pins"])
        if not route_finished(service_state(compile_unit), compile_invocation):
            raise ValueError("compile service is no longer terminal")
        report.update(status=PASS, link_completed=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        if (child / "execution.json").is_file():
            report["route_execution"] = identity(child / "execution.json")
        save()
    return report
