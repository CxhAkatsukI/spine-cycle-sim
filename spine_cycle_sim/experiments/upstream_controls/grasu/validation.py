"""Damage actual admitted source outputs; fail if any corruption is accepted."""

import hashlib
import shutil
import tempfile
from pathlib import Path

from .analysis import analyze, check_protocol, parse_stdout


def negative_controls(directory: Path, stdout: Path, stderr: Path) -> list[dict]:
    payload = (directory / "protocol.u32le").read_bytes(); result = check_protocol(payload, 7); records = []

    def reject(name, operation, expected, damaged):
        try: operation()
        except ValueError as error:
            if expected not in str(error): raise ValueError("G negative hit wrong gate: " + name) from error
            records.append({"id": name, "rejected": True, "diagnostic": str(error), "damaged_sha256": hashlib.sha256(damaged).hexdigest()})
        else: raise ValueError("G corruption was accepted: " + name)

    # First batch has 384 updates, followed by fixed six-word memory records.
    request = (9 + 384 * 6) * 4
    for name, offset, diagnostic in (("header", 0, "header"), ("packet_address", 36, "packet/dispatch"),
            ("packet_operation", 52, "packet/dispatch"), ("route", 56, "packet/dispatch"),
            ("memory_address", request + 12, "memory request"), ("memory_value", request + 16, "memory request")):
        damaged = bytearray(payload); damaged[offset] ^= 1; damaged = bytes(damaged)
        reject(name, lambda: check_protocol(damaged, 7), diagnostic, damaged)
    for name, damaged, diagnostic in (("truncated", payload[:-4], "truncated"), ("trailing", payload + b"\0" * 4, "trailing")):
        reject(name, lambda: check_protocol(damaged, 7), diagnostic, damaged)
    text = stdout.read_text().replace('"updates":896', '"updates":true')
    reject("boolean_counter", lambda: parse_stdout(text, result), "counters", text.encode())
    with tempfile.TemporaryDirectory(prefix="grasu-negative-") as temporary:
        target = Path(temporary)
        shutil.copyfile(directory / "protocol.u32le", target / "protocol.u32le")
        damaged = bytearray((directory / "state.u32le").read_bytes()); damaged[-4] ^= 1
        (target / "state.u32le").write_bytes(damaged)
        reject("untouched_final_slot", lambda: analyze(target, 7, stdout, stderr), "full-state", damaged)
        diagnostic = stderr.read_bytes() + b"runtime error: injected sanitizer diagnostic\n"
        (target / "stderr.txt").write_bytes(diagnostic)
        reject("sanitizer_diagnostic", lambda: analyze(target, 7, stdout, target / "stderr.txt"), "diagnostics", diagnostic)
    return records
