"""Run a bounded full-top RTL test from two immutable production XOs."""

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..execution import identity
from ..link_runtime import run_link
from ..routing import adapter_interface
from .analysis import parse_trace, TRIALS


BENCH = "cpp/tests/routed_regraph/adapter_axi_tb.sv"
RTL_PREFIX = "ip_repo/xilinx_com_hls_pma_to_regraph_adapter_1_0/hdl/verilog/"
COMMON_FLAGS = ("WEIGHTED_PMA", "SHARDED_PMA", "SHARE_ALL_MEMORY_PORTS",
                "ROW_PREFETCH", "STOP_AFTER_LAST")


def extract_rtl(xo: Path, directory: Path) -> list[Path]:
    with zipfile.ZipFile(xo) as archive:
        names = [name for name in archive.namelist() if name.startswith(RTL_PREFIX)
                 and PurePosixPath(name).suffix in (".v", ".vh")]
        if (not names or len(set(names)) != len(names)
                or any(str(PurePosixPath(name).parent) != RTL_PREFIX.rstrip("/") for name in names)):
            raise ValueError("missing or unsafe flat adapter RTL in production XO")
        paths = []
        for name in sorted(names):
            path = directory / PurePosixPath(name).name
            with path.open("xb") as stream:
                stream.write(archive.read(name))
            paths.append(path)
    if not any(path.name == "pma_to_regraph_adapter.v" for path in paths):
        raise ValueError("complete adapter top RTL required")
    return paths


def require_execution(record: dict) -> None:
    if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
            or record["cleanup_snapshot_error"] is not None
            or record["minimum_available_bytes"] < 16 * 1024**3
            or record["peak_tree_rss_kib"] > 4 * 1024**2
            or record["tree_memory_gib"] != 4 or record["reserve_gib"] != 16
            or record["timeout_seconds"] != 120):
        raise ValueError("RTL execution failed its resource gate")


def require_route_reference(previous: dict, route: dict) -> None:
    if (route["command"].count(previous["path"]) != 1 or previous not in route["pins"]
            or route["clock_mhz"] != 150):
        raise ValueError("previous XO must be exactly pinned by the production route command")


def run_study(root: Path, previous: Path, candidate: Path, route_manifest: Path,
              output: Path, vivado_bin: Path) -> dict:
    require_route_reference(identity(previous), json.loads(route_manifest.read_text()))
    interface, flags = adapter_interface(previous)
    candidate_interface, candidate_flags = adapter_interface(candidate)
    for skip, observed in (("0", flags), ("1", candidate_flags)):
        if (any(observed.get("GRASU_REGRAPH_" + flag) != "1" for flag in COMMON_FLAGS)
                or observed.get("GRASU_REGRAPH_SKIP_EMPTY_SEGMENT", "0") != skip
                or "GRASU_REGRAPH_COSIM_DEPTH" in observed):
            raise ValueError("production combined/skip-empty XO pair required")
    if interface != candidate_interface:
        raise ValueError("production adapter ABI differs")
    output.mkdir(parents=True, exist_ok=False)
    inputs = [root / BENCH, previous, candidate, route_manifest]
    inputs += sorted(Path(__file__).parent.glob("*.py"))
    inputs += [root / "spine_cycle_sim/experiments/sharded_k4_stages" / name
               for name in ("execution.py", "link_runtime.py", "process_cleanup.py", "routing.py")]
    inputs += [root / "spine_cycle_sim/experiments" / name
               for name in ("campaign_runtime.py", "upstream_controls/execution.py")]
    inputs += [vivado_bin / name for name in ("xvlog", "xelab", "xsim")]
    pins = [identity(path) for path in inputs]
    snapshots = output / "sources"
    snapshots.mkdir()
    source_copies = []
    for index, path in enumerate(inputs):
        if path.suffix not in (".py", ".sv", ".xo", ".json"):
            continue
        relative = path.relative_to(root) if path.is_relative_to(root) else Path(f"inputs/{index:02d}_{path.name}")
        target = snapshots / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source_copies.append({**identity(path), "archive_path": str(target.relative_to(output))})
    atomic_write_json(output / "manifest.json", {
        "schema": 1, "claim": "full_production_adapter_RTL_with_synthetic_memory_not_FPGA",
        "trials": TRIALS, "pins": pins, "source_copies": source_copies,
        "xos": {"previous": identity(previous), "candidate": identity(candidate)},
        "previous_route_manifest": identity(route_manifest),
        "interface": interface, "flags": {"previous": flags, "candidate": candidate_flags},
        "clock_period_ns": 10, "cycle_counts_not_frequency_scaled": True,
        "memory": "ordered_AR_to_first_RVALID_latency_plus_one_clock_no_refresh_or_bank_timing",
        "reset_between_trials": True,
    })
    arms = {}
    for arm, xo in (("previous", previous), ("candidate", candidate)):
        directory = output / arm
        directory.mkdir()
        rtl = extract_rtl(xo, directory)
        shutil.copy2(root / BENCH, directory / Path(BENCH).name)
        (directory / "run.tcl").write_text("run all\nquit\n")
        frozen = [identity(path) for path in [*rtl, directory / Path(BENCH).name, directory / "run.tcl"]]
        atomic_write_json(directory / "inputs.json", frozen)
        commands = {
            "compile": [str(vivado_bin / "xvlog"), "--sv", Path(BENCH).name]
                       + [path.name for path in rtl if path.suffix == ".v"],
            "elaborate": [str(vivado_bin / "xelab"), "adapter_axi_tb", "-s", "adapter_axi"],
            "simulate": [str(vivado_bin / "xsim"), "adapter_axi", "-tclbatch", "run.tcl"],
        }
        for step, command in commands.items():
            if any(identity(Path(pin["path"])) != pin for pin in pins + frozen):
                raise ValueError("RTL input changed after freezing")
            record = run_link(command, directory, directory / step, timeout=120,
                              tree_memory_gib=4, reserve_gib=16, poll_seconds=0.5)
            require_execution(record)
        arms[arm] = parse_trace((directory / "simulate.stdout.txt").read_text())
        if any(identity(Path(pin["path"])) != pin for pin in pins + frozen):
            raise ValueError("RTL input changed during execution")
        print(arm, "ADAPTER_AXI_PASS", flush=True)
    report = {"status": "FULL_ADAPTER_AXI_RTL_PASS_NOT_BOARD", "arms": arms,
              "simulator_modified": False, "HLS_modified": False,
              "hardware_timing_admitted": False}
    atomic_write_json(output / "summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "previous", "candidate", "route-manifest", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        run_study(args.root.resolve(), args.previous.resolve(), args.candidate.resolve(),
                  args.route_manifest.resolve(), args.output.resolve(), args.vivado_bin.resolve())
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
