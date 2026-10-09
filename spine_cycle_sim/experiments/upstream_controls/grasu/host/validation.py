"""Original-host failure gates, malformed traces and actual capture rejection."""

import hashlib
from pathlib import Path
import shutil
import tempfile

from .analysis import analyze
from .fixtures import read

INVALID = (
    ("duplicate_initial", "2 2 0\n0 1\n0 1\n", "G initial duplicate"),
    ("absent_delete", "2 0 1\n0 1 0\n", "G absent deletion"),
    ("duplicate_insert", "2 1 1\n0 1\n0 1 1\n", "G duplicate insertion"),
    ("vertex", "2 0 1\n0 2 1\n", "G host input vertex"),
    ("truncated", "2 1 0\n", "G host input vertex"),
    ("operation", "2 0 1\n0 1 2\n", "G host input operation"),
    ("trailing", "2 0 0\njunk\n", "G host input trailing fields"),
)


def input_negatives(binary: Path, output: Path, execute):
    records = []
    for name, text, diagnostic in INVALID:
        directory = output / ("negative_" + name); directory.mkdir()
        path = directory / "input.txt"; path.write_text(text)
        step = execute("negative_" + name, [str(binary), str(path), str(directory)], expected_code=1)
        if diagnostic not in Path(step["stderr"]).read_text(): raise ValueError("G invalid trace hit wrong gate")
        records.append({"id": name, "rejected": True, "diagnostic": diagnostic, "input_sha256": hashlib.sha256(text.encode()).hexdigest()})
    return records


def bounds_negatives(binaries: dict, input_path: Path, output: Path, execute):
    records = []
    for variant in ("original", "row_guard"):
        directory = output / ("bounds_" + variant); directory.mkdir()
        step = execute("bounds_" + variant, [str(binaries[variant]), str(input_path), str(directory)], expected_code=-6)
        diagnostic = Path(step["stderr"]).read_text()
        if "Assertion '__n < this->size()' failed." not in diagnostic or "long unsigned int" not in diagnostic:
            raise ValueError("G original host did not fail at the expected vector bounds gate")
        records.append({"id": variant, "expected_abort": True, "exit_code": step["exit_code"],
            "stderr_sha256": hashlib.sha256(diagnostic.encode()).hexdigest()})
    return records


def capture_negatives(input_path: Path, original: Path, stdout: Path, stderr: Path):
    updates = len(read(input_path)[2]); records = []
    with tempfile.TemporaryDirectory(prefix="grasu-host-negative-") as temporary:
        target = Path(temporary)
        for path in original.iterdir():
            if path.is_file(): shutil.copyfile(path, target / path.name)

        def reject(name, expected, damaged):
            try: analyze(input_path, target, target / "stdout.txt", target / "stderr.txt")
            except ValueError as error:
                if expected not in str(error): raise ValueError("G capture negative hit wrong gate: " + name) from error
                records.append({"id": name, "rejected": True, "diagnostic": str(error), "damaged_sha256": hashlib.sha256(damaged).hexdigest()})
            else: raise ValueError("G damaged host capture accepted: " + name)

        for name, filename, offset, diagnostic in (
            ("mapping", "mapping.u32le", 0, "permutation"), ("offsets", "row_offsets.u64le", -8, "offsets"),
            ("binary", "binary.u64le", 0, "search heads"), ("prepared", "prepared.u64le", -8, "prepared PMA"),
            ("mapped_operation", "mapped_updates.u64le", 7, "mapped updates"), ("updated", "updated.u64le", -8, "updated PMA"),
            ("protocol_header", "protocol.u32le", 0, "header"), ("protocol_route", "protocol.u32le", 36, "packet"),
            ("request_address", "protocol.u32le", 16 + updates * 24 + 12, "offset request")):
            shutil.copyfile(stdout, target / "stdout.txt"); shutil.copyfile(stderr, target / "stderr.txt")
            path = target / filename; original_bytes = path.read_bytes(); damaged = bytearray(original_bytes)
            if name == "mapping": damaged[0:4] = damaged[4:8]
            else: damaged[offset] ^= 1
            path.write_bytes(damaged); reject(name, diagnostic, damaged); path.write_bytes(original_bytes)
        for name, path, damaged, diagnostic in (
            ("counter", target / "stdout.txt", stdout.read_bytes().replace(f'"updates":{updates}'.encode(), b'"updates":true'), "counters"),
            ("diagnostic", target / "stderr.txt", stderr.read_bytes() + b"runtime error: injected UB\n", "diagnostics")):
            shutil.copyfile(stdout, target / "stdout.txt"); shutil.copyfile(stderr, target / "stderr.txt")
            path.write_bytes(damaged); reject(name, diagnostic, damaged)
        shutil.copyfile(stdout, target / "stdout.txt"); shutil.copyfile(stderr, target / "stderr.txt")
        path = target / "updated.u64le"; damaged = path.read_bytes()[:-8]; path.write_bytes(damaged)
        reject("truncated_capture", "extent", damaged)
    return records
