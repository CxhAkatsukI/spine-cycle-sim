"""Recheck a production compilation from immutable source and raw tool records."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..execution import identity
from .production import COMPILER, FLAGS, PLATFORM, require_report, require_xo


def require_execution(record: dict, *, budget: int, timeout: int) -> None:
    if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
            or record["cleanup_snapshot_error"] is not None
            or record["tree_memory_gib"] != budget or record["reserve_gib"] != 16
            or record["timeout_seconds"] != timeout
            or record["peak_tree_rss_kib"] > budget * 1024**2
            or record["minimum_available_bytes"] < 16 * 1024**3):
        raise ValueError("production execution failed its resource/cleanup gate")


def recheck(run: Path, *, current_inputs: bool = False) -> dict:
    report = json.loads((run / "results.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if (report["status"] != "production_XO_ABI_pass_not_routed"
            or report["hardware_timing_admitted"] is not False
            or report["simulator_modified"] is not False
            or manifest["flags"] != FLAGS or manifest["clock_mhz"] != 150
            or manifest["part"] != "xcu55c-fsvh2892-2L-e"):
        raise ValueError("production admission differs")
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    if len(pins) != len(manifest["pins"]):
        raise ValueError("duplicate production input")
    snapshots = {}
    for pin in manifest["snapshots"]:
        relative = Path(pin["archive_path"])
        path = run / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or pins.get(pin["path"]) != {key: value for key, value in pin.items() if key != "archive_path"}
                or sha256_file(path) != pin["sha256"] or pin["path"] in snapshots):
            raise ValueError("production source snapshot differs")
        snapshots[pin["path"]] = path
    if set(pins) - {str(COMPILER), str(PLATFORM)} != snapshots.keys():
        raise ValueError("incomplete production source snapshots")
    if current_inputs and any(identity(Path(pin["path"])) != pin for pin in pins.values()):
        raise ValueError("production input changed since compilation")
    execution = json.loads((run / "compile.resources.json").read_text())
    require_execution(execution, budget=8, timeout=1200)
    if (not same_typed(execution, report["execution"])
            or execution["command"] != manifest["command"] or execution["cwd"] != str(run)):
        raise ValueError("production raw command differs")
    command = manifest["command"]
    expected = [str(COMPILER), "--target", "hw", "--compile", "--kernel_frequency", "150",
                "--kernel", "pma_to_regraph_adapter", "--platform", str(PLATFORM), "--save-temps",
                "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in FLAGS.items()],
                "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
                "--temp_dir", str(run / "build"), "--report_dir", str(run / "reports"),
                "--log_dir", str(run / "logs"), "-o", str(run / "adapter.hw.xo")]
    if (command[:-1] != expected or command[-1] not in snapshots
            or not command[-1].endswith("/kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp")):
        raise ValueError("production compile contract differs")
    watchdog = json.loads(run.with_name(run.name + "_watchdog.resources.json").read_text())
    require_execution(watchdog, budget=10, timeout=1350)
    if (watchdog["command"][1:4] != ["-m", __package__ + ".production", "--worker"]
            or watchdog["command"][-2:] != ["--output", str(run)]):
        raise ValueError("production outer execution differs")
    reference = manifest["reference_xo"]
    if pins.get(reference["path"]) != reference:
        raise ValueError("reference XO is not frozen")
    if (identity(run / "adapter.hw.xo") != report["xo"]
            or not same_typed(require_xo(run / "adapter.hw.xo", snapshots[reference["path"]]), report["xo_contract"])
            or not same_typed(require_report(run), report["analysis"])):
        raise ValueError("production XO or synthesis report differs")
    functional = json.loads((run / "functional_gate/verification.json").read_text())
    if (identity(run / "functional_gate/verification.json") != manifest["functional_gate"]
            or functional["status"] != "twelve_CXX_configs_passed_not_RTL_or_board"
            or sha256_file(run / "functional_gate/raw_functional.tar.gz") != functional["archive"]["sha256"]):
        raise ValueError("production functional prerequisite differs")
    return {"report": report, "manifest": manifest, "watchdog": watchdog}
