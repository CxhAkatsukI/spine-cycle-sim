"""Seal and strictly review one exact local link; never request a board."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from ....continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from ....search_pipeline.synthesis import unchanged
from . import admission, artifacts, inputs
from .follow import MAXIMUM_WAIT_SECONDS

PASS = "ALGORITHM_LOCAL_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION"


def run(compilation, route, sources, output, *, unit, invocation, algorithm,
        maximum_wait=270000, poll_seconds=30):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact local route service and invocation required")
    if algorithm not in inputs.ALGORITHMS or type(maximum_wait) is not int or \
            not 1 <= maximum_wait <= MAXIMUM_WAIT_SECONDS or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("declared algorithm and finite wait/poll required")
    compilation, route, sources, output = (
        path.resolve() for path in (compilation, route, sources, output))
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "algorithm": algorithm,
              "unit": unit, "invocation": invocation, "states": [],
              "route": str(route), "maximum_wait_seconds": maximum_wait,
              "board_requested": False, **dict.fromkeys(artifacts.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=4)
        source = inputs.verify(sources)
        manifest_path = compilation / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("source_manifest") != identity(sources / "sources.json") or \
                manifest.get("integration_revision") != source["integration_revision"] or \
                manifest.get("algorithm") != algorithm or manifest.get("clock_mhz") != 150 or \
                any(manifest.get(key) is not False for key in inputs.CLAIMS):
            raise ValueError("requested source/algorithm differs from compilation")
        report.update(integration_revision=source["integration_revision"], pins=[
            identity(manifest_path), identity(sources / "sources.json"),
            *[identity(sources / row["member"]) for row in source["files"]], *runner_pins()])
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = service_state(unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_LOCAL_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("exact local algorithm route did not finish")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        report["status"] = "SEALING_LOCAL_RETURN"
        save()
        sealed = artifacts.seal(compilation, route, output / "returned", unit=unit, invocation=invocation)
        report["receipt_sha256"] = sealed["sha256"]
        receipt = artifacts.verify(output / "returned", report["receipt_sha256"])
        if receipt["algorithm"] != algorithm or receipt["integration_revision"] != source["integration_revision"] or \
                receipt["unit"] != unit or receipt["invocation"] != invocation:
            raise ValueError("sealed local source/algorithm/service differs")
        unchanged(report["pins"])
        report["status"] = "CHECKING_LOCAL_ADMISSION"
        save()
        checked = admission.review(output / "returned", sources, output / "admission",
                                   receipt_sha256=report["receipt_sha256"])
        unchanged(report["pins"])
        if checked["status"] != "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" or \
                checked["algorithm"] != algorithm:
            raise ValueError("strict local algorithm admission incomplete")
        if not route_finished(service_state(unit), invocation):
            raise ValueError("local route no longer terminal after admission")
        report.update(status=PASS, admission=identity(output / "admission/summary.json"))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report
