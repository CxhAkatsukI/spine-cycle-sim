"""Collect portable evidence without rewriting frozen measurements."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from .runtime import identity, save


def archive(target, entries):
    with tarfile.open(target, "w:gz") as stream:
        for source, name in entries:
            stream.add(source, arcname=name, filter=lambda item: None if "__pycache__" in item.name else item)


def package(root, output, production):
    if (output / "manifest.json").exists():
        raise ValueError("fresh delivery required")
    for directory in ("data", "evidence", "figures"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    for source in (root / "analysis-v1").iterdir():
        shutil.copy2(source, output / "data" / source.name)
    archive(output / "evidence/raw_board.tar.gz", [(root / name, name) for name in
                                                 ("campaign-v1", "campaign-r-v2", "campaign-r-v3")])
    report = json.loads((root / "campaign-r-v3/results.json").read_text())
    for name, pin in report["pins"].items():
        actual = identity(Path(pin["path"]))
        if any(actual[key] != pin[key] for key in ("sha256", "bytes")):
            raise ValueError(f"artifact changed since execution: {name}")
    expected_respr = "c112e790c3cfd81c05b4059f1dc34fcee23bc36a94a995ba1c0d6d49280058c0"
    if report["pins"]["r_current"]["sha256"] != expected_respr:
        raise ValueError("current R is not the pinned Figure 7 ResPR binary")
    frozen_input = Path(report["pins"]["g_input"]["path"])
    inputs = [(frozen_input, "g/au_131072.graph")]
    inputs += [(Path(items[0]["path"]).parent, "r/" + case) for case, items in report["input_pins"].items()]
    archive(output / "evidence/inputs.tar.gz", inputs)
    for version in ("v2", "v3"):
        name = f"execution_sources_{version}.tar.gz"
        shutil.copy2(root / name, output / "evidence" / name)
    archive(output / "evidence/production_source_review.tar.gz",
            [(production / name, name) for name in ("include", "kernels", "tools/sharded_k4_native_host.cpp",
                                                    "tools/sharded_k4_pagerank_native_host.cpp")])
    for arm in ("g_reference", "g_current", "r_reference", "r_current"):
        path = Path(report["pins"][arm]["path"])
        result = subprocess.run(["/opt/xilinx/xrt/bin/xclbinutil", "--info", "--input", str(path)],
                                capture_output=True, text=True, timeout=30, check=True)
        (output / "evidence" / f"{arm}_xclbin_info.txt").write_text(result.stdout + result.stderr)
    repository = Path(__file__).resolve().parents[5]
    archive(output / "evidence/reproduction_sources.tar.gz", [
        (Path(__file__).resolve().parent, "spine_cycle_sim/experiments/original_regraph_execution/hardware/source_retention"),
        (repository / "cpp/tests/publication_sources/source_retention", "cpp/tests/publication_sources/source_retention"),
        (repository / "tests/test_source_retention.py", "tests/test_source_retention.py"),
    ])
    metadata = {
        "scope": "same-platform source-port retention; G admitted, R fails performance gate",
        "publication_match": False, "production_source_review_is_bitstream_build_attestation": False,
        "production_git": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=production, text=True).strip(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True),
        "repository_parent": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
        "figure7_respr_binary_match": {"sha256": expected_respr, "verified_against_run_pin": True},
        "artifacts": {name: value for name, value in report["pins"].items() if name != "g_input"},
    }
    save(output / "data/artifacts.json", metadata)
    save(output / "manifest.json", {"scope": metadata["scope"], "files": [identity(p) for p in sorted(output.rglob("*"))
                                                                           if p.is_file()]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--production", type=Path, required=True)
    args = parser.parse_args()
    package(args.root, args.output, args.production)
