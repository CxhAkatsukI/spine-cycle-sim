"""Revalidate and seal wide-row HLS/RTL and separate host-contract evidence."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..adapter_axi.study import require_route_reference
from ..empty_segment.production import COMPILER, PLATFORM, require_report
from .evidence import bounded, rtl, sources
from .host import ALGORITHMS
from .validation import FLAGS, compare_traffic, require_functional, require_xos


def recheck(run: Path) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    stored = json.loads((run / "results.json").read_text())
    if ((run / "failure.json").exists() or stored["status"] != "ROW_LINE_PRODUCTION_AXI_PASS_NOT_ROUTED"
            or stored["simulator_modified"] is not False or stored["FPGA_timing_admitted"] is not False
            or manifest["flags"] != FLAGS
            or manifest["claim"] != "explicit_wide_directory_HLS_and_synthetic_AXI_RTL_not_FPGA_timing"):
        raise ValueError("wide-row admission differs")
    copies = sources(run, manifest, ("v++", PLATFORM.name, "xvlog", "xelab", "xsim"))
    require_route_reference(manifest["routed_reference"], json.loads(copies[manifest["route_manifest"]["path"]].read_text()))
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    for key in ("reference", "routed_reference", "route_manifest"):
        if pins.get(manifest[key]["path"]) != manifest[key]:
            raise ValueError("production reference is not pinned")
    candidate = run / "production/adapter.hw.xo"
    if sha256_file(candidate) != stored["xo"]["sha256"]:
        raise ValueError("candidate XO differs")
    contract = require_xos(copies[manifest["reference"]["path"]], candidate)
    if not same_typed(contract, stored["contract"]):
        raise ValueError("stored ABI analysis differs")
    hls = require_report(run / "production")
    for key in ("report", "burst_report"):
        if hls[key]["sha256"] != stored["hls"][key]["sha256"]:
            raise ValueError("production HLS report differs")
    if not same_typed({key: value for key, value in hls.items() if key not in ("report", "burst_report")},
                      {key: value for key, value in stored["hls"].items() if key not in ("report", "burst_report")}):
        raise ValueError("HLS analysis differs")
    recorded_output = str(Path(stored["xo"]["path"]).parent.parent)
    integration = str(Path(next(name for name in copies if name.endswith("/kernels/pma_to_regraph_adapter/row_line.hpp"))).parents[2])
    for step, command, timeout in (
        ("functional", ["bash", "scripts/check_pma_to_regraph_adapter.sh", "--out-dir", recorded_output + "/functional"], 240),
        ("host_contract", ["bash", "scripts/check_weighted_pma_runtime_plan.sh", "--out-dir", recorded_output + "/host_contract"], 120),
    ):
        bounded(run / f"{step}.resources.json", command, integration, timeout, 3)
    require_functional((run / "functional/test.log").read_text())
    build = Path(recorded_output) / "production"
    command = [str(COMPILER), "--target", "hw", "--compile", "--kernel_frequency", "150",
               "--kernel", "pma_to_regraph_adapter", "--platform", str(PLATFORM), "--save-temps",
               "-D_GTHREAD_USE_COND_INIT_FUNC", *[f"-D{key}={value}" for key, value in FLAGS.items()],
               "-I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc",
               "--temp_dir", str(build / "build"), "--report_dir", str(build / "reports"),
               "--log_dir", str(build / "logs"), "-o", str(build / "adapter.hw.xo"),
               integration + "/kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"]
    if json.loads((run / "production/command.json").read_text()) != command:
        raise ValueError("production compilation command differs")
    bounded(run / "production/compile.resources.json", command, str(build), 1200, 8)
    tools = {Path(pin["path"]).name: pin["path"] for pin in manifest["pins"]
             if Path(pin["path"]).name in ("xvlog", "xelab", "xsim")}
    arms = {arm: rtl(run, arm, pin, copies, tools) for arm, pin in (
        ("reference", manifest["reference"]), ("candidate", stored["xo"]))}
    comparison = compare_traffic(arms["reference"], arms["candidate"])
    if not same_typed(arms, stored["arms"]) or not same_typed(comparison, stored["comparison"]):
        raise ValueError("stored AXI analysis differs from raw traces")
    return stored


def recheck_host(run: Path) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    stored = json.loads((run / "results.json").read_text())
    if ((run / "failure.json").exists() or stored["status"] != "FOUR_ALGORITHM_ROW_LINE_HOST_PASS_NOT_BOARD"
            or stored["hardware_executed"] is not False or stored["padding_vertex_cases"] != 11):
        raise ValueError("host padding admission differs")
    copies = sources(run, manifest)
    compile_record = json.loads((run / "padding_compile.resources.json").read_text())
    original = Path(compile_record["command"][-1]).parent
    command = ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-Iinclude",
               "tests/weighted_pma_row_line_plan_test.cpp", "-o", str(original / "padding_test")]
    bounded(run / "padding_compile.resources.json", command, manifest["integration"], 120, 4)
    bounded(run / "padding_run.resources.json", [str(original / "padding_test")], manifest["integration"], 30, 4)
    results = {}
    for arm, flag in (("default", "0"), ("candidate", "1")):
        command = ["bash", "scripts/check_sharded_k4_native_host.sh"] + (["--row-line-read"] if flag == "1" else [])
        bounded(run / f"{arm}_check.resources.json", command, manifest["integration"], 300, 4)
        for algorithm in ALGORITHMS:
            directory = run / arm / algorithm
            fields = dict(line.split("=", 1) for line in (directory / "manifest.txt").read_text().splitlines())
            if fields["ROW_LINE_READ"] != flag or fields["PIPELINE_MODE"] != "sharded-k4":
                raise ValueError("host flags differ")
            for line in (directory / "weighted_pma_native_host.sha256").read_text().splitlines():
                digest, name = line.split(maxsplit=1)
                path = copies.get(name, directory / Path(name).name)
                if sha256_file(path) != digest:
                    raise ValueError("executed host binary or build source differs")
    for algorithm in ALGORITHMS:
        name = "six_partition_" + ("sssp" if algorithm == "sssp" else algorithm) + ".out"
        before, after = [(run / arm / name).read_bytes() for arm in ("default", "candidate")]
        if before != after or "status=PASS " not in before.decode():
            raise ValueError("host preparation differs")
        results[algorithm] = {"identical_prepare_output": True, "output": before.decode().strip()}
    if not same_typed(results, stored["algorithms"]):
        raise ValueError("stored host analysis differs")
    return stored


def raw_files(run: Path, prefix: str, production=False) -> list[tuple[Path, str]]:
    files = []
    for path in sorted(run.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in evidence")
        if not path.is_file():
            continue
        relative = path.relative_to(run)
        if "xsim.dir" in relative.parts or "__pycache__" in relative.parts:
            continue
        if production and relative.parts[0] == "production":
            if "build" in relative.parts and path.name not in ("pma_to_regraph_adapter_csynth.xml", "burst.xml"):
                continue
            if path.suffix not in (".xo", ".json", ".txt", ".xml", ".log"):
                continue
        files.append((path, prefix + "/" + relative.as_posix()))
    return files


def deliver(run: Path, host: Path, destination: Path, failed_host: list[Path]) -> dict:
    if destination.exists():
        raise FileExistsError("fresh evidence destination required")
    report, host_report = recheck(run), recheck_host(host)
    files = raw_files(run, "study", True) + raw_files(host, "host")
    for attempt in failed_host:
        if json.loads((attempt / "failure.json").read_text())["status"] != "FAILED_RETAINED":
            raise ValueError("development host attempt is not failed")
        files += raw_files(attempt, "development/" + attempt.name)
    destination.mkdir(parents=True)
    archive = destination / "raw_row_line.tar.gz"
    entries = seal(files, archive)
    atomic_write_json(destination / "results.json", report)
    atomic_write_json(destination / "host.json", host_report)
    verification = {"status": report["status"], "archive_sha256": sha256_file(archive),
                    "archive_bytes": archive.stat().st_size, "files": entries,
                    "results_sha256": sha256_file(destination / "results.json"),
                    "host_sha256": sha256_file(destination / "host.json"),
                    "raw_study": str(run), "raw_host": str(host),
                    "FPGA_timing_admitted": False, "simulator_modified": False}
    atomic_write_json(destination / "verification.json", verification)
    return verification


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "host", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--failed-host", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = deliver(args.run.resolve(), args.host.resolve(), args.destination.resolve(),
                     [path.resolve() for path in args.failed_host])
    print(json.dumps({key: result[key] for key in ("status", "archive_bytes")}))


if __name__ == "__main__":
    main()
