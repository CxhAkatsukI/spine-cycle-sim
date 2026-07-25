"""Matched HBM and selected-array energy evidence for PageRank comparisons."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from .energy import parse_cacti_output, render_cacti_config


class MatchedEnergyError(ValueError):
    """Raised when matched energy evidence is incomplete or mislabeled."""


_ENERGY_FIELDS = {
    "activate_energy_pj": ("act_energy",),
    "read_energy_pj": ("read_energy",),
    "write_energy_pj": ("write_energy",),
    "refresh_energy_pj": ("ref_energy", "refb_energy"),
    "active_standby_energy_pj": ("act_stb_energy",),
    "precharge_standby_energy_pj": ("pre_stb_energy",),
    "self_refresh_energy_pj": ("sref_energy",),
}

_SOURCE_CACHE_GEOMETRY = {
    "size_bytes": 16_384,
    "word_bytes": 64,
    "banks": 1,
    "technology_nm": 32,
    "temperature_k": 350,
    "read_write_ports": 0,
    "read_ports": 1,
    "write_ports": 1,
}

_GATHER_BANK_GEOMETRY = {
    "size_bytes": 65_536,
    "word_bytes": 8,
    "banks": 1,
    "technology_nm": 32,
    "temperature_k": 350,
    "read_write_ports": 0,
    "read_ports": 1,
    "write_ports": 1,
}

CURRENT_GRASU_ARRAY_GEOMETRIES = {
    "grasu_source_cache_bank_16k_x512": _SOURCE_CACHE_GEOMETRY,
    "regraph_gather_bank_64k_x64": _GATHER_BANK_GEOMETRY,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path, context: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatchedEnergyError(f"cannot read {context}: {path}") from exc
    if not isinstance(document, dict):
        raise MatchedEnergyError(f"{context} must be a JSON object: {path}")
    return document


def _nonnegative_number(value: Any, context: str) -> float:
    if isinstance(value, bool):
        raise MatchedEnergyError(f"{context} must be a nonnegative number")
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number) and number >= 0.0:
            return number
    if isinstance(value, dict):
        return sum(
            _nonnegative_number(item, f"{context}.{key}")
            for key, item in value.items()
        )
    raise MatchedEnergyError(f"{context} must be a nonnegative number or map")


def _nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MatchedEnergyError(f"{context} must be a nonnegative integer")
    return value


def aggregate_detailed_dramsim3(
    directory: str | Path, *, expected_channels: int = 32
) -> dict[str, Any]:
    """Aggregate one final DRAMSim3 JSON file per physical HBM controller."""

    root = Path(directory)
    files = sorted(root.glob("channel*/dramsim3.json"))
    if len(files) != expected_channels:
        raise MatchedEnergyError(
            f"expected {expected_channels} DRAMSim3 controllers in {root}, "
            f"found {len(files)}"
        )
    totals: dict[str, float | int] = {
        "reads": 0,
        "writes": 0,
        "read_row_hits": 0,
        "write_row_hits": 0,
        "activates": 0,
        "precharges": 0,
        "total_energy_pj": 0.0,
        **{name: 0.0 for name in _ENERGY_FIELDS},
    }
    channels: set[int] = set()
    controller_cycles = []
    idle_controllers = 0
    identities = []
    for path in files:
        content = path.read_bytes()
        document = _load_json(path, "DRAMSim3 output")
        if len(document) != 1:
            raise MatchedEnergyError(f"unexpected DRAMSim3 root: {path}")
        row = next(iter(document.values()))
        if not isinstance(row, dict):
            raise MatchedEnergyError(f"unexpected DRAMSim3 channel row: {path}")
        match = re.fullmatch(r"channel(\d+)", path.parent.name)
        if not match:
            raise MatchedEnergyError(f"invalid physical channel directory: {path}")
        physical_channel = int(match.group(1))
        local_channel = _nonnegative_int(row.get("channel"), f"{path}.channel")
        if local_channel != 0:
            raise MatchedEnergyError(
                f"{path} must describe local DRAMSim3 channel 0"
            )
        if physical_channel in channels:
            raise MatchedEnergyError(
                f"duplicate physical HBM channel {physical_channel}"
            )
        channels.add(physical_channel)
        reads = _nonnegative_int(row.get("num_reads_done"), f"{path}.reads")
        writes = _nonnegative_int(row.get("num_writes_done"), f"{path}.writes")
        totals["reads"] += reads
        totals["writes"] += writes
        idle_controllers += reads + writes == 0
        for output, field in (
            ("read_row_hits", "num_read_row_hits"),
            ("write_row_hits", "num_write_row_hits"),
            ("activates", "num_act_cmds"),
            ("precharges", "num_pre_cmds"),
        ):
            totals[output] += _nonnegative_int(row.get(field), f"{path}.{field}")
        for output, fields in _ENERGY_FIELDS.items():
            totals[output] += sum(
                _nonnegative_number(row.get(field), f"{path}.{field}")
                for field in fields
            )
        totals["total_energy_pj"] += _nonnegative_number(
            row.get("total_energy"), f"{path}.total_energy"
        )
        controller_cycles.append(
            _nonnegative_int(row.get("num_cycles"), f"{path}.num_cycles")
        )
        identities.append(
            {
                "physical_channel": physical_channel,
                "dramsim_local_channel": local_channel,
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(content),
            }
        )
    if channels != set(range(expected_channels)):
        raise MatchedEnergyError(
            f"DRAMSim3 channels are not exactly 0..{expected_channels - 1}"
        )
    if min(controller_cycles) != max(controller_cycles):
        raise MatchedEnergyError(
            "DRAMSim3 controllers do not share one matched timing window"
        )
    component_sum = sum(float(totals[name]) for name in _ENERGY_FIELDS)
    command_dynamic = sum(
        float(totals[name])
        for name in (
            "activate_energy_pj",
            "read_energy_pj",
            "write_energy_pj",
        )
    )
    background = component_sum - command_dynamic
    total_energy = float(totals["total_energy_pj"])
    tolerance = max(1.0e-3, total_energy * 1.0e-9)
    if abs(component_sum - total_energy) > tolerance:
        raise MatchedEnergyError(
            f"DRAMSim3 energy components do not close: {component_sum} != "
            f"{total_energy}"
        )
    read_commands = int(totals["reads"])
    write_commands = int(totals["writes"])
    return {
        **totals,
        "controller_instances": expected_channels,
        "idle_controller_instances": idle_controllers,
        "controller_cycles_min": min(controller_cycles),
        "controller_cycles_max": max(controller_cycles),
        "component_sum_pj": component_sum,
        "command_dynamic_energy_pj": command_dynamic,
        "background_and_refresh_energy_pj": background,
        "component_closure_error_pj": component_sum - total_energy,
        "read_row_hit_ratio": (
            int(totals["read_row_hits"]) / read_commands if read_commands else 0.0
        ),
        "write_row_hit_ratio": (
            int(totals["write_row_hits"]) / write_commands
            if write_commands
            else 0.0
        ),
        "files": identities,
        "claim_label": "dramsim3_full_32_controller_hbm_energy",
    }


def load_current_grasu_characterizations(
    manifest_path: str | Path,
) -> dict[str, dict[str, Any]]:
    """Load and identity-check current 8-lane GraSU/ReGraph CACTI arrays."""

    path = Path(manifest_path)
    manifest = _load_json(path, "CACTI characterization manifest")
    if manifest.get("schema_version") != 1:
        raise MatchedEnergyError("unsupported CACTI characterization schema")
    entries = manifest.get("characterizations")
    if not isinstance(entries, list):
        raise MatchedEnergyError("CACTI characterization manifest lacks entries")
    results = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise MatchedEnergyError("invalid CACTI characterization entry")
        char_id = entry.get("characterization_id")
        if char_id not in CURRENT_GRASU_ARRAY_GEOMETRIES or char_id in results:
            raise MatchedEnergyError(f"unexpected CACTI characterization: {char_id}")
        expected = CURRENT_GRASU_ARRAY_GEOMETRIES[char_id]
        if entry.get("geometry") != expected:
            raise MatchedEnergyError(f"CACTI geometry mismatch for {char_id}")
        config_path = path.parent / str(entry.get("config_path"))
        output_path = path.parent / str(entry.get("output_path"))
        config = config_path.read_bytes()
        output = output_path.read_bytes()
        if _sha256(config) != entry.get("config_sha256"):
            raise MatchedEnergyError(f"CACTI config hash mismatch for {char_id}")
        if _sha256(output) != entry.get("output_sha256"):
            raise MatchedEnergyError(f"CACTI output hash mismatch for {char_id}")
        if config.decode("utf-8") != render_cacti_config(expected):
            raise MatchedEnergyError(f"CACTI config is not canonical for {char_id}")
        parsed = parse_cacti_output(output.decode("utf-8"))
        observed_geometry = {
            key: parsed["geometry"][key]
            for key in (
                "size_bytes",
                "word_bytes",
                "banks",
                "technology_nm",
                "read_write_ports",
                "read_ports",
                "write_ports",
            )
        }
        expected_without_temperature = {
            key: value for key, value in expected.items() if key != "temperature_k"
        }
        if observed_geometry != expected_without_temperature:
            raise MatchedEnergyError(f"CACTI output geometry mismatch for {char_id}")
        results[char_id] = parsed
    if set(results) != set(CURRENT_GRASU_ARRAY_GEOMETRIES):
        raise MatchedEnergyError("CACTI manifest does not cover both current arrays")
    return results


def grasu_selected_array_energy(
    activity: Mapping[str, Any],
    characterizations: Mapping[str, Mapping[str, Any]],
    *,
    runtime_ns: float,
) -> dict[str, Any]:
    """Map execution counters to current 8-lane ReGraph SRAM accesses."""

    if (
        activity.get("edge_lanes") != 8
        or activity.get("gather_banks") != 8
        or activity.get("partition_vertices") != 65_536
    ):
        raise MatchedEnergyError(
            "GraSU activity does not use the current 8-lane profile"
        )
    if not math.isfinite(runtime_ns) or runtime_ns <= 0.0:
        raise MatchedEnergyError("runtime_ns must be positive")
    source = characterizations["grasu_source_cache_bank_16k_x512"]
    gather = characterizations["regraph_gather_bank_64k_x64"]
    source_reads = _nonnegative_int(
        activity.get("compute_pma_slots"), "compute_pma_slots"
    )
    source_writes = _nonnegative_int(
        activity.get("source_cache_lane_writes"), "source_cache_lane_writes"
    )
    gather_updates = _nonnegative_int(
        activity.get("gather_bank_updates"), "gather_bank_updates"
    )
    gather_reset = _nonnegative_int(
        activity.get("gather_reset_cycles"), "gather_reset_cycles"
    )
    gather_merge = _nonnegative_int(
        activity.get("gather_merge_cycles"), "gather_merge_cycles"
    )
    if gather_merge != activity.get("gather_rows_emitted"):
        raise MatchedEnergyError("gather merge cycles do not close emitted rows")
    gather_banks = 8
    arrays = [
        _array_energy(
            "source_property_pingpong_banks",
            source,
            instances=16,
            reads=source_reads,
            writes=source_writes,
            runtime_ns=runtime_ns,
            hardware_mapping=(
                "8 source-map lane copies x 2 ping-pong slots; each bank is "
                "4096 float32 values packed as 256 x 512-bit"
            ),
        ),
        _array_energy(
            "gather_temporary_property_banks",
            gather,
            instances=8,
            reads=gather_updates + gather_merge * gather_banks,
            writes=(
                gather_reset * gather_banks
                + gather_updates
                + gather_merge * gather_banks
            ),
            runtime_ns=runtime_ns,
            hardware_mapping=(
                "8 gather banks; each bank stores 8192 rows x 64-bit for a "
                "65536-vertex destination partition"
            ),
        ),
    ]
    return {
        "arrays": arrays,
        "dynamic_energy_pj": sum(row["dynamic_energy_pj"] for row in arrays),
        "leakage_energy_pj": sum(row["leakage_energy_pj"] for row in arrays),
        "total_energy_pj": sum(row["total_energy_pj"] for row in arrays),
        "projected_asic_sram_area_mm2": sum(
            row["projected_asic_sram_area_mm2"] for row in arrays
        ),
        "claim_label": "selected_projected_asic_sram_energy_not_fpga_power",
    }


def _array_energy(
    array_id: str,
    characterization: Mapping[str, Any],
    *,
    instances: int,
    reads: int,
    writes: int,
    runtime_ns: float,
    hardware_mapping: str,
) -> dict[str, Any]:
    dynamic = (
        reads * float(characterization["read_energy_nj"])
        + writes * float(characterization["write_energy_nj"])
    ) * 1000.0
    leakage = float(characterization["leakage_power_mw"]) * instances * runtime_ns
    return {
        "array_id": array_id,
        "instances": instances,
        "reads": reads,
        "writes": writes,
        "dynamic_energy_pj": dynamic,
        "leakage_energy_pj": leakage,
        "total_energy_pj": dynamic + leakage,
        "projected_asic_sram_area_mm2": (
            float(characterization["area_mm2"]) * instances
        ),
        "hardware_mapping": hardware_mapping,
        "claim_label": "selected_projected_asic_sram",
    }


def _validate_matrix(
    directory: Path, algorithm: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = directory / "matrix_manifest.json"
    manifest = _load_json(manifest_path, f"{algorithm} matrix manifest")
    if (
        manifest.get("status") != "PASS"
        or manifest.get("algorithm") != algorithm
        or manifest.get("all_correct") is not True
        or manifest.get("instantiate_all_hbm_channels") is not True
        or manifest.get("hbm_controller_instances") != 32
    ):
        raise MatchedEnergyError(f"{algorithm} matrix is not energy-eligible")
    selected = manifest.get("selected_run_ids")
    if (
        not isinstance(selected, list)
        or len(selected) < 3
        or len(set(selected)) != len(selected)
    ):
        raise MatchedEnergyError(f"{algorithm} requires at least three distinct runs")
    input_manifest_path = Path(str(manifest.get("input_manifest")))
    input_bytes = input_manifest_path.read_bytes()
    if _sha256(input_bytes) != manifest.get("input_manifest_sha256"):
        raise MatchedEnergyError(f"{algorithm} input manifest hash mismatch")
    input_manifest = json.loads(input_bytes)
    runs_by_id = {run["run_id"]: run for run in input_manifest["runs"]}
    try:
        runs = [runs_by_id[run_id] for run_id in selected]
    except KeyError as exc:
        raise MatchedEnergyError(f"{algorithm} selected an unknown run") from exc
    if len({run["dataset_id"] for run in runs}) < 3:
        raise MatchedEnergyError(f"{algorithm} energy matrix lacks three datasets")
    if any(run["scenario"] != "insert" for run in runs):
        raise MatchedEnergyError(
            f"{algorithm} energy matrix must use matched insert batches"
        )
    return manifest, runs


def analyze_matched_pagerank_energy(
    full_dir: str | Path,
    residual_dir: str | Path,
    cacti_manifest: str | Path,
) -> dict[str, Any]:
    """Build matched 32-controller HBM plus selected-array energy ledgers."""

    chars = load_current_grasu_characterizations(cacti_manifest)
    algorithm_dirs = {
        "full_pagerank": Path(full_dir),
        "thresholded_residual_pagerank": Path(residual_dir),
    }
    rows = []
    matrices = {}
    run_sets = []
    for algorithm, directory in algorithm_dirs.items():
        manifest, runs = _validate_matrix(directory, algorithm)
        matrices[algorithm] = {
            "path": str((directory / "matrix_manifest.json").resolve()),
            "sha256": _sha256((directory / "matrix_manifest.json").read_bytes()),
            "execution_sha256": manifest["execution_sha256"],
        }
        run_sets.append(tuple(run["run_id"] for run in runs))
        for run in runs:
            for system in ("spine", "grasu_regraph"):
                system_dir = directory / run["run_id"] / system
                if system == "spine":
                    activity_path = system_dir / "summary.json"
                    activity = _load_json(activity_path, "Spine activity")
                    profile_id = manifest["spine_profile_id"]
                    if activity.get("architecture_profile_id") != profile_id:
                        raise MatchedEnergyError("Spine profile identity mismatch")
                else:
                    activity_path = system_dir / "manifest.json"
                    child = _load_json(activity_path, "GraSU child manifest")
                    if child.get("status") != "PASS" or not isinstance(
                        child.get("result"), dict
                    ):
                        raise MatchedEnergyError(
                            f"invalid GraSU child for {run['run_id']}"
                        )
                    activity = child["result"]
                    profile_id = manifest["grasu_profile_id"]
                    if child.get("profile_sha256") != manifest.get(
                        "grasu_profile_sha256"
                    ):
                        raise MatchedEnergyError("GraSU profile identity mismatch")
                if activity.get("success") is not True or activity.get(
                    "correctness_mismatches"
                ) != 0:
                    raise MatchedEnergyError(
                        f"incorrect activity for {algorithm}/{run['run_id']}/{system}"
                    )
                cycles = _nonnegative_int(activity.get("cycles"), "cycles")
                core_mhz = _nonnegative_number(activity.get("core_mhz"), "core_mhz")
                if cycles == 0 or core_mhz == 0.0:
                    raise MatchedEnergyError("energy activity requires positive time")
                runtime_ns = cycles * 1000.0 / core_mhz
                dram = aggregate_detailed_dramsim3(system_dir / "dram")
                backend_requests = _nonnegative_int(
                    activity.get("backend_requests"), "backend_requests"
                )
                if dram["reads"] + dram["writes"] != backend_requests:
                    raise MatchedEnergyError(
                        "DRAM request closure failed for "
                        f"{algorithm}/{run['run_id']}/{system}"
                    )
                expected_dram_energy = (
                    activity.get("dram_total_energy_pj")
                    if system == "spine"
                    else child["dram"]["total_energy_pj"]
                )
                if abs(float(expected_dram_energy) - dram["total_energy_pj"]) > max(
                    1.0e-3, dram["total_energy_pj"] * 1.0e-12
                ):
                    raise MatchedEnergyError("parent/DRAMSim3 energy mismatch")
                selected = (
                    {
                        "arrays": [],
                        "dynamic_energy_pj": 0.0,
                        "leakage_energy_pj": 0.0,
                        "total_energy_pj": 0.0,
                        "projected_asic_sram_area_mm2": 0.0,
                        "claim_label": "no_spine_pagerank_array_characterized",
                    }
                    if system == "spine"
                    else grasu_selected_array_energy(
                        activity, chars, runtime_ns=runtime_ns
                    )
                )
                rows.append(
                    {
                        "algorithm": algorithm,
                        "run_id": run["run_id"],
                        "dataset_id": run["dataset_id"],
                        "scenario": run["scenario"],
                        "system": system,
                        "profile_id": profile_id,
                        "cycles": cycles,
                        "core_mhz": core_mhz,
                        "runtime_ns": runtime_ns,
                        "backend_requests": backend_requests,
                        "dram": dram,
                        "selected_onchip": selected,
                        "partial_energy_pj": (
                            dram["total_energy_pj"] + selected["total_energy_pj"]
                        ),
                        "activity_path": str(activity_path.resolve()),
                        "activity_sha256": _sha256(activity_path.read_bytes()),
                        "claim_label": (
                            "full_32_controller_hbm_plus_selected_projected_asic_sram"
                        ),
                    }
                )
    if len(set(run_sets)) != 1:
        raise MatchedEnergyError("Full and residual PageRank run sets differ")
    pairs = []
    by_key = {(row["algorithm"], row["run_id"], row["system"]): row for row in rows}
    for algorithm in algorithm_dirs:
        for run_id in run_sets[0]:
            spine = by_key[(algorithm, run_id, "spine")]
            grasu = by_key[(algorithm, run_id, "grasu_regraph")]
            pairs.append(
                {
                    "algorithm": algorithm,
                    "run_id": run_id,
                    "dataset_id": spine["dataset_id"],
                    "spine_dram_energy_pj": spine["dram"]["total_energy_pj"],
                    "grasu_dram_energy_pj": grasu["dram"]["total_energy_pj"],
                    "grasu_to_spine_dram_energy_ratio": (
                        grasu["dram"]["total_energy_pj"]
                        / spine["dram"]["total_energy_pj"]
                    ),
                    "spine_dram_command_dynamic_energy_pj": spine["dram"][
                        "command_dynamic_energy_pj"
                    ],
                    "grasu_dram_command_dynamic_energy_pj": grasu["dram"][
                        "command_dynamic_energy_pj"
                    ],
                    "grasu_to_spine_dram_command_dynamic_energy_ratio": (
                        grasu["dram"]["command_dynamic_energy_pj"]
                        / spine["dram"]["command_dynamic_energy_pj"]
                    ),
                    "spine_dram_background_refresh_energy_pj": spine["dram"][
                        "background_and_refresh_energy_pj"
                    ],
                    "grasu_dram_background_refresh_energy_pj": grasu["dram"][
                        "background_and_refresh_energy_pj"
                    ],
                    "spine_partial_energy_pj": spine["partial_energy_pj"],
                    "grasu_partial_energy_pj": grasu["partial_energy_pj"],
                    "partial_energy_ratio_valid_as_total": False,
                    "partial_energy_ratio_reason": (
                        "selected on-chip coverage is asymmetric and omits logic, "
                        "FIFOs, interconnect, and clock energy"
                    ),
                    "dram_energy_ratio_valid": True,
                    "dram_energy_scope": "all_32_hbm_controller_instances",
                }
            )
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": "matched_partial_energy_not_total_accelerator_energy",
        "matrices": matrices,
        "cacti_manifest": str(Path(cacti_manifest).resolve()),
        "cacti_manifest_sha256": _sha256(Path(cacti_manifest).read_bytes()),
        "system_rows": rows,
        "pairs": pairs,
        "all_correct": True,
        "limitations": [
            (
                "DRAMSim3 is the complete 32-controller simulated HBM energy "
                "for each run, not FPGA board power."
            ),
            (
                "CACTI-P is projected 32 nm ASIC SRAM characterization, not "
                "U55C BRAM/URAM power."
            ),
            "Spine PageRank on-chip FIFO and pipeline state is not yet characterized.",
            (
                "Logic, FIFO, interconnect, clock tree, host, PCIe, shell, and "
                "board energy are omitted."
            ),
            (
                "Only the HBM energy ratio is a matched cross-system energy "
                "comparison in this ledger."
            ),
        ],
    }


def flatten_system_rows(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten matched system ledgers for CSV output."""

    rows = []
    for row in ledger["system_rows"]:
        dram = row["dram"]
        selected = row["selected_onchip"]
        rows.append(
            {
                "algorithm": row["algorithm"],
                "run_id": row["run_id"],
                "dataset_id": row["dataset_id"],
                "system": row["system"],
                "cycles": row["cycles"],
                "core_mhz": row["core_mhz"],
                "runtime_ns": row["runtime_ns"],
                "backend_requests": row["backend_requests"],
                "dram_reads": dram["reads"],
                "dram_writes": dram["writes"],
                "dram_read_row_hit_ratio": dram["read_row_hit_ratio"],
                "dram_write_row_hit_ratio": dram["write_row_hit_ratio"],
                "dram_idle_controllers": dram["idle_controller_instances"],
                "dram_activate_energy_pj": dram["activate_energy_pj"],
                "dram_read_energy_pj": dram["read_energy_pj"],
                "dram_write_energy_pj": dram["write_energy_pj"],
                "dram_refresh_energy_pj": dram["refresh_energy_pj"],
                "dram_active_standby_energy_pj": dram[
                    "active_standby_energy_pj"
                ],
                "dram_precharge_standby_energy_pj": dram[
                    "precharge_standby_energy_pj"
                ],
                "dram_self_refresh_energy_pj": dram["self_refresh_energy_pj"],
                "dram_total_energy_pj": dram["total_energy_pj"],
                "dram_command_dynamic_energy_pj": dram[
                    "command_dynamic_energy_pj"
                ],
                "dram_background_refresh_energy_pj": dram[
                    "background_and_refresh_energy_pj"
                ],
                "selected_onchip_dynamic_pj": selected["dynamic_energy_pj"],
                "selected_onchip_leakage_pj": selected["leakage_energy_pj"],
                "selected_onchip_total_pj": selected["total_energy_pj"],
                "selected_onchip_area_mm2": selected[
                    "projected_asic_sram_area_mm2"
                ],
                "partial_energy_pj": row["partial_energy_pj"],
                "claim_label": row["claim_label"],
            }
        )
    return rows


def flatten_component_rows(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten selected on-chip arrays for CSV output."""

    rows = []
    for system in ledger["system_rows"]:
        for array in system["selected_onchip"]["arrays"]:
            rows.append(
                {
                    "algorithm": system["algorithm"],
                    "run_id": system["run_id"],
                    "dataset_id": system["dataset_id"],
                    "system": system["system"],
                    **array,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise MatchedEnergyError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
