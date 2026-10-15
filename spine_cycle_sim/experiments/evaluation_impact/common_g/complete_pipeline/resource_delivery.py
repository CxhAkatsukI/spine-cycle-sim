"""Package storage-query evidence, excluding vendor platforms and checkpoints."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..search_pipeline.synthesis import unchanged
from .resource_fit import account, platform_screen, query_capacity, resources, topology
from .resource_probe import capacity

CLAIMS = ("complete_g_resource_fit_admitted", "hardware_timing_admitted")
CHECKPOINT = "COMPLETE_G_STORAGE_SCREEN_NOT_ROUTING_OR_BOARD_ADMISSION"
QUERY_STATUSES = ("PHYSICAL_SITE_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION",
                  "PLATFORM_PBLOCK_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION", "FAILED_RETAINED")
FIT_STATUSES = ("URAM_PLACEMENT_CONFLICT_REQUIRES_NEW_CONFIG",
                "PLATFORM_URAM_PLACEMENT_CONFLICT_REQUIRES_NEW_CONFIG",
                "PHYSICAL_URAM_SCREEN_PASS_PLATFORM_AND_ROUTING_UNPROVEN")


def validate_query(attempt, report):
    if report["status"] not in QUERY_STATUSES or bool(report["errors"]) != (
            report["status"] == "FAILED_RETAINED"):
        raise ValueError("terminal storage query required")
    if any(report.get(key) is not False for key in (*CLAIMS, "platform_available_resources_admitted")):
        raise ValueError("storage query overstates hardware admission")
    unchanged(report["source"])
    execution = report.get("execution")
    if execution is not None and execution != json.loads((attempt / "execution.resources.json").read_text()):
        raise ValueError("storage query resource record changed")
    if report["status"] != "FAILED_RETAINED":
        if execution is None or execution["exit_code"] or execution["timed_out"]:
            raise ValueError("storage query pass requires completed execution")
        query_capacity(attempt, platform=report["status"] == QUERY_STATUSES[1])


def validate_fit(attempt, report):
    if report["status"] not in FIT_STATUSES or any(report.get(key) is not False for key in CLAIMS):
        raise ValueError("unpromoted terminal storage screen required")
    unchanged(report["source"])
    source = attempt / "source"
    kernels, placements = topology((source / "link.cfg").read_text())
    estimates = {name: resources(source / "hls" / (name + ".xml"), name) for name in kernels}
    physical = capacity(source / "uram_capacity.csv")
    if physical != report["physical_uram_capacity"]:
        raise ValueError("physical capacity disagrees with frozen query")
    original = account(kernels, placements, estimates, physical)
    changed = dict(placements)
    if changed.get("lksg_stream_4") == "SLR0":
        changed["lksg_stream_4"] = "SLR1"
    relocated = account(kernels, changed, estimates, physical)
    for expected, actual in ((original, report), (relocated, report["single_cu_relocation_screen"])):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("storage ledger disagrees with frozen topology/HLS reports")
        if "platform_storage_screen" in actual:
            platform = capacity(source / "platform/platform_uram_capacity.csv")
            if actual["platform_storage_screen"] != platform_screen(expected, physical, platform):
                raise ValueError("platform storage screen changed")


def validate(attempt, report):
    if report["status"] in QUERY_STATUSES:
        validate_query(attempt, report)
        kind = "query"
    else:
        validate_fit(attempt, report)
        kind = "ledger"
    return kind


def package(output, attempts):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct named storage attempts required")
    reports = [(path, json.loads((path / "results.json").read_text())) for path in attempts]
    kinds = [validate(path, report) for path, report in reports]
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for (attempt, report), kind in zip(reports, kinds):
        paths = {path for path in attempt.iterdir() if path.is_file()}
        paths.update(path for path in (attempt / "source").rglob("*") if path.is_file())
        if any(path.is_symlink() for path in paths):
            raise ValueError("storage capsule cannot contain symlinks")
        # The platform DCP/XSA is machine-local vendor input, indexed but not redistributed.
        excluded = [pin for pin in report["source"] if not Path(pin["path"]).is_relative_to(attempt / "source")]
        entry = {"attempt": attempt.name, "source": str(attempt), "kind": kind,
                 "status": report["status"], "files": [], "external_input_pins": excluded}
        archive = output / (attempt.name + ".tar.gz")
        with tarfile.open(archive, "w:gz") as stream:
            for path in sorted(paths):
                name = path.relative_to(attempt).as_posix()
                stream.add(path, arcname=name, recursive=False)
                entry["files"].append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
        entry.update(archive=archive.name, sha256=sha256_file(archive), bytes=archive.stat().st_size)
        entries.append(entry)
    index = {"status": CHECKPOINT, "attempts": entries, **dict.fromkeys(CLAIMS, False),
             "platform_free_capacity_admitted": False, "publication_match_admitted": False}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != CHECKPOINT or any(index.get(key) is not False for key in (
            *CLAIMS, "platform_free_capacity_admitted", "publication_match_admitted")):
        raise ValueError("invalid storage checkpoint admission boundary")
    for entry in index["attempts"]:
        archive = output / entry["archive"]
        if archive.parent != output or sha256_file(archive) != entry["sha256"]:
            raise ValueError("storage archive changed")
        with tarfile.open(archive) as stream:
            if sorted(stream.getnames()) != sorted(row["path"] for row in entry["files"]):
                raise ValueError("storage archive scope changed")
            for row in entry["files"]:
                name = PurePosixPath(row["path"])
                info = stream.getmember(row["path"])
                if name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"]:
                    raise ValueError("unsafe storage archive member")
                if hashlib.sha256(stream.extractfile(info).read()).hexdigest() != row["sha256"]:
                    raise ValueError("storage archive member changed")
            report = json.load(stream.extractfile("results.json"))
        allowed = QUERY_STATUSES if entry["kind"] == "query" else FIT_STATUSES if entry["kind"] == "ledger" else ()
        if report["status"] != entry["status"] or entry["status"] not in allowed or any(
                report.get(key) is not False for key in CLAIMS):
            raise ValueError("storage archive and index disagree")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
