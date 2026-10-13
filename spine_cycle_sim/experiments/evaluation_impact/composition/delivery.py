"""Package verified handoff logs and retained failed attempts, without binaries."""

import argparse
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze


def deliver(report_path, output, retained, previous_sst):
    report = json.loads(report_path.read_text())
    if report["status"] != "RESIDENT_HANDOFF_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION":
        raise ValueError("cannot package incomplete or failed handoff as accepted")
    if report.get("pins_unchanged") is not True or report.get("default_routed_stdout_exact") is not True:
        raise ValueError("missing frozen identity/default equivalence gate")
    for identity in report["pins"]:
        if sha256_file(Path(identity["path"])) != identity["sha256"]:
            raise ValueError("changed handoff evidence: " + identity["path"])
    steps = report["steps"]
    required = {"compiler", "configure", "core-build", "handoff", "default-routed", "ctest",
                "sst-build", "sst-info", "sst-memory", "sst-native"}
    if len(steps) != len(required) or {step["label"] for step in steps} != required:
        raise ValueError("incomplete verification steps")
    if any(step["exit_code"] or step["timed_out"] for step in steps):
        raise ValueError("failed handoff verification step")
    if any(not 0 < step["memory_limit_gib"] <= 2 or step["reserve_gib"] < 8 for step in steps):
        raise ValueError("unbounded handoff verification step")
    ctest = next(step for step in steps if step["label"] == "ctest")
    if "100% tests passed, 0 tests failed out of 32" not in Path(ctest["stdout"]).read_text():
        raise ValueError("missing complete 32-test C++ regression")
    handoff = next(step for step in steps if step["label"] == "handoff")
    analysis = analyze(Path(handoff["stdout"]).read_text())
    if analysis != report["analysis"]:
        raise ValueError("handoff report differs from raw observations")
    defaults = []
    comparisons = []
    for old_name, new_name in (("memory/summary.json", "sst-memory/summary.json"),
                               ("native/result.json", "sst-native/result.json")):
        old, new = previous_sst / old_name, report_path.parent / new_name
        if json.loads(old.read_text()) != json.loads(new.read_text()):
            raise ValueError("default SST numerical behavior changed: " + new_name)
        defaults.append({"file": new_name, "previous": str(old), "previous_sha256": sha256_file(old),
                         "current_sha256": sha256_file(new), "all_json_fields_exact": True})
        comparisons.append(("previous-sst/" + old_name, old))
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(report_path, output / "report.json")
    members = []
    roots = [("verified", report_path.parent)] + [(f"retained-{i}", p) for i, p in enumerate(retained)]
    with tarfile.open(output / "raw.tar.gz", "w:gz") as archive:
        def include(member, path):
            archive.add(path, arcname=member)
            members.append({"member": member, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

        for label, root in roots:
            paths = [p for p in root.iterdir() if p.is_file()]
            for name in ("raw", "sst-memory", "sst-native"):
                if (root / name).is_dir():
                    paths += [p for p in (root / name).rglob("*") if p.is_file()]
            for path in sorted(paths):
                include(label + "/" + str(path.relative_to(root)), path)
        for identity in report["pins"]:
            path = Path(identity["path"])
            if path.name in ("compile_commands.json", "CMakeCache.txt"):
                include("verified/build-flags/" + path.name, path)
        for member, path in comparisons:
            include(member, path)
    index = {**analysis, "default_routed_stdout_exact": True,
             "sst_scope": report["sst_scope"], "sst_exact_default_smokes": defaults,
             "core_tests": 32, "steps": steps, "raw_members": members,
             "retained_roots": [str(p) for p in retained],
             "files": [{"file": name, "bytes": (output / name).stat().st_size,
                        "sha256": sha256_file(output / name)} for name in ("report.json", "raw.tar.gz")]}
    atomic_write_json(output / "index.json", index)
    return index


def deliver_checks(base, output):
    expected = {"delivery": 0, "focused-tests": 1, "focused-tests-v2": 0,
                "check-docs": 0, "check-catalogs": 0, "diff-check": 0}
    checks = []
    for name, exit_code in expected.items():
        step = json.loads((base / (name + ".resources.json")).read_text())
        if step["exit_code"] != exit_code or step["timed_out"] or \
                not 0 < step["memory_limit_gib"] <= 2 or step["reserve_gib"] < 8:
            raise ValueError("unexpected verification result: " + name)
        checks.append({"label": name, "expected_exit_code": exit_code, **step})
    if "Ran 54 tests" not in (base / "focused-tests-v2.stderr.txt").read_text():
        raise ValueError("missing focused test scope")
    if "retained-1/build.stderr.txt" not in (base / "focused-tests.stderr.txt").read_text():
        raise ValueError("unexpected retained packaging-test failure")
    output.mkdir(parents=True, exist_ok=False)
    members = []
    with tarfile.open(output / "checks.tar.gz", "w:gz") as archive:
        for name in expected:
            for suffix in (".stdout.txt", ".stderr.txt", ".resources.json"):
                path = base / (name + suffix)
                archive.add(path, arcname=path.name)
                members.append({"member": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    result = {"status": "HANDOFF_DELIVERY_CHECKS_PASS", "focused_python_tests": 54, "checks": checks,
              "retained_failure": "test expected build.stderr.txt; preserved file is build-run.stderr.txt",
              "members": members, "baseline_admitted": False,
              "archive": {"file": "checks.tar.gz", "sha256": sha256_file(output / "checks.tar.gz"),
                          "bytes": (output / "checks.tar.gz").stat().st_size}}
    atomic_write_json(output / "index.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", type=Path)
    mode.add_argument("--checks", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retained", type=Path, action="append", default=[])
    parser.add_argument("--previous-sst", type=Path)
    args = parser.parse_args()
    if args.checks:
        index = deliver_checks(args.checks.resolve(), args.output.resolve())
    else:
        if not args.previous_sst:
            parser.error("--report requires --previous-sst")
        index = deliver(args.report.resolve(), args.output.resolve(), [p.resolve() for p in args.retained],
                        args.previous_sst.resolve())
    print(json.dumps({"status": index["status"], "baseline_admitted": False}))
