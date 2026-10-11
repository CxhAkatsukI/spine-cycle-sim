"""Seal helper-only RTL observations without changing any simulation profile."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .execution import identity
from .segment_schedule import BENCH, FILES, parse_trace, validate_inputs


def package_probe(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "schedule.json").exists() or (output / "raw_schedule.tar.gz").exists():
        raise FileExistsError("segment RTL evidence is frozen")
    run = data / "final"
    saved = json.loads((run / "summary.json").read_text())
    arms, files = {}, {"final/summary.json": run / "summary.json"}
    for arm in ("original", "candidate"):
        directory = run / arm
        validate_inputs(directory, arm)
        inputs = json.loads((directory / "inputs.json").read_text())
        names = {BENCH, "run.tcl", *(FILES[k] for k in ("parent", "helper", "flow"))}
        if inputs["arm"] != arm or {Path(p["path"]).name for p in inputs["sources"]} != names:
            raise ValueError("RTL input inventory differs")
        for pin in inputs["sources"]:
            if sha256_file(directory / Path(pin["path"]).name) != pin["sha256"]:
                raise ValueError("copied RTL input differs from its manifest")
        records = {}
        for step in ("compile", "elaborate", "simulate"):
            records[step] = json.loads((directory / f"{step}.resources.json").read_text())
            if records[step]["exit_code"] or records[step]["timed_out"]:
                raise ValueError("RTL process failed")
            for extension in ("resources.json", "stdout.txt", "stderr.txt"):
                name = f"{step}.{extension}"
                files[f"final/{arm}/{name}"] = directory / name
        for name in (BENCH, "run.tcl", "inputs.json", *(FILES[k] for k in ("parent", "helper", "flow"))):
            files[f"final/{arm}/{name}"] = directory / name
        rows = parse_trace((directory / "simulate.stdout.txt").read_text())
        if rows != saved["arms"][arm] or saved["status"] != "SEGMENT_RTL_PASS":
            raise ValueError("saved RTL report differs")
        arms[arm] = {"trials": rows, "verification": records}
    if arms["original"]["trials"] != arms["candidate"]["trials"]:
        raise ValueError("old/new schedule differs")
    # Keep failed testbench development separate from the final admitted trace.
    for path in data.glob("attempt*/*/*"):
        if path.is_file() and path.suffix in (".json", ".txt", ".sv", ".tcl"):
            files["exploratory/" + str(path.relative_to(data))] = path
    owner = "spine_cycle_sim/experiments/sharded_k4_stages"
    for name in ("segment_schedule.py", "segment_schedule_delivery.py"):
        files["source/" + name] = root / owner / name
    files["tests/test_sharded_k4_segment_schedule.py"] = root / "tests/test_sharded_k4_segment_schedule.py"
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive = output / "raw_schedule.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("evidence changed during packaging")
    dependency = identity(output.parent / "empty_row_rtl/rtl_raw_index.json")
    atomic_write_json(output / "schedule_raw_index.json", {"archive": identity(archive), "files": index,
                                                          "dependencies": [dependency]})
    report = {"status": "OCCUPIED_SEGMENT_ROUTED_RTL_COMPONENT_PASS", "arms": arms,
              "hardware_timing_admitted": False, "original_A4_match_admitted": False,
              "timing_fit_performed": False, "simulator_profile_changed": False,
              "claim": "73-clock empty exit must not be added after every occupied row",
              "limits": ["isolated generated helper, not parent adapter or full kernel",
                         "synthetic internal memory response timing, not AXI/HBM timing",
                         "does not establish real transport credits or physical address mapping",
                         "no change to the frozen v4 real-graph campaign"]}
    atomic_write_json(output / "schedule.json", report)
    return report
