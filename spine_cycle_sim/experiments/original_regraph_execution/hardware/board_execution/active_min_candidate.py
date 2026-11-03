"""Replay the production sharded-K4 active-min probe from raw outputs."""

import hashlib
from pathlib import Path
import re
from struct import iter_unpack

from .. import artifact, oracle
from .analysis import event_window


ALGORITHM = {"cc": "connected_components", "weighted_sssp": "weighted_sssp"}
EVENT = re.compile(
    r"SHARDED_DEVICE_EVENT stage=(\w+) round=(\d+) shard=(-?\d+) worker=(-?\d+)"
    r" queued_ns=(\d+) submit_ns=(\d+) start_ns=(\d+) end_ns=(\d+)"
)
RESULT = re.compile(
    r"ACTIVE_MIN_CANDIDATE_BOARD_RESULT status=PASS algorithm=(\w+) supersteps=1"
    r" vertices=(\d+) logical_edges=(\d+) shards=(\d+) active_outputs=(\d+) grasu_launches=0"
)


def inspect(stdout, directory, offline, expected, inputs):
    descriptor = oracle.read_words(inputs / "execution.u32le", 8 + 8 * offline["tasks"])
    vertices, edges, aligned, shards = (descriptor[i] for i in (2, 3, 4, 7))
    if ((vertices, edges) != (offline["vertices"], offline["logical_edges"])
            or shards <= 0 or aligned != shards * 65536 or not aligned - 65536 < vertices <= aligned):
        raise ValueError("candidate publication extent differs from the reference")

    reference = Path(expected["path"])
    if artifact.identity(reference) != expected or reference.stat().st_size != 4 * aligned + 64:
        raise ValueError("pinned reference oracle differs")
    with reference.open("rb") as stream:
        words = stream.read(4 * aligned)
    digest = hashlib.sha256(words).hexdigest()
    active = sum(bool(word & 0x80000000) for (word,) in iter_unpack("<I", words))
    if not active:
        raise ValueError("active-min retention requires propagation")
    output_pins = []
    for name in ("replica0", "replica1", "apply_property"):
        path = directory / f"{name}.u32le"
        pin = artifact.identity(path)
        if (pin["sha256"], path.stat().st_size) != (digest, len(words)):
            raise ValueError(f"candidate {name} differs from reference oracle")
        output_pins.append(pin)

    result_rows, events, identities = [], [], []
    with stdout.open() as stream:
        for line in stream:
            line = line.rstrip("\n")
            if line.startswith("ACTIVE_MIN_CANDIDATE_BOARD_RESULT"):
                result = RESULT.fullmatch(line)
                if not result:
                    raise ValueError("explicit candidate correctness pass required")
                result_rows.append((result[1], *map(int, result.groups()[1:])))
            elif line.startswith("SHARDED_DEVICE_EVENT"):
                event = EVENT.fullmatch(line)
                if not event:
                    raise ValueError("malformed candidate event")
                stage, *raw = event.groups()
                step, shard, worker, *times = map(int, raw)
                identities.append((stage, step, shard, worker))
                events.append(dict(zip(("queued_ns", "submitted_ns", "start_ns", "end_ns"), times)))
    if result_rows != [(ALGORITHM[offline["algorithm"]], vertices, edges, shards, active)]:
        raise ValueError("candidate execution geometry, policy, active count or run count differs")
    required = [(role, 0, -1, -1) for role in ("hbm", "apply")]
    required += [(role, 0, shard, shard % 4) for shard in range(shards)
                 for role in ("adapter", "gather", "mux")]
    if identities != required:
        raise ValueError("missing, unexpected or repeated candidate kernel event")
    busy, span = event_window(events)
    return {"event_span_ns": span, "event_union_ns": busy, "active_outputs": active,
            "kernel_events": len(events), "output_pins": output_pins, "oracle_sha256": digest}


def compare(reference, candidate, reference_clock, candidate_clock):
    if reference_clock["bdf"] != candidate_clock["bdf"]:
        raise ValueError("paired active-min observations must use one PCI device")
    control, current = reference["event_span_ns"], candidate["event_span_ns"]
    if any(type(value) is not int or value <= 0 for value in (control, current)):
        raise ValueError("positive device event spans required")
    equal_clocks = reference_clock["driver_reported_mhz"] == candidate_clock["driver_reported_mhz"]
    within = 100 * current <= 115 * control
    return {"candidate_over_reference": current / control, "at_most_15_percent_slower": within,
            "equal_driver_reported_clocks": equal_clocks, "retention_gate_pass": equal_clocks and within,
            "requested_runs_per_arm": 1}
