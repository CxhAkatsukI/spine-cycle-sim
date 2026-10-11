"""Predeclared, bounded old/new FPGA and fixed-model empty-row control."""

import csv
import json
import os
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import verify_source_snapshot
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .comparison import compare_bitstreams
from .execution import identity
from .row_sweep_analysis import inspect_fixture, incremental_slopes, summarize_case
from .sst_timing import run_sst_case


def load_contract(path: Path) -> dict:
    contract = json.loads(path.read_text())
    if (contract["study"] != "sharded_k4_empty_rows_v1" or contract["vertices"] != [4096, 8192, 16384, 32768]
            or contract["initial_edges"] != [[0, 1, 8], [1, 2, 8], [2, 3, 8], [3, 4, 8]]
            or contract["updates"] != [[0, 4, 1, 1]] or contract["source"] != 0
            or contract["repeats"] != 3 or contract["expected_rounds"] != 2
            or contract["timing_fit_allowed"] is not False):
        raise ValueError("unrecognized predeclared empty-row control")
    return contract


def run_sweep(*, root: Path, integration: Path, contract_path: Path, host: Path,
              admission: Path, exporter: Path, plugin_dir: Path, channel_evidence: Path,
              output: Path, device: int = 0) -> dict:
    contract = load_contract(contract_path)
    evidence = json.loads(channel_evidence.read_text())
    binding = evidence["legacy"]["candidate_identity"]
    verify_source_snapshot(root, binding["source"])
    if identity(plugin_dir / "libspine_cycle.so")["sha256"] != binding["plugin_sha256"]:
        raise ValueError("use the frozen channel-correction plugin, without parameter fitting")
    gate = json.loads(admission.read_text())
    profile = root / contract["profile"]
    output.mkdir(parents=True, exist_ok=False)
    pins = [identity(path) for path in (contract_path, host, admission, exporter,
            plugin_dir / "libspine_cycle.so", channel_evidence, profile,
            Path(__file__), Path(__file__).with_name("row_sweep_analysis.py"))]
    atomic_write_json(output / "manifest.json", {
        "contract": contract, "pins": pins, "device_index": device,
        "host_affinity": sorted(os.sched_getaffinity(0)), "board_jobs": 1,
        "memory_limit_gib_per_child": 8, "memory_reserve_gib": 16,
        "model_binding": binding, "timing_fit_allowed": False,
        "limits": ["same-partition synthetic diagnostic, not a real-graph performance comparison",
                   "adapter event lifetimes include downstream backpressure",
                   "host dispatch gaps and BO placement are not hardware-calibrated"]})
    matrix = output / "matrix.tsv"
    prepared = []
    with matrix.open("w") as stream:
        writer = csv.DictWriter(stream, delimiter="\t", fieldnames=(
            "case", "algorithm", "graph", "source", "gr_host", "gr_xclbin"))
        writer.writeheader()
        for vertices in contract["vertices"]:
            directory = output / str(vertices)
            directory.mkdir()
            graph = directory / "input.graph"
            lines = [f"{vertices} 4 1"]
            lines += [" ".join(map(str, row)) for row in contract["initial_edges"] + contract["updates"]]
            graph.write_text("\n".join(lines) + "\n")
            fixture = directory / "prepared.bin"
            commands = (("export", [str(exporter), str(graph), "0", str(fixture)]),
                        ("host_prepare", [str(host), "--prepare-only", str(graph),
                                          str(directory / "prepare_result.txt"), "0", "256"]))
            for name, command in commands:
                record = run_bounded(command, root, directory / name,
                                     timeout=120, memory_gib=8, reserve_gib=16)
                if record["exit_code"] or record["timed_out"]:
                    raise RuntimeError(f"preparation failed; preserved {directory}")
            audit = inspect_fixture(graph, fixture)
            prepared.append(audit)
            atomic_write_json(directory / "input_audit.json", audit)
            writer.writerow(dict(case=str(vertices), algorithm="weighted_sssp", graph=str(graph),
                                 source=0, gr_host=str(host), gr_xclbin=gate["original"]["path"]))
    if len({row["fixed_payload_sha256"] for row in prepared}) != 1:
        raise ValueError("PMA or live-state payload changed across the empty-row sweep")
    pins += [identity(matrix)] + [identity(output / str(v) / "input.graph") for v in contract["vertices"]]
    atomic_write_json(output / "prepared.json", {"status": "PASS", "rows": prepared, "pins": pins})
    rows = []
    for vertices in contract["vertices"]:
        directory = output / str(vertices)
        compare_bitstreams(integration=integration, matrix=matrix, case=str(vertices), host=host,
                           admission=admission, output=directory / "board", repeats=3, device=device)
        for arm in ("original", "candidate"):
            run_sst_case(root=root, integration=integration, plugin_dir=plugin_dir, exporter=exporter,
                         profile_path=profile, graph=directory / "input.graph", source=0,
                         board_run=directory / f"board/r0_{arm}", output=directory / arm,
                         arm=arm, timeout=300, max_cycles=50000000)
            if identity(directory / f"{arm}/resident.bin")["sha256"] != identity(directory / "prepared.bin")["sha256"]:
                raise ValueError("model resident fixture changed after preflight")
        rows.append(summarize_case(directory, vertices))
        atomic_write_json(output / "progress.json", {"completed_vertices": [r["vertices"] for r in rows]})
        print(f"{vertices} paired FPGA and fixed-model correctness PASS", flush=True)
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("pinned control input changed during execution")
    report = {"status": "EMPTY_ROW_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC",
              "hardware_timing_admitted": False, "original_A4_match_admitted": False,
              "timing_fit_performed": False, "rows": rows, "slopes": incremental_slopes(rows),
              "claim": contract["claim"]}
    atomic_write_json(output / "summary.json", report)
    return report
