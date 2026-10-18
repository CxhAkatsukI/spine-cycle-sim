"""Audit frozen A4 predictions against replayed board controls without fitting."""

import argparse
import json
from pathlib import Path
from statistics import median

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ... import analysis as model_analysis
from ...preparation import verify_inputs
from .. import artifact
from ..control_analysis import BINDINGS
from ..source_build.snapshot import unchanged
from . import comparison, preparation

STATUS = "A4_MODEL_BOARD_IDENTITY_AUDIT_NOT_TIMING_CALIBRATION"
BASE_CASES = {"boundary_ring": "boundary", "skewed_sources": "skewed", "amazon": "amazon"}
INPUTS = (*comparison.INPUTS, "tasks.u32le")
CLAIMS = ("timing_calibrated", "publication_match", "latest_k4_performance_measured",
          "spine_speedup_measured", "figure_admission")


def load_model(report_path, verification_path, contract_path):
    report = json.loads(report_path.read_text())
    verification = json.loads(verification_path.read_text())
    contract = json.loads(contract_path.read_text())
    report_pin = artifact.identity(report_path)
    if (report_pin["sha256"] != verification["results_sha256"] or
            artifact.identity(contract_path)["sha256"] != report["contract_sha256"] or
            report["status"] != model_analysis.STATUS or
            verification["status"] != model_analysis.STATUS or
            verification["all_raw_numerical_inputs_binary_and_resource_evidence_rechecked"] is not True or
            report["ubsan_identical_no_diagnostics"] is not True or
            report["FPGA_measured_cycles"] is not None or report["publication_rate_error_pct"] is not None or
            report["boundary"] != contract["boundary"] or
            [row["id"] for row in report["cases"]] != [row["id"] for row in contract["cases"]] or
            [row["id"] for row in report["inputs"]] != list(BASE_CASES)):
        raise ValueError("complete frozen model checkpoint and verification required")
    verify_inputs(report["inputs"])
    binaries = [{"path": item["path"], "sha256": item["sha256"]} for item in report["binaries"]]
    dependencies = [pin for item in report["binaries"] for pin in item.get("dependencies", [])]
    unchanged(binaries)
    current_dependencies = [artifact.identity(Path(pin["path"])) for pin in dependencies]
    dependency_drift = [{"frozen": old, "current": new} for old, new in
                        zip(dependencies, current_dependencies, strict=True) if old != new]
    pins = [report_pin, artifact.identity(verification_path), artifact.identity(contract_path),
            *binaries, *current_dependencies]
    for item in report["inputs"]:
        pins.extend(artifact.identity(Path(item["directory"]) / name)
                    for name in (*INPUTS, "execution.u32le"))
    steps = {item["id"]: item for item in report["steps"]}
    if len(steps) != len(report["steps"]):
        raise ValueError("duplicate model execution steps")
    for spec, row in zip(contract["cases"], report["cases"], strict=True):
        if row["status"] != model_analysis.STATUS or len(row["runs"]) != 2:
            raise ValueError("complete repeated model matrix required")
        admitted = next(item for item in report["inputs"] if item["id"] == spec["input"])
        for repetition, run in zip(("first", "repeat"), row["runs"], strict=True):
            directory = Path(run["directory"])
            step = steps[spec["id"] + "_" + repetition]
            analysis_pin = artifact.identity(directory / "analysis.json")
            if (step["exit_code"] != 0 or step["timed_out"] is not False or
                    Path(step["stderr"]).read_text() or analysis_pin["sha256"] != run["analysis_sha256"] or
                    json.loads((directory / "analysis.json").read_text()) != run["analysis"] or
                    model_analysis.analyze(Path(step["stdout"]).read_text(), directory,
                                          spec, admitted, contract) != run["analysis"]):
                raise ValueError("raw model evidence differs from the frozen checkpoint")
            pins.extend([analysis_pin, artifact.identity(Path(step["stdout"])),
                         artifact.identity(Path(step["stderr"]))])
            pins.extend(artifact.identity(directory / item["path"]) for item in run["analysis"]["files"])
        if row["runs"][0]["analysis"] != row["runs"][1]["analysis"]:
            raise ValueError("repeated model state, cycles or counters differ")
    if model_analysis.analyze_matrix(report["cases"]) != report["analysis"]:
        raise ValueError("model matrix analysis differs")
    return {"report": report, "contract": contract, "pins": preparation.unique(pins),
            "historical_source_dependency_drift": dependency_drift}


