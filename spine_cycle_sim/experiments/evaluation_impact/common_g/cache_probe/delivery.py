"""Package cache probes and failed attempts without promoting timing claims."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import analyze


def selected_files(attempt, report):
    paths = {attempt / "results.json"}
    paths.update(path for path in (attempt / "source").rglob("*") if path.is_file())
    for arm in report["arms"]:
        folder = attempt / arm["arm"]
        paths.update(path for path in folder.iterdir() if path.is_file())
        for owner in ("syn/report", "csim/report", "sim/report"):
            paths.update(path for path in (folder / "project/solution" / owner).rglob("*")
                         if path.is_file())
        # XSIM may leave deadlock evidence outside sim/report when cosim fails.
        sim = folder / "project/solution/sim"
        paths.update(path for path in sim.rglob("*") if path.is_file() and
                     ("deadlock" in path.name.lower() or path.name in ("xsim.log", "simulate.log")))
    return sorted(paths)


def package(output: Path, attempts: list[Path]):
    if not attempts or len({path.name for path in attempts}) != len(attempts):
        raise ValueError("distinct named attempts required")
    entries = []
    for attempt in attempts:
        report = json.loads((attempt / "results.json").read_text())
        if report["status"] not in (
                "FAILED_RETAINED", "FULL_CACHE_RTL_PASS_WITH_SEPARATE_CLOCK_GATES",
                "ISOLATED_BANK_RTL_PASS_WITH_SEPARATE_CLOCK_GATES"):
            raise ValueError("do not freeze an active or unknown attempt")
        for pin in report["source"]:
            path = Path(pin["path"])
            path.relative_to(attempt / "source")
            if sha256_file(path) != pin["sha256"]:
                raise ValueError("frozen probe source changed")
        if any(report.get(key) is not False for key in (
                "hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted")):
            raise ValueError("isolated probe cannot promote a baseline")
        if "declared_arms" in report and [arm["arm"] for arm in report["arms"]] != report["declared_arms"]:
            raise ValueError("incomplete declared cache-probe scope")
        summary = []
        for arm in report["arms"]:
            script = attempt / arm["arm"] / "run.tcl"
            if sha256_file(script) != arm["script_sha256"]:
                raise ValueError("frozen HLS command changed")
            if "analysis" not in arm:
                summary.append({"arm": arm["arm"], "error": arm.get("error", "incomplete arm")})
                continue
            full = arm["arm"] in ("original_full", "registered_full")
            observation = analyze(attempt / arm["arm"], full=full,
                                  full_extended=full and report.get("full_stimuli_version") == 2)
            for key in ("top_clock_ns", "top_resources", "transactions", "target_5ns_met"):
                # Earlier retained attempts did not yet record transactions.
                if key in arm["analysis"] and observation[key] != arm["analysis"][key]:
                    raise ValueError("analysis no longer agrees with raw reports")
            for before in (*arm["analysis"]["reports"], arm["analysis"]["cosim"]):
                path = Path(before["path"])
                path.relative_to(attempt / arm["arm"])
                if sha256_file(path) != before["sha256"]:
                    raise ValueError("frozen HLS report changed")
            summary.append({"arm": arm["arm"], **{key: observation[key] for key in (
                "top_clock_ns", "target_5ns_met", "top_resources", "state_control_calls",
                "same_row_incremental_cycles_per_update")}})
        entries.append({"attempt": attempt.name, "source": str(attempt),
                        "status": report["status"], "arms": summary, "files": []})
    output.mkdir(parents=True, exist_ok=False)
    for attempt, entry in zip(attempts, entries):
        archive = output / (attempt.name + ".tar.gz")
        report = json.loads((attempt / "results.json").read_text())
        with tarfile.open(archive, "w:gz") as stream:
            for path in selected_files(attempt, report):
                name = path.relative_to(attempt).as_posix()
                stream.add(path, arcname=name, recursive=False)
                entry["files"].append({"path": name, "sha256": sha256_file(path),
                                       "bytes": path.stat().st_size})
        entry.update(archive=archive.name, sha256=sha256_file(archive), bytes=archive.stat().st_size)
    index = {"status": "CACHE_PROBE_CHECKPOINT_NOT_G_ADMISSION", "attempts": entries,
             "hardware_timing_admitted": False, "production_baseline_admitted": False,
             "publication_match_admitted": False, "new_spine_comparison_executed": False}
    atomic_write_json(output / "index.json", index)
    verify(output)
    return index


def verify(output: Path):
    index = json.loads((output / "index.json").read_text())
    for entry in index["attempts"]:
        archive = output / entry["archive"]
        if sha256_file(archive) != entry["sha256"]:
            raise ValueError("archive identity changed")
        with tarfile.open(archive) as stream:
            if sorted(stream.getnames()) != sorted(row["path"] for row in entry["files"]):
                raise ValueError("archive scope changed")
            for row in entry["files"]:
                member = stream.extractfile(row["path"])
                if member is None or hashlib.sha256(member.read()).hexdigest() != row["sha256"]:
                    raise ValueError("archived evidence changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    args = parser.parse_args()
    package(args.output.resolve(), [path.resolve() for path in args.attempt])
