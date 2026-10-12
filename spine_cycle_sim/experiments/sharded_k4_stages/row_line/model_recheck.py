"""Recompute model evidence from preserved files, without original local paths."""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs
from ..sst_candidate import load_profile
from .evidence import bounded
from .model_contract import BASIS, PROFILE_ID
from .model_scope import SMOKE, study_scope
from .model_validation import compare, inventory

LIMITS = SMOKE.limits


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def source_files(archive: Path, snapshot: dict, extras: dict[str, str] | None = None,
                 *, fallback: dict[str, bytes] | None = None) -> dict[str, bytes]:
    expected = {row["path"]: row["sha256"] for row in snapshot["files"]}
    if len(expected) != len(snapshot["files"]):
        raise ValueError("duplicate source identity")
    for name, digest in (extras or {}).items():
        if name in expected and expected[name] != digest:
            raise ValueError("conflicting source identity")
        expected[name] = digest
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        names = {row.name for row in members}
        if (len(members) != len(names) or sum(row.size for row in members) > 128 * 1024**2
                or (fallback is None and names != expected.keys())):
            raise ValueError("source archive membership or size differs")
        result = {}
        for member in members:
            if not member.isfile() or Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                raise ValueError("unsafe source archive member")
            if member.name not in expected:
                continue
            with stream.extractfile(member) as content:
                data = content.read()
            if hashlib.sha256(data).hexdigest() != expected[member.name]:
                raise ValueError("archived source differs: " + member.name)
            result[member.name] = data
        for name in expected.keys() - result.keys():
            data = (fallback or {}).get(name)
            if (not name.startswith("scripts/") or data is None
                    or hashlib.sha256(data).hexdigest() != expected[name]):
                raise ValueError("missing pre-edit source or different recovery copy: " + name)
            result[name] = data
    return result


def smoke_sources(run: Path, manifest: dict) -> tuple[Path, dict[str, bytes]]:
    if sha256_file(run / "source.tar.gz") != manifest["source_archive"]["sha256"]:
        raise ValueError("executed model source archive differs")
    pins = {pin["path"]: pin["sha256"] for pin in manifest["pins"]}
    root = Path(read_json(run / manifest["cases"][0]["id"] / "original/sst.resources.json")["cwd"])
    if len(pins) != len(manifest["pins"]):
        raise ValueError("duplicate model pin")
    extras = {str(Path(name).relative_to(root)): digest for name, digest in pins.items()
              if Path(name).is_relative_to(root)}
    return root, source_files(run / "source.tar.gz", manifest["source"], extras)


def recheck_study(run: Path, plugin: Path) -> dict:
    manifest, stored = read_json(run / "manifest.json"), read_json(run / "results.json")
    scope = study_scope(manifest.get("study_scope", SMOKE.name))
    scope.require_cases(manifest["cases"])
    if ((run / "failure.json").exists() or manifest["limits"] != scope.limits
            or manifest["claim"] != scope.claim
            or manifest["reference"] != "unrouted_skip_empty_prefetch_not_historical_routed_original"
            or sha256_file(plugin) != manifest["plugin"]["plugin_sha256"]):
        raise ValueError("model smoke identity or boundary differs")
    root, sources = smoke_sources(run, manifest)
    pins = {pin["path"]: pin["sha256"] for pin in manifest["pins"]}
    profile_name = f"configs/architectures/{PROFILE_ID}.json"
    with tempfile.TemporaryDirectory() as temporary:
        copy_root = Path(temporary)
        memory_name = json.loads(sources[BASIS["path"]])["memory"]["config"]
        for name in (profile_name, BASIS["path"], memory_name):
            path = copy_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(sources[name])
        if not same_typed(load_profile(copy_root, copy_root / profile_name), manifest["profile"]):
            raise ValueError("expanded model profile differs")
    cases = manifest["cases"]
    rows = []
    for case in cases:
        directory = run / case["id"]
        geometry = inventory(directory / "resident.bin", **scope.inventory_limits)
        for key, filename in (("fixture", "resident.bin"), ("expected_values", "expected.values.txt")):
            pin = case[key]
            if pins.get(pin["path"]) != pin["sha256"] or sha256_file(directory / filename) != pin["sha256"]:
                raise ValueError("frozen fixture or expected state differs")
        if not same_typed(geometry, case["geometry"]):
            raise ValueError("stored fixture geometry differs")
        arms = {}
        for arm in ("original", "candidate"):
            target = directory / arm
            config = read_json(target / "run_config.json")
            recorded_target = Path(config["output"]).parent
            recorded_fixture = recorded_target.parent / "resident.bin"
            expected_config = {"profile": str(root / profile_name), "fixture": str(recorded_fixture),
                               "output": str(recorded_target / "result.json"),
                               "dram_output": str(recorded_target / "dram"), "arm": arm, "max_cycles": scope.max_cycles}
            if not same_typed(config, expected_config) or recorded_target.name != arm or recorded_target.parent.name != case["id"]:
                raise ValueError("executed model configuration differs")
            command = ["taskset", "-c", scope.limits["affinity"], "env", f"ROUTED_K4_RUN_CONFIG={recorded_target}/run_config.json",
                       "/data/feiyang/sst/bin/sst", manifest["plugin"]["command_option"], str(root / "sst/routed_k4_compute.py")]
            bounded(target / "sst.resources.json", command, str(root), scope.limits["timeout_seconds"],
                    scope.limits["tree_memory_gib"])
            if sha256_file(target / "result.json.values.txt") != case["expected_values"]["sha256"]:
                raise ValueError("complete external result state differs")
            arms[arm] = read_json(target / "result.json")
        row = {"id": case["id"], "geometry": geometry, "complete_external_state_equal": True,
               **compare(arms["original"], arms["candidate"], geometry)}
        if not same_typed(row, read_json(directory / "comparison.json")):
            raise ValueError("stored model comparison differs")
        rows.append(row)
    result = {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "rows": rows,
              "hardware_timing_admitted": False, "original_A4_comparison_complete": False}
    if not same_typed(result, stored):
        raise ValueError("stored model summary differs")
    return result


