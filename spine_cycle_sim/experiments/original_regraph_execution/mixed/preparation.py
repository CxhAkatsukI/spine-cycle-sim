"""Admit unchanged original-host captures and declare publication-tail padding."""

import json
from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import STATUS, analyze_layout
from spine_cycle_sim.experiments.original_regraph_inputs.study import source_identities
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..preparation import verify_checkpoint


def geometry(summary: dict) -> dict:
    aligned = summary["aligned_vertices"]
    published = summary["dense_partitions"] * 65536 + summary["sparse_groups"] * 524288
    return {"aligned_vertices": aligned, "published_vertices": published,
            "allocation_vertices": max(aligned, published), "extra_padding_vertices": max(0, published - aligned),
            "original_host_capacity_pass": published <= aligned}


def admit(root: Path, run: Path, destination: Path) -> list[dict]:
    report = json.loads((run / "report.json").read_text())
    contract = json.loads((run / "contract.json").read_text())
    frozen = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    accepted = json.loads((frozen / "input_results.json").read_text())
    verification = json.loads((frozen / "input_verification.json").read_text())
    if (sha256_file(frozen / "input_results.json") != verification["results_sha256"] or
            sha256_file(run / "contract.json") != report["contract_sha256"]):
        raise ValueError("mixed execution requires unchanged delivered original-host inputs")
    verify_checkpoint(report, contract, accepted, json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text()),
                      source_identities(root))
    topology = next(item for item in report["topologies"] if item["id"] == "original_example")
    if (topology["little"], topology["big"], topology["dense_partitions_argument"]) != (11, 3, 1):
        raise ValueError("mixed graph executor requires the separately named artifact example")
    result = []
    for graph in report["inputs"]:
        case_id = "original_example_" + graph["id"]
        case = next(item for item in report["cases"] if item["id"] == case_id)
        step = next(item for item in report["steps"] if item["id"] == case_id + "_first")
        original = Path(case["runs"][0]["directory"])
        layout = analyze_layout(Path(step["stdout"]).read_text(), original, topology, graph, contract)
        previous = next(item for item in accepted["cases"] if item["id"] == case_id)
        if (case["status"] != STATUS or case.get("repeat_all_captures_identical") is not True or
                not same_typed(layout, case["runs"][0]["analysis"]) or not same_typed(layout, previous["runs"][0]["analysis"]) or
                sha256_file(Path(graph["path"])) != graph["sha256"]):
            raise ValueError("original mixed graph/layout capture changed")
        target = destination / graph["id"]
        target.mkdir(parents=True, exist_ok=False)
        summary = layout["summary"]; shape = geometry(summary)
        words = [0x4d47524f, 1, summary["vertices"], summary["logical_edges"], shape["aligned_vertices"],
            shape["published_vertices"], shape["allocation_vertices"], len(layout["tasks"]), summary["dense_partitions"],
            summary["sparse_groups"], 11, 3]
        for task in layout["tasks"]:
            words.extend(task[key] for key in ("partition", "subpartition", "kernel", "dst_offset", "dst_len", "offset_words", "words"))
            words.append(int(task["kind"] == "sparse"))
        descriptor = target / "mixed.u32le"
        with descriptor.open("xb") as stream: stream.write(struct.pack(f"<{len(words)}I", *words))
        files = []
        for name in ("tasks.u32le", "initial.u32le", "degrees.u32le", "csr_offsets.u32le", "csr_destinations.u32le"):
            expected = next(item for item in layout["files"] if item["path"] == name)
            shutil.copyfile(original / name, target / name)
            if sha256_file(target / name) != expected["sha256"]: raise ValueError("mixed input copy differs")
            files.append({**expected, "path": str(target / name)})
        result.append({"id": graph["id"], "directory": str(target), "layout": layout, "geometry": shape,
            "descriptor_sha256": sha256_file(descriptor), "files": files, "source_report_sha256": sha256_file(run / "report.json")})
    return result


def verify(inputs: list[dict]) -> None:
    for item in inputs:
        if sha256_file(Path(item["directory"]) / "mixed.u32le") != item["descriptor_sha256"]:
            raise ValueError("mixed descriptor changed")
        if geometry(item["layout"]["summary"]) != item["geometry"]: raise ValueError("mixed allocation declaration changed")
        for capture in item["files"]:
            if sha256_file(Path(capture["path"])) != capture["sha256"]: raise ValueError("mixed input changed")
