"""Bind historical paired reports to raw commands, source bytes and HLS flags."""

import json
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import analyze


def compile_contract(directory: Path, skip: int) -> None:
    project = ET.parse(directory / "project/hls.app").getroot()
    files = project.findall("files/file")
    expected = {"GRASU_REGRAPH_COSIM_DEPTH": "1", "GRASU_REGRAPH_SHARDED_PMA": "1",
                "GRASU_REGRAPH_SHARE_ALL_MEMORY_PORTS": "1", "GRASU_REGRAPH_ROW_PREFETCH": "1",
                "GRASU_REGRAPH_STOP_AFTER_LAST": "1", "GRASU_REGRAPH_WEIGHTED_PMA": "1",
                "GRASU_REGRAPH_SKIP_EMPTY_SEGMENT": str(skip)}
    if len(files) != 2 or [Path(item.attrib["name"]).name for item in files] != [
            "pma_to_regraph_adapter.cpp", "pma_adapter_cosim_tb.cpp"]:
        raise ValueError("DUT and reference project files differ")
    for item in files:
        definitions = [flag[2:].split("=", 1) for flag in shlex.split(item.attrib["cflags"])
                       if flag.startswith("-DGRASU_")]
        if len(definitions) != len(expected) or dict(definitions) != expected:
            raise ValueError("effective HLS compile flags differ")
    report = ET.parse(directory / "project/solution/syn/report/pma_to_regraph_adapter_csynth.xml").getroot()
    assigned = report.find("UserAssignments")
    if (assigned is None or assigned.findtext("Part") != "xcu55c-fsvh2892-2L-e"
            or abs(float(assigned.findtext("TargetClockPeriod")) - round(1000 / 150, 2)) > 1e-9):
        raise ValueError("HLS part or requested clock differs")


def recheck(run: Path) -> dict:
    report = json.loads((run / "results.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if (not same_typed(report["manifest"], manifest)
            or report["status"] != "passed_paired_C_RTL_not_board"
            or manifest["variants"] != {"combined": 0, "skip_empty": 1}
            or manifest["clock_mhz"] != 150 or manifest["row_prefetch"] != 1
            or manifest["stop_after_last"] != 1 or manifest["part"] != "xcu55c-fsvh2892-2L-e"
            or any(report[key] is not False for key in (
                "hardware_timing_admitted", "original_A4_match_admitted", "simulator_modified", "timing_fit_performed"))
            or list(report["runs"]) != ["combined", "skip_empty"]):
        raise ValueError("paired study admission differs")
    snapshots = {}
    for pin in manifest["source"]:
        relative = Path(pin["archive_path"])
        path = run / "sources" / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or sha256_file(path) != pin["sha256"]):
            raise ValueError("frozen execution source changed")
        snapshots[pin["path"]] = path
    for name, skip in manifest["variants"].items():
        directory = run / name
        saved = report["runs"][name]
        execution = json.loads((directory / "cosim.resources.json").read_text())
        command = execution["command"]
        expected_env = [f"PMA_COSIM_OUT={directory}", "PMA_COSIM_MODE=weighted",
                        "PMA_COSIM_PREFETCH=1", "PMA_COSIM_STOP=1", f"PMA_COSIM_SKIP_EMPTY={skip}"]
        if (not same_typed(execution, saved["execution"]) or execution["exit_code"]
                or execution["timed_out"] or execution["memory_limit_gib"] != 8
                or execution["reserve_gib"] != 16 or execution["cwd"] != str(directory)
                or len(command) != 9 or command[:6] != ["env", *expected_env]
                or command[6:] != ["/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls",
                                   "-f", next(path for path in snapshots if path.endswith("tests/pma_adapter_cosim.tcl"))]
                or not same_typed(analyze(directory), saved["analysis"])):
            raise ValueError("raw C/RTL execution or analysis differs")
        compile_contract(directory, skip)
    watchdog = json.loads(run.with_name(run.name + "_watchdog.resources.json").read_text())
    command = watchdog["command"]
    if (watchdog["exit_code"] or watchdog["stop_reason"] != "process_exit"
            or watchdog["cleanup_snapshot_error"] is not None or watchdog["tree_memory_gib"] != 8
            or watchdog["reserve_gib"] != 16 or watchdog["timeout_seconds"] != 2700
            or watchdog["peak_tree_rss_kib"] > 8 * 1024**2
            or watchdog["minimum_available_bytes"] < 16 * 1024**3
            or len(command) != 8 or command[1:4] != ["-m", __package__ + ".study", "--worker"]
            or command[4] != "--integration" or command[6:] != ["--output", str(run)]):
        raise ValueError("paired process-tree gate differs")
    return report
