"""Recheck complete prepared targets and actual raw reads, not host PASS strings."""

import math
from pathlib import Path

from .. import artifact, oracle
from ..board_execution.analysis import event_window
from . import analysis

PREPARED = "K4_BOARD_HOST_PREFLIGHT_PASS_NOT_FPGA"
PASS = "MATCHED_K4_A4_GUARDED_BOARD_CONTROL_PASS"
METRICS = {"status", "bdf", "board_programmed", "hardware_timing_measured", "complete_buffers_verified",
           "events", "enqueue_to_completion_ms", "event_union_ns", "event_span_ns"}
FALSE_CLAIMS = ("publication_match", "default_profile_equivalence", "same_resource_claim",
                "host_inclusive_measured", "convergence_measured")


def schedule(partitions):
    commands = [{"role": name, "ordinal": 0, "lane": 0, "waits": []}
                for name in ("hbm_wrapper", "apply")]
    for partition in range(partitions):
        for offset, role in enumerate(("adapter", "little", "frontend_mux")):
            index = len(commands)
            waits = ([index - 12] if partition >= 4 else []) if offset < 2 else ([index - 3] if partition else [])
            commands.append({"role": role, "ordinal": partition, "lane": partition % 4, "waits": waits})
    return commands


def targets(report, directory):
    partitions = report["partitions"]
    states = {"source_a0": 23, "source_a1": 24, "source_b0": 23, "source_b1": 24,
              "rank": 25, "divisor": 27, "stats": 27}
    mutable = {"source_b0", "source_b1", "rank", "stats"}
    names = {f"shard{p}_{name}" for p in range(partitions)
             for name in ("row", "binary", *[f"{kind}{i}" for kind in ("pma", "update") for i in range(4)])}
    names.update(states)
    buffers = report.get("buffers")
    if (not isinstance(buffers, list) or len(buffers) != len(names) or
            any(not isinstance(item, dict) for item in buffers) or
            {item.get("name") for item in buffers} != names):
        raise ValueError("complete unique graph/state buffer descriptions required")
    folder = directory / "expected_buffers"
    if folder.is_symlink() or not folder.is_dir() or {p.name for p in folder.iterdir()} != {n + ".u32le" for n in names}:
        raise ValueError("exact complete prepared target files required")
    banks, pins = [0] * 32, []
    for item in buffers:
        if (set(item) != {"name", "bank", "logical_words", "allocated_words", "words", "mutable"} or
                any(type(item[key]) is not int for key in ("bank", "logical_words", "allocated_words", "words")) or
                type(item["mutable"]) is not bool or item["mutable"] != (item["name"] in mutable) or
                not 0 <= item["logical_words"] <= item["allocated_words"] or
                item["words"] != item["allocated_words"] + 16 or not 0 < item["words"] * 4 < 256 * 1024**2 or
                not 0 <= item["bank"] < 32):
            raise ValueError("exact guarded buffer shape and mutability required")
        name = item["name"]
        if (name in states and (item["bank"] != states[name] or item["logical_words"] !=
                (16 if name == "stats" else report["capacity_vertices"]))) or (name not in states and item["bank"] >= 23):
            raise ValueError("production graph/state bank or capacity differs")
        path = folder / (name + ".u32le")
        pin = artifact.identity(path)
        if path.stat().st_size != item["words"] * 4:
            raise ValueError("complete target allocation including guards required")
        with path.open("rb") as stream:
            stream.seek(item["allocated_words"] * 4)
            if stream.read() != (0xA55A5AA5).to_bytes(4, "little") * 16:
                raise ValueError("prepared trailing canaries differ")
        banks[item["bank"]] += path.stat().st_size
        pins.append(pin)
    if max(banks) > 512 * 1024**2:
        raise ValueError("guarded aggregate bank capacity exceeded")
    return pins


