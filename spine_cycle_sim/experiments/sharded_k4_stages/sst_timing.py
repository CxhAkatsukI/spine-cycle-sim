"""Bounded HLS-input/SST diagnostics; nominal spans are not a calibration pass."""

import json
from pathlib import Path
import struct

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import source_snapshot, verify_source_snapshot
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.sst_library import forced_sst_library_binding
from .analysis import analyze_log
from .execution import identity
from .sst_candidate import component_parameters, load_profile, require_export_headers


def timing_diagnostic(result: dict, board: dict) -> dict:
    if result["success"] is not True or not result["ledger_closed"] or not result["replicas_equal"]:
        raise ValueError("candidate functionality and traffic must pass before timing analysis")
    geometry = board["result"]
    if (result["vertices"] != int(geometry["vertices"])
            or result["partitions"] != int(geometry["destination_partitions"])
            or result["pma_slots"] != int(geometry["pma_slots_total"])
            or result["live_edges_per_round"] != int(geometry["final_edges"])
            or len(result["rounds"]) != int(geometry["executed_supersteps"])):
        raise ValueError("board and simulator geometry or convergence differs")
    predicted = (result["counters"]["end_cycle"] - result["counters"]["start_cycle"]) / 150000
    spans = []
    for index, model in enumerate(result["rounds"]):
        events = [event for event in board["events"] if event["round"] == index]
        if not events or not model["end"]:
            raise ValueError("incomplete round timeline")
        measured = (max(e["end_ns"] for e in events) - min(e["start_ns"] for e in events)) / 1e6
        spans.append({"round": index + 1, "predicted_no_host_ms": (model["end"] - model["start"]) / 150000,
                      "board_kernel_span_ms": measured})
    return {"status": "DIAGNOSTIC_ONLY_WINDOWS_NOT_IDENTICAL", "hardware_timing_admitted": False,
            "predicted_no_host_ms": predicted, "board_compute_span_ms": board["compute_span_ms"],
            "board_sum_round_spans_ms": sum(row["board_kernel_span_ms"] for row in spans),
            "nominal_predicted_over_board_span": predicted / board["compute_span_ms"],
            "rounds": spans,
            "limits": ["XRT dispatch, same-CU relaunch and inter-round host gaps are absent from candidate",
                       "physical state BO addresses are deterministic model offsets, not captured FPGA addresses",
                       "kernel lifetimes include overlapping stalls and are not exclusive component counters"]}


def run_capped_equivalence(root: Path, plugin_dir: Path, parent: Path, output: Path) -> dict:
    """Replay two preserved partial observations; this is not a correctness gate."""
    output.mkdir(parents=True, exist_ok=False)
    binding = forced_sst_library_binding(Path("/data/feiyang/sst/bin/sst"), plugin_dir)
    rows = []
    for name in ("au_original", "su_original"):
        before_dir = parent / "matrix_final" / name
        before = json.loads((before_dir / "result.json").read_text())
        config = json.loads((before_dir / "run_config.json").read_text())
        if before["done"] or before["failed"] or before["observed_cycles"] <= 0:
            raise ValueError("expected preserved incomplete, non-failed observation")
        directory = output / name
        directory.mkdir()
        config.update(max_cycles=before["observed_cycles"], output=str(directory / "result.json"),
                      dram_output=str(directory / "dram"))
        component_parameters(root, config)
        config_path = directory / "run_config.json"
        atomic_write_json(config_path, config)
        command = ["taskset", "-c", "114-115", "env", f"ROUTED_K4_RUN_CONFIG={config_path}",
                   "/data/feiyang/sst/bin/sst", binding["command_option"], str(root / "sst/routed_k4_compute.py")]
        resource = run_bounded(command, root, directory / "sst", timeout=300, memory_gib=8, reserve_gib=16)
        if resource["exit_code"] or resource["timed_out"]:
            raise ValueError("partial runtime-equivalence replay process failed")
        after = json.loads((directory / "result.json").read_text())
        changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        if changed or sha256_file(before_dir / "result.json.values.txt") != sha256_file(directory / "result.json.values.txt"):
            raise ValueError(f"partial runtime optimization changed result fields: {changed}")
        rows.append({"id": name, "observed_cycles": before["observed_cycles"], "every_result_field_equal": True,
                     "complete_state_bytes_equal": True, "ignored_fields": [], "resources": resource,
                     "parent": identity(before_dir / "result.json")})
    report = {"status": "PASS", "claim": "partial_observation_equivalence_not_workload_correctness",
              "plugin": binding, "rows": rows}
    atomic_write_json(output / "summary.json", report)
    return report


