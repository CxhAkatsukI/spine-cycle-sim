"""Probe occupied/empty calls of the pinned routed adapter helper, not HBM."""

from pathlib import Path
import re
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity
from .row_exit_contract import FILES, FLOW_HASH, RTL_HASHES


BENCH = "occupied_segment_handshake_tb.sv"
BENCH_SHA = "39599c1909c5ab107c6b5e3a1c41c55f881dd729897a5baf78734200864c60ff"
# offset, segments, internal response latency, initial sink stall, elapsed
TRIALS = [(0, 0, 1, 0, 73), (0, 1, 1, 0, 75), (0, 2, 1, 0, 77),
          (0, 8, 1, 0, 89), (0, 1, 64, 0, 75), (0, 8, 64, 0, 89),
          (0, 1, 100, 0, 105), (0, 8, 100, 0, 119), (0, 8, 1, 150, 165),
          (3, 8, 64, 150, 165), (3, 64, 64, 0, 201), (0, 0, 1, 100, 73)]


def parse_trace(text: str) -> list[dict]:
    fields = ("offset", "count", "latency", "ready_delay", "start", "exit",
              "first_packet", "last_packet", "done", "elapsed")
    pattern = "^SEGMENT " + " ".join(f"{key}=(-?\\d+)" for key in fields) + "$"
    rows = [dict(zip(fields, map(int, values))) for values in re.findall(pattern, text, re.M)]
    observed = [(r["offset"], r["count"], r["latency"], r["ready_delay"], r["elapsed"]) for r in rows]
    if (observed != TRIALS or text.count("SEGMENT_PASS cases=12") != 1
            or len(re.findall(r"^SEGMENT ", text, re.M)) != len(TRIALS)
            or re.search(r"\b(?:fatal|error|fail)\b", text, re.I)):
        raise ValueError("complete pinned twelve-case segment trace required")
    for index, row in enumerate(rows):
        if (row["done"] - row["start"] != row["elapsed"]
                or row["exit"] - row["start"] != 2 * row["count"] + 1
                or (index and row["start"] <= rows[index - 1]["done"])):
            raise ValueError("invalid segment completion or restart order")
        if row["count"]:
            if (row["first_packet"] <= row["start"] or row["last_packet"] != row["done"]
                    or row["last_packet"] - row["first_packet"] != 2 * row["count"] - 1):
                raise ValueError("occupied output/completion timeline differs")
        elif (row["first_packet"], row["last_packet"]) != (-1, -1):
            raise ValueError("empty helper emitted a packet")
    return rows


def validate_inputs(directory: Path, arm: str) -> None:
    expected = {FILES[key]: RTL_HASHES[arm][key] for key in ("parent", "helper")}
    expected.update({FILES["flow"]: FLOW_HASH, BENCH: BENCH_SHA})
    for name, checksum in expected.items():
        if sha256_file(directory / name) != checksum:
            raise ValueError(f"routed source or handshake test changed: {arm}/{name}")
    if (directory / "run.tcl").read_text().strip() != "run all\nquit":
        raise ValueError("RTL probe must run to completion")


def run_probe(root: Path, sources: Path, output: Path, vivado_bin: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    arms = {}
    for arm in ("original", "candidate"):
        directory = output / arm
        directory.mkdir()
        inputs = [root / "cpp/tests/routed_regraph" / BENCH]
        inputs += [sources / arm / FILES[key] for key in ("parent", "helper", "flow")]
        inputs.append(sources / arm / "run.tcl")
        pins = [identity(path) for path in inputs]
        for path in inputs:
            shutil.copy2(path, directory / path.name)
        validate_inputs(directory, arm)
        atomic_write_json(directory / "inputs.json", {"arm": arm, "sources": pins})
        commands = {
            "compile": [str(vivado_bin / "xvlog"), "--sv"]
                       + (["--define", "OPTIMIZED"] if arm == "candidate" else [])
                       + [BENCH, FILES["helper"], FILES["flow"]],
            "elaborate": [str(vivado_bin / "xelab"), "occupied_segment_handshake_tb", "-s", "occupied_segment"],
            "simulate": [str(vivado_bin / "xsim"), "occupied_segment", "-tclbatch", "run.tcl"],
        }
        for step, command in commands.items():
            record = run_bounded(command, directory, directory / step,
                                 timeout=120, memory_gib=4, reserve_gib=16)
            if record["exit_code"] or record["timed_out"]:
                raise RuntimeError(f"segment RTL {arm}/{step} failed; output retained")
        validate_inputs(directory, arm)
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("RTL source changed during execution")
        arms[arm] = parse_trace((directory / "simulate.stdout.txt").read_text())
        print(arm, "SEGMENT_RTL_PASS", flush=True)
    if arms["original"] != arms["candidate"]:
        raise ValueError("old/new helper schedules differ")
    report = {"status": "SEGMENT_RTL_PASS", "arms": arms}
    atomic_write_json(output / "summary.json", report)
    return report
