"""Freeze sources, synthesize production cross-row HLS and run full AXI RTL."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...adapter_axi.study import BENCH
from ...empty_segment.production import COMPILER, PLATFORM, require_report
from ...execution import identity
from ...link_runtime import run_link
from ..evidence import bounded
from ..probe import probe
from ..study import INTEGRATION_FILES
from ..validation import require_functional as require_legacy
from .validation import BASE, BASE_SHA, CLAIM, FLAGS, REFERENCE_SHA, STATUS
from .validation import compare, require_functional, require_xos


def compile_command(integration, build):
    return [str(COMPILER), "--target", "hw", "--compile", "--kernel_frequency", "150",
            "--kernel", "pma_to_regraph_adapter", "--platform", str(PLATFORM), "--save-temps",
            "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in FLAGS.items()],
            "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
            "--temp_dir", str(build / "build"), "--report_dir", str(build / "reports"),
            "--log_dir", str(build / "logs"), "-o", str(build / "adapter.hw.xo"),
            str(integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp")]


def run(integration, reference, output, vivado_bin):
    root = Path(__file__).resolve().parents[5]
    base = root / BASE
    if sha256_file(reference) != REFERENCE_SHA or sha256_file(base) != BASE_SHA:
        raise ValueError("immutable whole-line reference XO/report required")
    output.mkdir(parents=True, exist_ok=False)
    names = (*INTEGRATION_FILES, "kernels/pma_to_regraph_adapter/cross_row_pipeline.hpp",
             "scripts/check_pma_adapter_cross_row.sh")
    paths = [integration / name for name in names] + [root / BENCH, reference, base]
    owner = Path(__file__).parent.parent.parent
    for directory in (owner, owner / "row_line", owner / "row_line/cross_row",
                      owner / "row_line/occupied_rows", owner / "adapter_axi", owner / "empty_segment"):
        paths += sorted(directory.glob("*.py"))
    paths += [root / "spine_cycle_sim/experiments" / name for name in (
        "campaign_runtime.py", "upstream_controls/execution.py",
        "original_regraph_execution/sssp_real_round/delivery.py",
        "original_regraph_execution/sssp_real_round/recheck.py", "original_regraph_validation/analysis.py")]
    tools = [COMPILER, PLATFORM] + [vivado_bin / name for name in ("xvlog", "xelab", "xsim")]
    pins, copies = [], []
    for index, path in enumerate(dict.fromkeys(paths + tools)):
        pin = identity(path)
        pins.append(pin)
        if path in tools:
            continue
        relative = (Path("integration") / path.relative_to(integration) if path.is_relative_to(integration)
                    else Path("simulator") / path.relative_to(root) if path.is_relative_to(root)
                    else Path(f"external/{index}_{path.name}"))
        target = output / "sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copies.append(pin | {"archive_path": str(target.relative_to(output))})
    manifest = {"schema": 1, "claim": CLAIM, "pins": pins, "source_copies": copies, "flags": FLAGS,
                "reference": identity(reference), "base": identity(base), "integration": str(integration),
                "gxx": subprocess.check_output(["g++", "--version"], text=True),
                "tools": {name: str(vivado_bin / name) for name in ("xvlog", "xelab", "xsim")}}
    atomic_write_json(output / "manifest.json", manifest)

    def checked(command, cwd, prefix, timeout, budget):
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("frozen cross-row input changed")
        run_link(command, cwd, prefix, timeout=timeout, tree_memory_gib=budget, reserve_gib=16)
        bounded(prefix.with_name(prefix.name + ".resources.json"), command, str(cwd), timeout, budget)
        print(prefix.name, "PASS", flush=True)

    for step, script in (("legacy", "check_pma_to_regraph_adapter.sh"),
                         ("functional", "check_pma_adapter_cross_row.sh")):
        checked(["bash", "scripts/" + script, "--out-dir", str(output / step)],
                integration, output / step, 240, 3)
    require_legacy((output / "legacy/test.log").read_text())
    require_functional((output / "functional.stdout.txt").read_text())
    build = output / "production"
    build.mkdir()
    command = compile_command(integration, build)
    atomic_write_json(build / "command.json", command)
    checked(command, build, build / "compile", 1200, 8)
    candidate = build / "adapter.hw.xo"
    contract, hls = require_xos(reference, candidate), require_report(build)
    arms = {}
    for arm, xo in (("reference", reference), ("candidate", candidate)):
        arms[arm] = probe(root, xo, output / arm, vivado_bin)
        print(arm, "FULL_AXI_RTL_PASS", flush=True)
    comparison = compare(arms["reference"], arms["candidate"], json.loads(base.read_text()))
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("frozen input changed during study")
    report = {"status": STATUS, "contract": contract, "hls": hls, "xo": identity(candidate),
              "arms": arms, "comparison": comparison, "simulator_modified": False, "FPGA_timing_admitted": False}
    atomic_write_json(output / "results.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "reference", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(**{name: path.resolve() for name, path in vars(args).items()})
        print(json.dumps({"status": result["status"]}))
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
