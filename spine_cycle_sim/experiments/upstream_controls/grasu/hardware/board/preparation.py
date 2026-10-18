"""Replay the author-host captures before exporting bounded standalone inputs."""

import json
from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..configuration import REVISION
from ...host.analysis import CAPTURES, STATUS, analyze
from ...host.fixtures import NAMES

BASELINE_SHA256 = "b548229594e31b4d78eefa2ec79502a97134fad35a274504c9089cadadd06048"
PACKET_CAPTURES = ("row_offsets.u64le", "binary.u64le", "prepared.u64le", "mapped_updates.u64le", "updated.u64le")


def regular(path, maximum):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("bounded regular original G input required: " + str(path))
    return identity(path)


def export(directory: Path, facts: dict, destination: Path):
    n, segments, count = (facts[key] for key in ("vertices", "segments", "updates"))
    if not (type(n) is int and 0 < n <= 262208 and type(segments) is int and
            0 <= segments <= 524416 and type(count) is int and 0 <= count <= 524416):
        raise ValueError("original G packet dimensions")
    lengths = (n + 1, segments, 16 * segments, count, 16 * segments)
    pins = []
    for name, length in zip(PACKET_CAPTURES, lengths):
        item = regular(directory / name, 64 * 1024**2)
        if (directory / name).stat().st_size != 8 * length:
            raise ValueError("original G packet capture extent: " + name)
        pins.append(item)
    with destination.open("xb") as output:
        output.write(struct.pack("<IIIII", 0x3142474f, 1, n, segments, count))
        for name in PACKET_CAPTURES:
            with (directory / name).open("rb") as source:
                shutil.copyfileobj(source, output, length=1024**2)
    if destination.stat().st_size != 20 + 8 * (n + 1 + 33 * segments + count):
        raise ValueError("original G packet total extent")
    return pins


def prepare(baseline: Path, output: Path):
    report_path = baseline / "report.json"
    pins = [regular(report_path, 16 * 1024**2)]
    if pins[0]["sha256"] != BASELINE_SHA256:
        raise ValueError("unreviewed original G author-host baseline")
    baseline_report = json.loads(report_path.read_text())
    cases = baseline_report["cases"]
    if (baseline_report["status"] != STATUS or baseline_report["author_source"]["revision"] != REVISION or
            [item["id"] for item in cases] != list(NAMES)):
        raise ValueError("original G author-host baseline scope")
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in cases:
        name = case["id"]
        input_path = baseline / "inputs" / (name + ".txt")
        pins.append(regular(input_path, 64 * 1024**2))
        if case["status"] != STATUS or len(case["runs"]) != 3:
            raise ValueError("original G baseline case incomplete: " + name)
        observed = []
        for suffix, stored in zip(("first", "repeat", "ubsan"), case["runs"]):
            directory = baseline / "captures" / name / suffix
            stdout, stderr = (baseline / f"{name}_{suffix}.{kind}.txt" for kind in ("stdout", "stderr"))
            pins += [regular(directory / capture, 64 * 1024**2) for capture in CAPTURES]
            pins += [regular(path, 64 * 1024**2) for path in (stdout, stderr)]
            facts = analyze(input_path, directory, stdout, stderr)
            if facts != stored["analysis"] or (observed and facts != observed[0]):
                raise ValueError("original G baseline replay differs: " + name)
            observed.append(facts)
        destination = output / (name + ".ogb")
        export(baseline / "captures" / name / "first", observed[0], destination)
        rows.append({"id": name, "packet": identity(destination), "facts": observed[0],
                     "expected_slots_including_guards": observed[0]["checked_device_slots"] + 128})
    for item in pins:
        if identity(Path(item["path"])) != item:
            raise ValueError("original G baseline changed during replay")
    manifest = {"status": "ORIGINAL_G_CAPTURE_REPLAY_PASS_NOT_BOARD", "baseline": str(baseline),
                "baseline_sha256": sha256_file(report_path), "pins": pins, "cases": rows}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