def recheck_smoke(run: Path, plugin: Path) -> dict:
    if read_json(run / "manifest.json").get("study_scope", SMOKE.name) != SMOKE.name:
        raise ValueError("legacy checkpoint requires the smoke scope")
    return recheck_study(run, plugin)


def recheck(run: Path) -> dict:
    smoke = recheck_smoke(run / "sst", run / "plugin/libspine_cycle.so")
    before = read_json(run / "before_identity.json")
    if sha256_file(run / "source_before.tar.gz") != before["source_archive_sha256"]:
        raise ValueError("pre-edit archive differs")
    # The pre-edit archive omitted five thin scripts. The executed source archive
    # supplies byte-identical copies, checked against the pre-edit hash pins.
    smoke_manifest = read_json(run / "sst/manifest.json")
    _, recovery = smoke_sources(run / "sst", smoke_manifest)
    source_files(run / "source_before.tar.gz", read_json(run / "source_before.json"), fallback=recovery)
    contract = read_json(run / "baseline/contract.json")
    if hashlib.sha256((run / "baseline/contract.json").read_bytes()).hexdigest() != read_json(run / "baseline/identity.json")["contract_sha256"]:
        raise ValueError("legacy contract differs")
    legacy = compare_runs(contract, run / "baseline", run / "legacy_after")
    if (legacy["status"] != "PASS" or legacy["correctness_admitted_cases"] != 5
            or legacy["known_rejections"] or not same_typed(legacy, read_json(run / "legacy_after/equivalence.json"))
            or legacy["baseline_identity"]["plugin_sha256"] != before["reference_plugin_sha256"]
            or legacy["candidate_identity"]["plugin_sha256"] != sha256_file(run / "plugin/libspine_cycle.so")):
        raise ValueError("legacy full-result equivalence differs")
    for step in ("configure", "build", "plugin_build", "core_tests", "baseline_run", "legacy_after_run"):
        path = run / (step + ".resources.json")
        record = read_json(path)
        bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    log = (run / "core/Testing/Temporary/LastTest.log").read_text()
    if (log.count("Test Passed.") != 27 or "Test Failed." in log
            or "Whole-line directory PASS cases=240" not in log
            or "PASS: 9 whole-line/reference executions" not in log
            or "100% tests passed, 0 tests failed out of 27" not in (run / "core_tests.stdout.txt").read_text()):
        raise ValueError("core test admission differs")
    return {"status": "MODEL_FUNCTIONAL_TRAFFIC_AND_LEGACY_EQUALITY_PASS_NOT_HARDWARE_TIMING",
            "smoke": smoke, "legacy_cases": legacy["cases"], "core_executables_passed": 27,
            "pre_edit_archive_note": "Five omitted thin scripts recovered from executed source archive; each matches its pre-edit hash.",
            "hardware_timing_admitted": False, "original_A4_comparison_complete": False}
