"""Freeze the accepted case selection before observing new timing results."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

from scripts.run_current_fpga_spine_compacted_matrix import build_command, PROFILE
from scripts.run_rq3_carry_trace_matrix import build_case
from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file

ROOT = Path(__file__).resolve().parents[5]
OLD = ROOT / "docs/evaluation_refresh_20260810/figure7_10_handoff_v1"
INPUTS = Path("/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812")
FRESH = "fresh_20261103_"
SELECTION = (
    ("ZN", "Syn", "zero_net_sssp"),
    ("SI", "AU", "current_fpga_v12_au_weighted_sssp_u8"),
    ("SI", "SU", "current_fpga_v12_su_weighted_sssp_u8"),
    ("SI", "WK", "current_fpga_v12_wk_weighted_sssp_u8"),
    ("Carry", "L1", "rq3_trace_carry_l1_e8"),
    ("Carry", "L3", "rq3_trace_carry_l3_e8"),
    ("Carry", "L5", "rq3_trace_carry_l5_e8"),
    ("PR-corr", "FL", "current_fpga_v12_flickr_respr_correction_u8"),
    ("PR-corr", "SU", "current_fpga_v12_su_thresholded_residual_pagerank_u8"),
    ("PR-corr", "WK", "current_fpga_v12_wk_thresholded_residual_pagerank_u8"),
    ("Del", "Syn", "current_fpga_v12_delete_fallback_sssp"),
)


def replace_option(command: list[str], key: str, value: Path | str) -> None:
    command[command.index(key) + 1] = str(value)


def prepare(output: Path, library: Path) -> dict:
    if (output / "matrix.json").exists():
        raise FileExistsError("refuse to overwrite a frozen matrix")
    profiles = {}
    for algorithm, original in PROFILE.items():
        profile = json.loads(original.read_text())
        profile["parameters"]["maintenance_architecture"] = "candidate10_one_pass"
        profile["derived_from"] = {"path": str(original), "sha256": sha256_file(original)}
        profile["profile_id"] += "_onepass_prediction_20261103"
        profile["evidence_tier"] = "structural_execution_driven"
        profile["status"] = "prediction_not_stage_calibrated"
        path = output / "profiles" / original.name
        atomic_write_json(path, profile)
        profiles[algorithm] = path
    template = OLD / "data/fig11_rq3_prediction_rows.csv"
    with template.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows.append({"execution_id": "zero_net_sssp", "dataset_id": "synthetic_sssp_zero_net",
                 "algorithm": "weighted_sssp", "role": "excluded_fig10_only",
                 "dataset_kind": "synthetic"})
    cases = []
    for row in rows:
        old_id, algorithm = row["execution_id"], row["algorithm"]
        execution_id = FRESH + old_id
        destination = output / "runs" / execution_id
        common = [sys.executable, str(ROOT / "scripts/run_sst_spine_vertical.py"),
                  "--validation-mode", "generic", "--profile", str(profiles[algorithm]),
                  "--lib-dir", str(library), "--out-dir", str(destination),
                  "--max-cycles", "2000000000", "--no-build"]
        batch, physical = 8, 8
        if old_id.startswith("rq3_trace_carry_"):
            replace_option(common, "--validation-mode", "fixture")
            level, batch = (int(part[1:]) for part in old_id.split("_")[-2:])
            carry = build_case(output / "inputs" / f"e{batch}", target=level, batch_edges=batch)
            physical = batch
            command = common + ["--scenario", "rq3_trace_carry", "--workload", str(carry["update_path"]),
                                "--carry-history", str(carry["history_path"]),
                                "--carry-history-batch-edges", str(batch),
                                "--expected-carry-target-level", str(level), "--source", "0"]
        elif "flickr_respr_correction_" in old_id:
            batch = int(old_id.rsplit("u", 1)[1])
            physical = batch * 2
            command = common + ["--scenario", "residual_pagerank", "--workload",
                str(ROOT / "tests/data/deltahls_real/real_soc_flickr_und_reciprocal_sinkfree.slice"),
                "--update-workload", str(ROOT / f"tests/data/deltahls_real/real_soc_flickr_und_insert_u{batch}.slice"),
                "--pagerank-damping", "0.85", "--pagerank-epsilon", "1e-6", "--residual-contract",
                "deltahls_sink_free_linf_warm", "--residual-max-iterations", "256"]
        elif old_id.endswith("delete_fallback_sssp"):
            batch = physical = 1
            command = common + ["--scenario", "dynamic_sssp_delete", "--source", "0",
                "--workload", str(ROOT / "tests/data/dynamic_nonmonotonic_initial.slice"),
                "--update-workload", str(ROOT / "tests/data/dynamic_delete_update.slice")]
        elif old_id == "zero_net_sssp":
            batch, physical = 2, 4
            base = ROOT / "tests/data/connected_components_formal"
            command = common + ["--scenario", "dynamic_sssp_delete", "--source", "0",
                "--workload", str(base / "cc_zero_net_base.slice"),
                "--update-workload", str(base / "cc_zero_net_delete_then_reinsert_u2.slice")]
        else:
            command = build_command(INPUTS, library, row["dataset_id"], algorithm)
            replace_option(command, "--out-dir", destination)
            replace_option(command, "--profile", profiles[algorithm])
            if algorithm != "weighted_sssp":
                physical = 16
        inputs = {}
        for flag in ("--workload", "--update-workload", "--carry-history"):
            if flag in command:
                path = Path(command[command.index(flag) + 1])
                inputs[flag] = {"path": str(path), "sha256": sha256_file(path)}
        cases.append({"execution_id": execution_id, "previous_execution_id": old_id,
            "dataset_id": row["dataset_id"], "algorithm": algorithm, "role": row["role"],
            "dataset_kind": row["dataset_kind"], "batch_size": batch, "physical_records": physical,
            "command": command, "inputs": inputs, "out_dir": str(destination)})
    matrix = {"schema": "figure10_11_fresh_v1", "template": str(template),
              "template_sha256": sha256_file(template), "cases": cases,
              "selection": SELECTION, "fit_rows": 41, "fig10_bars": 11,
              "evidence_tier": "simulator_prediction_not_fpga_stage_calibration",
              "profile_override": {"maintenance_architecture": "candidate10_one_pass"},
              "residual_apply_mode": "dense_default_sparse_candidate_not_wired_in_SST"}
    atomic_write_json(output / "matrix.json", matrix)
    return matrix
