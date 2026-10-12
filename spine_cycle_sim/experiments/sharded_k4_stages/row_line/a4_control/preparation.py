"""Pin inherited evidence, explicitly declare changes, and freeze all new inputs."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.layout_audit import audit
from .contract import BASES, DOC, EXTRACTION_SHA, HARNESS_CHANGE, NUMERICAL_CHANGES


def identity(path):
    return {"path": str(path), "sha256": sha256_file(path)}


def bases(root: Path) -> dict:
    result = {}
    for name, (relative, expected) in BASES.items():
        path = root / DOC / relative
        if sha256_file(path) != expected:
            raise ValueError("historical report differs: " + name)
        result[name] = json.loads(path.read_text())
    return result


def changed_sources(root: Path, reports: dict) -> list[dict]:
    changes = []
    for name in ("numerical", "partition", "sensitivity"):
        observed = []
        for item in reports[name]["sources"]:
            current = identity(root / item["path"])["sha256"]
            if current != item["sha256"]:
                observed.append(item["path"])
                changes.append({"basis": name, "path": item["path"],
                                "before_sha256": item["sha256"], "after_sha256": current})
        expected = NUMERICAL_CHANGES if name == "numerical" else (
            NUMERICAL_CHANGES | {HARNESS_CHANGE} if name == "sensitivity" else set())
        if set(observed) != expected:
            raise ValueError("undeclared historical source change: " + name)
    return changes


def pins(root: Path, reports: dict) -> list[dict]:
    paths = {root / item["path"] for report in reports.values() for item in report["sources"]}
    paths.update((root / "cpp/tests/routed_regraph").rglob("*.hpp"))
    paths.update((root / "cpp/tests/routed_regraph/row_line").glob("*"))
    paths.update(root / name for name in (
        "cpp/tests/routed_regraph/round_execution.hpp", "cpp/tests/routed_regraph/empty_segment/CMakeLists.txt",
        "tests/test_sharded_k4_row_line_a4_control.py"))
    paths.update(Path(__file__).parent.glob("*.py"))
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            path = Path(filename).resolve()
            if path.suffix == ".py" and path.is_relative_to(root / "spine_cycle_sim"):
                paths.add(path)
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted(paths) if path.is_file()]


def copy_checked(source: Path, target: Path, expected: str) -> None:
    if source.is_symlink() or sha256_file(source) != expected:
        raise ValueError("frozen input identity differs: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha256_file(target) != expected:
        raise ValueError("frozen input copy differs")


def freeze(root: Path, output: Path, extraction: Path, reports: dict) -> dict:
    if output.exists():
        raise FileExistsError("fresh model control output required")
    changes = changed_sources(root, reports)
    if sha256_file(extraction) != EXTRACTION_SHA:
        raise ValueError("pre-extraction source archive differs")
    with tarfile.open(extraction, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            expected = (next(item["sha256"] for item in reports["sensitivity"]["sources"]
                             if item["path"] == HARNESS_CHANGE) if member.name == HARNESS_CHANGE
                        else sha256_file(root / member.name))
            with bundle.extractfile(member) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != expected:
                    raise ValueError("pre-extraction source differs: " + member.name)
    source_pins = pins(root, reports)
    output.mkdir(parents=True)
    for item in source_pins:
        copy_checked(root / item["path"], output / "sources" / item["path"], item["sha256"])
    for name, (relative, expected) in BASES.items():
        copy_checked(root / DOC / relative, output / "bases" / (name + ".json"), expected)
    copy_checked(extraction, output / "pre_extraction.tar.gz", EXTRACTION_SHA)
    inputs = []
    for geometry in reports["partition"]["inputs"]:
        mode = geometry["mode"]
        for item in geometry["files"]:
            copy_checked(Path(item["path"]), output / "inputs" / mode / Path(item["path"]).name, item["sha256"])
        expected = next(case for case in reports["partition"]["cases"] if case["mode"] == mode)["outputs"][0]
        copy_checked(Path(expected["path"]), output / "expected" / (mode + ".u32le"), expected["sha256"])
        inputs.append(geometry)
    layout = audit(output / "inputs/cold", inputs[0]["vertices"])
    if layout != reports["partition"]["layout_audit"]:
        raise ValueError("independent PMA layout changed")
    return {"sources": source_pins, "declared_source_changes": changes, "inputs": inputs,
            "layout_audit": layout, "pre_extraction_sha256": EXTRACTION_SHA}
