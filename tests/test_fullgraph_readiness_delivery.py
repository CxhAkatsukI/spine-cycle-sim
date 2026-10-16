import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import analysis, delivery, preparation
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.recheck import CLAIMS, recheck, smoke_rows
import test_fullgraph_readiness as readiness_tests


def fixture(root):
    inputs = root / "inputs"
    inputs.mkdir()
    manifest, _ = readiness_tests.PreparationTests().fixture(inputs)
    attempt = root / "attempt"
    attempt.mkdir()
    raw = attempt / "raw"
    raw.mkdir()
    source = attempt / "source" / "host.cpp"
    source.parent.mkdir()
    source.write_text("// frozen production source fixture\n")
    report = {"status": analysis.PASS, "source_revision": "1" * 40,
              "matrix": preparation.matrix(manifest), "smokes": [], "cases": [],
              "steps": [], "compiler_diagnostics": {}, "errors": [],
              "pins": [preparation.identity(source)],
              "memory_events_after": "max 0\noom 0\noom_kill 0\noom_group_kill 0\n",
              **{key: False for key in CLAIMS}}
    report["pins"] += [row["input_identity"] for row in report["matrix"]]
    rows = smoke_rows(attempt) + report["matrix"]
    for algorithm in preparation.ALGORITHMS:
        label = "compile_" + algorithm
        report["compiler_diagnostics"][algorithm] = []
        add_step(report, attempt, label, preparation.compile_command(
            Path("/compiler"), attempt / "source", algorithm, attempt / algorithm,
            Path("/xrt"), Path("/hls")), "", "[]")
    for row in rows:
        label = row["dataset"] + "_" + row["algorithm"]
        stdout = readiness_tests.prepared_log(row)
        add_step(report, attempt, label,
                 preparation.prepare_command(attempt / row["algorithm"], row, attempt / (label + ".unused-result")), stdout, "")
        report["smokes" if row["dataset"] == "SMOKE" else "cases"].append(analysis.analyze(row, stdout, ""))
    save(attempt, report)
    return attempt, report


def add_step(report, attempt, label, command, stdout, stderr):
    record = {"command": command, "cwd": str(attempt), "exit_code": 0,
              "stop_reason": "process_exit", "cleanup_snapshot_error": None}
    report["steps"].append({"label": label, **record})
    for suffix, text in ((".stdout.txt", stdout), (".stderr.txt", stderr),
                         (".resources.json", json.dumps(record))):
        (attempt / "raw" / (label + suffix)).write_text(text)


def save(attempt, report):
    (attempt / "results.json").write_text(json.dumps(report))


def rewrite_member(destination, name, change):
    archive = destination / "raw_fullgraph_readiness.tar.gz"
    with tarfile.open(archive, "r:gz") as bundle:
        entries = [(member.name, bundle.extractfile(member).read()) for member in bundle.getmembers()]
    with tarfile.open(archive, "w:gz") as bundle:
        for path, data in entries:
            if path == name:
                data = change(data)
            member = tarfile.TarInfo(path)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    index = json.loads((destination / "index.json").read_text())
    for item in index["files"]:
        if item["path"] == name:
            data = change(dict(entries)[name])
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    index.update(archive_bytes=archive.stat().st_size, archive_sha256=sha256_file(archive))
    (destination / "index.json").write_text(json.dumps(index))


