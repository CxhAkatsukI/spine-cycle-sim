"""Run the fixed six-input original-R host/artifact audit, offline only."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import STATUS as INPUT_PASS
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.upstream_controls.sources import read_pins
from . import artifact, oracle, sources

STATUS = "ORIGINAL_R_PREFLIGHT_AUDIT_COMPLETE_NOT_BOARD_ADMISSION"
EXPECTED = {f"{topology}_{graph}" for topology in ("a4", "original_example")
            for graph in ("boundary_ring", "skewed_sources", "amazon")}


def validate_matrix(document: dict) -> None:
    if (document["status"] != INPUT_PASS or len(document["cases"]) != len(EXPECTED) or
            {case["id"] for case in document["cases"]} != EXPECTED):
        raise ValueError("complete admitted six-input author layout matrix required")


def runner_pins() -> list[dict]:
    paths = {Path(module.__file__).resolve() for name, module in list(sys.modules.items())
             if name.startswith("spine_cycle_sim.") and (getattr(module, "__file__", "") or "").endswith(".py")}
    paths.update(Path(__file__).parent.glob("*.py"))
    paths.add(Path(__file__).resolve())
    return [artifact.identity(path) for path in sorted(paths)]


def run(root: Path, inputs: Path, upstream: Path, prebuilt: Path, output: Path) -> dict:
    document = json.loads(inputs.read_text())
    validate_matrix(document)
    source_pin = read_pins(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json")["regraph"]
    source_review = sources.review(upstream, source_pin)
    binary = prebuilt / "xclbin_hw_pr/graph_fpga.hw..xclbin"
    timing = prebuilt / "_x/reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt"
    utility = Path("/opt/xilinx/xrt/bin/xclbinutil")
    pins = [artifact.identity(path) for path in (inputs, binary, timing, utility)]
    pins += runner_pins()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARED", "cases": [], "errors": [], "source_review": source_review,
              "pins": pins, "board_programmed": False, "board_correctness": False,
              "hardware_timing_measured": False, "publication_match": False,
              "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "worktree_status": subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).splitlines()}
    def save():
        atomic_write_json(output / "results.json", report)
    save()
    try:
        metadata = output / "artifact"
        metadata.mkdir()
        command = artifact.dump_command(binary, metadata, utility)
        step = run_bounded(command, root, output / "extract", timeout=120, memory_gib=2, reserve_gib=104)
        report["extraction"] = step
        if step["exit_code"] or step["timed_out"]:
            raise ValueError("read-only artifact metadata extraction failed")
        report["artifact"] = artifact.inspect(metadata, timing)
        for case in document["cases"]:
            if case["status"] != INPUT_PASS or case.get("repeat_all_captures_identical") is not True or len(case["runs"]) != 2:
                raise ValueError("both admitted author input repetitions required")
            first, second = case["runs"]
            if first["analysis"] != second["analysis"]:
                raise ValueError("original input repetitions differ")
            directory = Path(first["directory"])
            layout_path = directory / "layout.json"
            if (artifact.identity(layout_path)["sha256"] != first["layout_sha256"] or
                    json.loads(layout_path.read_text()) != first["analysis"]):
                raise ValueError("first author layout report changed")
            result = oracle.audit(directory, first["analysis"])
            report["pins"] += [artifact.identity(layout_path)] + result.pop("pins")
            report["cases"].append({"id": case["id"], **result})
            save()
            print("Audited " + case["id"] + " (offline, not FPGA execution)", flush=True)
        if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
            raise ValueError("preflight inputs, artifact or runner changed during audit")
        if sources.review(upstream, source_pin) != source_review:
            raise ValueError("author source review changed during audit")
        report["status"] = STATUS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "upstream", "prebuilt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    print(run(root, *(path.resolve() for path in (args.inputs, args.upstream, args.prebuilt, args.output)))["status"], flush=True)
