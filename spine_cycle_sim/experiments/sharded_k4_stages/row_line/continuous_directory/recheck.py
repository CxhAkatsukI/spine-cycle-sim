"""Recompute every saved model row, RTL trace, schedule decision and regression."""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs
from ...adapter_axi.study import BENCH
from ...empty_segment.production import require_report
from ...routing import adapter_interface
from ..cross_row.validation import FLAGS, require_functional
from ..evidence import bounded, rtl
from .analysis import admit, validate_matrix
from .decision import recheck as schedule_decision
from .study import BASIS_SHA


def read(path):
    return json.loads(path.read_text())


def require_pin(path, pin):
    if (path.is_symlink() or ("bytes" in pin and path.stat().st_size != pin["bytes"])
            or sha256_file(path) != pin["sha256"]):
        raise ValueError("frozen evidence differs: " + str(path))


def source_archive(run):
    pins = read(run / "manifest.json")["sources"]
    root = min((Path(pin["path"]).parent for pin in pins if Path(pin["path"]).name == "CMakeLists.txt"),
               key=lambda path: len(path.parts))
    expected = {}
    for pin in pins:
        path = Path(pin["path"])
        if path.is_relative_to(root):
            name = "simulator/" + path.relative_to(root).as_posix()
        elif "pma_to_regraph_adapter" in path.parts or path.name in {
                "pma_adapter_row_prefetch_tb.cpp", "check_pma_adapter_cross_row.sh", "env.sh"}:
            integration = path.parents[2] if "kernels" in path.parts else path.parents[1]
            name = "integration/" + path.relative_to(integration).as_posix()
        else:
            continue  # The reference XO is separately retained and checked.
        expected[name] = pin
    with tarfile.open(run / "sources.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != len(expected) or {member.name for member in members} != expected.keys():
            raise ValueError("executed source archive membership differs")
        for member in members:
            pin = expected[member.name]
            if not member.isfile():
                raise ValueError("executed source type/size differs")
            with archive.extractfile(member) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != pin["sha256"]:
                    raise ValueError("executed source bytes differ")


def model(root):
    run, basis = root / "model", read(root / "basis/results.json")
    if sha256_file(root / "basis/results.json") != BASIS_SHA:
        raise ValueError("frozen A4/V3 basis differs")
    manifest, report = read(run / "manifest.json"), read(run / "results.json")
    if report["manifest_sha256"] != sha256_file(run / "manifest.json"):
        raise ValueError("model manifest differs")
    source_archive(run)
    for pin in manifest["input_pins"]:
        require_pin(run / "inputs" / Path(pin["path"]).parent.name / Path(pin["path"]).name, pin)
    for item in read(root / "basis/manifest.json")["inputs"]:
        for pin in item["files"]:
            require_pin(run / "inputs" / Path(pin["path"]).parent.name / Path(pin["path"]).name, pin)
    for pin in report["build_files"]:
        old = Path(pin["path"])
        relative = old.relative_to(Path(manifest["build_commands"][0][4]))
        require_pin(run / "build" / relative, pin)
    cases = []
    for row in report["cases"]:
        mode, latency, reverse, arm = (row[key] for key in ("mode", "latency", "reverse", "arm"))
        label = f"{mode}_lat{latency}_reverse{reverse}_{arm}"
        old_arm = "original" if arm == "original" else "cross_row"
        previous = root / "basis/raw" / f"{mode}_lat{latency}_reverse{reverse}_{old_arm}.stdout.txt"
        cases.append(admit((run / "raw" / (label + ".stdout.txt")).read_text(), run / "states" / label,
                           basis, mode, latency, reverse, arm, previous.read_text()))
    validate_matrix(cases)
    if not same_typed(cases, report["cases"]) or report["default_plugin_unchanged"] is not True:
        raise ValueError("saved model conclusion differs")
    for path in (run / "raw").glob("*.resources.json"):
        record = read(path)
        bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    if "Continuous-directory structural model PASS cases=210" not in (
            run / "raw/continuous_adapter.stdout.txt").read_text():
        raise ValueError("complete candidate adapter matrix missing")
    return report


def hls(root):
    run = root / "hls"
    source_archive(run)
    manifest, report = read(run / "manifest.json"), read(run / "results.json")
    reference, candidate = root / "reference.xo", run / "production/adapter.hw.xo"
    require_pin(reference, manifest["sources"][-1])
    require_pin(candidate, report["xo"])
    interface, flags = adapter_interface(candidate)
    old_interface, old_flags = adapter_interface(reference)
    if (not same_typed(interface, report["interface"]) or not same_typed(interface, old_interface)
            or {k: v for k, v in flags.items() if k.startswith("GRASU_")} != FLAGS | {
                "GRASU_REGRAPH_CROSS_ROW_PIPELINE": "1", "GRASU_REGRAPH_CONTINUOUS_DIRECTORY": "1"}
            or {k: v for k, v in old_flags.items() if k.startswith("GRASU_")} != FLAGS | {
                "GRASU_REGRAPH_CROSS_ROW_PIPELINE": "1"}):
        raise ValueError("exact production ABI/flags differ")
    require_functional((run / "functional.stdout.txt").read_text())
    parsed = require_report(run / "production")
    for key in parsed:
        value = parsed[key]["sha256"] if key in {"report", "burst_report"} else parsed[key]
        old = report["hls"][key]["sha256"] if key in {"report", "burst_report"} else report["hls"][key]
        if not same_typed(value, old):
            raise ValueError("HLS summary differs")
    bench_pin = next(pin for pin in manifest["sources"] if pin["path"].endswith("/" + BENCH))
    with tempfile.TemporaryDirectory(prefix="continuous-rtl-recheck-") as temporary:
        bench = Path(temporary) / Path(BENCH).name
        with tarfile.open(run / "sources.tar.gz", "r:gz") as archive:
            with archive.extractfile("simulator/" + BENCH) as stream:
                bench.write_bytes(stream.read())
        require_pin(bench, bench_pin)
        copies = {bench_pin["path"]: bench, manifest["sources"][-1]["path"]: reference}
        commands = read(run / "reference/compile.resources.json")["command"]
        tool_directory = Path(commands[0]).parent
        tools = {name: str(tool_directory / name) for name in ("xvlog", "xelab", "xsim")}
        arms = {arm: rtl(run, arm, pin, copies, tools) for arm, pin in (
            ("reference", manifest["sources"][-1]), ("candidate", report["xo"]))}
    if not same_typed(arms, report["arms"]):
        raise ValueError("saved RTL result differs from complete raw trace")
    for path in run.rglob("*.resources.json"):
        record = read(path)
        bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    return schedule_decision(run)


def recheck(root):
    model_report, decision = model(root), hls(root)
    regression = root / "regression"
    contract = read(regression / "contract.json")
    legacy = compare_runs(contract, root / "legacy_basis", regression / "legacy-after")
    if legacy["status"] != "PASS" or not same_typed(legacy, read(regression / "legacy-after/equivalence.json")):
        raise ValueError("complete SST regression differs")
    plugin = regression / "plugin/libspine_cycle.so"
    if sha256_file(plugin) != legacy["candidate_identity"]["plugin_sha256"]:
        raise ValueError("executed regression plugin differs")
    for step in ("core-configure", "core-full-build", "core-full-tests", "plugin-build", "sst-replay",
                 "sharded-k4-tests-v2", "original-regraph-tests-v2", "refactor-tests-v2"):
        path = regression / (step + ".resources.json")
        record = read(path)
        bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    path = regression / "portable-transport-tests.resources.json"
    record = read(path)
    bounded(path, record["command"], record["cwd"], record["timeout_seconds"], record["tree_memory_gib"])
    if "100% tests passed, 0 tests failed out of 27" not in (regression / "core-full-tests.stdout.txt").read_text():
        raise ValueError("complete core tests missing")
    return {"status": decision["status"], "decision": decision, "model_runs": len(model_report["cases"]),
            "original_A4_and_V3_exact_replay": True, "candidate_state_and_work_pass": True,
            "core_tests": 27, "SST_cases": len(legacy["cases"]), "default_plugin_unchanged": True,
            "hardware_timing_admitted": False, "paper_modified": False}
