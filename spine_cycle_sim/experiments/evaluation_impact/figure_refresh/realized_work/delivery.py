"""Assemble a data-only Figures 7--11 handoff without touching the paper."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import write_csv
from .matrix import OLD, ROOT

SOURCE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="ascii") as stream:
        return list(csv.DictReader(stream))


def merge_fig9(original: list[dict], fixed: list[dict]) -> list[dict]:
    rows = [r for r in original if r["algorithm"] != "ResPR"] + fixed
    counts = {algorithm: sum(r["algorithm"] == algorithm for r in rows)
              for algorithm in ("SSSP", "CC", "ResPR")}
    if counts != {"SSSP": 3, "CC": 3, "ResPR": 3}:
        raise ValueError(f"incomplete Figure 9 pairs: {counts}")
    if len({(r["algorithm"], r["dataset"]) for r in rows}) != 9:
        raise ValueError("duplicate Figure 9 pair")
    if any(r["algorithm"] != "ResPR" for r in fixed):
        raise ValueError("fixed-threshold replacement contains another algorithm")
    return rows


def archive(path: Path, files: list[tuple[Path, str]], *, part_bytes: int = 64 * 1024 * 1024) -> dict:
    members = []
    names = set()
    with tarfile.open(path, "w:gz") as target:
        for source, name in sorted(files, key=lambda pair: pair[1]):
            if name in names:
                raise ValueError(f"duplicate archive member: {name}")
            names.add(name)
            if not source.is_file():
                raise FileNotFoundError(source)
            members.append({"path": name, "sha256": sha256_file(source), "bytes": source.stat().st_size})
            target.add(source, arcname=name, recursive=False)
    index = {"path": path.name, "sha256": sha256_file(path), "members": members}
    if path.stat().st_size > part_bytes:
        parts = []
        with path.open("rb") as source:
            while chunk := source.read(part_bytes):
                part = path.with_name(f"{path.name}.part{len(parts):03d}")
                part.write_bytes(chunk)
                parts.append({"path": part.name, "sha256": sha256_file(part), "bytes": len(chunk)})
        index["parts"] = parts
        path.unlink()
    return index


def package(campaign: Path, output: Path, integration: Path, board: Path,
            failed_attempt: Path | None = None) -> dict:
    summary = json.loads((campaign / "analysis/fresh_summary.json").read_text())
    if summary["status"] != "PASS_SIMULATOR_PREDICTION" or summary["executions"] != 42:
        raise ValueError("fresh campaign incomplete")
    if output.exists():
        raise FileExistsError("use a new delivery directory")
    for directory in ("data", "provenance", "evidence"):
        (output / directory).mkdir(parents=True)
    provenance = {"scope": "data_only_no_paper_edits", "sources": {}, "external_evidence": []}

    def copy(source: Path, relative: str) -> None:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        provenance["sources"][relative] = {"path": str(source), "sha256": sha256_file(source)}

    hardware = integration / "docs/sharded_k4_cache_extent"
    copy(hardware / "single_pass_20261026.csv", "data/fig7_fpga_speedup.csv")
    copy(hardware / "single_pass_20261026.audit.json", "provenance/fig7_board_audit.json")
    copy(hardware / "single_pass.md", "provenance/fig7_original_report.md")
    measured = read_csv(output / "data/fig7_fpga_speedup.csv")
    if len(measured) != 24 or any(r["status"] != "RESIDENT_PAIR_PASS" for r in measured):
        raise ValueError("expected 24 admitted FPGA pairs")
    for row in measured:
        ratio = float(row["gr_wall_ms"]) / float(row["spine_wall_ms"])
        if abs(ratio / float(row["speedup_gr_over_spine"]) - 1) > 1e-12:
            raise ValueError("FPGA ratio differs from raw walls")
    legacy = [r for r in read_csv(OLD / "data/fig7_fpga_speedup.csv") if r["algorithm"] == "full_pagerank"]
    if legacy:
        write_csv(output / "data/fig7_fullpr_legacy_not_refreshed.csv", legacy)
        provenance["sources"]["data/fig7_fullpr_legacy_not_refreshed.csv"] = {
            "path": str(OLD / "data/fig7_fpga_speedup.csv"), "status": "LEGACY_ONLY_NOT_CURRENT"}
    for name in ("fig8_update_cross_dataset.csv", "fig8_update_batch_sensitivity.csv", "fig8_arms.csv"):
        copy(SOURCE / "data" / name, "data/" + name)
    copy(SOURCE / "data/summary.json", "provenance/fig8_original_summary.json")
    multi, fixed = SOURCE / "multialgorithm", SOURCE / "respr_fixed_epsilon"
    write_csv(output / "data/fig9_memory_energy_rows.csv", merge_fig9(
        read_csv(multi / "data/fig9_memory_energy_rows.csv"),
        read_csv(fixed / "data/fig9_memory_energy_rows.csv")))
    arms = [r for r in read_csv(multi / "data/fig9_arms.csv") if r["algorithm"] != "ResPR"]
    arms += read_csv(fixed / "data/fig9_arms.csv")
    if len(arms) != 18 or len({(r["algorithm"], r["dataset"], r["arm"]) for r in arms}) != 18:
        raise ValueError("expected 18 distinct Figure 9 arms")
    write_csv(output / "data/fig9_arms.csv", arms)
    copy(fixed / "data/threshold_comparison.csv", "data/fig9_respr_threshold_comparison.csv")
    for name, source in (("fig9_sssp_cc", multi), ("fig9_respr_fixed", fixed)):
        copy(source / "data/summary.json", f"provenance/{name}_original_summary.json")
    propagation, sparse = SOURCE / "respr_propagation", SOURCE / "respr_sparse_apply"
    for name, source, table in (
        ("fig9_respr_nonempty_dense", propagation, "propagation_comparison.csv"),
        ("fig9_respr_sparse_candidate", sparse, "before_after.csv"),
    ):
        copy(source / "data" / table, f"data/{name}.csv")
        copy(source / "data/summary.json", f"provenance/{name}_summary.json")
    for source in (SOURCE, multi, fixed, propagation, sparse):
        files = [source / "evidence/index.json", *sorted((source / "evidence").glob("evidence.tar.gz*"))]
        provenance["external_evidence"].extend({"path": str(p.relative_to(ROOT)), "sha256": sha256_file(p)}
                                                for p in files)
    for name in ("fig10_stage_rows.csv", "fig10_normalized_breakdown_rows.csv"):
        copy(campaign / "analysis" / name, "data/" + name)
    for source in sorted((campaign / "analysis").glob("rq3_*")):
        copy(source, "data/fig11_" + source.name.removeprefix("rq3_"))
    copy(campaign / "analysis/fresh_summary.json", "data/fig10_11_fresh_summary.json")
    for name in ("matrix.json", "identity.json", "status.json"):
        copy(campaign / name, "provenance/fig10_11_" + name)

    matrix = json.loads((campaign / "matrix.json").read_text())
    raw_files, inputs = [], {}
    for case in matrix["cases"]:
        directory = Path(case["out_dir"])
        raw_files += [(p, f"runs/{case['execution_id']}/{p.relative_to(directory)}")
                      for p in sorted(directory.rglob("*")) if p.is_file()]
        for item in case["inputs"].values():
            inputs[item["sha256"]] = Path(item["path"])
    raw_files += [(p, f"inputs/{sha}/{p.name}") for sha, p in inputs.items()]
    raw_files += [(p, "profiles/" + p.name) for p in sorted((campaign / "profiles").iterdir())]
    provenance["fig10_11_archive"] = archive(output / "evidence/fig10_11_raw.tar.gz", raw_files)
    if failed_attempt:
        failed_files = [(p, str(p.relative_to(failed_attempt))) for p in failed_attempt.rglob("*")
                        if p.is_file() and p.suffix in (".json", ".txt", ".log") and "plugin" not in p.parts]
        provenance["failed_attempt_archive"] = archive(
            output / "evidence/retained_preflight_failure.tar.gz", failed_files)
    board_files = []
    for algorithm in ("sssp", "cc", "respr"):
        for dataset in ("au", "su", "wk", "so", "pk", "lj", "lj08", "r19"):
            directory = board / f"{algorithm}-{dataset}"
            for name in ("manifest.json", "gr-clocks.json", "spine-clocks.json",
                         "sample-1/gr.stdout.txt", "sample-1/spine.stdout.txt",
                         "sample-1/gr.resources.json", "sample-1/spine.resources.json"):
                board_files.append((directory / name, f"{directory.name}/{name}"))
    provenance["fig7_archive"] = archive(output / "evidence/fig7_board_raw.tar.gz", board_files)
    provenance["simulator_git_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    provenance["integration_git_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=integration, text=True).strip()
    atomic_write_json(output / "provenance/package.json", provenance)
    manifest = {str(p.relative_to(output)): sha256_file(p) for p in sorted(output.rglob("*")) if p.is_file()}
    atomic_write_json(output / "manifest.json", {"status": "DATA_PACKAGE_COMPLETE", "files": manifest})
    return {"directory": str(output), "files": len(manifest), "fresh_executions": 42}


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--board-evidence", type=Path, required=True)
    parser.add_argument("--failed-attempt", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.campaign.resolve(), args.output.resolve(),
                             args.integration.resolve(), args.board_evidence.resolve(),
                             args.failed_attempt.resolve() if args.failed_attempt else None), indent=2))


if __name__ == "__main__":
    main()
