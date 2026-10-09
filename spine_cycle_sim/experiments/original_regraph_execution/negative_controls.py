"""Deliberately damage input controls; never mutate the admitted source captures."""

from __future__ import annotations

import shutil
import struct
from pathlib import Path


def run_negative_controls(binary: Path, output: Path, admitted: dict, contract: dict, execute) -> list[dict]:
    source = Path(admitted["directory"])
    cases = [
        ("header", "execution.u32le", 0, 0, "descriptor header"),
        ("assignment", "execution.u32le", 10, 3, "task ordering, assignment or extent"),
        ("source", "tasks.u32le", 0, admitted["layout"]["summary"]["vertices"] + 1, "task source/lookahead"),
        ("arithmetic", "initial.u32le", 0, 2147483647, "signed arithmetic domain"),
        ("edge_value", "tasks.u32le", 1, None, "pre-Apply sum differs"),
        ("truncated", "degrees.u32le", None, None, "input capture extent mismatch"),
    ]
    results = []
    for name, filename, word, value, diagnostic in cases:
        directory = output / "negative" / name
        inputs, capture = directory / "input", directory / "capture"
        inputs.mkdir(parents=True); capture.mkdir()
        for path in source.iterdir():
            if path.name != filename:
                (inputs / path.name).symlink_to(path)
        target = inputs / filename
        shutil.copyfile(source / filename, target)
        with target.open("r+b") as stream:
            if word is None:
                stream.truncate(4)
            else:
                stream.seek(word * 4)
                if value is None:
                    value = (struct.unpack("<I", stream.read(4))[0] + 1) % 65536
                    stream.seek(word * 4)
                stream.write(struct.pack("<I", value))
        step = execute("negative_" + name, [str(binary), str(inputs), str(capture), "16", "64", "0",
            str(contract["max_cycles"])], contract["run_timeout_seconds"], expected_failure=True)
        observed = Path(step["stderr"]).read_text()
        if step["exit_code"] != 1 or step["timed_out"] or diagnostic not in observed:
            raise ValueError("whole-A4 damaged input did not produce the expected rejection")
        results.append({"id": name, "expected_rejection": True, "diagnostic": diagnostic})
    return results