def prepared(report, directory, expected, binding):
    required = {**analysis.profile(expected, binding), "status": PREPARED, "bdf": "",
                **dict.fromkeys((*FALSE_CLAIMS, "board_programmed", "hardware_timing_measured",
                                  "complete_buffers_verified"), False),
                **dict.fromkeys(("enqueue_to_completion_ms", "event_union_ns", "event_span_ns")), "events": []}
    if any(type(report.get(key)) is not type(value) or report[key] != value for key, value in required.items()):
        raise ValueError("exact non-device prepared K4 profile required")
    partitions = report["partitions"]
    commands, workers = report.get("commands"), report.get("worker_partitions")
    if (not isinstance(commands, list) or any(not isinstance(command, dict) or
            set(command) != {"role", "ordinal", "lane", "waits"} or
            type(command["role"]) is not str or
            any(type(command[key]) is not int for key in ("ordinal", "lane")) or
            not isinstance(command["waits"], list) or
            any(type(index) is not int for index in command["waits"]) for command in commands) or
            commands != schedule(partitions) or not isinstance(workers, list) or
            any(type(count) is not int for count in workers) or
            workers != [(partitions + 3 - w) // 4 for w in range(4)]):
        raise ValueError("production shared-mux and worker-reuse schedule required")
    checked = analysis.values(directory, expected, binding, gather="expected_gather.u32le", payload="expected_payload.u32le")
    pins = targets(report, directory)
    projection(report, directory, "expected_buffers", "expected_gather", "expected_payload")
    pins += [artifact.identity(directory / name) for name in
             ("result.json", "expected_gather.u32le", "expected_payload.u32le", "external_to_internal.u32le")]
    return {"values": checked, "targets": {Path(pin["path"]).name: pin["sha256"] for pin in pins
                                         if Path(pin["path"]).parent.name == "expected_buffers"}, "pins": pins}


def matrix(rows):
    projected = []
    for row in rows:
        if row["status"] not in (PREPARED, analysis.UNSUPPORTED):
            raise ValueError("only prepared or explicitly unsupported matrix rows allowed")
        projected.append({**row, "status": analysis.PASS if row["status"] == PREPARED else row["status"],
                          "analysis": {key: row["analysis"][key] for key in ("values", "targets")}
                          if row["status"] == PREPARED else None})
    analysis.matrix(projected)


def projection(report, directory, folder, gathered, payload):
    permutation = oracle.read_words(directory / "external_to_internal.u32le", report["vertices"])
    for raw, logical in (("rank", gathered), ("source_b0", payload)):
        words = oracle.read_words(directory / folder / (raw + ".u32le"), report["capacity_vertices"] + 16)
        external = oracle.read_words(directory / (logical + ".u32le"), report["vertices"])
        if any(external[v] != words[permutation[v]] for v in range(report["vertices"])):
            raise ValueError("external output is not the full buffer projection")


def readback(report, directory, case, bdf):
    required = {"status": PASS, "bdf": bdf, "board_programmed": True,
                "hardware_timing_measured": True, "complete_buffers_verified": True}
    if any(type(report.get(key)) is not type(value) or report[key] != value for key, value in required.items()):
        raise ValueError("guarded K4 board success on the leased BDF required")
    offline = case["offline"]
    if ({k: v for k, v in report.items() if k not in METRICS} !=
            {k: v for k, v in offline.items() if k not in METRICS}):
        raise ValueError("board profile, buffers or schedule differs from pinned preparation")
    checked = analysis.values(directory, case["reference"], case["binding"])
    if checked != case["expected"]["values"]:
        raise ValueError("actual external values differ from independent CSR expectation")
    folder, targets = directory / "readback", case["expected"]["targets"]
    if folder.is_symlink() or not folder.is_dir() or {p.name for p in folder.iterdir()} != set(targets):
        raise ValueError("every complete raw readback required")
    pins = [artifact.identity(folder / name) for name in sorted(targets)]
    if any(pin["sha256"] != targets[Path(pin["path"]).name] for pin in pins):
        raise ValueError("raw graph/state readback, padding or canary differs from CPU target")
    projection(offline, directory, "readback", "gathered_external", "payload_external")
    events = report.get("events")
    busy, span = event_window(events)
    if len(events) != len(offline["commands"]):
        raise ValueError("complete K4 event set required")
    for event, command in zip(events, offline["commands"]):
        if (any(type(event.get(key)) is not type(command[key]) or event[key] != command[key]
                for key in ("role", "ordinal", "lane")) or
                any(events[index]["end_ns"] > event["start_ns"] for index in command["waits"])):
            raise ValueError("K4 event identity or reuse dependency differs")
    wall = report.get("enqueue_to_completion_ms")
    if (type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0 or span > math.ceil(wall * 1e6) or
            type(report.get("event_union_ns")) is not int or type(report.get("event_span_ns")) is not int or
            (busy, span) != (report["event_union_ns"], report["event_span_ns"])):
        raise ValueError("overlap-aware event window or resident wall time differs")
    pins += [artifact.identity(directory / name) for name in
             ("result.json", "gathered_external.u32le", "payload_external.u32le", "external_to_internal.u32le")]
    return {"values": checked, "event_union_ns": busy, "event_span_ns": span,
            "enqueue_to_completion_ms": wall, "pins": pins}
