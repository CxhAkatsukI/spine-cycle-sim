"""Bind the matched wall-timing CC hosts to a frozen resident workload."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import single

from . import cc_resident_results, cc_spine_route, spine_cc_layout, spine_cc_warm_receipt
from .follow import unchanged
from .runtime import identity, save


BOUNDARY = "resident_old_graph_host_pack_to_final_readback"
IMAGE = "4071c0f792530fb0b62e6fc4a404ce1c78087c866d2c7c6f44c9fc2d05e64c62"
SPINE_HOST = "c7f81eeb24cbabc13e6a28366370417106af2a2063c457c970fe171900fe1153"
GR_HOST = "b72c20fec3bc7130edf430ff0006963e3112dfa57ea31bc96e38246b303f7412"


def warm_evidence(layout, dataset, host, image, inputs, source, candidate):
    if candidate is None:
        if host["sha256"] != spine_cc_warm_receipt.BALANCED_HOST_SHA256:
            raise ValueError("warm CC pair did not use the pinned wall host")
        abi, offline_host = None, host
        route_pins = spine_cc_warm_receipt.route_pins(image)
    else:
        abi, files = cc_spine_route.matrix_route(candidate)
        if (host, image) != (files["host"], files["image"]):
            raise ValueError("warm CC pair does not use the replacement route and host")
        offline_host = json.loads(Path(layout).read_text())["host"]
        if offline_host["sha256"] != host["sha256"]:
            raise ValueError("offline layout did not use the replacement board host binary")
        route_pins = [candidate, *files.values(), identity(cc_spine_route.__file__)]
    _, layout_pins = spine_cc_layout.replay(layout, dataset, host=offline_host, inputs=inputs, frozen=source)
    return abi, route_pins, layout_pins


def configure(args, case, pins, *, retained_spine=None):
    if args.algorithm != "cc":
        raise ValueError("the matched wall host pair is CC-only")
    packet = args.cc_wall_packet
    pin = identity(packet)
    paths = json.loads(packet.read_text())
    layout = getattr(args, "cc_warm_layout", None)
    candidate = getattr(args, "cc_warm_candidate", None)
    if candidate is not None and layout is None:
        raise ValueError("a replacement CC route requires a checked offline layout")
    if layout is not None and (retained_spine is not None or case["dataset"] == "AU"):
        raise ValueError("warm layout is for new non-AU measurements, not the retained AU arm")
    expected = {"spine_host": SPINE_HOST, "spine_binary": IMAGE, "gr_host": GR_HOST}
    if retained_spine is not None:
        expected.update(spine_host=identity(retained_spine["command"][3])["sha256"],
                        spine_binary=retained_spine["clock"]["binary"]["sha256"])
    elif layout is not None:
        expected.update(spine_host=None, spine_binary=None)
    if set(paths) != expected.keys() | {"inputs"}:
        raise ValueError("unexpected CC wall packet members")
    binaries = {name: identity(paths[name]) for name in expected}
    if any(binaries[name]["sha256"] != sha for name, sha in expected.items() if sha is not None):
        raise ValueError("expected the qualified CC image and wall host binaries")
    if retained_spine is not None and (binaries["spine_host"]["path"] != retained_spine["command"][3]
                                       or binaries["spine_binary"] != retained_spine["clock"]["binary"]):
        raise ValueError("wall packet uses a different host or image than the retained Spine arm")
    inputs = identity(paths["inputs"])
    split = json.loads(Path(inputs["path"]).read_text())
    source = next((row for row in pins if row["path"] == case["graph"]), None)
    if (source is None or split["source"] != source
            or any(split[key] != case[key] for key in ("vertices", "edges", "updates"))):
        raise ValueError("CC split input does not match the frozen workload")
    if retained_spine is not None and retained_spine["command"][-4:] != [
            "--slice", split["graph"]["path"], "--update", split["update"]["path"]]:
        raise ValueError("wall packet does not match the retained Spine inputs")
    new_pins = [pin, inputs, *binaries.values(), split["graph"], split["update"], identity(__file__),
                identity(cc_resident_results.__file__)]
    if layout is not None:
        abi, route_pins, layout_pins = warm_evidence(
            layout, case["dataset"], binaries["spine_host"], binaries["spine_binary"], inputs["path"],
            source, candidate)
        new_pins += [*route_pins, *layout_pins, identity(spine_cc_layout.__file__),
                     identity(spine_cc_warm_receipt.__file__)]
        if abi is not None:
            case = dict(case, spine_route_abi=abi)
    unchanged(new_pins)
    return dict(case, **{name: row["path"] for name, row in binaries.items()},
                graph_slice=split["graph"]["path"], update_slice=split["update"]["path"],
                memory_gib=32, boundary=BOUNDARY), new_pins


def commands(case, gate, output):
    return {
        "spine": [case["spine_host"], "--xclbin", case["spine_binary"], "--hot", "balanced",
                  "--mode", "partial", "--samples", "1", "--slice", case["graph_slice"],
                  "--update", case["update_slice"]],
        "gr": [case["gr_host"], gate["image"]["path"], case["graph"], str(output / "gr-state.txt"),
               str(case["source"]), "256"],
    }


def check_candidate_sample(abi, observed, spine_stdout):
    if (observed["spine"]["driver_reported_mhz"] != observed["gr"]["driver_reported_mhz"]
            or single(spine_stdout.splitlines(), "CC_SETUP").get("source_config_sha256") != abi):
        raise ValueError("replacement Spine CC sample does not match the baseline clock and route ABI")


def replay_warm_pair(child, source, observed, recorded):
    """Recheck the warm layout and wall samples when indexing a finished pair."""
    case, arms, pins = (child[key] for key in ("case", "arms", "pins"))
    if (child["bdf"], tuple(child["cpu_affinity"])) != (
            spine_cc_warm_receipt.BDF, spine_cc_warm_receipt.AFFINITY) or case["dataset"] == "AU":
        raise ValueError("warm CC pair did not use its qualified board, affinity and dataset")
    packet, layout = child["wall_packet"], child["warm_layout"]
    unchanged([packet, layout])
    inputs = json.loads(Path(packet["path"]).read_text())
    image, host = observed["spine"]["binary"], identity(case["spine_host"])
    if (inputs["spine_binary"], inputs["spine_host"], inputs["gr_host"]) != (
            image["path"], host["path"], case["gr_host"]) or (
                identity(case["gr_host"])["sha256"] != GR_HOST):
        raise ValueError("warm CC pair did not use the pinned wall hosts and Spine image")
    split = json.loads(Path(inputs["inputs"]).read_text())
    if [case["graph_slice"], case["update_slice"]] != [split[key]["path"] for key in ("graph", "update")]:
        raise ValueError("warm CC pair did not use the checked split inputs")
    abi, route_pins, layout_pins = warm_evidence(layout["path"], case["dataset"], host, image,
                                                inputs["inputs"], source, child.get("warm_candidate"))
    if case.get("spine_route_abi") != abi:
        raise ValueError("recorded Spine ABI differs from the checked route")
    if any(pin not in pins for pin in [packet, *route_pins, *layout_pins]):
        raise ValueError("warm CC layout or route differs from the pre-measurement pins")
    output = Path(child["comparison_log"]["path"]).parent
    expected = commands(case, child["stage_gates"], output)
    if child["commands"] != expected or any(arms[name]["command"] != cmd for name, cmd in expected.items()):
        raise ValueError("warm CC arm commands differ from the frozen packet")
    logs = [arms[name]["stdout"] for name in ("gr", "spine")]
    unchanged(logs)
    gr, spine = (Path(pin["path"]).read_text() for pin in logs)
    if abi is not None:
        check_candidate_sample(abi, observed, spine)
    if cc_resident_results.analyze(case, gr, spine, bdf=child["bdf"]) != recorded:
        raise ValueError("warm CC wall times or oracle results differ from the raw logs")
    unchanged([packet, *route_pins, *layout_pins, *logs])
    return {"warm_layout": layout, "wall_packet": packet, "spine_route": route_pins}


def compare(case, arms, output, bdf):
    logs = [arms[name]["stdout"] for name in ("gr", "spine")]
    unchanged(logs)
    gr, spine = (Path(pin["path"]).read_text() for pin in logs)
    if "spine_route_abi" in case:
        check_candidate_sample(case["spine_route_abi"], {name: arm["clock"] for name, arm in arms.items()}, spine)
    pair = cc_resident_results.analyze(case, gr, spine, bdf=bdf)
    unchanged(logs)
    result = output / "pair.json"
    save(result, pair)
    return pair, identity(result)