def run_sst_case(*, root: Path, integration: Path, plugin_dir: Path, exporter: Path, profile_path: Path,
                 graph: Path, source: int, board_run: Path, output: Path, arm: str,
                 timeout: int = 600, max_cycles: int = 300000000) -> dict:
    profile = load_profile(root, profile_path)
    if timeout <= 0 or source < 0:
        raise ValueError("positive timeout and nonnegative source required")
    headers = require_export_headers(integration, profile)
    output.mkdir(parents=True, exist_ok=False)
    contract_path = root / "configs/experiments/grasu_component_refactor_v1.json"
    source_identity = source_snapshot(root, contract_path, json.loads(contract_path.read_text()))
    pins = [identity(path) for path in (profile_path, graph, exporter, board_run / "run.log",
                                      board_run / "result.txt", board_run / "run.env",
                                      root / "cpp/tools/routed_regraph/export_hls_fixture.cpp",
                                      root / "cpp/tools/routed_regraph/fixture_oracle.hpp")]
    binding = forced_sst_library_binding(Path("/data/feiyang/sst/bin/sst"), plugin_dir)
    config = {"profile": str(profile_path.resolve()), "fixture": str(output / "resident.bin"),
              "output": str(output / "result.json"), "dram_output": str(output / "dram"),
              "arm": arm, "max_cycles": max_cycles}
    component_parameters(root, config)
    board = analyze_log((board_run / "run.log").read_text(), require_trace=True)
    environment = dict(line.split("=", 1) for line in (board_run / "run.env").read_text().splitlines() if "=" in line)
    if (arm not in ("original", "candidate") or environment["GRAPH_SHA256"] != sha256_file(graph)
            or environment["XCLBIN_SHA256"] != profile["target"][f"{arm}_xclbin_sha256"]
            or int(board["result"]["source_external"]) != source):
        raise ValueError("board arm, source, graph or xclbin differs from declared input")
    manifest = {"schema_version": 1, "source": source_identity, "pins": pins, "headers": headers,
                "plugin": binding, "config": config, "claim": "candidate_SST_diagnostic_not_timing_admission",
                "timeout_seconds": timeout, "memory_limit_gib": 8, "reserve_gib": 16, "affinity": "112-113"}
    atomic_write_json(output / "manifest.json", manifest)
    atomic_write_json(output / "run_config.json", config)
    resources = []
    commands = (
        ("prepare", [str(exporter), str(graph), str(source), config["fixture"]], 120),
        ("sst", ["taskset", "-c", "112-113", "env", f"ROUTED_K4_RUN_CONFIG={output}/run_config.json",
                 "/data/feiyang/sst/bin/sst", binding["command_option"], str(root / "sst/routed_k4_compute.py")], timeout),
    )
    for name, command, cap in commands:
        record = run_bounded(command, root, output / name, timeout=cap, memory_gib=8, reserve_gib=16)
        resources.append({"name": name, "resources": record})
        atomic_write_json(output / "attempts.json", resources)
        if record["exit_code"] or record["timed_out"]:
            atomic_write_json(output / "summary.json", {"status": "RUN_FAILED", "attempts": resources,
                                                       "hardware_timing_admitted": False})
            raise RuntimeError(f"routed SST {name} failed; raw attempt retained: {output}")
    result = json.loads((output / "result.json").read_text())
    equal = sha256_file(output / "result.json.values.txt") == sha256_file(board_run / "result.txt")
    if not equal:
        raise ValueError("complete external result bytes differ from the FPGA result")
    diagnostic = timing_diagnostic(result, board)
    verify_source_snapshot(root, source_identity)
    if any(identity(Path(pin["path"])) != pin for pin in pins + headers):
        raise ValueError("a pinned candidate input changed during execution")
    if sha256_file(plugin_dir / "libspine_cycle.so") != binding["plugin_sha256"]:
        raise ValueError("candidate plugin changed during execution")
    with (output / "resident.bin").open("rb") as stream:
        geometry = dict(zip(("magic", "version", "vertices", "partitions", "cache_segments", "rounds", "active"),
                            struct.unpack("<7I", stream.read(28))))
    summary = {"status": "FUNCTIONAL_PASS_TIMING_DIAGNOSTIC", "geometry": geometry,
               "complete_external_result_bytes_equal": equal, "timing": diagnostic,
               "fixture": identity(output / "resident.bin"), "attempts": resources}
    atomic_write_json(output / "summary.json", summary)
    return summary
