"""Preserve failed attempts and pre-hardening execution bytes without rewriting."""

import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..sssp_real_round.delivery import members
from .archive import seal_compact

WATCHDOG_SUFFIXES = ("resources.json", "stdout.txt", "stderr.txt", "progress.json")


def watchdog_files(run, prefix):
    return [(run.with_name(run.name + "_watchdog." + suffix),
             prefix + "/" + run.name + "_watchdog." + suffix) for suffix in WATCHDOG_SUFFIXES]


def numerical_equality(previous, current):
    old = json.loads((previous / "results.json").read_text())
    if old["status"] != current["status"] or len(old["cases"]) != len(current["cases"]):
        raise ValueError("previous successful matrix differs")
    for a, b in zip(old["cases"], current["cases"], strict=True):
        if not same_typed({k: v for k, v in a.items() if k != "outputs"},
                          {k: v for k, v in b.items() if k != "outputs"}):
            raise ValueError("hardening changed cycles, counters or case declarations")
        if ([row["sha256"] for row in a["outputs"]] != [row["sha256"] for row in b["outputs"]]
                or any(sha256_file(Path(row["path"])) != row["sha256"] for row in a["outputs"])):
            raise ValueError("hardening changed complete states or previous raw state changed")


def archive_prior(attempts, current, destination):
    files, records = [], []
    if len({str(path) for path in attempts}) != len(attempts):
        raise ValueError("duplicate prior attempt")
    for run in attempts:
        report = json.loads((run / "results.json").read_text())
        if report["status"] != "failed":
            numerical_equality(run, current)
        prefix = "attempts/" + run.name
        files.extend(members(run, prefix + "/run"))
        files.extend(watchdog_files(run, prefix + "/watchdog"))
        snapshot = run.with_name(run.name + "_sources.tar.gz")
        index = run.with_name(run.name + "_sources.json")
        source_status = "historical_source_hashes_only_bytes_not_recoverable"
        if snapshot.exists() or index.exists():
            identity = json.loads(index.read_text())
            if sha256_file(snapshot) != identity["archive_sha256"]:
                raise ValueError("prior source snapshot changed")
            expected = {"sources/" + row["path"]: row["sha256"] for row in report["sources"]}
            if {row["path"]: row["sha256"] for row in identity["files"]} != expected:
                raise ValueError("prior source snapshot does not match recorded identities")
            with tarfile.open(snapshot, "r:gz") as bundle:
                if set(bundle.getnames()) != set(expected):
                    raise ValueError("prior source snapshot membership differs")
                for name, digest in expected.items():
                    if hashlib.sha256(bundle.extractfile(name).read()).hexdigest() != digest:
                        raise ValueError("prior source bytes changed")
            files.extend([(snapshot, prefix + "/" + snapshot.name), (index, prefix + "/" + index.name)])
            source_status = "source_bytes_match_original_execution_hashes"
        records.append({"name": run.name, "status": report["status"], "error": report.get("error"),
                        "results_sha256": sha256_file(run / "results.json"),
                        "source_status": source_status,
                        "numerical_equality_to_current": report["status"] != "failed"})
    archive = destination / "prior_attempts.tar.xz"
    index = seal_compact(files, archive)
    return {"attempts": records, "files": index, "archive_bytes": archive.stat().st_size,
            "archive_sha256": sha256_file(archive)}
