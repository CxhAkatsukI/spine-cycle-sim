"""Freeze the pre-route gates separately from mutable implementation jobs."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity


def package_pre_route(data: Path, integration: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_pre_route.tar.gz"
    if archive_path.exists() or (output / "pre_route.json").exists():
        raise FileExistsError("pre-route evidence already frozen")
    files = {}

    def add(path):
        if not path.is_file():
            raise FileNotFoundError(path)
        files[str(path.relative_to(data))] = path

    def common(directory):
        for name in ("manifest.json", "attempts.json", "summary.json"):
            path = directory / name
            if path.exists():
                add(path)

    rtl = {}
    for mode in ("weighted", "destination", "unit"):
        directory = data / f"rtl_{mode}_safe_index"
        result = json.loads((directory / "summary.json").read_text())
        if result["status"] != "RTL_COSIM_PASS_NOT_BOARD" or result["mode"] != mode:
            raise ValueError("all three RTL format gates required")
        if any(identity(Path(pin["path"])) != pin for pin in result["source"]):
            raise ValueError("RTL source identity changed before delivery")
        common(directory)
        rtl[mode] = result
        for variant, run in result["runs"].items():
            root = directory / variant
            if run["execution"]["exit_code"] != 0 or run["execution"]["timed_out"]:
                raise ValueError("RTL child execution failed")
            log = root / "cosim.stdout.txt"
            if log.read_text().count("PMA_COSIM_RESULT status=PASS cases=13 packets=200") != 3:
                raise ValueError("C/RTL transaction checks missing")
            for path in root.glob("cosim.*"):
                add(path)
            report = Path(run["analysis"]["raw_report"]["path"])
            if identity(report) != run["analysis"]["raw_report"]:
                raise ValueError("RTL report changed")
            add(report)
            for path in root.glob("project/solution/syn/verilog/*"):
                if path.is_file():
                    add(path)
    directory = data / "ablations_safe_index"
    synthesis = json.loads((directory / "summary.json").read_text())
    if synthesis["status"] != "HLS_PASS_NOT_ROUTED":
        raise ValueError("HLS ablations incomplete")
    common(directory)
    for variant, run in synthesis["runs"].items():
        if identity(Path(run["xo"]["path"])) != run["xo"]:
            raise ValueError("candidate XO changed")
        for path in (directory / variant).glob("compile.*"):
            add(path)
        for key in ("report", "burst_report"):
            path = Path(run["analysis"][key]["path"])
            if identity(path) != run["analysis"][key]:
                raise ValueError("HLS report changed")
            add(path)
    failures = {}
    for name in ("rtl_weighted", "rtl_weighted_threads2", "rtl_weighted_depth", "rtl_weighted_pragma"):
        directory = data / name
        common(directory)
        for path in (directory / "original").glob("cosim.*"):
            add(path)
        failures[name] = json.loads((directory / "original/cosim.resources.json").read_text())
        if failures[name]["exit_code"] == 0:
            raise ValueError("failed-attempt index unexpectedly passed")
    board = data / "board_helper_regression"
    regression = json.loads((board / "summary.json").read_text())
    old = json.loads((data / "au_sssp/summary.json").read_text())
    if regression["status"] != "PASS" or not all(regression["checks"].values()):
        raise ValueError("shared board-helper regression failed")
    for attempt in regression["attempts"]:
        if (attempt["result"]["sha256"] != old["attempts"][0]["result"]["sha256"] or
                attempt["analysis"]["result"] != old["attempts"][0]["analysis"]["result"]):
            raise ValueError("board helper changed the frozen result")
    for path in board.rglob("*"):
        if path.is_file():
            add(path)
    for path in (data / "source_safe_index").iterdir():
        if path.suffix in (".log", ".env") or path.name == "SHA256SUMS":
            add(path)
    for path in data.glob("source_safe_index_execution.*"):
        add(path)
    source_check = json.loads((data / "source_safe_index_execution.resources.json").read_text())
    if source_check["exit_code"] != 0 or source_check["timed_out"]:
        raise ValueError("source checks failed")
    for pin in rtl["weighted"]["source"]:
        path = Path(pin["path"])
        files["source/integration/" + str(path.relative_to(integration))] = path
    for name in ("tests/pma_adapter_row_prefetch_tb.cpp", "tests/pma_to_regraph_adapter_tb.cpp",
                 "scripts/check_pma_to_regraph_adapter.sh"):
        files["source/integration/" + name] = integration / name
    for path in Path(__file__).parent.glob("*.py"):
        files["source/simulator/" + path.name] = path
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    raw_index = {"archive": identity(archive_path), "files": [
        {"archive_path": name, **identity(path)} for name, path in sorted(files.items())]}
    atomic_write_json(output / "pre_route_raw_index.json", raw_index)
    result = {"status": "SOURCE_RTL_HLS_AND_OLD_BOARD_REGRESSION_PASS_NOT_OPTIMIZED_FPGA",
              "rtl": rtl, "synthesis": synthesis, "source_checks": source_check,
              "board_helper_regression": regression, "retained_failures": failures,
              "not_complete": ["optimized_routing_and_board_validation", "optimized_production_simulator",
                               "matched_original_A4_vs_actual_K4", "publication_speed_match"]}
    atomic_write_json(output / "pre_route.json", result)
    return result