class DeliveryTests(unittest.TestCase):
    def test_complete_round_trip_is_portable_without_live_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = fixture(root)
            destination = root / "delivery"
            record = delivery.deliver([attempt], destination)
            attempt.rename(root / "moved-attempt")
            self.assertEqual(delivery.verify(destination), record)
            self.assertEqual(record["attempts"][0]["cases"], 24)
            self.assertFalse(record["attempts"][0]["hardware_timing_measured"])

    def test_retains_compiler_gate_failure_without_promoting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, report = fixture(root)
            report.update(status="FAILED_RETAINED", steps=report["steps"][:1], smokes=[], cases=[],
                          errors=["ValueError('unexpected host compilation diagnostic')"])
            report.pop("compiler_diagnostics")
            (attempt / "raw/compile_weighted_sssp.stderr.txt").write_text("unreviewed upstream note\n")
            save(attempt, report)
            record = delivery.deliver([attempt], root / "delivery")
            self.assertEqual(record["attempts"][0]["status"], "FAILED_RETAINED")
            self.assertEqual(record["attempts"][0]["cases"], 0)

    def test_running_claims_missing_rows_duplicate_steps_memory_events_and_commands_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            attempt, good = fixture(Path(directory))
            for mutation in ("running", "claim", "missing", "duplicate", "oom", "command", "smoke"):
                with self.subTest(mutation=mutation):
                    report = copy.deepcopy(good)
                    if mutation == "running":
                        report["status"] = "RUNNING_AU_weighted_sssp"
                    elif mutation == "claim":
                        report["hardware_timing_measured"] = True
                    elif mutation == "missing":
                        report["cases"].pop()
                    elif mutation == "duplicate":
                        report["steps"][-1] = report["steps"][0]
                    elif mutation == "oom":
                        report["memory_events_after"] = report["memory_events_after"].replace("oom_kill 0", "oom_kill 1")
                    elif mutation == "smoke":
                        report["smokes"].pop()
                    else:
                        report["steps"][3]["command"][1] = "--program-board"
                    with self.assertRaises(ValueError):
                        recheck(report, lambda name: (attempt / name).read_text())

    def test_raw_analysis_rejects_rehashed_inconsistent_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = fixture(root)
            destination = root / "delivery"
            delivery.deliver([attempt], destination)
            rewrite_member(destination, "attempts/0/raw/AU_weighted_sssp.stdout.txt",
                           lambda data: data.replace(b"k4_frontends=4", b"k4_frontends=8"))
            with self.assertRaises(ValueError):
                delivery.verify(destination)

    def test_consistent_raw_command_edits_cannot_change_execution_boundary_or_capacity(self):
        for index, before, after in ((0, "-DGRASU_MAX_CACHE_SEGMENT=131072", "-DGRASU_MAX_CACHE_SEGMENT=16"),
                                     (3, "--prepare-only", "--program-board")):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                attempt, report = fixture(Path(directory))
                step = report["steps"][index]
                step["command"] = [after if token == before else token for token in step["command"]]
                (attempt / "raw" / (step["label"] + ".resources.json")).write_text(json.dumps(
                    {key: value for key, value in step.items() if key != "label"}))
                with self.assertRaises(ValueError):
                    recheck(report, lambda name: (attempt / name).read_text())

    def test_snapshot_must_match_frozen_pin_even_after_rehash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = fixture(root)
            destination = root / "delivery"
            delivery.deliver([attempt], destination)
            rewrite_member(destination, "attempts/0/source/host.cpp", lambda data: data + b"// changed\n")
            with self.assertRaisesRegex(ValueError, "frozen input pin"):
                delivery.verify(destination)

    def test_drift_symlinks_duplicates_and_overwrite_rejected(self):
        for mutation in ("drift", "symlink", "duplicate", "overwrite"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, _ = fixture(root)
                destination = root / "delivery"
                attempts = [attempt]
                if mutation == "drift":
                    (attempt / "source/host.cpp").write_text("// changed\n")
                elif mutation == "symlink":
                    (attempt / "raw/alias").symlink_to(attempt / "results.json")
                elif mutation == "duplicate":
                    attempts.append(attempt)
                else:
                    destination.mkdir()
                with self.assertRaises(ValueError):
                    delivery.deliver(attempts, destination)

    def test_tampered_index_cannot_promote_board_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = fixture(root)
            destination = root / "delivery"
            record = delivery.deliver([attempt], destination)
            record["attempts"][0]["hardware_timing_measured"] = True
            (destination / "index.json").write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                delivery.verify(destination)
