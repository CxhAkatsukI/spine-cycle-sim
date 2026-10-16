"""Encode board-control descriptors from the exact independently audited captures."""

import json
from pathlib import Path
import shutil
import struct

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from . import artifact, study


def admit(captures: Path, reference: dict, destination: Path) -> dict:
    report_path = captures
    if (reference["status"] != study.STATUS or reference["errors"] or
            artifact.identity(report_path) not in reference["pins"]):
        raise ValueError("input report must be pinned by the passing independent audit")
    report = json.loads(report_path.read_text())
    study.validate_matrix(report)
    admitted = {"a4": [], "original_example": []}
    for topology in admitted:
        for graph in ("boundary_ring", "skewed_sources", "amazon"):
            case = next(row for row in report["cases"] if row["id"] == f"{topology}_{graph}")
            if case.get("repeat_all_captures_identical") is not True or len(case["runs"]) != 2:
                raise ValueError("both unchanged original-host repetitions required")
            first, repeated = case["runs"]
            if first["analysis"] != repeated["analysis"]:
                raise ValueError("original-host capture repetitions differ")
            source = Path(first["directory"])
            layout_path = source / "layout.json"
            if (artifact.identity(layout_path) not in reference["pins"] or
                    sha256_file(layout_path) != first["layout_sha256"] or
                    json.loads(layout_path.read_text()) != first["analysis"]):
                raise ValueError("layout is not the exact independently audited capture")
            layout, summary = first["analysis"], first["analysis"]["summary"]
            vertices, aligned = summary["vertices"], summary["aligned_vertices"]
            dense, sparse = summary["dense_partitions"], summary["sparse_groups"]
            published = (dense + sparse * 8) * 65536
            allocation = max(aligned, published)
            tasks = layout["tasks"]
            if topology == "a4":
                if sparse or published > aligned:
                    raise ValueError("A4 must have a bounded dense-only publication prefix")
                words = [0x3447524F, 1, vertices, summary["logical_edges"],
                         aligned, published, len(tasks), dense]
                descriptor = "execution.u32le"
            else:
                if dense != 1:
                    raise ValueError("the artifact example must retain its named one-dense-partition layout")
                words = [0x4D47524F, 1, vertices, summary["logical_edges"],
                         aligned, published, allocation, len(tasks), dense, sparse, 11, 3]
                descriptor = "mixed.u32le"
            for task in tasks:
                words.extend(task[key] for key in ("partition", "subpartition", "kernel", "dst_offset",
                                                  "dst_len", "offset_words", "words"))
                words.append(int(task["kind"] == "sparse"))
            target = destination / topology / graph
            target.mkdir(parents=True, exist_ok=False)
            with (target / descriptor).open("xb") as stream:
                stream.write(struct.pack(f"<{len(words)}I", *words))
            pins = [artifact.identity(target / descriptor)]
            for name in ("tasks.u32le", "initial.u32le", "degrees.u32le", "csr_offsets.u32le", "csr_destinations.u32le"):
                pin = artifact.identity(source / name)
                declared = next(row for row in layout["files"] if row["path"] == name)
                if pin not in reference["pins"] or pin["sha256"] != declared["sha256"]:
                    raise ValueError("input is not the exact independently audited capture")
                shutil.copyfile(source / name, target / name)
                copied = artifact.identity(target / name)
                if copied["sha256"] != pin["sha256"]:
                    raise ValueError("copied capture identity differs")
                pins.extend((pin, copied))
            admitted[topology].append({"id": graph, "directory": str(target), "pins": pins})
    return admitted
