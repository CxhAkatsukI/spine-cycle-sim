"""Portable raw-source, watchdog and generated-RTL admission checks."""

import json
from pathlib import Path
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..adapter_axi.analysis import parse_trace
from ..adapter_axi.study import BENCH, RTL_PREFIX, require_execution


def sources(run: Path, manifest: dict, external_names=()) -> dict[str, Path]:
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    if len(pins) != len(manifest["pins"]):
        raise ValueError("duplicate frozen input")
    copies = {}
    for pin in manifest["source_copies"]:
        relative = Path(pin["archive_path"])
        path = run / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or sha256_file(path) != pin["sha256"] or pin["path"] in copies
                or pins.get(pin["path"]) != {key: value for key, value in pin.items() if key != "archive_path"}):
            raise ValueError("frozen source differs")
        copies[pin["path"]] = path
    if set(copies) != {name for name in pins if Path(name).name not in external_names}:
        raise ValueError("incomplete frozen source set")
    return copies


def bounded(path: Path, command: list[str], cwd: str, timeout: int, budget: int) -> dict:
    record = json.loads(path.read_text())
    if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
            or record["cleanup_snapshot_error"] is not None
            or record["command"] != command or record["cwd"] != cwd
            or record["timeout_seconds"] != timeout or record["tree_memory_gib"] != budget
            or record["reserve_gib"] != 16 or record["minimum_available_bytes"] < 16 * 1024**3
            or record["peak_tree_rss_kib"] > budget * 1024**2):
        raise ValueError("bounded raw execution differs")
    return record


def rtl(run: Path, arm: str, xo_pin: dict, copies: dict[str, Path], tools: dict) -> list[dict]:
    directory = run / arm
    pins = json.loads((directory / "inputs.json").read_text())
    names = {}
    bench_key = next(name for name in copies if name.endswith("/" + BENCH))
    external = {xo_pin["path"]: copies.get(xo_pin["path"], run / "production/adapter.hw.xo"),
                bench_key: copies[bench_key]}
    external_seen = set()
    recorded_directory = None
    for pin in pins:
        recorded = Path(pin["path"])
        if pin["path"] in external:
            if pin["path"] in external_seen or sha256_file(external[pin["path"]]) != pin["sha256"]:
                raise ValueError("RTL external input differs")
            external_seen.add(pin["path"])
            continue
        path = directory / recorded.name
        if (recorded_directory not in (None, str(recorded.parent)) or path.is_symlink()
                or recorded.name in names or sha256_file(path) != pin["sha256"]):
            raise ValueError("executed RTL source differs")
        names[recorded.name] = path
        recorded_directory = str(recorded.parent)
    if external_seen != external.keys() or recorded_directory is None:
        raise ValueError("missing RTL external inputs")
    with zipfile.ZipFile(external[xo_pin["path"]]) as archive:
        generated = {Path(name).name: archive.read(name) for name in archive.namelist()
                     if name.startswith(RTL_PREFIX) and Path(name).suffix in (".v", ".vh")}
    if (not generated or names.keys() != generated.keys() | {Path(BENCH).name, "run.tcl"}
            or any(names[name].read_bytes() != data for name, data in generated.items())
            or names[Path(BENCH).name].read_bytes() != copies[bench_key].read_bytes()
            or names["run.tcl"].read_text() != "run all\nquit\n"):
        raise ValueError("executed RTL/testbench differs from complete production XO")
    commands = {
        "compile": [tools["xvlog"], "--sv", Path(BENCH).name] + sorted(name for name in generated if name.endswith(".v")),
        "elaborate": [tools["xelab"], "adapter_axi_tb", "-s", "adapter_axi"],
        "simulate": [tools["xsim"], "adapter_axi", "-tclbatch", "run.tcl"],
    }
    for step, command in commands.items():
        record = bounded(directory / f"{step}.resources.json", command, recorded_directory, 120, 4)
        require_execution(record)
    return parse_trace((directory / "simulate.stdout.txt").read_text())
