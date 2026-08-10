#!/usr/bin/env python3
"""Derive a materialization manifest with an update-only SSSP source cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.publication_cases import (  # noqa: E402
    load_materialization_manifest,
)
def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def _iter_sources(path: Path):
    with path.open("r", encoding="ascii") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            yield int(stripped.split(maxsplit=1)[0])


def update_only_source_from_manifest(manifest: dict[str, Any]) -> int:
    directed = manifest.get("graphs", {}).get("directed")
    if not isinstance(directed, dict):
        raise ValueError("materialization manifest lacks graphs.directed")
    base_path = Path(str(directed["path"]))
    vertices = int(directed["vertices"])

    update_sources: set[int] = set()
    for artifact in manifest.get("updates", []):
        if artifact.get("projection") != "directed" or artifact.get("scenario") != "insert":
            continue
        update_sources.update(_iter_sources(Path(str(artifact["path"]))))

    candidate = 0
    previous_source = -1
    for source in _iter_sources(base_path):
        if source == previous_source:
            continue
        previous_source = source
        while candidate < source:
            if candidate not in update_sources:
                return candidate
            candidate += 1
        if candidate == source:
            candidate += 1
    while candidate < vertices:
        if candidate not in update_sources:
            return candidate
        candidate += 1
    raise ValueError("no update-only zero-outdegree source is available")


def derive_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], int]:
    directed = manifest.get("graphs", {}).get("directed")
    if not isinstance(directed, dict):
        raise ValueError("materialization manifest lacks graphs.directed")
    update_source = update_only_source_from_manifest(manifest)
    derived = json.loads(json.dumps(manifest))
    source_cohorts = dict(derived["graphs"]["directed"].get("source_cohorts", {}))
    source_cohorts["update_only"] = update_source
    derived["graphs"]["directed"]["source_cohorts"] = source_cohorts
    derived.setdefault("derived_metadata", {})[
        "update_only_source_derivation"
    ] = {
        "method": "lowest_sink_only_vertex_absent_from_directed_insert_sources",
        "source": update_source,
    }
    return derived, update_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_materialization_manifest(args.input.resolve())
    derived, source = derive_manifest(manifest)
    write_json(args.output.resolve(), derived)
    print(
        f"DERIVED_UPDATE_ONLY_MANIFEST source={source} output={args.output.resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
