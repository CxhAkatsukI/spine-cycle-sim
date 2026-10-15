"""Portable metadata capsule for the read-only checkpoint inspection."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from . import artifact, checkpoint

FILES = ("results.json", "environment.json", "checkpoint.tcl", "vivado.log", "vivado.jou",
         "extract.stdout.txt", "extract.stderr.txt", "extract.resources.json",
         "query_run.stdout.txt", "query_run.stderr.txt", "query_run.progress.json", "query_run.resources.json",
         "query/design.tsv", "query/clocks.tsv", "query/clocks.rpt", "query/route_status.rpt", "query/timing.rpt")


def terminal(report):
    if report["status"] != checkpoint.STATUS or report["errors"] or any(
            report.get(key) is not False or report["analysis"].get(key) is not False
            for key in checkpoint.CLAIMS):
        raise ValueError("completed read-only inspection without promoted claims required")
    if (report["analysis"]["status"] != checkpoint.STATUS or
            report["analysis"]["constraints_modified"] is not False or
            report["analysis"]["implementation_or_bitstream_rewritten"] is not False):
        raise ValueError("native read-only checkpoint boundary required")


def recheck(attempt, report, prebuilt, audit):
    terminal(report)
    if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
        raise ValueError("checkpoint query pin changed")
    if checkpoint.analyze(attempt, prebuilt, audit) != report["analysis"]:
        raise ValueError("checkpoint raw observations disagree with results")
    source = Path(checkpoint.__file__).with_suffix(".tcl")
    if sha256_file(attempt / "checkpoint.tcl") != sha256_file(source):
        raise ValueError("executed query script differs from pinned source")
    for name, field in (("extract", "extraction"), ("query_run", "execution")):
        step = json.loads((attempt / (name + ".resources.json")).read_text())
        if step != report[field] or step["exit_code"] or step.get("timed_out", False) or \
                step.get("stop_reason", "process_exit") != "process_exit":
            raise ValueError("successful bounded checkpoint extraction/query required")


def package(attempt, prebuilt, audit, output):
    report = json.loads((attempt / "results.json").read_text())
    recheck(attempt, report, prebuilt, audit)
    files = []
    for name in FILES:
        path = attempt / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024**2:
            raise ValueError("bounded regular checkpoint metadata/log required")
        files.append((path, "query/" + name))
    root = Path(__file__).resolve().parents[4]
    for pin in report["pins"]:
        path = Path(pin["path"])
        if path.suffix in (".py", ".tcl") and path.is_relative_to(root):
            files.append((path, "runner/" + path.relative_to(root).as_posix()))
    references = [(audit / "results.json", "references/offline_audit.json"),
                  (prebuilt / checkpoint.IMPL / "_new_clk_freq", "references/recorded_scaled_clocks.txt")]
    files += references
    files.append((Path(__file__).resolve(), "delivery/checkpoint_delivery.py"))
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "original_r_checkpoint.tar.gz"
    index = {"status": checkpoint.STATUS, "archive": archive.name, "files": seal(files, archive),
             "sha256": sha256_file(archive), "analysis": report["analysis"],
             "external_hash_indexed_not_archived": ["DCP", "xclbin", "saved and extracted partial bitstreams", "tools"],
             **dict.fromkeys(checkpoint.CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != checkpoint.STATUS or any(index.get(key) is not False for key in checkpoint.CLAIMS):
        raise ValueError("invalid checkpoint capsule claim boundary")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("checkpoint capsule archive changed")
    with tarfile.open(archive) as bundle:
        if bundle.getnames() != [row["path"] for row in index["files"]]:
            raise ValueError("checkpoint capsule membership changed")
        for row in index["files"]:
            name, info = PurePosixPath(row["path"]), bundle.getmember(row["path"])
            if name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"] or \
                    hashlib.sha256(bundle.extractfile(info).read()).hexdigest() != row["sha256"]:
                raise ValueError("checkpoint capsule member changed")
        report = json.load(bundle.extractfile("query/results.json"))
    terminal(report)
    if report["analysis"] != index["analysis"]:
        raise ValueError("checkpoint capsule index disagrees with results")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("attempt", "prebuilt", "audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    package(*(path.resolve() for path in (args.attempt, args.prebuilt, args.audit, args.output)))
