"""Freeze the complete empty-row control, retaining mismatches and raw samples."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import verify_source_snapshot
from .analysis import analyze_log
from .execution import identity
from .row_sweep import load_contract
from .row_sweep_analysis import inspect_fixture, incremental_slopes, summarize_case


def validate_sweep(root: Path, data: Path) -> tuple[dict, dict]:
    manifest = json.loads((data / "manifest.json").read_text())
    prepared = json.loads((data / "prepared.json").read_text())
    report = json.loads((data / "summary.json").read_text())
    contract = load_contract(Path(manifest["pins"][0]["path"]))
    if (report["status"] != "EMPTY_ROW_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
            or manifest["contract"] != contract or manifest["timing_fit_allowed"]
            or report["timing_fit_performed"] or report["hardware_timing_admitted"]
            or report["original_A4_match_admitted"]):
        raise ValueError("the frozen control cannot admit fitting or hardware timing")
    pins = manifest["pins"] + prepared["pins"]
    rows, audits, source = [], [], None
    for vertices in contract["vertices"]:
        directory = data / str(vertices)
        audits.append(inspect_fixture(directory / "input.graph", directory / "prepared.bin"))
        board = json.loads((directory / "board/summary.json").read_text())
        board_manifest = json.loads((directory / "board/manifest.json").read_text())
        pins += board_manifest["pins"]
        if (len(board["attempts"]) != 6 or board_manifest["repeats"] != 3
                or {(a["arm"], a["repeat"]) for a in board["attempts"]}
                != {(arm, r) for arm in ("original", "candidate") for r in range(3)}):
            raise ValueError("all six paired FPGA executions must be preserved")
        values = set()
        for attempt in board["attempts"]:
            path = directory / f"board/r{attempt['repeat']}_{attempt['arm']}"
            resource = attempt["resources"]
            if (resource["exit_code"] or resource["timed_out"]
                    or analyze_log((path / "run.log").read_text(), require_trace=True) != attempt["analysis"]
                    or identity(path / "result.txt") != attempt["result"]):
                raise ValueError("FPGA attempt differs from saved admission")
            values.add(identity(path / "result.txt")["sha256"])
        for arm in ("original", "candidate"):
            model = json.loads((directory / arm / "result.json").read_text())
            run = json.loads((directory / arm / "manifest.json").read_text())
            pins += run["pins"] + run["headers"]
            source = source or run["source"]
            if (run["source"] != source or run["plugin"]["plugin_sha256"]
                    != manifest["model_binding"]["plugin_sha256"]):
                raise ValueError("all eight model runs must use the same frozen source/plugin")
            if not all(model[name] is True for name in ("success", "done", "ledger_closed", "replicas_equal")):
                raise ValueError("model correctness and conservation must pass")
            counters = model["counters"]
            if (counters["axi_requests"] != counters["axi_completions"]
                    or counters["axi_beats"] != counters["axi_completed_beats"]
                    or identity(directory / arm / "resident.bin")["sha256"]
                    != identity(directory / "prepared.bin")["sha256"]):
                raise ValueError("model traffic or resident input differs")
            values.add(identity(directory / arm / "result.json.values.txt")["sha256"])
        if len(values) != 1:
            raise ValueError("all eight complete output files must be byte-identical")
        rows.append(summarize_case(directory, vertices))
    if (audits != prepared["rows"] or len({a["fixed_payload_sha256"] for a in audits}) != 1
            or report["rows"] != rows or report["slopes"] != incremental_slopes(rows)):
        raise ValueError("saved invariants or statistics differ from complete raw data")
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("a frozen input, bitstream, source or plugin changed")
    verify_source_snapshot(root, source)
    return report, source


def package_sweep(root: Path, data: Path, output: Path) -> dict:
    report, source = validate_sweep(root, data)
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_empty_rows.tar.gz"
    if archive_path.exists() or (output / "empty_rows.json").exists():
        raise FileExistsError("empty-row checkpoint is already frozen")
    files = {"campaign/" + str(p.relative_to(data)): p for p in data.rglob("*") if p.is_file()}
    for pin in source["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for name in ("configs/experiments/sharded_k4_empty_rows_v1.json",
                 "configs/architectures/grasu_regraph_routed_sssp_compute_v2.json",
                 "scripts/run_sharded_k4_empty_rows.py", "scripts/package_sharded_k4_empty_rows.py",
                 "tests/test_sharded_k4_empty_rows.py", "tests/test_sharded_k4_empty_rows_package.py"):
        files["source/simulator/" + name] = root / name
    files["source/simulator/" + str(Path(__file__).relative_to(root))] = Path(__file__)
    manifest = json.loads((data / "manifest.json").read_text())
    for pin in manifest["pins"]:
        path = Path(pin["path"])
        if path.name in ("sharded_k4_sssp_native_host", "export_hls_fixture"):
            files["binaries/" + path.name] = path
    run = json.loads((data / "4096/original/manifest.json").read_text())
    for pin in run["headers"]:
        path = Path(pin["path"])
        files["source/HLS/include/" + path.name] = path
    dependencies = [identity(output.parent / "independent_channels/channels_raw_index.json"),
                    identity(output.parent / "sst_raw_index.json"),
                    identity(output.parents[2] / "adapter_optimization/board_raw_index.json")]
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("raw evidence changed during packaging")
    atomic_write_json(output / "empty_rows_raw_index.json", {
        "archive": identity(archive_path), "files": index, "dependencies": dependencies,
        "external_bitstreams": "identities and route evidence preserved; xclbins not copied into this archive"})
    atomic_write_json(output / "empty_rows.json", report)
    return report
