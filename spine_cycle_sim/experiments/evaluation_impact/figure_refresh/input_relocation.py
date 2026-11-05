"""Relocate input paths only after matching the transferred file digests."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..r_credits.freeze import pin


def prepare(source, output, replacements):
    if output.exists():
        raise ValueError("relocated manifest must be new")
    if set(replacements) != {"graph", "updates"}:
        raise ValueError("both graph and updates must be relocated")
    report = json.loads(source.read_text())
    identities = {}
    for key, (path, digest) in replacements.items():
        identity = pin(path)
        if identity["sha256"] != digest:
            raise ValueError("transferred " + key + " digest differs")
        identities[key] = identity
        report[key] = str(path)
    report["input_relocation"] = dict(source_manifest=pin(source), inputs=identities,
                                      semantics="only graph/updates paths changed")
    atomic_write_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for key in ("graph", "updates"):
        parser.add_argument("--" + key, type=Path, required=True)
        parser.add_argument("--" + key + "-sha256", required=True)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve(), {
        key: (getattr(args, key).resolve(), getattr(args, key + "_sha256"))
        for key in ("graph", "updates")})
