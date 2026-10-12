"""Read frozen sources and complete handshakes, not the original run paths."""

import json
from pathlib import Path
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...adapter_axi.study import BENCH, RTL_PREFIX
from ..evidence import sources, bounded
from ..validation import require_xos
from .analysis import analyze, helper_instance, require_replay
from .study import BASE_SHA, MONITOR, XO_HASHES


def recheck(run):
    manifest = json.loads((run / "manifest.json").read_text())
    copies = sources(run, manifest, ("xvlog", "xelab", "xsim"))
    base = copies[manifest["base"]["path"]]
    if sha256_file(base) != BASE_SHA:
        raise ValueError("frozen RTL baseline differs")
    xos = {arm: copies[pin["path"]] for arm, pin in manifest["xos"].items()}
    if set(xos) != set(XO_HASHES) or any(sha256_file(path) != XO_HASHES[arm] for arm, path in xos.items()):
        raise ValueError("production XO identities differ")
    require_xos(xos["reference"], xos["candidate"])
    original = json.loads(base.read_text())
    report = {}
    for arm, xo in xos.items():
        directory = run / arm
        with zipfile.ZipFile(xo) as bundle:
            expected = {Path(name).name: bundle.read(name) for name in bundle.namelist()
                        if name.startswith(RTL_PREFIX) and Path(name).suffix in (".v", ".vh")}
        for name in (BENCH, MONITOR):
            key = next(key for key in copies if key.endswith("/" + name))
            expected[Path(name).name] = copies[key].read_bytes()
        expected["run.tcl"] = b"run all\nquit\n"
        pins = json.loads((directory / "inputs.json").read_text())
        if (len(pins) != len(expected) or {Path(pin["path"]).name for pin in pins} != expected.keys()
                or len({str(Path(pin["path"]).parent) for pin in pins}) != 1):
            raise ValueError("incomplete executed RTL/source set")
        recorded = str(Path(pins[0]["path"]).parent)
        for pin in pins:
            path = directory / Path(pin["path"]).name
            if (path.is_symlink() or path.read_bytes() != expected[path.name]
                    or sha256_file(path) != pin["sha256"]):
                raise ValueError("executed RTL or observer changed")
        helper = helper_instance(expected["pma_to_regraph_adapter.v"].decode())
        tools = manifest["tools"]
        commands = {
            "compile": [tools["xvlog"], "--sv", "-d", "ADAPTER_HELPER=" + helper,
                        Path(BENCH).name, Path(MONITOR).name]
                       + sorted(name for name in expected if name.endswith(".v")),
            "elaborate": [tools["xelab"], "adapter_axi_tb", "occupied_row_monitor", "-s", "observed_adapter"],
            "simulate": [tools["xsim"], "observed_adapter", "-tclbatch", "run.tcl"],
        }
        if json.loads((directory / "commands.json").read_text()) != commands:
            raise ValueError("observed RTL commands differ")
        for step, command in commands.items():
            bounded(directory / f"{step}.resources.json", command, recorded, 120, 4)
        cases, report[arm] = analyze((directory / "simulate.stdout.txt").read_text())
        require_replay(cases, original["arms"][arm])
    expected_result = {"status": "OCCUPIED_ROW_RTL_REPLAY_PASS_NOT_BOARD", "arms": report,
                       "production_HLS_and_simulator_unchanged": True, "FPGA_timing_admitted": False,
                       "exclusive_stall_attribution": False}
    if json.loads((run / "results.json").read_text()) != expected_result:
        raise ValueError("raw-observed result differs from delivered conclusion")
    return expected_result
