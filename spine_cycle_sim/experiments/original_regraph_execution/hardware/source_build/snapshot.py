"""Copy tracked clean author files, then invoke only the author's topology generator."""

from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.upstream_controls.sources import GENERATED_FILES, read_pins
from .. import artifact, sources
from .configuration import GENERATOR_PYTHON


def tracked_files(source: Path) -> list[str]:
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode().split("\0")[:-1]
    if not names or len(set(names)) != len(names):
        raise ValueError("unique tracked author files required")
    for name in names:
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or
                any((source / parent).is_symlink() for parent in (path, *path.parents))):
            raise ValueError("regular in-tree tracked author files required")
        artifact.identity(source / path)
    return names


def unchanged(pins: list[dict]) -> None:
    if any(artifact.identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("frozen build source, tool, environment or artifact changed")


def prepare(root: Path, upstream: Path, output: Path) -> dict:
    pin_file = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"
    pin = read_pins(pin_file)["regraph"]
    review = sources.review(upstream, pin)
    names = tracked_files(upstream)
    original = [artifact.identity(upstream / name) for name in names]
    destination = output / "source"
    destination.mkdir()
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upstream / name, target)
    # The author generator overwrites six known outputs; no C-simulation helper headers are added.
    command = [str(GENERATOR_PYTHON), "autogen/autogen.py", "11", "3", "true", "false"]
    execution = run_bounded(command, destination, output / "generator",
                            timeout=60, memory_gib=2, reserve_gib=32)
    if execution["exit_code"] or execution["timed_out"]:
        raise ValueError("author topology generation failed; preserve raw generator logs")
    generated_names = sorted(str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file())
    if generated_names != sorted(names):
        raise ValueError("author generator added or removed an unexpected source file")
    copied = [artifact.identity(destination / name) for name in names]
    changed = [name for name, before, after in zip(names, original, copied)
               if before["sha256"] != after["sha256"]]
    if set(changed) - set(GENERATED_FILES):
        raise ValueError("device source changed outside the six author-generated files")
    unchanged(original)
    if sources.review(upstream, pin) != review:
        raise ValueError("original author worktree changed during snapshot")
    return {"source_review": review, "upstream": str(upstream), "source": str(destination),
            "pins": [artifact.identity(pin_file), *original, *copied],
            "generator": execution, "generator_command": command,
            "generated_files": list(GENERATED_FILES), "changed_generated_files": changed,
            "device_algorithm_edits": False}
