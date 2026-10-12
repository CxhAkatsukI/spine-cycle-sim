"""Observe two immutable production XOs with the unchanged twelve-case AXI bench."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...adapter_axi.study import BENCH, extract_rtl, require_execution
from ...execution import identity
from ...link_runtime import run_link
from ..validation import require_xos
from .analysis import analyze, helper_instance, require_replay


MONITOR = "cpp/tests/routed_regraph/occupied_row_monitor.sv"
BASE = ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
        "adapter_optimization/row_line/evidence/results.json")
BASE_SHA = "076e276a091c30f08cdc604de0d43fa10e9a33204f2ad177e4c4e13ab7fa3b31"
XO_HASHES = {"reference": "4bae8791463a71f8b02ccad870d0178b2268cea8cfa6173c480e8a596a24417a",
             "candidate": "752a0395caa5b0117624e6a8055f738e6e608b2272be2d8d118c51b38efa80a2"}


def run(root, reference, candidate, output, vivado_bin):
    base = root / BASE
    if sha256_file(base) != BASE_SHA:
        raise ValueError("frozen production RTL report changed")
    xos = {"reference": reference, "candidate": candidate}
    if any(sha256_file(path) != XO_HASHES[arm] for arm, path in xos.items()):
        raise ValueError("immutable production XO pair required")
    require_xos(reference, candidate)
    output.mkdir(parents=True, exist_ok=False)
    inputs = [base, root / BENCH, root / MONITOR, *xos.values()]
    inputs += sorted(Path(__file__).parent.glob("*.py"))
    owner = Path(__file__).parent.parent.parent
    inputs += sorted((owner / "adapter_axi").glob("*.py"))
    inputs += [owner / name for name in ("execution.py", "link_runtime.py", "process_cleanup.py", "routing.py")]
    inputs += [owner / "row_line/validation.py", owner / "row_line/evidence.py",
               root / "spine_cycle_sim/experiments/campaign_runtime.py",
               root / "spine_cycle_sim/experiments/upstream_controls/execution.py",
               root / "spine_cycle_sim/experiments/original_regraph_execution/sssp_real_round/delivery.py"]
    inputs += [vivado_bin / tool for tool in ("xvlog", "xelab", "xsim")]
    pins, copies = [], []
    for index, path in enumerate(dict.fromkeys(inputs)):
        pin = identity(path)
        pins.append(pin)
        if path.parent == vivado_bin:
            continue
        relative = path.relative_to(root) if path.is_relative_to(root) else Path(f"external/{index}_{path.name}")
        target = output / "sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copies.append(pin | {"archive_path": str(target.relative_to(output))})
    manifest = {"schema": 1, "pins": pins, "source_copies": copies, "base": identity(base),
                "xos": {arm: identity(path) for arm, path in xos.items()},
                "tools": {name: str(vivado_bin / name) for name in ("xvlog", "xelab", "xsim")},
                "claim": "read_only_production_RTL_observation_not_FPGA_or_calibration"}
    atomic_write_json(output / "manifest.json", manifest)
    frozen = json.loads(base.read_text())
    report = {}
    for arm, xo in xos.items():
        directory = output / arm
        directory.mkdir()
        rtl = extract_rtl(xo, directory)
        for name in (BENCH, MONITOR):
            shutil.copyfile(root / name, directory / Path(name).name)
        (directory / "run.tcl").write_text("run all\nquit\n")
        helper = helper_instance((directory / "pma_to_regraph_adapter.v").read_text())
        commands = {
            "compile": [str(vivado_bin / "xvlog"), "--sv", "-d", "ADAPTER_HELPER=" + helper,
                        Path(BENCH).name, Path(MONITOR).name] + [p.name for p in rtl if p.suffix == ".v"],
            "elaborate": [str(vivado_bin / "xelab"), "adapter_axi_tb", "occupied_row_monitor", "-s", "observed_adapter"],
            "simulate": [str(vivado_bin / "xsim"), "observed_adapter", "-tclbatch", "run.tcl"],
        }
        local_pins = [identity(p) for p in (*rtl, directory / Path(BENCH).name,
                      directory / Path(MONITOR).name, directory / "run.tcl")]
        atomic_write_json(directory / "inputs.json", local_pins)
        atomic_write_json(directory / "commands.json", commands)
        for step, command in commands.items():
            if any(identity(Path(p["path"])) != p for p in pins + local_pins):
                raise ValueError("frozen input changed")
            require_execution(run_link(command, directory, directory / step, timeout=120,
                tree_memory_gib=4, reserve_gib=16, poll_seconds=0.5))
        cases, report[arm] = analyze((directory / "simulate.stdout.txt").read_text())
        require_replay(cases, frozen["arms"][arm])
        print(arm, "OBSERVED_COMPLETE_REPLAY_PASS", flush=True)
    if any(identity(Path(p["path"])) != p for p in pins):
        raise ValueError("frozen study input changed")
    result = {"status": "OCCUPIED_ROW_RTL_REPLAY_PASS_NOT_BOARD", "arms": report,
              "production_HLS_and_simulator_unchanged": True, "FPGA_timing_admitted": False,
              "exclusive_stall_attribution": False}
    atomic_write_json(output / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "candidate", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    try:
        result = run(root, **{key: path.resolve() for key, path in vars(args).items()})
        print(json.dumps({"status": result["status"]}))
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
