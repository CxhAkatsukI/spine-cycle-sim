"""Record the resident image and driver-reported clocks outside the timing window."""

import json
from pathlib import Path
import re
import subprocess
import uuid

from .runtime import identity, save


def image(binary, output, name):
    tool = Path("/opt/xilinx/xrt/bin/xclbinutil").resolve(strict=True)
    raw = output / f"{name}.xclbin-info.txt"
    result = subprocess.run([str(tool), "--info", "--input", str(binary)],
                            capture_output=True, text=True, timeout=30)
    raw.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("cannot establish the expected bitstream UUID; raw diagnostic retained")
    return {"uuid": image_uuid(result.stdout), "binary": identity(binary),
            "info": identity(raw), "tool": identity(tool)}


def image_uuid(text):
    matches = re.findall(r"UUID \(xclbin\):\s+([0-9a-fA-F-]+)", text)
    if len(matches) != 1:
        raise ValueError("one bitstream UUID required in xclbinutil output")
    return str(uuid.UUID(matches[0]))


def validate(record, expected):
    frequencies = record.get("driver_reported_mhz", [])
    if (record.get("uuid") != expected["uuid"]
            or record.get("binary") != expected["binary"]
            or not 3 <= len(frequencies) <= 4
            or any(type(value) is not int or value < 0 for value in frequencies)
            or any(value <= 0 for value in frequencies[:3])):
        raise ValueError("resident image or clock evidence is missing or inconsistent")


def capture(bdf, expected, output, name, *, device_root=Path("/sys/bus/pci/devices")):
    device = device_root / bdf
    paths = list(device.glob("icap.*/clock_freqs"))
    if len(paths) != 1:
        raise ValueError("one driver clock source required for the leased device")
    raw = {"uuid": (device / "xclbinuuid").read_text(), "clock_freqs": paths[0].read_text()}
    raw_path = output / f"{name}.clock-raw.json"
    save(raw_path, raw)
    record = {"uuid": str(uuid.UUID(raw["uuid"].strip())), "binary": expected["binary"],
              "driver_reported_mhz": [int(value) for value in raw["clock_freqs"].split()],
              "bdf": bdf, "sysfs_clock_source": str(paths[0]), "raw": identity(raw_path),
              "boundary": "queried after host exit, under the same exclusive board lease; not timed"}
    validate(record, expected)
    path = output / f"{name}.clock.json"
    save(path, record)
    return {"record": identity(path), "expected": expected}


def replay(evidence, raw_root=None):
    def checked(pin):
        original = Path(pin["path"])
        path = Path(raw_root) / original.parent.name / original.name if raw_root else original
        actual = identity(path)
        if any(actual[key] != pin[key] for key in ("bytes", "sha256")):
            raise ValueError("clock or image identity changed")
        return path

    if image_uuid(checked(evidence["expected"]["info"]).read_text()) != evidence["expected"]["uuid"]:
        raise ValueError("expected image UUID differs from pinned xclbinutil output")
    record = json.loads(checked(evidence["record"]).read_text())
    raw = json.loads(checked(record["raw"]).read_text())
    if (str(uuid.UUID(raw["uuid"].strip())) != record["uuid"]
            or [int(value) for value in raw["clock_freqs"].split()] != record["driver_reported_mhz"]):
        raise ValueError("parsed clock evidence differs from raw driver output")
    validate(record, evidence["expected"])
    return record
