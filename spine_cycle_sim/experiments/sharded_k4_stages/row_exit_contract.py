"""Artifact-pinned empty segment-loop latency, independent of FPGA time fitting."""

import json
from pathlib import Path
import re
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .execution import identity

EMPTY_EXIT_CYCLES = 73
RTL_HASHES = {
    "original": {
        "parent": "9973065e35c6eaafa47c0e31425b793c4b40425efe7a07d47040d5d4c717a792",
        "helper": "42b3b548bb1d2f4c13e15024f52efb03f36e29cd619fed6624c522ec76b0dcd1",
        "testbench": "d9f9bf2f1c48c45f26dbdd428ee5e45a2ed137eb3e19e1a9cca55cebfb9555c9",
    },
    "candidate": {
        "parent": "17d3b318163404c18c0ba548e2b0d8784fbf930472b15b0bad0eb4f172f78c8c",
        "helper": "a84a90152cac1d18511fe059416898d69a7761f2243e8887706827823cd61e3a",
        "testbench": "ce7d8921c1a3c7f2ce708604807168999df571d3af68c44f3651b75b106a36ee",
    },
}
FLOW_HASH = "9f6aa7446ff5854481d7932964355d76fab2a3e3d4af26243cf8f3fbb04bcf6a"
FILES = {
    "parent": "pma_to_regraph_adapter.v",
    "helper": "pma_to_regraph_adapter_pma_to_regraph_adapter_Pipeline_segment_loop.v",
    "flow": "pma_to_regraph_adapter_flow_control_loop_pipe_sequential_init.v",
    "testbench": "empty_segment_handshake_tb.sv",
}
TRIALS = [(0, 0), (16, 0), (4096, 0), (16, 20), (16, 100), (0, 0)]


def parse_trace(text: str) -> list[dict]:
    pattern = (r"^EMPTY_SEGMENT offset=(\d+) ready_delay=(\d+) start_cycle=(\d+) "
               r"exit_cycle=(\d+) done_cycle=(\d+) elapsed=(\d+)$")
    fields = ("offset", "ready_delay", "start", "exit", "done", "elapsed")
    rows = [dict(zip(fields, map(int, values))) for values in re.findall(pattern, text, re.M)]
    if (len(rows) != 6 or text.count("EMPTY_SEGMENT_PASS cases=6") != 1
            or re.search(r"\b(?:FATAL|ERROR|FAIL)\b", text)
            or [(r["offset"], r["ready_delay"]) for r in rows] != TRIALS):
        raise ValueError("complete six-case handshake-correct RTL test required")
    for index, row in enumerate(rows):
        if (row["exit"] - row["start"] != 1 or row["done"] - row["start"] != EMPTY_EXIT_CYCLES
                or row["elapsed"] != EMPTY_EXIT_CYCLES
                or (index and row["start"] <= rows[index - 1]["done"])):
            raise ValueError("empty exit latency or repeated invocation order differs")
    return rows


def package_rtl(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "raw_rtl.tar.gz").exists() or (output / "rtl.json").exists():
        raise FileExistsError("empty-row RTL evidence is frozen")
    files, arms = {}, {}
    for arm in ("original", "candidate"):
        directory = data if arm == "original" else data / arm
        for kind, name in FILES.items():
            path = directory / name
            expected = FLOW_HASH if kind == "flow" else RTL_HASHES[arm][kind]
            if sha256_file(path) != expected:
                raise ValueError(f"unmodified routed RTL/protocol required: {arm}/{name}")
            files[f"{arm}/{name}"] = path
        suffix = "_handshake" if arm == "original" else ""
        records = {}
        for step in ("compile", "elaborate", "simulate"):
            name = step + suffix
            records[step] = json.loads((directory / f"{name}.resources.json").read_text())
            if records[step]["exit_code"] or records[step]["timed_out"]:
                raise ValueError(f"RTL process gate failed: {arm}/{step}")
            for extension in ("resources.json", "stdout.txt", "stderr.txt"):
                files[f"{arm}/{step}.{extension}"] = directory / f"{name}.{extension}"
        files[f"{arm}/run.tcl"] = directory / "run.tcl"
        arms[arm] = {"trials": parse_trace((directory / f"simulate{suffix}.stdout.txt").read_text()),
                     "verification": records}
    for name in ("empty_segment_tb.sv", "compile", "elaborate", "simulate"):
        paths = [data / name] if name.endswith(".sv") else [data / f"{name}.{ext}" for ext in
                                                          ("resources.json", "stdout.txt", "stderr.txt")]
        for path in paths:
            files[f"rejected_start_held_until_done/{path.name}"] = path
    files["source/row_exit_contract.py"] = Path(__file__)
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive = output / "raw_rtl.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in index):
        raise ValueError("RTL evidence changed during packaging")
    profile = json.loads((root / "configs/architectures/grasu_regraph_routed_sssp_compute_v3.json").read_text())
    report = {"status": "EMPTY_ROW_ROUTED_RTL_COMPONENT_PASS", "cycles": EMPTY_EXIT_CYCLES,
              "timing_fit_performed": False, "hardware_timing_admitted": False,
              "original_A4_match_admitted": False, "target_artifacts": profile["target"],
              "rtl_sha256": RTL_HASHES, "arms": arms,
              "excluded": "initial start-held-until-done test has an invalid handshake; its PASS is rejected"}
    atomic_write_json(output / "rtl_raw_index.json", {"archive": identity(archive), "files": index})
    atomic_write_json(output / "rtl.json", report)
    return report
