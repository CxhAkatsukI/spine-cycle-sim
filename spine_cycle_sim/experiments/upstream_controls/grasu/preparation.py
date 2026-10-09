"""Pin original source/dependencies and preserve old model/evidence identities."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.sources import read_pins, verify_snapshot
from .fixtures import NAMES


def validate_contract(contract):
    expected = {"schema_version": 1, "cases": list(NAMES), "segment_slots": 16, "hot_segments_per_half": 131072,
        "segments_per_half": 131104, "search_kernels": 4, "search_lanes_per_kernel": 64, "bipa_lanes": 16,
        "cache_banks_per_half": 16, "repetitions": 2, "instrument_all_cases": True,
        "memory_limit_gib": 3, "reserve_gib": 16,
        "evidence_class": "original_G_source16_functional_composition_not_timing"}
    for key, value in expected.items():
        if key not in contract or json.dumps(contract[key]) != json.dumps(value): raise ValueError("G contract changed: " + key)
    for key in ("compile_timeout_seconds", "run_timeout_seconds"):
        if type(contract.get(key)) is not int or not 1 <= contract[key] <= 300: raise ValueError("G timeout must remain bounded")


def identities(root: Path):
    paths = [root / name for name in ("scripts/run_original_grasu_source_path.py", "tests/test_original_grasu_source_path.py",
        "cpp/tests/publication_sources/grasu_path_probe.cpp", "configs/experiments/original_grasu_source_path_v1.json")]
    paths += sorted((root / "cpp/tests/publication_sources/grasu_path").glob("*.hpp"))
    paths += sorted((root / "spine_cycle_sim/experiments/upstream_controls/grasu").glob("*.py"))
    paths += [root / "spine_cycle_sim/experiments/upstream_controls" / name for name in ("execution.py", "sources.py")]
    paths += [root / "spine_cycle_sim/experiments/campaign_runtime.py", root / "cpp/tests/publication_sources/probe_support.hpp"]
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in sorted(paths)]


def preserve(root: Path, baseline: Path):
    record = json.loads((baseline / "baseline.json").read_text())
    for item in record["files"]:
        if sha256_file(root / item["path"]) != item["sha256"]: raise ValueError("G study changed old code/evidence: " + item["path"])
    return {"baseline_sha256": sha256_file(baseline / "baseline.json"), "unchanged_files": len(record["files"])}


def author_snapshot(root: Path, source: Path):
    pins = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"
    return verify_snapshot(source, read_pins(pins)["grasu"])


def legacy_reference(root: Path, stream: str) -> bytes:
    if stream not in ("stdout", "stderr"): raise ValueError("invalid legacy stream")
    folder = root / "docs/experiments/comparisons/grasu_regraph_stage_validation"
    archive = folder / "raw_source_controls.tar.gz"
    verification = json.loads((folder / "verification.json").read_text())
    if sha256_file(archive) != verification["archive_sha256"]: raise ValueError("old source archive changed")
    name = "source_functional_final_v1/g_original_cache/run." + stream + ".txt"
    with tarfile.open(archive, "r:gz") as bundle:
        members = [item for item in bundle.getmembers() if item.name == name]
        if len(members) != 1 or not members[0].isfile() or members[0].size > 1024**2:
            raise ValueError("legacy source reference absent or unsafe")
        with bundle.extractfile(members[0]) as payload: return payload.read()


def compiler_command(root: Path, source: Path, include: Path, output: Path, compiler: str, *, instrumented=False, legacy=False):
    command = [compiler, "-std=c++17", "-O1", "-g0", "-Wno-unknown-pragmas", "-Wno-deprecated-declarations",
        "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT", f"-I{include}", f"-I{include / 'etc'}", f"-I{source / 'GraSU/GraSU_kernels/src'}",
        "-MD", "-MF", str(output / "dependencies.d"), "-MT", "probe"]
    if instrumented: command += ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    name = "grasu_cache_probe.cpp" if legacy else "grasu_path_probe.cpp"
    return command + [str(root / "cpp/tests/publication_sources" / name), "-pthread", "-lgmp", "-o", str(output / "probe")]
