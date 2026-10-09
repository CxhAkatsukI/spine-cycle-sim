"""Prove that the compiled comparator rejects damaged/excess source data."""

from __future__ import annotations

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded


def run_negative_controls(root: Path, output: Path, binary: Path,
                          captures: list[dict], contract: dict) -> list[dict]:
    fixtures = output / "negative_fixtures"
    fixtures.mkdir()
    original = Path(captures[0]["path"])
    cases = (
        ("changed_word", "differs from original source"),
        ("truncated_word", "truncated original-source capture"),
        ("excess_word", "excess original-source capture words"),
    )
    rows = []
    for name, diagnostic in cases:
        destination = fixtures / f"{name}.u32le"
        shutil.copyfile(original, destination)
        with destination.open("r+b") as stream:
            if name == "changed_word":
                value = int.from_bytes(stream.read(4), "little") ^ 1
                stream.seek(0)
                stream.write(value.to_bytes(4, "little"))
            elif name == "truncated_word":
                stream.truncate(destination.stat().st_size - 4)
            else:
                stream.seek(0, 2)
                stream.write(bytes(4))
        row = {"id": name, "input_sha256": sha256_file(destination),
               "input_bytes": destination.stat().st_size, "expected_diagnostic": diagnostic,
               **run_bounded([str(binary), str(destination), captures[1]["path"]], root,
                   output / f"negative_{name}", timeout=contract["run_timeout_seconds"],
                   memory_gib=contract["memory_limit_gib"], reserve_gib=contract["reserve_gib"])}
        row["expected_rejection"] = (row["exit_code"] == 1 and not row["timed_out"] and
                                     diagnostic in Path(row["stderr"]).read_text())
        rows.append(row)
    return rows
