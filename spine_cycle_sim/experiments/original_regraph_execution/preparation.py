"""Admit the frozen author-host captures and encode a bounded C++ input interface."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import STATUS, analyze_layout
from spine_cycle_sim.experiments.original_regraph_inputs.study import source_identities
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed


def verify_checkpoint(report: dict, contract: dict, frozen: dict, canonical: dict, identities: list[dict]) -> None:
    if (report.get("status") != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            not same_typed(contract, canonical) or not same_typed(report.get("source_identities"), identities) or
            not same_typed(report.get("source_identities"), frozen["source_identities"]) or
            not same_typed(report.get("source_snapshot"), frozen["source_snapshot"]) or
            [case["id"] for case in report["cases"]] != [case["id"] for case in frozen["cases"]] or
            [item["id"] for item in report["inputs"]] != [item["id"] for item in frozen["inputs"]]):
        raise ValueError("whole-A4 requires the fixed passing author-host source and input matrix")


def admit_inputs(root: Path, run: Path, destination: Path) -> list[dict]:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    frozen = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    verification = json.loads((frozen / "input_verification.json").read_text())
    accepted = json.loads((frozen / "input_results.json").read_text())
    canonical = json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())
    if (sha256_file(frozen / "input_results.json") != verification["results_sha256"] or
            sha256_file(run / "contract.json") != report["contract_sha256"]):
        raise ValueError("whole-A4 execution requires the unchanged delivered original-host checkpoint")
    verify_checkpoint(report, contract, accepted, canonical, source_identities(root))
    topology = next(item for item in report["topologies"] if item["id"] == "a4")
    steps = {item["id"]: item for item in report["steps"]}
    admitted = []
    for graph in report["inputs"]:
        case = next(item for item in report["cases"] if item["id"] == "a4_" + graph["id"])
        capture = Path(case["runs"][0]["directory"])
        step = steps[case["id"] + "_first"]
        layout = analyze_layout(Path(step["stdout"]).read_text(), capture, topology, graph, contract)
        accepted_case = next(item for item in accepted["cases"] if item["id"] == case["id"])
        if (case["status"] != STATUS or case.get("repeat_all_captures_identical") is not True or
                sha256_file(Path(graph["path"])) != graph["sha256"] or
                not same_typed(layout, case["runs"][0]["analysis"]) or
                not same_typed(layout, accepted_case["runs"][0]["analysis"])):
            raise ValueError("original author-host input or layout changed")
        target = destination / graph["id"]
        target.mkdir(parents=True, exist_ok=False)
        summary = layout["summary"]
        words = [0x3447524F, 1, summary["vertices"], summary["logical_edges"], summary["aligned_vertices"],
                 summary["partitions"] * 65536, len(layout["tasks"]), summary["partitions"]]
        for task in layout["tasks"]:
            if task["kind"] != "dense":
                raise ValueError("A4 must use only original dense tasks")
            words.extend([task[key] for key in ("partition", "subpartition", "kernel", "dst_offset", "dst_len",
                                                "offset_words", "words")])
            words.append(0)
        descriptor = target / "execution.u32le"
        with descriptor.open("xb") as stream:
            stream.write(struct.pack(f"<{len(words)}I", *words))
        copied = []
        for name in ("tasks.u32le", "initial.u32le", "degrees.u32le", "csr_offsets.u32le", "csr_destinations.u32le"):
            item = next(item for item in layout["files"] if item["path"] == name)
            shutil.copyfile(capture / name, target / name)
            if sha256_file(target / name) != item["sha256"]:
                raise ValueError("copied original input identity differs")
            copied.append({**item, "path": str(target / name)})
        admitted.append({"id": graph["id"], "directory": str(target), "layout": layout,
            "descriptor_sha256": sha256_file(descriptor), "files": copied,
            "source_report_sha256": sha256_file(run / "report.json"),
            "accepted_original_host_results_sha256": verification["results_sha256"]})
    return admitted


def verify_inputs(inputs: list[dict]) -> None:
    for item in inputs:
        if sha256_file(Path(item["directory"]) / "execution.u32le") != item["descriptor_sha256"]:
            raise ValueError("execution task descriptor changed")
        for capture in item["files"]:
            if sha256_file(Path(capture["path"])) != capture["sha256"]:
                raise ValueError("execution input capture changed")
