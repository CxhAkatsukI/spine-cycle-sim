"""Compile one production empty-helper XO after its frozen C++/RTL gates."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..execution import identity
from ..link_runtime import run_link
from ..routing import adapter_interface
from ..synthesis import read_report
from .functional import deliver as deliver_functional
from .delivery import raw_files as paired_files
from .validation import recheck

FLAGS = {"GRASU_REGRAPH_" + name: "1" for name in (
    "WEIGHTED_PMA", "SHARDED_PMA", "SHARE_ALL_MEMORY_PORTS", "ROW_PREFETCH",
    "STOP_AFTER_LAST", "SKIP_EMPTY_SEGMENT")}
COMPILER = Path("/data/yxx/tools/xilinx/Vitis/2024.1/bin/v++")
PLATFORM = Path("/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/"
                "xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm")


def require_xo(candidate: Path, reference: Path) -> dict:
    interface, flags = adapter_interface(candidate)
    baseline, _ = adapter_interface(reference)
    effective = {key: value for key, value in flags.items() if key.startswith("GRASU_")}
    if interface != baseline:
        raise ValueError("production adapter ABI differs from frozen K4")
    if effective != FLAGS:
        raise ValueError("production flags differ, or a test-only flag is present")
    return {"interface": interface, "flags": flags}


def require_report(directory: Path) -> dict:
    analysis = read_report(directory)
    xml = ET.parse(analysis["report"]["path"]).getroot()
    assigned = xml.find("UserAssignments")
    if (assigned is None or assigned.findtext("Part") != "xcu55c-fsvh2892-2L-e"
            or abs(float(assigned.findtext("TargetClockPeriod")) - 6.67) > 1e-9):
        raise ValueError("production HLS part or requested clock differs")
    return analysis


def compile_xo(integration: Path, paired: Path, functional: Path,
               reference: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("fresh production-XO output required")
    rtl = recheck(paired)
    cxx = json.loads((functional / "manifest.json").read_text())
    gate_sources = [pin for pin in rtl["manifest"]["source"]
                    if pin["archive_path"].startswith("integration/")]
    gate_sources += [pin for pin in cxx["source"] if not pin["archive_path"].startswith("runner/")]
    for pin in gate_sources:
        if identity(Path(pin["path"]))["sha256"] != pin["sha256"]:
            raise ValueError("current HLS/test source differs from a prerequisite gate")
        if Path(pin["path"]).resolve() != integration / Path(pin["archive_path"].removeprefix("integration/")):
            raise ValueError("prerequisite gate belongs to another integration checkout")
    output.mkdir(parents=True)
    watchdog = json.loads(functional.with_name(functional.name + "_watchdog.resources.json").read_text())
    deliver_functional(functional, watchdog, output / "functional_gate")
    root = Path(__file__).resolve().parents[4]
    paths = [Path(pin["path"]) for pin in gate_sources]
    paths += [paired / "manifest.json", paired / "results.json", functional / "manifest.json",
              functional / "execution.resources.json", reference, COMPILER, PLATFORM]
    paths += [root / "spine_cycle_sim/experiments" / name for name in (
        "campaign_runtime.py", "upstream_controls/execution.py", "sharded_k4_stages/execution.py",
        "sharded_k4_stages/link_runtime.py", "sharded_k4_stages/process_cleanup.py",
        "sharded_k4_stages/routing.py", "sharded_k4_stages/synthesis.py", "sharded_k4_stages/rtl.py",
        "original_regraph_validation/analysis.py", "original_regraph_execution/sssp_real_round/delivery.py",
        "original_regraph_execution/sssp_real_round/recheck.py")]
    paths += [path for path, _ in paired_files(paired)]
    paths += [path for path in functional.rglob("*") if path.is_file()]
    paths += [output / "functional_gate" / name for name in ("verification.json", "raw_functional.tar.gz")]
    paths += sorted(Path(__file__).parent.glob("*.py"))
    pins = [identity(path) for path in dict.fromkeys(paths)]
    snapshots = []
    for index, pin in enumerate(pins):
        if pin["path"] in {str(COMPILER), str(PLATFORM)}:
            continue
        name = f"sources/{index:02d}_{Path(pin['path']).name}"
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pin["path"], destination)
        snapshots.append({"archive_path": name, **pin})
    source = integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"
    command = [str(COMPILER), "--target", "hw", "--compile", "--kernel_frequency", "150",
               "--kernel", "pma_to_regraph_adapter", "--platform", str(PLATFORM), "--save-temps",
               "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in FLAGS.items()],
               "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
               "--temp_dir", str(output / "build"), "--report_dir", str(output / "reports"),
               "--log_dir", str(output / "logs"), "-o", str(output / "adapter.hw.xo"), str(source)]
    manifest = {"pins": pins, "snapshots": snapshots, "command": command,
                "reference_xo": identity(reference), "flags": FLAGS, "clock_mhz": 150,
                "part": "xcu55c-fsvh2892-2L-e", "paired_gate": identity(paired / "results.json"),
                "functional_gate": identity(output / "functional_gate/verification.json"),
                "claim": "production_XO_ABI_gate_not_route_board_or_simulator_timing"}
    atomic_write_json(output / "manifest.json", manifest)
    result = {"status": "running"}
    try:
        execution = run_link(command, output, output / "compile", timeout=1200,
                             tree_memory_gib=8, reserve_gib=16)
        result["execution"] = execution
        if (execution["exit_code"] or execution["stop_reason"] != "process_exit"
                or execution["cleanup_snapshot_error"] is not None):
            raise RuntimeError("production compilation failed; raw evidence retained")
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("production input/source changed during compilation")
        recheck(paired)
        result.update({"analysis": require_report(output),
                       "xo_contract": require_xo(output / "adapter.hw.xo", reference),
                       "xo": identity(output / "adapter.hw.xo"), "status": "production_XO_ABI_pass_not_routed",
                       "hardware_timing_admitted": False, "simulator_modified": False})
    except Exception as error:
        result.update({"status": "failed", "error": str(error)})
        atomic_write_json(output / "results.json", result)
        raise
    atomic_write_json(output / "results.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "paired", "functional", "reference", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve() for name in (
        "integration", "paired", "functional", "reference", "output")}
    if args.worker:
        print(json.dumps({"status": compile_xo(**paths)["status"]}))
        return
    if paths["output"].exists():
        raise FileExistsError("fresh production-XO output required")
    command = [sys.executable, "-m", __package__ + ".production", "--worker"]
    for name, path in paths.items():
        command += ["--" + name, str(path)]
    execution = run_link(command, Path.cwd(), paths["output"].with_name(paths["output"].name + "_watchdog"),
                         timeout=1350, tree_memory_gib=10, reserve_gib=16)
    if execution["exit_code"] or execution["stop_reason"] != "process_exit":
        raise SystemExit("production-XO worker failed; inspect preserved raw logs")
    print(json.dumps({"status": json.loads((paths["output"] / "results.json").read_text())["status"]}))


if __name__ == "__main__":
    main()