def compare(model, board):
    report, contract = model["report"], model["contract"]
    rows = []
    board_plan = json.loads(Path(board["reports"][1]["path"]).read_text())
    if set(board["cases"]) != {(graph, binding) for graph in BASE_CASES
                              for binding in BINDINGS}:
        raise ValueError("all three graphs and both board bindings required")
    for graph, case_id in BASE_CASES.items():
        original = next(item for item in report["inputs"] if item["id"] == graph)
        captured = {Path(item["path"]).name: item["sha256"] for item in original["files"]}
        measured = board["cases"][(graph, "csr_degree")]
        if any(captured[name] != measured["inputs"][name] for name in comparison.INPUTS):
            raise ValueError("model and board logical inputs/state/divisors differ")
        plan = next(item for item in board_plan["cases"] if
                    (item["graph"], item["binding"]) == (graph, "csr_degree"))
        task_pin = artifact.identity(Path(plan["input"]) / "tasks.u32le")
        if task_pin["sha256"] != captured["tasks.u32le"] or task_pin not in board["pins"]:
            raise ValueError("model and board physical task payload differs or is unpinned")
        case = next(item for item in report["cases"] if item["id"] == case_id)
        analysis = case["runs"][0]["analysis"]
        result = analysis["result"]
        replicas = {item["sha256"] for item in analysis["files"]}
        selected = [item for item in board["board"]["rows"] if
                    (item["graph"], item["binding"]) == (graph, "csr_degree")]
        if len(selected) != preparation.REPEATS or {item["repeat"] for item in selected} != {0, 1, 2}:
            raise ValueError("three board repeats required")
        board_hashes = {item["analysis"]["independent_oracle"]["canonical_aligned_sha256"]
                        for item in selected}
        if replicas != board_hashes:
            raise ValueError("complete model and board aligned outputs differ")
        work = ("vertices", "logical_edges", "physical_edges", "dummy_edges", "published_vertices")
        if any(any(item["observation"][name] != result[name] for name in work) for item in selected):
            raise ValueError("model and board physical/logical work differs")
        if any(item["analysis"]["clock_mhz"] != 150 for item in selected):
            raise ValueError("replayed implemented 150-MHz board clock required")
        event_cycles = median(item["analysis"]["event_span_cycles_at_implemented_clock"] for item in selected)
        rows.append({"graph": graph, "binding": "csr_degree", "model_case": case_id,
            "inputs": captured, "aligned_output_sha256": next(iter(replicas)),
            "work": {name: result[name] for name in work}, "model_cycles": result["cycles"],
            "model_clock_mhz": result["clock_mhz"], "model_duration_ms": result["cycles"] / result["clock_mhz"] / 1000,
            "board_clock_mhz": 150, "board_repeats": preparation.REPEATS,
            "board_event_span_cycles_median": event_cycles,
            "board_event_span_ms_median": median(item["analysis"]["event_span_ns"] for item in selected) / 1e6,
            "board_resident_wall_ms_median": median(item["analysis"]["enqueue_to_completion_ms"] for item in selected),
            "diagnostic_cycle_count_ratio": result["cycles"] / event_cycles,
            "timing_match_eligible": False, "timing_error_pct": None})
    return {"status": STATUS, "errors": [], "rows": rows,
        "frozen_model_recomputed": False, "raw_model_outputs_replayed": True,
        "historical_source_dependency_drift": model["historical_source_dependency_drift"],
        "current_model_revalidated": False,
        "raw_board_outputs_replayed": True, "model_boundary": report["boundary"],
        "board_boundary": preparation.BOUNDARY, "model_memory_contract": contract["memory_model"],
        "excluded_board_bindings": [{"binding": "author_initial", "rows": 9,
            "reason": "model uses CSR-degree divisors, not initial-state divisors"}],
        "timing_match_blockers": ["model 210-MHz contract differs from implemented 150-MHz hardware",
            "mock memory latency/AXI arbitration are not calibrated to this routed A4",
            "model tasks start on local drain; board event span includes actual task launch gaps"],
        "ratio_definition": "model cycle count / board event-span cycles; diagnostic only, not speedup or calibrated error",
        **dict.fromkeys(CLAIMS, False),
        "pins": preparation.unique([*model["pins"], *board["pins"], *board["reports"],
                                    artifact.identity(Path(__file__))])}


def markdown(report):
    lines = ["# A4 Model Versus Board: Identity And Timing Audit", "", report["status"], "",
        "The frozen model is not rerun or fitted. All eight model cases (two repetitions each) "
        "and all eighteen board runs are replayed before selecting the three matching CSR-degree rows.", "",
        "| Graph | Model cycles | Model MHz | Board MHz | Board span cycles | Count ratio | Board span ms | Board resident wall ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["rows"]:
        lines.append(f"| {row['graph']} | {row['model_cycles']:,} | {row['model_clock_mhz']} | "
            f"{row['board_clock_mhz']} | {row['board_event_span_cycles_median']:,.2f} | "
            f"{row['diagnostic_cycle_count_ratio']:.3f} | {row['board_event_span_ms_median']:.6f} | "
            f"{row['board_resident_wall_ms_median']:.6f} |")
    lines += ["", "CSR, initial state, degree arrays, physical task payload, logical/physical work "
        "and complete aligned results agree. All nine author-initial board rows remain replayed "
        "but excluded from numerical comparison because their divisor semantics differ.", "",
        "## No Timing-Match Admission", "", *["- " + item for item in report["timing_match_blockers"]], "",
        "The count ratio does not convert the model to 150 MHz, estimate adapter overhead, "
        "or establish a publication-speed match. It must not be presented as a calibrated "
        "percentage error. No clock, latency or scaling factor was fitted. The latest actual "
        "adapter/K4 route and board matrix remain independent pending gates.", "",
        f"The historical binary and numerical captures remain hash-checked; "
        f"{len(report['historical_source_dependency_drift'])} dependency paths now differ from "
        "the historical checkpoint. Their frozen and current identities are recorded separately. "
        "This audit does not revalidate the current simulator or rebuild the historical binary. "
        "The original delivery validator is unchanged.", ""]
    return "\n".join(lines)


def run(model_report, verification, contract, a4, output):
    model = load_model(model_report, verification, contract)
    board = comparison.load(a4, "a4")
    report = compare(model, board)
    unchanged(report["pins"])
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "results.json", report)
    (output / "README.md").write_text(markdown(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-report", "verification", "contract", "a4", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(run(*(getattr(args, name).resolve() for name in
                ("model_report", "verification", "contract", "a4", "output")))["status"], flush=True)
