"""Package cached handoff and verified regression capsules without duplicate JSON trees."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..common_g.parallel.delivery import verify_pins
from . import cached_analysis as analysis
from .banked_delivery import deliver as deliver_banked


def deliver(report_path, output, pre_edit, previous_matrix, previous_sst):
    report = json.loads(report_path.read_text())
    flags = ("pins_unchanged", "previous_banked_stdout_exact", "previous_default_stdout_and_sst_exact")
    if report["status"] != analysis.STATUS or any(report.get(name) is not True for name in flags) or \
            type(report.get("core_tests")) is not int or report["core_tests"] < 34 or \
            report.get("exact_previous_g_rows") != 228:
        raise ValueError("complete cached correctness and regression required")
    verify_pins(report["pins"])
    base = report_path.parent
    steps = report["steps"]
    if len(steps) != 1 or steps[0]["label"] != "cached-handoff" or steps[0]["exit_code"] or \
            steps[0]["timed_out"] or not 0 < steps[0]["memory_limit_gib"] <= 2 or steps[0]["reserve_gib"] < 8:
        raise ValueError("complete bounded cached execution required")
    checked = analysis.analyze((base / "raw/cached-handoff.stdout.txt").read_text())
    if checked != report["analysis"]:
        raise ValueError("cached analysis differs from raw observations")
    if (base / "banked/raw/banked-handoff.stdout.txt").read_bytes() != (pre_edit / "banked-handoff.stdout.txt").read_bytes():
        raise ValueError("preceding banked numerical observations changed")
    with tempfile.TemporaryDirectory() as temporary:
        regression = Path(temporary) / "regression"
        verified = deliver_banked(base / "banked/results.json", regression, pre_edit, previous_matrix, previous_sst)
        if verified["core_tests"] != report["core_tests"]:
            raise ValueError("cached/core regression counts differ")
        sources = [("regression/" + str(p.relative_to(regression)), p)
                   for p in regression.rglob("*") if p.is_file()]
        sources += [("verified/" + str(p.relative_to(base)), p)
                    for p in (base / "raw").rglob("*") if p.is_file()]
        sources += [("verified/results.json", report_path)]
        for path in sorted(pre_edit.parent.glob("smoke-v*/*")):
            if path.is_file():
                sources.append(("preflight/" + str(path.relative_to(pre_edit.parent)), path))
        if len({name for name, _ in sources}) != len(sources):
            raise ValueError("ambiguous cached evidence members")
        output.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(report_path, output / "report.json")
        members = []
        with tarfile.open(output / "raw.tar.gz", "w:gz") as archive:
            for name, path in sorted(sources):
                archive.add(path, arcname=name, recursive=False)
                members.append({"member": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        files = [p for p in output.iterdir() if p.is_file()]
        index = {**checked, **{name: True for name in flags}, "core_tests": report["core_tests"],
                 "exact_previous_g_rows": verified["exact_previous_g_rows"],
                 "sst_scope": report["sst_scope"], "raw_members": members,
                 "steps": verified["steps"] + steps,
                 "files": [{"file": p.name, "bytes": p.stat().st_size, "sha256": sha256_file(p)}
                           for p in sorted(files)]}
        atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "output", "pre-edit", "previous-matrix", "previous-sst"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = deliver(args.report.resolve(), args.output.resolve(), args.pre_edit.resolve(),
                     args.previous_matrix.resolve(), args.previous_sst.resolve())
    print(json.dumps({"status": result["status"], "rows": len(result["rows"])}))
