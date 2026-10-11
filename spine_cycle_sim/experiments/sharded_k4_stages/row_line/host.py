"""Freeze and compare default/wide-row host preparation, without using a board."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..execution import identity
from ..link_runtime import run_link


ALGORITHMS = ("sssp", "cc", "full_pr", "residual_pr")


def run(integration: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[4]
    paths = sorted((integration / "include").glob("*.hpp"))
    paths += sorted((integration / "tools").glob("*.cpp"))
    paths += [integration / name for name in (
        "scripts/env.sh", "scripts/check_sharded_k4_native_host.sh",
        "scripts/build_weighted_pma_native_host.sh", "tests/weighted_pma_row_line_plan_test.cpp")]
    paths += [Path(__file__)]
    paths += [root / "spine_cycle_sim/experiments" / name for name in (
        "campaign_runtime.py", "sharded_k4_stages/execution.py", "sharded_k4_stages/link_runtime.py",
        "sharded_k4_stages/process_cleanup.py", "upstream_controls/execution.py")]
    pins, copies = [], []
    for path in dict.fromkeys(paths):
        pin = identity(path)
        relative = (Path("integration") / path.relative_to(integration) if path.is_relative_to(integration)
                    else Path("simulator") / path.relative_to(root))
        target = output / "sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        pins.append(pin)
        copies.append(pin | {"archive_path": str(target.relative_to(output))})
    atomic_write_json(output / "manifest.json", {
        "pins": pins, "source_copies": copies, "integration": str(integration),
        "gxx": subprocess.check_output(["g++", "--version"], text=True),
        "claim": "host_padding_and_prepare_equivalence_not_FPGA"})

    def checked(command, prefix, timeout, environment=None):
        if any(identity(Path(pin["path"])) != pin for pin in pins):
            raise ValueError("frozen host source changed")
        record = run_link(command, integration, output / prefix, timeout=timeout,
                          tree_memory_gib=4, reserve_gib=16, environment=environment)
        if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
            raise ValueError("host gate failed; retain raw logs")

    checked(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-Iinclude",
             "tests/weighted_pma_row_line_plan_test.cpp", "-o", str(output / "padding_test")], "padding_compile", 120)
    checked([str(output / "padding_test")], "padding_run", 30)
    for arm, flag in (("default", []), ("candidate", ["--row-line-read"])):
        environment = dict(os.environ, OUT_DIR=str(output / arm))
        checked(["bash", "scripts/check_sharded_k4_native_host.sh", *flag], arm + "_check", 300, environment)
        print(arm, "FOUR_ALGORITHM_HOST_PASS", flush=True)
    results = {}
    for algorithm in ALGORITHMS:
        name = "six_partition_" + ("sssp" if algorithm == "sssp" else algorithm) + ".out"
        before, after = [(output / arm / name).read_bytes() for arm in ("default", "candidate")]
        if before != after:
            raise ValueError("default/wide preparation or oracle output differs")
        for arm, flag in (("default", "0"), ("candidate", "1")):
            if f"ROW_LINE_READ={flag}\n" not in (output / arm / algorithm / "manifest.txt").read_text():
                raise ValueError("host build flag differs")
        results[algorithm] = {"identical_prepare_output": True, "output": before.decode().strip()}
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("host input changed during execution")
    report = {"status": "FOUR_ALGORITHM_ROW_LINE_HOST_PASS_NOT_BOARD", "padding_vertex_cases": 11,
              "algorithms": results, "hardware_executed": False}
    atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({"status": run(args.integration.resolve(), args.output.resolve())["status"]}))
    except Exception as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"error": repr(error), "status": "FAILED_RETAINED"})
        raise


if __name__ == "__main__":
    main()
