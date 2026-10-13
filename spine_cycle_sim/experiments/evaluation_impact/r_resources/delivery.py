"""Retain resource observations and source identities without admitting timing."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze


def package(run, output):
    report_path = run / "results.json"
    report = json.loads(report_path.read_text())
    if (report.get("status") != "RESOURCE_ACCOUNTING_VERIFIED_NOT_PERFORMANCE_ADMISSION"
            or report.get("pins_unchanged") is not True):
        raise ValueError("completed identity-verified resource audit required")
    for identity in report["pins"]:
        if sha256_file(Path(identity["path"])) != identity["sha256"]:
            raise ValueError("pinned resource audit identity changed")
    steps = report["steps"]
    if len(steps) != 5 or any(step["exit_code"] or step["timed_out"] for step in steps):
        raise ValueError("complete successful resource audit steps required")
    analysis = analyze(Path(steps[-1]["stdout"]).read_text())
    if analysis != report["analysis"]:
        raise ValueError("resource audit stdout changed")
    raw = sorted((run / "raw").glob("*"))
    if not raw or any(not p.is_file() for p in raw):
        raise ValueError("raw resource audit logs missing")
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for name, source in (("report.json", report_path), ("sources.tar.gz", run / "sources.tar.gz")):
        shutil.copy2(source, output / name)
        files.append({"file": name, "source": str(source), "sha256": sha256_file(output / name)})
    members = []
    archive = output / "raw_logs.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for path in raw:
            handle.add(path, arcname=path.name, recursive=False)
            members.append({"member": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    files.append({"file": archive.name, "sha256": sha256_file(archive)})
    index = {"status": analysis["status"], "analysis": analysis,
             "reports": files, "raw_members": members,
             "maximum_child_process_rss_kib": max(step["peak_rss_kib"] for step in steps),
             "audit_process_rss_kib": steps[-1]["peak_rss_kib"],
             "rss_scope": "maximum process RSS, not simultaneous process-tree total",
             "delivery_implementation_sha256": sha256_file(Path(__file__)),
             "core_or_sst_numerical_code_changed": False,
             "production_baseline_admitted": False, "publication_match_admitted": False,
             "new_spine_comparison_executed": False, "hardware_timing_admitted": False}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.run.resolve(), args.output.resolve())
    print(json.dumps({"status": result["status"], "files": len(result["reports"])}))
