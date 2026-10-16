"""Explicit placement-only controls; never rewrite the author snapshot."""

from pathlib import Path

from .. import artifact
from . import configuration as config

DEFAULT = "author"
CHOICES = (DEFAULT, "apply_slr0")


def validate(topology: str, placement: str) -> None:
    config.counts(topology)
    if not isinstance(placement, str) or placement not in CHOICES:
        raise ValueError("explicit author or apply_slr0 placement required")
    if placement != DEFAULT and topology != "a4":
        raise ValueError("apply_slr0 is only an A4 placement control")


def move_apply(contents: str) -> str:
    # v++ connectivity permits repeated keys, unlike ordinary INI mappings.
    lines = contents.splitlines(keepends=True)
    section = None
    matches = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("["):
            if not stripped.endswith("]"):
                raise ValueError("malformed connectivity section")
            section = stripped[1:-1]
            continue
        key, equal, value = stripped.partition("=")
        if section == "connectivity" and equal and key.strip() == "slr":
            instance, colon, location = value.strip().partition(":")
            if colon and instance == "kernelApply_1":
                if location != "SLR1":
                    raise ValueError("author Apply must start in SLR1")
                matches.append(index)
    if len(matches) != 1:
        raise ValueError("exactly one author Apply placement required")
    index = matches[0]
    original = lines[index]
    ending = "\r\n" if original.endswith("\r\n") else "\n" if original.endswith("\n") else ""
    lines[index] = "slr=kernelApply_1:SLR0" + ending
    return "".join(lines)


def prepare(source: Path, output: Path, topology: str, placement: str = DEFAULT) -> dict:
    validate(topology, placement)
    author = source / "acc_template/connectivity.cfg"
    result = {"name": placement, "config": str(author), "pins": [], "changes": [],
              "device_algorithm_edits": False, "clock_or_timing_constraint_edits": False}
    if placement == DEFAULT:
        return result
    before = artifact.identity(author)
    destination = output / "placement"
    destination.mkdir()
    target = destination / "connectivity.cfg"
    target.write_text(move_apply(author.read_text()))
    if artifact.identity(author) != before:
        raise ValueError("author connectivity changed during placement preparation")
    result.update(config=str(target), pins=[before, artifact.identity(target)],
                  changes=[{"instance": "kernelApply_1", "from": "SLR1", "to": "SLR0"}])
    return result
