"""Freeze, test, synthesize and probe explicit whole-line directory reads."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..adapter_axi.study import BENCH, require_route_reference
from ..empty_segment.production import COMPILER, PLATFORM, require_report
from ..execution import identity
from ..link_runtime import run_link
from .probe import probe
from .validation import FLAGS, compare_traffic, require_functional, require_xos


INTEGRATION_FILES = (
    "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
    "kernels/pma_to_regraph_adapter/row_prefetch.hpp",
    "kernels/pma_to_regraph_adapter/row_line.hpp",
    "tests/pma_to_regraph_adapter_tb.cpp", "tests/pma_adapter_row_prefetch_tb.cpp",
    "tests/weighted_pma_runtime_plan_test.cpp", "include/weighted_pma_runtime_plan.hpp",
    "include/weighted_pma_graph.hpp", "include/weighted_pma_update_reference.hpp",
    "scripts/check_pma_to_regraph_adapter.sh", "scripts/check_weighted_pma_runtime_plan.sh",
    "scripts/env.sh",
)


def run(integration: Path, reference: Path, routed: Path, route_manifest: Path,
        output: Path, vivado_bin: Path) -> dict:
    require_route_reference(identity(routed), json.loads(route_manifest.read_text()))
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[4]
    files = [integration / name for name in INTEGRATION_FILES]
    files += [root / BENCH, reference, routed, route_manifest, COMPILER, PLATFORM]
    files += [vivado_bin / name for name in ("xvlog", "xelab", "xsim")]
    files += sorted(Path(__file__).parent.glob("*.py"))
    # Freeze imported execution/validation owners as well as the command module.
    files += sorted(Path(__file__).parent.parent.glob("*.py"))
    files += sorted((Path(__file__).parent.parent / "adapter_axi").glob("*.py"))
    files += sorted((Path(__file__).parent.parent / "empty_segment").glob("*.py"))
    files += [root / "spine_cycle_sim/experiments" / name for name in (
        "campaign_runtime.py", "upstream_controls/execution.py",
        "original_regraph_execution/sssp_real_round/delivery.py",
        "original_regraph_execution/sssp_real_round/recheck.py", "original_regraph_validation/analysis.py")]
    pins = [identity(path) for path in dict.fromkeys(files)]
    copies = []
    for index, pin in enumerate(pins):
        path = Path(pin["path"])
        if path in (COMPILER, PLATFORM) or path in [vivado_bin / tool for tool in ("xvlog", "xelab", "xsim")]:
            continue
        relative = path.relative_to(integration) if path.is_relative_to(integration) else (
            path.relative_to(root) if path.is_relative_to(root) else Path(f"inputs/{index}_{path.name}"))
        target = output / "sources" / ("integration" if path.is_relative_to(integration) else "simulator") / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copies.append(pin | {"archive_path": str(target.relative_to(output))})
    manifest = {"schema": 1, "claim": "explicit_wide_directory_HLS_and_synthetic_AXI_RTL_not_FPGA_timing",
                "pins": pins, "source_copies": copies, "flags": FLAGS,
                "reference": identity(reference), "routed_reference": identity(routed),
                "route_manifest": identity(route_manifest),
                "gxx": subprocess.check_output(["g++", "--version"], text=True)}
    atomic_write_json(output / "manifest.json", manifest)

    def checked(command, cwd, prefix, timeout, budget):
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("a frozen study input changed")
        record = run_link(command, cwd, prefix, timeout=timeout,
                          tree_memory_gib=budget, reserve_gib=16)
        if (record["exit_code"] != 0 or record["stop_reason"] != "process_exit"
                or record["cleanup_snapshot_error"] is not None):
            raise ValueError("bounded execution failed; preserve raw logs")
        print(prefix.name, "PASS", flush=True)
        return record

    checked(["bash", "scripts/check_pma_to_regraph_adapter.sh", "--out-dir", str(output / "functional")],
            integration, output / "functional", 240, 3)
    require_functional((output / "functional/test.log").read_text())
    checked(["bash", "scripts/check_weighted_pma_runtime_plan.sh", "--out-dir", str(output / "host_contract")],
            integration, output / "host_contract", 120, 3)
    build = output / "production"
    build.mkdir()
    command = [str(COMPILER), "--target", "hw", "--compile", "--kernel_frequency", "150",
               "--kernel", "pma_to_regraph_adapter", "--platform", str(PLATFORM), "--save-temps",
               "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in FLAGS.items()],
               "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
               "--temp_dir", str(build / "build"), "--report_dir", str(build / "reports"),
               "--log_dir", str(build / "logs"), "-o", str(build / "adapter.hw.xo"), str(files[0])]
    atomic_write_json(build / "command.json", command)
    checked(command, build, build / "compile", 1200, 8)
    candidate = build / "adapter.hw.xo"
    contract = require_xos(reference, candidate)
    hls = require_report(build)
    arms = {}
    for arm, xo in (("reference", reference), ("candidate", candidate)):
        arms[arm] = probe(root, xo, output / arm, vivado_bin)
        print(arm, "AXI_RTL_PASS", flush=True)
    comparison = compare_traffic(arms["reference"], arms["candidate"])
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("a study input changed during execution")
    report = {"status": "ROW_LINE_PRODUCTION_AXI_PASS_NOT_ROUTED", "contract": contract,
              "hls": hls, "xo": identity(candidate), "arms": arms, "comparison": comparison,
              "simulator_modified": False, "FPGA_timing_admitted": False}
    atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "reference", "routed", "route-manifest", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({"status": run(**{key.replace("-", "_"): value.resolve()
              for key, value in vars(args).items()})["status"]}))
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"error": repr(error), "status": "FAILED_RETAINED"})
        raise


if __name__ == "__main__":
    main()
