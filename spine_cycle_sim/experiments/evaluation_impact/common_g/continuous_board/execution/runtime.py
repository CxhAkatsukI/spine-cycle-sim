"""Freeze actual runtime/driver/device identities under the shared board lease."""

import json
import os
from pathlib import Path
import re
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

FORBIDDEN = ("XRT_INI_PATH", "XCL_EMULATION_MODE", "LD_PRELOAD", "LD_LIBRARY_PATH", "CONTINUOUS_G_EXPECT_BDF")


def require_clean_environment(host, cwd):
    if any(os.environ.get(name) for name in FORBIDDEN) or any(
            (directory / "xrt.ini").exists() for directory in (host.parent, cwd)):
        raise ValueError("uncontrolled XRT/loader configuration; no board programming")


def library_paths(output):
    if "not found" in output:
        raise ValueError("missing dynamic runtime dependency")
    paths = set()
    for line in output.splitlines():
        match = re.search(r"(?:=>\s+|^\s*)(/\S+)\s+\(", line)
        if match:
            paths.add(Path(match.group(1)).resolve(strict=True))
    if not any(path.name.startswith("libxilinxopencl.so") for path in paths):
        raise ValueError("Xilinx OpenCL runtime is not resolved")
    return sorted(paths)


def device_identity(render):
    sysfs = Path("/sys/class/drm") / render.name / "device"
    device = sysfs.resolve(strict=True)
    bdf = device.name
    if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", bdf) or \
            (device / "driver").resolve(strict=True).name != "xocl":
        raise ValueError("leased render node is not a known XRT PCIe device")
    return {"render": str(render), "sysfs": str(device), "bdf": bdf,
            "driver_version": Path("/sys/module/xocl/version").read_text().strip(),
            "driver_srcversion": Path("/sys/module/xocl/srcversion").read_text().strip(),
            "kernel_release": os.uname().release}


def platform(document, bdf):
    devices = document.get("devices", [])
    if len(devices) != 1 or devices[0].get("device_id") != bdf or devices[0].get("device_status") != "HEALTHY":
        raise ValueError("leased FPGA is not healthy or platform identity differs")
    rows = devices[0].get("platforms", [])
    if len(rows) != 1 or "u55c" not in rows[0].get("static_region", {}).get("vbnv", "") or \
            rows[0].get("status", {}).get("mig_calibrated") != "true":
        raise ValueError("calibrated U55C platform required")
    return {key: rows[0][key] for key in ("static_region", "controller", "status")}


def capture(host, render, output, xrt=Path("/opt/xilinx/xrt")):
    output.mkdir()
    device = device_identity(render)
    ldd = subprocess.run(["ldd", str(host)], capture_output=True, text=True, check=True, timeout=15)
    (output / "ldd.stdout.txt").write_text(ldd.stdout)
    (output / "ldd.stderr.txt").write_text(ldd.stderr)
    if ldd.stderr.strip():
        raise ValueError("unexpected loader diagnostic")
    libraries = library_paths(ldd.stdout)
    # XRT loads the PCIe core dynamically, beyond the ELF dependency list.
    libraries.append((xrt / "lib/libxrt_core.so.2").resolve(strict=True))
    executable = (xrt / "bin/xbutil").resolve(strict=True)
    json_path = output / "platform.json"
    result = subprocess.run([str(executable), "examine", "--device", device["bdf"], "--report", "platform",
                             "--format", "JSON", "--output", str(json_path)],
                            capture_output=True, text=True, timeout=30)
    (output / "platform.stdout.txt").write_text(result.stdout)
    (output / "platform.stderr.txt").write_text(result.stderr)
    if result.returncode:
        raise ValueError("XRT platform query failed; retain raw diagnostic")
    document = json.loads(json_path.read_text())
    captured = {"device": device, "platform": platform(document, device["bdf"]),
                "pins": [identity(path) for path in sorted({*libraries, executable, Path(__file__)})]}
    atomic_write_json(output / "identity.json", captured)
    return captured


def unchanged(captured, render):
    if captured["device"] != device_identity(render) or any(identity(Path(pin["path"])) != pin
                                                            for pin in captured["pins"]):
        raise ValueError("runtime, driver or leased device identity changed")
