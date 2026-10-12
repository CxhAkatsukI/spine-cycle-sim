"""Recompute the unfitted RTL timing diagnostic from portable raw probe output."""

import json
from pathlib import Path
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...sst_candidate import load_profile
from ..evidence import bounded
from ..model_contract import BASIS
from ..model_recheck import read_json, source_files
from .model_contract import PROFILE_ID
from .model_timing import compare


def recheck(run: Path, binary: Path) -> dict:
    manifest = read_json(run / "manifest.json")
    record = read_json(run / "probe.resources.json")
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    if ((run / "failure.json").exists() or len(pins) != len(manifest["pins"])
            or manifest["claim"] != "same_logical_input_not_identical_memory_or_endpoint_timing"
            or sha256_file(binary) != manifest["binary"]["sha256"]
            or sha256_file(run / "rtl_results.json") != manifest["rtl"]["sha256"]
            or sha256_file(run / "source.tar.gz") != manifest["source_archive"]["sha256"]):
        raise ValueError("frozen structural timing identity differs")
    root = Path(record["cwd"])
    for item in (manifest["binary"], manifest["rtl"], manifest["profile"], manifest["basis"],
                 *manifest["test_files"]):
        if pins.get(item["path"]) != item:
            raise ValueError("structural timing input was not pinned")
    extras = {str(Path(item["path"]).relative_to(root)): item["sha256"]
              for item in (manifest["profile"], manifest["basis"], *manifest["test_files"])}
    sources = source_files(run / "source.tar.gz", manifest["source"], extras)
    with tempfile.TemporaryDirectory() as temporary:
        copy_root = Path(temporary)
        memory = json.loads(sources[BASIS["path"]])["memory"]["config"]
        for name in (f"configs/architectures/{PROFILE_ID}.json", BASIS["path"], memory):
            path = copy_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(sources[name])
        load_profile(copy_root, copy_root / f"configs/architectures/{PROFILE_ID}.json")
    bounded(run / "probe.resources.json", [manifest["binary"]["path"], "--rtl-matrix"], str(root), 90, 3)
    rows = [json.loads(line) for line in (run / "probe.stdout.txt").read_text().splitlines()]
    report = compare(rows, read_json(run / "rtl_results.json"))
    if report != read_json(run / "results.json"):
        raise ValueError("stored structural timing summary differs")
    return report
