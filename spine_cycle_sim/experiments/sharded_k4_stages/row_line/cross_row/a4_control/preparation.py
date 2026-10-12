"""Copy portable historical fixtures and pin the entire executed numerical source."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.layout_audit import audit
from ...a4_control.preparation import copy_checked
from ...a4_control.recheck import recheck as recheck_basis
from ...model_archive import extracted
from ...model_recheck import source_files
from .contract import BASIS, BASIS_SHA, HARNESS_CHANGE, PRE_EDIT_SHA, profile


def pins(root):
    paths = {p for p in (root / "cpp").rglob("*") if p.suffix in {".cpp", ".hpp", ".txt"} and p.is_file()}
    paths.update(p for p in (root / "configs").rglob("*") if p.suffix in {".json", ".ini"} and p.is_file())
    paths.update((root / "spine_cycle_sim/experiments").rglob("*.py"))
    paths.update((root / "tests").glob("test_sharded_k4_cross_row_a4*.py"))
    return [{"path": str(p.relative_to(root)), "sha256": sha256_file(p)} for p in sorted(paths)]


def changes(source_root, archive, index):
    if sha256_file(archive) != PRE_EDIT_SHA or index["archive_sha256"] != PRE_EDIT_SHA:
        raise ValueError("pre-edit numerical snapshot differs")
    before = source_files(archive, index)
    observed = [{"path": name, "before_sha256": item["sha256"],
                 "after_sha256": sha256_file(source_root / name)}
                for name, item in ((i["path"], i) for i in index["files"])
                if sha256_file(source_root / name) != item["sha256"]]
    if {row["path"] for row in observed} != {HARNESS_CHANGE} or not before:
        raise ValueError("undeclared pre-existing numerical source change")
    return observed


def freeze(root, output, pre_edit):
    if output.exists():
        raise FileExistsError("fresh cross-row control output required")
    index_path = pre_edit.with_name("pre_edit_source_index.json")
    index = json.loads(index_path.read_text())
    declared = changes(root, pre_edit, index)
    expanded = profile(root)
    basis = root / BASIS
    if sha256_file(basis / "results.json") != BASIS_SHA:
        raise ValueError("historical A4 report differs")
    record = json.loads((basis / "verification.json").read_text())
    with extracted(basis / "raw_A4_control.tar.gz", record, max_bytes=512 * 1024**2) as temporary:
        previous = temporary / "run"
        report = recheck_basis(previous)
        if report != json.loads((basis / "results.json").read_text()):
            raise ValueError("historical raw A4 report differs")
        manifest = json.loads((previous / "manifest.json").read_text())
        output.mkdir(parents=True)
        copy_checked(previous / "manifest.json", output / "bases/manifest.json", report["manifest_sha256"])
        copy_checked(basis / "results.json", output / "bases/results.json", BASIS_SHA)
        compiler = previous / "raw/compiler.stdout.txt"
        copy_checked(compiler, output / "bases/compiler.txt", sha256_file(compiler))
        for geometry in manifest["inputs"]:
            mode = geometry["mode"]
            for item in geometry["files"]:
                name = Path(item["path"]).name
                copy_checked(previous / "inputs" / mode / name, output / "inputs" / mode / name, item["sha256"])
            oracle = previous / "expected" / (mode + ".u32le")
            copy_checked(oracle, output / "expected" / oracle.name, sha256_file(oracle))
    source_pins = pins(root)
    for item in source_pins:
        copy_checked(root / item["path"], output / "sources" / item["path"], item["sha256"])
    copy_checked(pre_edit, output / "pre_edit_source.tar.gz", PRE_EDIT_SHA)
    copy_checked(index_path, output / "pre_edit_source_index.json", sha256_file(index_path))
    if audit(output / "inputs/cold", manifest["inputs"][0]["vertices"]) != manifest["layout_audit"]:
        raise ValueError("independent PMA layout differs")
    return {"sources": source_pins, "declared_source_changes": declared, "profile": expanded,
            "inputs": manifest["inputs"], "layout_audit": manifest["layout_audit"],
            "memory": manifest["memory"], "historical_model": manifest["model"],
            "basis_manifest_sha256": report["manifest_sha256"], "basis_report_sha256": BASIS_SHA}
