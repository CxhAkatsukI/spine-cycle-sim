"""Freeze one screened repair attempt without promoting it to figure evidence."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from .package import archive
from .runtime import identity, save
from .clocks import replay as clock_replay


def checkpoint(campaign, analysis, hosts, production, output):
    report = json.loads((campaign / "results.json").read_text())
    summary = json.loads((analysis / "summary.json").read_text())
    build = json.loads((hosts / "manifest.json").read_text())
    if report["status"] != "BOARD_EXECUTION_PASS_PENDING_ANALYSIS":
        raise ValueError("a completed board execution is required")
    if identity(campaign / "results.json") not in summary["input_reports"]:
        raise ValueError("analysis does not describe this campaign")
    pins = list(report["pins"].values()) + summary["input_reports"]
    pins += [pin for group in report["input_pins"].values() for pin in group]
    pins += [row[name] for row in report["rows"] for name in ("stdout", "stderr", "result_json") if name in row]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("a frozen execution input changed")
    for row in report["rows"]:
        if "clock_evidence" in row:
            clock_replay(row["clock_evidence"])
    if build["status"] != "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD":
        raise ValueError("a completed paired host build is required")
    for record in build["builds"]:
        name = "r_host" if record["arm"] == "reference" else "r_candidate"
        if record["binary"] != report["pins"][name]:
            raise ValueError("executed host differs from paired build")
    repository = Path(__file__).resolve().parents[5]
    output.mkdir(parents=True, exist_ok=False)
    (output / "data").mkdir()
    (output / "evidence").mkdir()
    for name in ("summary.json", "comparison.csv", "repetitions.csv"):
        shutil.copy2(analysis / name, output / "data" / name)
    archive(output / "evidence/raw_board.tar.gz", [(campaign, campaign.name), (hosts, hosts.name)])
    archive(output / "evidence/reproduction_sources.tar.gz", [
        (Path(__file__).resolve().parent, "spine_cycle_sim/experiments/original_regraph_execution/hardware/source_retention"),
        (repository / "cpp/tests/original_regraph/hardware", "cpp/tests/original_regraph/hardware"),
        (repository / "cpp/tests/original_regraph/whole_graph", "cpp/tests/original_regraph/whole_graph"),
        (repository / "cpp/tests/publication_sources/source_retention", "cpp/tests/publication_sources/source_retention"),
        (repository / "cpp/tests/publication_sources/grasu_board", "cpp/tests/publication_sources/grasu_board"),
        (production / "include", "integration/include"),
    ])
    metadata = {"status": "REPAIR_CHECKPOINT_NOT_FINAL_EVALUATION", "analysis_status": summary["status"],
                "publication_match": False, "artifacts": report["pins"], "inputs": report["input_pins"],
                "input_files_archived_here": False,
                "input_archive_repository_relative": "docs/experiments/comparisons/grasu_regraph_stage_validation/"
                    "evaluation_impact/hardware_validation/source_performance_retention_20261103/evidence/inputs.tar.gz",
                "paired_host_build": identity(hosts / "manifest.json"),
                "production_git": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=production, text=True).strip(),
                "production_source_is_bitstream_attestation": False}
    save(output / "data/artifacts.json", metadata)
    save(output / "manifest.json", {"status": metadata["status"], "files": [identity(p) for p in sorted(output.rglob("*"))
                                                                           if p.is_file()]})
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "analysis", "hosts", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(checkpoint(*(getattr(args, name).resolve() for name in
                       ("campaign", "analysis", "hosts", "production", "output")))["status"])
