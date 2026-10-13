"""Deliver bank-routing correctness and exact replay without promoting timing."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..common_g.delivery import package_control
from ..common_g.parallel.delivery import verify_pins
from . import banked_analysis as analysis


def deliver(report_path, output, pre_edit, previous_matrix, previous_sst):
    report = json.loads(report_path.read_text())
    required = ("pins_unchanged", "legacy_handoff_stdout_exact", "default_sst_json_fields_exact")
    if report["status"] != analysis.STATUS or any(report.get(name) is not True for name in required) or \
            type(report.get("core_tests")) is not int or report["core_tests"] < 33 or report.get("exact_previous_g_rows") != 228:
        raise ValueError("complete banked correctness and exact-replay gates required")
    verify_pins(report["pins"])
    base = report_path.parent
    compatibility = json.loads((base / "compatibility/results.json").read_text())
    if compatibility.get("pins_unchanged") is not True or compatibility.get("default_routed_stdout_exact") is not True:
        raise ValueError("default compatibility evidence required")
    core_steps = compatibility["steps"]
    if {step["label"] for step in core_steps} != {"compiler", "configure", "core-build", "handoff",
            "default-routed", "ctest", "sst-build", "sst-info", "sst-memory", "sst-native"} or len(core_steps) != 10:
        raise ValueError("incomplete core/SST verification")
    if len(report["steps"]) != 2 or {step["label"] for step in report["steps"]} != {"metadata-routing", "banked-handoff"}:
        raise ValueError("missing bank routing verification")
    for step in core_steps + report["steps"]:
        if step["exit_code"] or step["timed_out"] or not 0 < step["memory_limit_gib"] <= 2 or step["reserve_gib"] < 8:
            raise ValueError("failed or unbounded banked verification")
    if analysis.core_tests(compatibility) != report["core_tests"]:
        raise ValueError("core regression count differs from report")
    checked = analysis.analyze((base / "raw/banked-handoff.stdout.txt").read_text())
    if checked != report["analysis"]:
        raise ValueError("banked analysis differs from raw observations")
    for name, current in (("handoff", base / "compatibility/raw/handoff.stdout.txt"),
                          ("finite-search", base / "raw/metadata-routing.stdout.txt")):
        if current.read_bytes() != (pre_edit / (name + ".stdout.txt")).read_bytes():
            raise ValueError("default stdout changed: " + name)
    comparisons = []
    for name in ("sst-memory/summary.json", "sst-native/result.json"):
        old, new = previous_sst / name, base / "compatibility" / name
        if json.loads(old.read_text()) != json.loads(new.read_text()):
            raise ValueError("default SST observations changed")
        comparisons.append(("previous-sst/" + name, old))
    output.mkdir(parents=True, exist_ok=False)
    replay = package_control(output / "g_replay", base / "g-replay/results.json", previous_matrix,
        analyze=analysis.replay, required_status="G_FINITE_BANK_ROUTING_DEFAULTS_EXACT_228",
        status="G_FINITE_BANK_ROUTING_DEFAULTS_EXACT_228", previous_name="previous_finite.json")
    shutil.copyfile(report_path, output / "report.json")
    sources = []
    for label, root in (("verified", base), ("pre-edit", pre_edit)):
        paths = [p for p in root.iterdir() if p.is_file()]
        for owner in ("raw", "compatibility/raw", "compatibility/sst-memory", "compatibility/sst-native"):
            paths += [p for p in (root / owner).rglob("*") if p.is_file()]
        if label == "verified":
            paths += [root / "compatibility" / name for name in ("results.json", "sources.tar.gz")]
            paths += [root / "compatibility/build" / name for name in ("compile_commands.json", "CMakeCache.txt")]
        sources += [(label + "/" + str(p.relative_to(root)), p) for p in paths]
    sources += comparisons
    if len({name for name, _ in sources}) != len(sources):
        raise ValueError("ambiguous banked evidence members")
    members = []
    with tarfile.open(output / "raw.tar.gz", "w:gz") as archive:
        for name, path in sorted(sources):
            archive.add(path, arcname=name, recursive=False)
            members.append({"member": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    files = [p for p in output.rglob("*") if p.is_file()]
    index = {**checked, "core_tests": report["core_tests"], "exact_previous_g_rows": replay["exact_replayed_rows"],
             **{name: True for name in required}, "sst_scope": report["sst_scope"],
             "raw_members": members, "steps": core_steps + report["steps"],
             "files": [{"file": str(p.relative_to(output)), "bytes": p.stat().st_size,
                        "sha256": sha256_file(p)} for p in sorted(files)]}
    atomic_write_json(output / "index.json", index)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "output", "pre-edit", "previous-matrix", "previous-sst"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = deliver(args.report.resolve(), args.output.resolve(), args.pre_edit.resolve(),
                     args.previous_matrix.resolve(), args.previous_sst.resolve())
    print(json.dumps({"status": result["status"], "exact_previous_g_rows": result["exact_previous_g_rows"]}))
