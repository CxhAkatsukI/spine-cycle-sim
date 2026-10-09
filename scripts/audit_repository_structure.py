"""Inventory tracked source and generate topic catalogs without running models."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import posixpath
import subprocess
from typing import Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".cpp", ".hpp", ".h", ".py", ".sh"}
SOURCE_DIRECTORIES = {"cpp", "spine_cycle_sim", "scripts", "tests", "tools"}
DOCUMENT_CATALOG = Path("docs/repository/document_catalog.md")
SCRIPT_CATALOG = Path("scripts/CATALOG.md")
DOCUMENT_LOCATIONS = Path("docs/repository/document_locations.json")
DOCUMENT_TOPICS = {
    "architecture": "Architecture and contracts",
    "implementation/spine": "Spine implementation",
    "implementation/grasu_regraph": "GraSU and ReGraph implementation",
    "implementation/runtime": "Runtime and memory integration",
    "implementation/algorithms": "Algorithm implementation",
    "experiments/calibration": "Hardware alignment and calibration records",
    "experiments/comparisons": "Workloads and comparison records",
    "experiments/cost_models": "Cost and resource analysis",
    "history/early_models": "Early component-model history",
    "history/campaigns": "Campaign history",
    "history/runtime_optimization": "Runtime optimization history",
}
DOCUMENT_GUIDES = (
    "docs/README.md", "docs/implementation/README.md",
    "docs/experiments/README.md", "docs/history/README.md",
    "docs/evidence/README.md", "docs/repository/README.md",
    *(f"docs/{directory}/README.md" for directory in DOCUMENT_TOPICS),
)


def document_locations(root: Path) -> dict[str, str]:
    path = root / DOCUMENT_LOCATIONS
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("moves"), dict):
        raise ValueError("Unsupported document relocation map")
    moves = data["moves"]
    for old, new in moves.items():
        if not isinstance(new, str):
            raise ValueError(f"Invalid document destination for {old}")
        source, destination = Path(old), Path(new)
        if (
            len(source.parts) != 2 or source.parts[0] != "docs"
            or source.suffix != ".md" or source.name == "README.md"
            or destination.is_absolute() or ".." in destination.parts
            or destination.name != source.name
            or "/".join(destination.parts[1:-1]) not in DOCUMENT_TOPICS
            or destination.parts[0] != "docs"
        ):
            raise ValueError(f"Unsafe or unsupported document relocation: {old} -> {new}")
    if len(set(moves.values())) != len(moves):
        raise ValueError("Document relocation destinations must be unique")
    return moves


def check_document_layout(root: Path) -> list[str]:
    errors = []
    try:
        moves = document_locations(root)
    except (ValueError, TypeError) as error:
        return [str(error)]
    if not moves:
        errors.append(f"Missing or empty relocation map: {DOCUMENT_LOCATIONS}")
    for old, new in moves.items():
        if (root / old).exists():
            errors.append(f"Old flat record still exists: {old}")
        if not (root / new).is_file():
            errors.append(f"Missing relocated record: {new}")
    for path in sorted((root / "docs").glob("*.md")):
        if path.name != "README.md":
            errors.append(f"Place this record in a topic directory: {path.relative_to(root)}")
    for guide in DOCUMENT_GUIDES:
        if not (root / guide).is_file():
            errors.append(f"Missing reading guide: {guide}")
    return errors


def tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    paths = [Path(value.decode("utf-8")) for value in result.stdout.split(b"\0") if value]
    moves = document_locations(root)
    # Reflect unstaged relocations without staging unrelated user changes.
    return sorted(
        Path(moves.get(path.as_posix(), path.as_posix()))
        if not (root / path).exists() else path
        for path in paths
    )


def count_lines(path: Path) -> int:
    data = path.read_bytes()
    return data.count(b"\n") + int(bool(data) and not data.endswith(b"\n"))


def build_inventory(root: Path, paths: Iterable[Path]) -> dict:
    paths = list(paths)
    directories = Counter(path.parts[0] for path in paths)
    code = []
    for path in paths:
        if path.parts[0] in SOURCE_DIRECTORIES and path.suffix in SOURCE_SUFFIXES:
            code.append({"path": path.as_posix(), "lines": count_lines(root / path)})
    code.sort(key=lambda row: (-row["lines"], row["path"]))
    return {
        "tracked_files": len(paths),
        "files_by_top_level": dict(sorted(directories.items())),
        "top_level_markdown_records": sum(
            len(path.parts) == 2 and path.parts[0] == "docs" and path.suffix == ".md"
            for path in paths
        ),
        "source_lines": sum(row["lines"] for row in code),
        "largest_source_files": code[:15],
        "scope": "tracked files; no performance or evidence-admission inference",
    }


def document_topic(name: str) -> str:
    if name.startswith(("current_fpga", "k4_fpga", "hw_", "refactor31")):
        return "FPGA alignment and calibration investigations"
    if name.startswith(("grasu", "askubuntu")):
        return "GraSU and ReGraph implementation records"
    if name.startswith(("spine", "device_")):
        return "Spine implementation records"
    if name.startswith(("simulator_", "scheduler_", "dramsim3_", "sst_")):
        return "Runtime, scheduling, and memory integration"
    if name.startswith(("candidate", "formal", "publication", "shared_comparison", "large_")):
        return "Campaigns and candidate investigations"
    if any(word in name for word in ("energy", "power", "area", "rq3", "component_model")):
        return "Analysis and resource models"
    return "Contracts and supporting design records"


def script_topic(name: str) -> str:
    if name.startswith("run_"):
        return "Execution and experiment drivers"
    if name.startswith("analyze_"):
        return "Analysis and calibration"
    if name.startswith(("render_", "export_", "finalize_", "package_")):
        return "Export, packaging, and rendering"
    if name.startswith(("audit_", "check_", "validate_")):
        return "Audits and validation"
    if name.startswith(("build_", "generate_", "freeze_", "extract_", "prepare_", "materialize_")):
        return "Input preparation, profiles, and freezes"
    return "Supporting commands"


def render_groups(groups: dict[str, list[Path]], prefix: str) -> list[str]:
    lines = []
    for topic, paths in sorted(groups.items()):
        lines.extend([f"## {topic}", ""])
        for path in sorted(paths):
            target = quote(prefix + path.name, safe="/._-")
            lines.append(f"- [{path.name}]({target})")
        lines.append("")
    return lines


def render_document_catalog(paths: Iterable[Path]) -> str:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        if path.parts[0] != "docs" or path.suffix != ".md" or path.name == "README.md":
            continue
        directory = "/".join(path.parts[1:-1])
        if directory in DOCUMENT_TOPICS:
            groups.setdefault(DOCUMENT_TOPICS[directory], []).append(path)
        elif len(path.parts) == 2:
            groups.setdefault(document_topic(path.name), []).append(path)
    lines = [
        "# Detailed Record Catalog", "",
        "Generated by `scripts/audit_repository_structure.py --write-catalogs`.", "",
        "Collections are navigation only, not current/obsolete or pass/fail labels.",
        "This is a lookup appendix, not a required reading list.",
        "Start with the [documentation index](../README.md) and its topic guides.", "",
    ]
    for topic, records in sorted(groups.items()):
        lines.extend([f"## {topic}", ""])
        for path in sorted(records):
            relative = posixpath.relpath(path.as_posix(), DOCUMENT_CATALOG.parent.as_posix())
            target = quote(relative, safe="/._-")
            lines.append(f"- [{path.name}]({target})")
        lines.append("")
    return "\n".join(lines)


def render_script_catalog(paths: Iterable[Path]) -> str:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        if len(path.parts) == 2 and path.parts[0] == "scripts" and path.suffix in {".py", ".sh"}:
            groups.setdefault(script_topic(path.name), []).append(path)
    lines = [
        "# Script Role Catalog", "",
        "Generated by `scripts/audit_repository_structure.py --write-catalogs`.", "",
        "This includes historical commands; role does not imply evidence acceptance.",
        "Read the [script guide](README.md) and the owning contract before execution.", "",
    ]
    return "\n".join(lines + render_groups(groups, ""))


def expected_catalogs(paths: Iterable[Path]) -> dict[Path, str]:
    paths = list(paths)
    audit_path = Path("scripts/audit_repository_structure.py")
    if audit_path not in paths:
        paths.append(audit_path)
    return {
        DOCUMENT_CATALOG: render_document_catalog(paths),
        SCRIPT_CATALOG: render_script_catalog(paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Print tracked inventory as JSON")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write-catalogs", action="store_true")
    modes.add_argument("--check-catalogs", action="store_true")
    modes.add_argument("--check-docs", action="store_true", help="Check document layout and relocation map")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.check_docs:
        errors = check_document_layout(root)
        if errors:
            print("\n".join(errors))
            return 1
        print("PASS topic guides, document relocations, and clean docs root")
        return 0
    paths = tracked_paths(root)
    if args.write_catalogs or args.check_catalogs:
        stale = []
        for path, expected in expected_catalogs(paths).items():
            target = root / path
            if args.write_catalogs:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(expected, encoding="utf-8")
                print(f"WROTE {path}")
            elif not target.exists() or target.read_text(encoding="utf-8") != expected:
                stale.append(path)
        if stale:
            for path in stale:
                print(f"STALE {path}")
            print("Regenerate with --write-catalogs after adding new record/script paths.")
            return 1
        if args.check_catalogs:
            print("PASS documentation and script catalogs")
        return 0
    inventory = build_inventory(root, paths)
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        print(f"Tracked files: {inventory['tracked_files']}")
        print(f"Top-level documentation records: {inventory['top_level_markdown_records']}")
        print(f"Source/script/test-code lines: {inventory['source_lines']}")
        print("Largest source files:")
        for row in inventory["largest_source_files"]:
            print(f"  {row['lines']:6d}  {row['path']}")
        print("Inventory only; no simulation, hardware run, or calibration performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
