"""Freeze the legacy harness and its complete reference before extracting it."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..analysis import summarize

ROOT = Path(__file__).resolve().parents[4]


def pin(path):
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def freeze(output, reference):
    report = json.loads(reference.read_text())
    summarize(report["r_rows"])
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim/experiments/evaluation_impact")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and p.suffix in (".cpp", ".hpp", ".py", ".txt"))
    sources.append(ROOT / "CMakeLists.txt")
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=str(source.relative_to(ROOT)))
    external = [p for p in report["pins"] if any(token in p["path"] for token in
                ("/inputs/warm_update/", "/build/regraph_convergence_demo", "/build/CMakeCache.txt",
                 "/build/compile_commands.json"))]
    if not external or any(sha256_file(Path(p["path"])) != p["sha256"] for p in external):
        raise ValueError("legacy input/binary/flags identity changed")
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    (output / "pre_edit.diff").write_bytes(diff)
    shutil.copyfile(reference, output / "reference.json")
    identity = {"status": "PRE_EXTRACTION_FROZEN", "sources": [pin(p) for p in sources],
        "external": external, "reference": pin(reference),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True),
        "artifacts": [pin(output / name) for name in ("sources.tar.gz", "reference.json", "pre_edit.diff")],
        "required_equivalence": ["all 12 trajectories", "cycles", "physical read/write bytes", "final state hashes"],
        "baseline_admitted": False}
    atomic_write_json(output / "freeze.json", identity)
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"status": freeze(args.output.resolve(), args.reference.resolve())["status"]}))
