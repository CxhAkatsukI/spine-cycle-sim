"""Freeze the author source, fresh synthesis configuration, and old evidence."""

import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.hls_preparation import prepare_hls_job


def identities(root):
    paths = [root / name for name in ("configs/experiments/original_grasu_ddr_rtl_v1.json", "scripts/run_original_grasu_ddr_rtl.py", "tests/test_original_grasu_ddr_rtl.py")]
    for directory in ("cpp/tests/grasu_ddr_rtl", "spine_cycle_sim/experiments/grasu_ddr_rtl"):
        paths.extend(path for path in (root / directory).rglob("*") if path.suffix in (".cpp", ".sv", ".py"))
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(paths)]


def capture_baseline(root: Path, output: Path):
    paths = []
    for name in ("cpp/src", "cpp/include", "cpp/sst", "cpp/tests/original_regraph", "cpp/tests/pma_adapter",
                 "spine_cycle_sim/experiments/upstream_controls", "spine_cycle_sim/experiments/pma_adapter"):
        paths.extend(path for path in (root / name).rglob("*") if path.suffix in (".cpp", ".hpp", ".h", ".cc", ".py"))
    paths.extend(root / name for name in ("CMakeLists.txt", "cpp/CMakeLists.txt", "cpp/sst/Makefile"))
    plugin = root / "build/sst/libspine_cycle.so"
    record = {"source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "files": [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(set(paths))],
        "user_dirty_diff": subprocess.check_output(["git", "diff", "--", "scripts/build_current_fpga_spine_v4_index.py"], cwd=root, text=True),
        "plugin_sha256": sha256_file(plugin) if plugin.exists() else None,
        "accepted_A4_B_result_sha256": sha256_file(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/finite_pma_results.json")}
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "baseline.json", record)
    return record


def preserve(root: Path, baseline: Path):
    record = json.loads((baseline / "baseline.json").read_text())
    changed = [item["path"] for item in record["files"] if sha256_file(root / item["path"]) != item["sha256"]]
    user = subprocess.check_output(["git", "diff", "--", "scripts/build_current_fpga_spine_v4_index.py"], cwd=root, text=True)
    plugin = root / "build/sst/libspine_cycle.so"
    result = {"old_source_files": len(record["files"]), "changed_old_files": changed,
        "plugin_sha256": sha256_file(plugin) if plugin.exists() else None,
        "accepted_A4_B_result_sha256": sha256_file(root / "docs/experiments/comparisons/grasu_regraph_stage_validation/finite_pma_results.json"),
        "user_dirty_diff_preserved": user == record["user_dirty_diff"], "baseline_sha256": sha256_file(baseline / "baseline.json")}
    if changed or result["plugin_sha256"] != record["plugin_sha256"] or result["accepted_A4_B_result_sha256"] != record["accepted_A4_B_result_sha256"] or not result["user_dirty_diff_preserved"]:
        raise ValueError("original DDR RTL control changed old numerical code, evidence or user patch")
    return result


def prepare(root: Path, output: Path, include: Path, contract):
    checkout = root / "build/publication_sources/grasu"
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if revision != contract["source_revision"] or subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout, text=True):
        raise ValueError("original GraSU checkout is not pinned and clean")
    source = checkout / "GraSU/GraSU_kernels/src"
    for name, field in (("kernel_process_ddr.cpp", "kernel_sha256"), ("kernel_config.h", "header_sha256")):
        if sha256_file(source / name) != contract[field]:
            raise ValueError("original DDR source identity differs")
    directory = output / "hls"
    directory.mkdir()
    description = prepare_hls_job({"family": "grasu", "id": "g_source16_ddr", "kernel": "ddr"},
        {"grasu_part": "xcu250-figd2104-2L-e", "grasu_clock_ns": contract["clock_ns"]},
        root / "build/publication_sources", directory, include)
    shutil.copytree(root / "cpp/tests/grasu_ddr_rtl", output / "bench")
    return description


def freeze_rtl(output: Path):
    directory = output / "hls/project/solution/syn/verilog"
    files = sorted(directory.glob("*.v"))
    if not files or not (directory / "process_ddr.v").is_file():
        raise ValueError("fresh original DDR RTL missing")
    target = output / "rtl"
    target.mkdir()
    for path in files:
        shutil.copyfile(path, target / path.name)
    return [{"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(target.glob("*.v"))]


def schedules(output: Path):
    directory = output / "hls/project/solution/syn/report"
    fields = []
    for name in ("process_Pipeline_process_ddr_sub_loop_csynth.xml", "process_1_Pipeline_process_ddr_sub_loop_csynth.xml"):
        path = directory / name
        tree = ET.parse(path)
        ii, depth = [int(tree.findtext(".//" + tag)) for tag in ("PipelineII", "PipelineDepth")]
        if (ii, depth) != (1, 146):
            raise ValueError("original DDR fresh inner-loop schedule changed")
        fields.append({"path": str(path.relative_to(output)), "sha256": sha256_file(path), "inner_II": ii, "inner_depth": depth})
    return fields
