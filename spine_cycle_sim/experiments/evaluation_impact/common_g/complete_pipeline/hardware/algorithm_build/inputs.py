"""Small, portable source closure, independent of legacy absolute build paths."""

import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

SCHEMA = "production_algorithm_sources_v1"
ALGORITHMS = ("connected_components", "residual_pagerank", "full_pagerank")
SUFFIXES = {".cpp", ".hpp", ".h", ".tpp", ".sh", ".py", ".ini", ".cfg", ".json"}
GENERATORS = {"connected_components": "prepare_pure_hw_pipeline_build.sh",
              "residual_pagerank": "prepare_pagerank_pipeline_build.sh",
              "full_pagerank": "prepare_pagerank_pipeline_build.sh"}
CLAIMS = {"routed": False, "board_admitted": False, "publication_match": False}


def prepare(integration, grasu, regraph, output):
    integration, grasu, regraph, output = (path.resolve() for path in (integration, grasu, regraph, output))
    result = subprocess.run(["git", "-C", str(integration), "status", "--porcelain"],
                            check=True, capture_output=True, text=True, timeout=30)
    if result.stdout:
        raise ValueError("commit the reviewed integration source before freezing")
    revision = subprocess.check_output(["git", "-C", str(integration), "rev-parse", "HEAD"],
                                       text=True, timeout=30).strip()
    output.mkdir(parents=True, exist_ok=False)
    roots = {"integration": integration, "GraSU": grasu, "ReGraph": regraph}
    trees = {"integration": ("kernels", "include", "scripts"),
             "GraSU": ("GraSU/GraSU_kernels/src", "GraSU/GraSU/src", "u55c_hbm/config"),
             "ReGraph": ("acc_template", "acc_udfs")}
    records = []
    for owner, members in trees.items():
        for member in members:
            directory = roots[owner] / member
            if not directory.is_dir():
                raise ValueError("missing source directory: " + str(directory))
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or path.suffix not in SUFFIXES or "__pycache__" in path.parts:
                    continue
                if path.is_symlink():
                    raise ValueError("source closure must not contain symlinks: " + str(path))
                before = identity(path)
                destination = output / "source" / owner / path.relative_to(roots[owner])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                copied = identity(destination)
                if before != identity(path) or before["sha256"] != copied["sha256"]:
                    raise ValueError("source changed during copy: " + str(path))
                records.append({"member": destination.relative_to(output).as_posix(),
                                "original": before, "sha256": copied["sha256"]})
    if not 1 <= len(records) <= 2000:
        raise ValueError("source closure is empty or unexpectedly large")
    for row in records:
        if identity(Path(row["original"]["path"])) != row["original"]:
            raise ValueError("source changed while freezing")
    manifest = {"schema": SCHEMA, "integration_revision": revision, "algorithms": list(ALGORITHMS),
                "clock_mhz": 150, "cache_segments": 131072, "adapter_policy": "bank-stream",
                "host_row_line_read_required": True, "files": records, **CLAIMS}
    atomic_write_json(output / "sources.json", manifest)
    verify(output)
    return manifest


def verify(root):
    manifest = json.loads((root / "sources.json").read_text())
    expected = {"schema": SCHEMA, "algorithms": list(ALGORITHMS), "clock_mhz": 150,
                "cache_segments": 131072, "adapter_policy": "bank-stream",
                "host_row_line_read_required": True, **CLAIMS}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("source contract changed")
    files = manifest["files"]
    if not 1 <= len(files) <= 2000:
        raise ValueError("invalid source closure size")
    members = set()
    for row in files:
        member = Path(row["member"])
        if not member.parts or member.is_absolute() or ".." in member.parts or member.parts[0] != "source":
            raise ValueError("unsafe source member")
        path = root / member
        if row["member"] in members or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("duplicate or escaped source")
        if path.is_symlink() or identity(path)["sha256"] != row["sha256"]:
            raise ValueError("source identity changed: " + row["member"])
        members.add(row["member"])
    actual = {path.relative_to(root).as_posix() for path in (root / "source").rglob("*") if path.is_file()}
    if actual != members:
        raise ValueError("unindexed or missing source")
    return manifest


def generation(root, output, algorithm, xilinx, platform):
    if algorithm not in ALGORITHMS:
        raise ValueError("unsupported algorithm")
    source = root.resolve() / "source"
    output, xilinx, platform = (path.resolve() for path in (output, xilinx, platform))
    environment = {"GRI_ROOT": str(source / "integration"), "GRASU_ROOT": str(source / "GraSU"),
                   "REGRAPH_ROOT": str(source / "ReGraph")}
    command = ["/bin/bash", str(source / "integration/scripts" / GENERATORS[algorithm]),
               "--target", "hw", "--algorithm", algorithm, "--pipeline-mode", "sharded-k4",
               "--grasu-implementation", "complete-search-cache", "--adapter-policy", "bank-stream",
               "--kernel-frequency", "150", "--max-cache-segment", "131072",
               "--platform-xpfm", str(platform), "--hls-include", str(xilinx / "Vitis_HLS/2024.1/include"),
               "--hls-include-etc", str(xilinx / "Vitis_HLS/2024.1/include/etc"),
               "--build-root", str(output / "packet")]
    return command, environment
