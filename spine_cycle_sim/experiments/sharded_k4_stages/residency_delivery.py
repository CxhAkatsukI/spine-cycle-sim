"""Seal one reviewable initial-residency checkpoint without replacing prior evidence."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity
from .residency_validation import validate_campaigns


def package_residency(*, root: Path, integration: Path, campaign: Path, traced: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if any((output / n).exists() for n in ("raw_residency.tar.gz", "residency.json", "residency_raw_index.json")):
        raise FileExistsError("initial-residency evidence is frozen")
    report, files = validate_campaigns(campaign, traced)
    for label, directory in (("control", campaign / "control"), ("matrix", campaign / "matrix"), ("trace", traced)):
        for pin in json.loads((directory / "manifest.json").read_text())["pins"]:
            path = Path(pin["path"])
            if path.suffix in (".py", ".sh", ".hpp", ".json", ".ini", ".tsv"):
                files["reference/" + str(path).lstrip("/")] = path
    owner = root / "spine_cycle_sim/experiments/sharded_k4_stages"
    for path in owner.glob("*.py"):
        files["source/sharded_k4_stages/" + path.name] = path
    for leaf in ("experiments/campaign_runtime.py", "experiments/upstream_controls/execution.py"):
        files["source/" + leaf] = root / "spine_cycle_sim" / leaf
    for path in (root / "tests").glob("test_sharded_k4_*residency*.py"):
        files["tests/" + path.name] = path
    files["tests/test_sharded_k4_runtime_trace.py"] = root / "tests/test_sharded_k4_runtime_trace.py"
    original = subprocess.run(["git", "show", "429185d656813442c144f801b8fb8c695338516f:tools/sharded_k4_native_host.cpp"],
                              cwd=integration, capture_output=True, check=True, timeout=10).stdout
    if hashlib.sha256(original).hexdigest() != "5c3180ffe1ebe8ee074818940b3e53768cb200a7f3da0c75238af00a4f396da1":
        raise ValueError("unexpected pre-intervention host source")
    original_name = "source/frozen_host/sharded_k4_native_host.cpp"
    index = [{"archive_path": n, **identity(p)} for n, p in sorted(files.items())]
    index.append({"archive_path": original_name, "git_object": "429185d:tools/sharded_k4_native_host.cpp",
                  "sha256": hashlib.sha256(original).hexdigest()})
    archive = output / "raw_residency.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
        info = tarfile.TarInfo(original_name)
        info.size = len(original)
        info.mode = 0o644
        stream.addfile(info, io.BytesIO(original))
    if any(identity(Path(p["path"]))["sha256"] != p["sha256"] for p in index if "path" in p):
        raise ValueError("residency evidence changed during packaging")
    dependencies = [identity(output.parent / n) for n in
                    ("empty_exit_matrix/matrix_raw_index.json", "dispatch_affinity/dispatch_raw_index.json")]
    atomic_write_json(output / "residency_raw_index.json", {
        "archive": identity(archive), "files": index, "dependencies": dependencies,
        "external_full_results": report["external_full_results"],
        "external_large_inputs": "graph/xclbin/runtime/SST identities remain in archived manifests; not duplicated"})
    atomic_write_json(output / "residency.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "campaign", "traced", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    package_residency(root=Path(__file__).resolve().parents[3], integration=args.integration.resolve(),
                      campaign=args.campaign.resolve(), traced=args.traced.resolve(), output=args.output.resolve())
