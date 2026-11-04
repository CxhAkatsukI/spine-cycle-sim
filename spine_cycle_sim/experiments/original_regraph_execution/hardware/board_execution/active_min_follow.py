"""Wait for two pinned route jobs, then screen a single active-min R pair."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from .. import artifact
from ..source_build import configuration, portable_return, snapshot
from ..source_retention.runtime import check_memory, save
from . import active_min_pair


def exact_service(unit, invocation):
    if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
            and re.fullmatch(r"[0-9a-f]{32}", invocation)):
        raise ValueError("each dependency needs an exact service and invocation ID")


def prior_finished(row):
    state = service_state(row["unit"])
    row["state"] = state
    if state["LoadState"] == "loaded" and state["InvocationID"] == row["invocation"]:
        row["observed"] = True
        if state["MainPID"] != "0" or state["ActiveState"] not in ("inactive", "failed", "active"):
            return False
        if state["ActiveState"] == "active" and state["SubState"] != "exited":
            return False
    elif not (row["observed"] and state["LoadState"] == "not-found" and not state["InvocationID"]):
        raise ValueError("earlier pair service was never observed or changed invocation")
    receipt = Path(row["journal"])
    result = json.loads(receipt.read_text())
    if result["status"] not in ("PAIRED_ACTIVE_MIN_R_GATE_PASS", "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED",
                                "FAILED_RETAINED"):
        raise ValueError("earlier pair exited without a terminal receipt")
    row["receipt"] = artifact.identity(receipt)
    return True


def fixture_pin(args, input_pins):
    receipt, digest = args.odd_fixture
    pin = artifact.identity(Path(receipt))
    fixture = json.loads(Path(pin["path"]).read_text())
    expected = {(row["path"], row["sha256"]) for row in fixture["input_pins"]}
    if (pin["sha256"] != digest or fixture["frontier"] != "odd-vertices"
            or fixture["status"] != "ACTIVE_MIN_COMPONENT_INPUTS_OFFLINE_PASS"
            or any((row["path"], row["sha256"]) not in expected for row in input_pins)):
        raise ValueError("high-activity fixture or pair inputs differ from the frozen receipt")
    return pin


def ready(name, route, state, invocation, observed, algorithm):
    if state["LoadState"] == "loaded":
        finished = route_finished(state, invocation)
    elif observed and state["LoadState"] == "not-found" and not state["InvocationID"]:
        # systemd may garbage-collect a transient unit on successful exit.
        finished = True
    else:
        raise ValueError("route unit was never observed at its pinned invocation")
    if not finished:
        return False
    path = route / ("results.json" if name == "reference" else "execution/execution.json")
    expected = (configuration.routed_status("a4", algorithm=algorithm) if name == "reference"
                else "LINK_PASS_AWAITING_TIMING_AND_BOARD")
    if not path.is_file() or json.loads(path.read_text())["status"] != expected:
        raise ValueError(f"{name} route ended without successful artifact evidence")
    return True


def completed_reference(route, digest, algorithm):
    pin = artifact.identity(route / "results.json")
    receipt = json.loads(Path(pin["path"]).read_text())
    snapshot.unchanged([pin])
    if (pin["sha256"], receipt.get("status")) != (
            digest, configuration.routed_status("a4", algorithm=algorithm)):
        raise ValueError("completed reference digest or routed status does not match")
    return pin


def returned_ready(name, route, digest, state, invocation, observed):
    if state["LoadState"] == "loaded":
        if not route_finished(state, invocation):
            return None
    elif not (observed and state["LoadState"] == "not-found" and not state["InvocationID"]):
        raise ValueError("return service was never observed at its pinned invocation")
    transfer = artifact.identity(route.parent / "transfer.json")
    report = json.loads(Path(transfer["path"]).read_text())
    if name == "candidate":
        status = "REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE"
        image_matches = report.get("candidate") == artifact.identity(route / "route/candidate.hw.xclbin")
    elif name == "reference":
        status = portable_return.STATUS
        image_matches = artifact.identity(route / portable_return.BINARY) in report.get("pins", [])
    else:
        raise ValueError(f"unexpected returned arm: {name}")
    if digest is None:
        digest = artifact.identity(route / "receipt.json")["sha256"]
    if report.get("status") != status or report.get("receipt_sha256") != digest or not image_matches:
        raise ValueError("returned route does not match the verified collector receipt")
    return transfer


def return_parameters(explicit, pending, pins):
    if explicit and pending:
        raise ValueError("choose either a presealed or a pending return for each arm")
    if not pending:
        return explicit
    capsule, *others = [Path(value).resolve(strict=True) for value in pending]
    pins.extend(artifact.identity(path) for path in (capsule / "capsule.json", *others))
    return [None, str(capsule), *map(str, others)]


def seal_parameters(parameters, transfer):
    if parameters[0] is not None:
        return parameters
    snapshot.unchanged([transfer])
    return [json.loads(Path(transfer["path"]).read_text())["receipt_sha256"], *parameters[1:]]


def run(args):
    if not 1 <= args.wait_seconds <= 111600:
        raise ValueError("route wait must be bounded to 31 hours")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "queue.json"
    report = {"status": "PREPARING", "routes": {}, "requested_pair": False}
    save(journal, report)
    try:
        check_memory()
        report["preflight_xrt_libraries"] = active_min_pair.paired_loader(args.reference_host, args.candidate_host)
        pins = [artifact.identity(path) for path in active_min_pair.input_paths(args)]
        prior = getattr(args, "after_pair", [])
        odd = getattr(args, "odd_fixture", None)
        if odd:
            if not 1 <= len(prior) <= 2 or len({row[0] for row in prior}) != len(prior) or not args.board_wait_seconds:
                raise ValueError("high-activity run requires distinct earlier pairs and bounded board admission")
            pins.append(fixture_pin(args, pins[2:]))
        returned = {arm: return_parameters(getattr(args, "returned_" + arm, None),
                                           getattr(args, "pending_return_" + arm, None), pins)
                    for arm in ("reference", "candidate")}
        if not returned["candidate"]:
            pins.append(artifact.identity(args.candidate_route / "manifest.json"))
        completed = getattr(args, "completed_reference", None)
        if completed and (returned["reference"] or args.reference_unit or args.reference_invocation):
            raise ValueError("choose a completed reference or an exact reference service")
        pins += runner_pins()
        report["pins"] = pins
        report["earlier_pairs"] = []
        for unit, invocation, journal_path in prior:
            exact_service(unit, invocation)
            report["earlier_pairs"].append(dict(unit=unit, invocation=invocation,
                                                 journal=str(Path(journal_path).absolute()), observed=False))
        for arm in ("reference", "candidate"):
            unit = getattr(args, arm + "_unit")
            invocation = getattr(args, arm + "_invocation")
            route = getattr(args, arm + "_route")
            if arm == "reference" and completed:
                pin = completed_reference(route, completed, args.algorithm)
                pins.append(pin)
                report["routes"][arm] = dict(route=str(route), completed_receipt=pin, ready=True)
                continue
            exact_service(unit, invocation)
            report["routes"][arm] = {"unit": unit, "invocation": invocation, "route": str(route), "observed": False}
        deadline = time.monotonic() + args.wait_seconds
        while True:
            report["status"] = "WAITING_FOR_BOTH_ROUTES"
            for arm, row in report["routes"].items():
                if "completed_receipt" in row:
                    continue
                state = service_state(row["unit"])
                row["state"] = state
                row["observed"] |= state["LoadState"] == "loaded" and state["InvocationID"] == row["invocation"]
                route = Path(row["route"])
                if returned[arm]:
                    row["transfer"] = returned_ready(arm, route, returned[arm][0], state,
                                                     row["invocation"], row["observed"])
                    row["ready"] = row["transfer"] is not None
                else:
                    row["ready"] = ready(arm, route, state, row["invocation"], row["observed"], args.algorithm)
            for row in report["earlier_pairs"]:
                if not row.get("receipt"):
                    prior_finished(row)
            routes_ready = all(row["ready"] for row in report["routes"].values())
            if routes_ready and not all(row.get("receipt") for row in report["earlier_pairs"]):
                report["status"] = "WAITING_FOR_EARLIER_PAIRS"
            save(journal, report)
            if routes_ready and all(row.get("receipt") for row in report["earlier_pairs"]):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("route or earlier pair prerequisites did not finish before the deadline")
            time.sleep(min(30, remaining))
        snapshot.unchanged(pins + [row["receipt"] for row in report["earlier_pairs"]]
                           + [row["transfer"] for row in report["routes"].values() if row.get("transfer")])
        for arm, parameters in returned.items():
            if parameters:
                setattr(args, "returned_" + arm, seal_parameters(parameters, report["routes"][arm]["transfer"]))
        report.update(status="REQUESTING_ONE_PAIRED_RUN", requested_pair=True)
        save(journal, report)
        args.output = args.output / "pair"
        measured = active_min_pair.run(args)
        report.update(status=measured["status"], result=artifact.identity(args.output / "results.json"),
                      retention_gate_pass=measured["retention_gate_pass"])
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def wait_arguments(parser):
    for arm in ("reference", "candidate"):
        parser.add_argument(f"--{arm}-unit", default="", required=arm == "candidate")
        parser.add_argument(f"--{arm}-invocation", default="", required=arm == "candidate")
    parser.add_argument("--completed-reference", metavar="RESULTS_SHA256")
    parser.add_argument("--wait-seconds", type=int, default=108000)
    parser.add_argument("--board-wait-seconds", type=int, default=0)
    parser.add_argument("--after-pair", action="append", nargs=3, default=[], metavar=("UNIT", "INVOCATION", "JOURNAL"))
    parser.add_argument("--odd-fixture", nargs=2, metavar=("MANIFEST", "SHA256"))
    parser.add_argument("--pending-return-candidate", nargs=3, metavar=("CAPSULE", "XPFM", "PREDECESSOR"))
    parser.add_argument("--pending-return-reference", nargs=1, metavar="CAPSULE")


if __name__ == "__main__":
    result = run(active_min_pair.parse_arguments(extend=wait_arguments))
    print(result["status"], flush=True)
    raise SystemExit(0 if result.get("retention_gate_pass") else 1)
