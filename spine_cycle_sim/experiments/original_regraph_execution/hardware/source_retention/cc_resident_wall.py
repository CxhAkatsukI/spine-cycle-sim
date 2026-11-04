"""Bind the matched wall-timing CC hosts to a frozen resident workload."""

import json
from pathlib import Path

from . import cc_resident_results, spine_cc_layout, spine_cc_warm_receipt
from .follow import unchanged
from .runtime import identity, save


BOUNDARY = "resident_old_graph_host_pack_to_final_readback"
IMAGE = "4071c0f792530fb0b62e6fc4a404ce1c78087c866d2c7c6f44c9fc2d05e64c62"
SPINE_HOST = "c7f81eeb24cbabc13e6a28366370417106af2a2063c457c970fe171900fe1153"
GR_HOST = "b72c20fec3bc7130edf430ff0006963e3112dfa57ea31bc96e38246b303f7412"


def configure(args, case, pins, *, retained_spine=None):
    if args.algorithm != "cc":
        raise ValueError("the matched wall host pair is CC-only")
    packet = args.cc_wall_packet
    pin = identity(packet)
    paths = json.loads(packet.read_text())
    layout = getattr(args, "cc_warm_layout", None)
    if layout is not None and (retained_spine is not None or case["dataset"] == "AU"):
        raise ValueError("warm layout is for new non-AU measurements, not the retained AU arm")
    expected = {"spine_host": SPINE_HOST, "spine_binary": IMAGE, "gr_host": GR_HOST}
    if retained_spine is not None:
        expected.update(spine_host=identity(retained_spine["command"][3])["sha256"],
                        spine_binary=retained_spine["clock"]["binary"]["sha256"])
    elif layout is not None:
        expected.update(spine_host=spine_cc_warm_receipt.BALANCED_HOST_SHA256, spine_binary=None)
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
        route_pins = spine_cc_warm_receipt.route_pins(binaries["spine_binary"])
        _, layout_pins = spine_cc_layout.replay(layout, case["dataset"], host=binaries["spine_host"],
                                                inputs=inputs["path"], frozen=source)
        new_pins += [*route_pins, *layout_pins, identity(spine_cc_layout.__file__),
                     identity(spine_cc_warm_receipt.__file__)]
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


def compare(case, arms, output, bdf):
    logs = [arms[name]["stdout"] for name in ("gr", "spine")]
    unchanged(logs)
    gr, spine = (Path(pin["path"]).read_text() for pin in logs)
    pair = cc_resident_results.analyze(case, gr, spine, bdf=bdf)
    unchanged(logs)
    result = output / "pair.json"
    save(result, pair)
    return pair, identity(result)
