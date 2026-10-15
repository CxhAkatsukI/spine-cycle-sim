"""Seal preflight inputs, raw convergence checks and failures without hardware claims."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from ..complete_pipeline.delivery import CHECKPOINT, verify as verify_archive
from ..search_pipeline.synthesis import unchanged
from .analysis import CLAIMS, PASS, UNIT_PASS, analyze

KIND = "continuous_gr_sssp_host_preflight_not_board"


def terminal(report):
    if report["status"] not in (PASS, "FAILED_RETAINED") or any(
            report.get(key) is not False for key in CLAIMS) or \
            bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("invalid handoff preflight claim boundary")


def validate(attempt, report):
    terminal(report)
    pins = report["source"]
    if not pins or len({pin["path"] for pin in pins}) != len(pins):
        raise ValueError("missing or duplicate frozen source")
    for pin in pins:
        relative = Path(pin["path"]).relative_to(attempt)
        if relative.parts[0] != "source" and relative.name not in (
                "contract.json", "continuous_contract.json", "handoff_contract.json"):
            raise ValueError("source pin outside preflight")
    unchanged(pins)
    contract = json.loads((attempt / "handoff_contract.json").read_text())
    if contract != report["contract"]:
        raise ValueError("handoff contract changed")
    cases = contract["cases"]
    suffixes = ("mixed-512", "weight_change-4096") + (("warm-decrease-64",) if "warm_controls" in contract else ())
    names = {f"{dataset}-{suffix}" for dataset in ("AU", "SU", "WK") for suffix in suffixes}
    if len(cases) != len(names) or {row["case"] for row in cases} != names or any(
            row["partition_vertices"] != 65536 or row["shards"] != 1 or len(row["batches"]) != 3 for row in cases):
        raise ValueError("wrong single-partition matrix")
    steps = report["steps"]
    if len({row["label"] for row in steps}) != len(steps):
        raise ValueError("duplicate execution step")
    for step in steps:
        resource = json.loads((attempt / (step["label"] + ".resources.json")).read_text())
        if {key: value for key, value in step.items() if key != "label"} != resource or any(
                Path(step[key]).parent != attempt for key in ("stdout", "stderr")):
            raise ValueError("resource/raw-output identity changed")
    if report["status"] != PASS:
        return
    if [step["label"] for step in steps] != ["unit-compile", "unit", "compile", *(case["case"] for case in cases)] or any(
            step["exit_code"] or step["timed_out"] for step in steps):
        raise ValueError("passing preflight requires the complete matrix")
    for step in steps[:3]:
        out, err = (Path(step[key]).read_text() for key in ("stdout", "stderr"))
        if err.strip() or out != (UNIT_PASS + "\n" if step["label"] == "unit" else ""):
            raise ValueError("unexpected compile/unit diagnostic")
    actual = [{"case": case["case"], **analyze(case, Path(step["stdout"]).read_text(),
                                               Path(step["stderr"]).read_text())}
              for case, step in zip(cases, steps[3:], strict=True)]
    if actual != report["cases"] or any(sha256_file(attempt / binary) != report[label + "_binary_sha256"]
            for label, binary in (("compile", "probe"), ("unit-compile", "resident-test"))):
        raise ValueError("raw execution/binary differs from analysis")
    unchanged(report["dependencies"])


def package(output, attempts):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct attempts required")
    reports = [json.loads((path / "results.json").read_text()) for path in attempts]
    for attempt, report in zip(attempts, reports, strict=True):
        validate(attempt, report)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for attempt, report in zip(attempts, reports, strict=True):
        paths = sorted(path for path in attempt.rglob("*") if path.is_file() and
                       (path.is_relative_to(attempt / "source") or path.parent == attempt and
                        path.name not in ("probe", "resident-test")))
        if any(path.is_symlink() for path in paths):
            raise ValueError("evidence cannot contain symlinks")
        archive = output / (attempt.name + ".tar.gz")
        files = seal([(path, path.relative_to(attempt).as_posix()) for path in paths], archive)
        entries.append({"attempt": attempt.name, "source": str(attempt), "status": report["status"],
                        "errors": report["errors"], "cases": report["cases"], "files": files,
                        "archive": archive.name, "sha256": sha256_file(archive), "bytes": archive.stat().st_size})
    atomic_write_json(output / "index.json", {"status": CHECKPOINT, "study_kind": KIND,
                                              "attempts": entries, **dict.fromkeys(CLAIMS, False)})
    return verify(output)


def verify(output):
    index = verify_archive(output)
    if index.get("study_kind") != KIND or any(index.get(key) is not False for key in CLAIMS):
        raise ValueError("wrong preflight or promoted hardware claim")
    for entry in index["attempts"]:
        with tarfile.open(output / entry["archive"]) as bundle:
            report = json.load(bundle.extractfile("results.json"))
        terminal(report)
        if any(entry[key] != report[key] for key in ("status", "errors", "cases")):
            raise ValueError("archive and handoff index disagree")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
