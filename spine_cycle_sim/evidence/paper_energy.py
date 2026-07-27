"""Fail-closed aggregation for publication-facing matched HBM energy."""

from __future__ import annotations

import math
from typing import Mapping, Sequence


ALGORITHM_LABELS = {
    "full_pagerank": "Full PR",
    "thresholded_residual_pagerank": "Residual PR",
}
EXPECTED_SCOPE = "all_32_hbm_controller_instances"


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _positive(row: Mapping[str, object], key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{key} must be finite and positive")
    return value


def _geometric_mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("geometric mean requires samples")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def paper_hbm_energy_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Aggregate only matched all-controller HBM energy ratios."""

    output: list[dict[str, object]] = []
    for algorithm, label in ALGORITHM_LABELS.items():
        selected = [row for row in rows if row.get("algorithm") == algorithm]
        if len(selected) != 3 or len({row.get("dataset_id") for row in selected}) != 3:
            raise ValueError(f"{algorithm} requires three distinct matched datasets")
        if any(
            not _bool(row.get("dram_energy_ratio_valid", False))
            or _bool(row.get("partial_energy_ratio_valid_as_total", True))
            or row.get("dram_energy_scope") != EXPECTED_SCOPE
            for row in selected
        ):
            raise ValueError(f"{algorithm} energy claim boundary is invalid")

        total_ratios: list[float] = []
        command_ratios: list[float] = []
        background_ratios: list[float] = []
        for row in selected:
            spine_total = _positive(row, "spine_dram_energy_pj")
            grasu_total = _positive(row, "grasu_dram_energy_pj")
            spine_command = _positive(
                row, "spine_dram_command_dynamic_energy_pj"
            )
            grasu_command = _positive(
                row, "grasu_dram_command_dynamic_energy_pj"
            )
            spine_background = _positive(
                row, "spine_dram_background_refresh_energy_pj"
            )
            grasu_background = _positive(
                row, "grasu_dram_background_refresh_energy_pj"
            )
            total_ratio = grasu_total / spine_total
            command_ratio = grasu_command / spine_command
            if not math.isclose(
                total_ratio,
                _positive(row, "grasu_to_spine_dram_energy_ratio"),
                rel_tol=1e-12,
            ) or not math.isclose(
                command_ratio,
                _positive(
                    row, "grasu_to_spine_dram_command_dynamic_energy_ratio"
                ),
                rel_tol=1e-12,
            ):
                raise ValueError(f"{algorithm} stored energy ratio does not close")
            total_ratios.append(total_ratio)
            command_ratios.append(command_ratio)
            background_ratios.append(grasu_background / spine_background)

        output.append(
            {
                "algorithm": label,
                "algorithm_id": algorithm,
                "pairs": len(selected),
                "grasu_to_spine_total_hbm": _geometric_mean(total_ratios),
                "grasu_to_spine_command_dynamic": _geometric_mean(
                    command_ratios
                ),
                "grasu_to_spine_background_refresh": _geometric_mean(
                    background_ratios
                ),
            }
        )
    return output
