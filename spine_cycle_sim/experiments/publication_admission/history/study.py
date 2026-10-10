"""Freeze history/source observations and execute a bounded read-only audit."""

import json
from pathlib import Path
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...upstream_controls.execution import run_bounded
from .git_store import blob, git, snapshot
from .inspection import inspect_archive, inspect_sources

CONTRACT = "configs/experiments/upstream_publication_history_v1.json"


def identities(root):
    files = sorted((root / "spine_cycle_sim/experiments/publication_admission/history").glob("*.py"))
    files += [root / path for path in (CONTRACT, "scripts/audit_upstream_publication_history.py",
        "tests/test_upstream_publication_history.py", "spine_cycle_sim/experiments/campaign_runtime.py",
        "spine_cycle_sim/experiments/upstream_controls/execution.py")]
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in files]


def collect(root: Path, out: Path):
    out.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / CONTRACT).read_text())
    report = {"status": "RUNNING", "contract": contract, "code": identities(root),
              "repositories": {}, "git_version": git(root, "--version").decode().strip(),
              "publication_timing_match": None}
    for family in ("grasu", "regraph"):
        spec = contract[family]
        checkout = root / spec["checkout"]
        original = snapshot(checkout, spec, contract["limits"])
        sources = inspect_sources(checkout, original, spec, contract)
        result = {"history": original, "author_source_versions": sources}
        if family == "grasu":
            archive = spec["deleted_archive"]
            oid = git(checkout, "rev-parse", f'{archive["revision"]}:{archive["path"]}').decode().strip()
            result["deleted_archive"] = inspect_archive(blob(checkout, oid, contract["limits"]["archive_bytes"]), contract)
            if result["deleted_archive"]["sha256"] != archive["sha256"]:
                raise ValueError("historical GraSU archive identity differs")
        else:
            changed = git(checkout, "diff", "--name-only", spec["release"], spec["head"], "--", *spec["source_prefixes"]).decode().splitlines()
            # Dataset additions are not author implementation changes.
            changed = [path for path in changed if not path.startswith("dataset/")]
            if changed != spec["expected_changed_source_files"]:
                raise ValueError("ReGraph release author-source diff differs")
            diff = git(checkout, "diff", spec["release"], spec["head"], "--", *changed)
            (out / "regraph_release.diff").write_bytes(diff)
            result["release_source_changed_files"] = changed
            result["release_source_diff_sha256"] = sha256_file(out / "regraph_release.diff")
            result["release_source_diff"] = diff.decode()
        if snapshot(checkout, spec, contract["limits"]) != original:
            raise ValueError("source history or checkout changed during inspection")
        report["repositories"][family] = result
    if identities(root) != report["code"]:
        raise ValueError("history audit code changed during collection")
    report["status"] = "REACHABLE_HISTORY_INSPECTED_NOT_PUBLICATION_RECOVERY"
    atomic_write_json(out / "observations.json", report)
    return report


def run(root: Path, out: Path):
    out.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / CONTRACT).read_text())
    limits = contract["limits"]
    frozen = identities(root)
    step = run_bounded([sys.executable, str(root / "scripts/audit_upstream_publication_history.py"),
        "--worker", "--out", str(out / "capture")], root, out / "logs" / "history",
        timeout=limits["timeout_seconds"], memory_gib=limits["memory_gib"], reserve_gib=limits["reserve_gib"])
    if step["exit_code"] or step["timed_out"]:
        raise ValueError("bounded history inspection failed; preserved logs contain the reason")
    if identities(root) != frozen:
        raise ValueError("history audit code changed during bounded execution")
    report = json.loads((out / "capture/observations.json").read_text())
    report["resource_step"] = step
    atomic_write_json(out / "report.json", report)
    return report
