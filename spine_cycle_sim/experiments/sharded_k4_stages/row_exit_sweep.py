"""Replay the fixed-payload board control with explicit old and RTL-exit models."""

import copy
import json
from pathlib import Path
from statistics import median

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity
from .row_sweep_analysis import incremental_slopes, inspect_fixture
from .sst_timing import run_sst_case


def corrected_row(prior: dict, directory: Path) -> dict:
    row = copy.deepcopy(prior)
    for arm in ("original", "candidate"):
        model = json.loads((directory / arm / "result.json").read_text())
        summary = json.loads((directory / arm / "summary.json").read_text())
        if (model["profile_id"] != "grasu_regraph_routed_sssp_compute_v4"
                or summary["status"] != "FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
                or not summary["complete_external_result_bytes_equal"]):
            raise ValueError("complete version-4 output comparison required")
        events = {(event["stage"], event["round"]): event for event in model["invocations"]}
        durations, tails = [], []
        for index in (1, 2):
            adapter, gather = (events[stage, index] for stage in ("adapter", "gather"))
            durations.append((adapter["end"] - adapter["start"]) * 1000 / 150)
            tails.append(max(0, adapter["end"] - gather["end"]) * 1000 / 150)
        values = row["arms"][arm]
        values.update(model_median_duration_ns=median(durations), model_median_tail_ns=median(tails),
                      model_round_duration_ns=durations, model_round_tail_ns=tails,
                      nominal_compute_diagnostic=summary["timing"])
        values["nominal_duration_relative_error"] = median(durations) / values["board_median_duration_ns"] - 1
    return row


def replay_sweep(*, root: Path, integration: Path, plugin_dir: Path, exporter: Path,
                 parent: Path, output: Path) -> dict:
    parent_report = json.loads((parent / "summary.json").read_text())
    if (parent_report["status"] != "EMPTY_ROW_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
            or [r["vertices"] for r in parent_report["rows"]] != [4096, 8192, 16384, 32768]):
        raise ValueError("complete frozen four-size board control required")
    parent_pin = identity(parent / "summary.json")
    output.mkdir(parents=True, exist_ok=False)
    rows, comparisons = [], []
    for prior in parent_report["rows"]:
        vertices = prior["vertices"]
        graph = parent / str(vertices) / "input.graph"
        frozen_fixture = parent / str(vertices) / "prepared.bin"
        audit = inspect_fixture(graph, frozen_fixture)
        for version in (2, 4):
            directory = output / ("replay_v2" if version == 2 else "corrected_v4") / str(vertices)
            for arm in ("original", "candidate"):
                run_sst_case(root=root, integration=integration, plugin_dir=plugin_dir, exporter=exporter,
                             profile_path=root / f"configs/architectures/grasu_regraph_routed_sssp_compute_v{version}.json",
                             graph=graph, source=0, board_run=parent / str(vertices) / f"board/r0_{arm}",
                             output=directory / arm, arm=arm, timeout=300, max_cycles=50000000)
                if identity(directory / arm / "resident.bin")["sha256"] != identity(frozen_fixture)["sha256"]:
                    raise ValueError("controlled resident input changed")
                if version == 2:
                    baseline = parent / str(vertices) / arm
                    for name in ("result.json", "result.json.values.txt"):
                        if (directory / arm / name).read_bytes() != (baseline / name).read_bytes():
                            raise ValueError(f"legacy empty sweep changed: {vertices}/{arm}/{name}")
                    comparisons.append({"vertices": vertices, "arm": arm, "all_result_fields_and_bytes_equal": True})
        rows.append(corrected_row(prior, output / "corrected_v4" / str(vertices)))
        atomic_write_json(output / "progress.json", {"rows": rows, "replays": comparisons, "last_input_audit": audit})
        print(f"empty_exit vertices={vertices} legacy_exact=2 v4_correct=2", flush=True)
    if identity(parent / "summary.json") != parent_pin:
        raise ValueError("parent board evidence changed")
    report = {"status": "EMPTY_EXIT_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC",
              "parent": parent_pin, "rows": rows, "slopes": incremental_slopes(rows), "replays": comparisons,
              "hardware_timing_admitted": False, "original_A4_match_admitted": False,
              "timing_fit_performed": False, "new_board_runs": 0,
              "boundary": "adapter event lifetime; full system and host gaps remain distinct"}
    atomic_write_json(output / "summary.json", report)
    return report
