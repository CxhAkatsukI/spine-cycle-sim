"""Recheck immutable RTL runs, then package raw evidence and concise results."""

import argparse
from collections import Counter
import json
from pathlib import Path
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..routing import adapter_interface
from .analysis import parse_trace, ROW_BASE
from .study import BENCH, COMMON_FLAGS, require_execution, require_route_reference, RTL_PREFIX


def recheck(run: Path) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    report = json.loads((run / "summary.json").read_text())
    if ((run / "failure.json").exists()
            or report["status"] != "FULL_ADAPTER_AXI_RTL_PASS_NOT_BOARD"
            or any(report[key] is not False for key in ("simulator_modified", "HLS_modified", "hardware_timing_admitted"))
            or manifest["claim"] != "full_production_adapter_RTL_with_synthetic_memory_not_FPGA"
            or manifest["reset_between_trials"] is not True):
        raise ValueError("full-top RTL admission differs")
    sources = {}
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    if len(pins) != len(manifest["pins"]):
        raise ValueError("duplicate frozen input")
    for pin in manifest["source_copies"]:
        path = run / pin["archive_path"]
        if (Path(pin["archive_path"]).is_absolute() or ".." in Path(pin["archive_path"]).parts
                or path.is_symlink() or sha256_file(path) != pin["sha256"]
                or pins.get(pin["path"]) != {key: value for key, value in pin.items() if key != "archive_path"}
                or pin["path"] in sources):
            raise ValueError("frozen RTL source or XO differs")
        sources[pin["path"]] = path
    if set(sources) != {path for path in pins if Path(path).suffix in (".py", ".sv", ".xo", ".json")}:
        raise ValueError("incomplete frozen source copies")
    route_pin = manifest["previous_route_manifest"]
    if pins.get(route_pin["path"]) != route_pin:
        raise ValueError("route manifest not in frozen inputs")
    require_route_reference(manifest["xos"]["previous"], json.loads(sources[route_pin["path"]].read_text()))
    tool_bins = {Path(path).name: path for path in pins if Path(path).name in ("xvlog", "xelab", "xsim")}
    concise = {}
    for arm, skip in (("previous", "0"), ("candidate", "1")):
        directory = run / arm
        if pins.get(manifest["xos"][arm]["path"]) != manifest["xos"][arm]:
            raise ValueError("XO identity not in frozen inputs")
        xo = sources[manifest["xos"][arm]["path"]]
        interface, flags = adapter_interface(xo)
        if (interface != manifest["interface"] or flags != manifest["flags"][arm]
                or any(flags.get("GRASU_REGRAPH_" + flag) != "1" for flag in COMMON_FLAGS)
                or flags.get("GRASU_REGRAPH_SKIP_EMPTY_SEGMENT", "0") != skip
                or "GRASU_REGRAPH_COSIM_DEPTH" in flags):
            raise ValueError("production XO pair differs")
        frozen = json.loads((directory / "inputs.json").read_text())
        names = {}
        recorded_directory = Path(frozen[0]["path"]).parent
        for pin in frozen:
            recorded = Path(pin["path"])
            path = directory / recorded.name
            if (recorded.parent != recorded_directory or path.is_symlink()
                    or sha256_file(path) != pin["sha256"] or path.name in names):
                raise ValueError("extracted RTL input differs")
            names[path.name] = path
        with zipfile.ZipFile(xo) as archive:
            rtl = {Path(name).name: archive.read(name) for name in archive.namelist()
                   if name.startswith(RTL_PREFIX) and Path(name).suffix in (".v", ".vh")}
        if any(name not in names or names[name].read_bytes() != data for name, data in rtl.items()):
            raise ValueError("executed RTL differs from production XO bytes")
        bench = next(path for source, path in sources.items() if source.endswith("/" + BENCH))
        if (names[Path(BENCH).name].read_bytes() != bench.read_bytes()
                or names["run.tcl"].read_text() != "run all\nquit\n"
                or names.keys() != rtl.keys() | {Path(BENCH).name, "run.tcl"}):
            raise ValueError("testbench, Tcl or RTL set differs")
        commands = {
            "compile": [tool_bins["xvlog"], "--sv", Path(BENCH).name] + sorted(name for name in rtl if name.endswith(".v")),
            "elaborate": [tool_bins["xelab"], "adapter_axi_tb", "-s", "adapter_axi"],
            "simulate": [tool_bins["xsim"], "adapter_axi", "-tclbatch", "run.tcl"],
        }
        for step, command in commands.items():
            resources = json.loads((directory / f"{step}.resources.json").read_text())
            require_execution(resources)
            if resources["command"] != command or resources["cwd"] != str(recorded_directory):
                raise ValueError("raw RTL execution command differs")
        rows = parse_trace((directory / "simulate.stdout.txt").read_text())
        if not same_typed(rows, report["arms"][arm]):
            raise ValueError("stored RTL analysis differs from raw transcript")
        concise[arm] = []
        for row in rows:
            lines = Counter((request["address"] + beat * request["size"]) // 64
                            for request in row["requests"] if request["address"] >= ROW_BASE
                            for beat in range(request["beats"]))
            concise[arm].append({key: value for key, value in row.items() if key not in ("requests", "responses")} | {
                "unique_row_request_lines": len(lines), "maximum_row_line_repeats": max(lines.values(), default=0)})
    return {"status": report["status"], "arms": concise,
            "boundary": "first_ap_start_high_to_ap_done_in_reset_isolated_full_adapter_RTL",
            "memory_scope": manifest["memory"], "hardware_timing_admitted": False,
            "simulator_modified": False, "HLS_modified": False}


def raw_files(run: Path, prefix: str) -> list[tuple[Path, str]]:
    paths = [run / name for name in ("manifest.json", "summary.json", "failure.json") if (run / name).exists()]
    paths += [path for path in (run / "sources").rglob("*") if path.is_file()]
    for arm in ("previous", "candidate"):
        directory = run / arm
        if not directory.exists():
            continue
        paths += [path for path in directory.iterdir() if path.is_file()
                  and (path.suffix in (".v", ".vh", ".sv", ".tcl", ".json") or path.name.endswith(("stdout.txt", "stderr.txt")))]
    if any(path.is_symlink() for path in paths):
        raise ValueError("symlink in raw RTL evidence")
    return [(path, prefix + "/" + path.relative_to(run).as_posix()) for path in sorted(paths)]


def deliver(run: Path, destination: Path, prior: list[Path]) -> dict:
    if destination.exists():
        raise FileExistsError("fresh RTL delivery required")
    report = recheck(run)
    files = raw_files(run, "accepted")
    for attempt in prior:
        files += raw_files(attempt, "development/" + attempt.name)
    destination.mkdir(parents=True)
    archive = destination / "raw_adapter_axi.tar.gz"
    entries = seal(files, archive)
    atomic_write_json(destination / "results.json", report)
    verification = {"status": report["status"], "archive_sha256": sha256_file(archive),
                    "archive_bytes": archive.stat().st_size, "files": entries,
                    "results_sha256": sha256_file(destination / "results.json"),
                    "accepted_raw_run": str(run), "development_runs": [str(path) for path in prior],
                    "complete_XOs_extracted_RTL_testbench_sources_and_logs_retained": True}
    atomic_write_json(destination / "verification.json", verification)
    return verification


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--prior", type=Path, nargs="*", default=[])
    args = parser.parse_args()
    report = deliver(args.run.resolve(), args.destination.resolve(), [path.resolve() for path in args.prior])
    print(json.dumps({"status": report["status"], "archive_bytes": report["archive_bytes"]}))


if __name__ == "__main__":
    main()
