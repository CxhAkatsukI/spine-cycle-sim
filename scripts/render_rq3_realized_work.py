#!/usr/bin/env python3
"""Render GraphyFlow-style RQ3 figures from correctness-gated CSV evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


CASE_ORDER = (
    "zero_net",
    "shallow_insertion",
    "deep_carry",
    "pagerank_correction",
    "deletion_fallback",
)
CASE_LABELS = {
    "zero_net": "Zero-net",
    "shallow_insertion": "Shallow\ninsert",
    "deep_carry": "Deep\ncarry",
    "pagerank_correction": "PR\ncorrection",
    "deletion_fallback": "Deletion\nfallback",
}
ALGORITHM_LABELS = {
    "weighted_sssp": "SSSP",
    "connected_components": "CC",
    "thresholded_residual_pagerank": "Residual PR",
}
COMPONENTS = (
    ("maintenance_cycles", "Maintenance", "#1f77b4", "///"),
    ("resolve_only_cycles", "Resolve", "#ff7f0e", "\\\\\\"),
    ("app_only_cycles", "Apply", "#2ca02c", "|||"),
    ("resolve_app_overlap_cycles", "Resolve/app overlap", "#d62728", "xxx"),
    ("integrated_resolve_app_cycles", "Integrated resolve/app", "#9467bd", "..."),
    ("sync_cycles", "Drain/sync", "#8c564b", "++"),
    ("other_cycles", "Other", "#7f7f7f", "---"),
)
REGRESSIONS = (
    (
        "carry",
        "w_carry_records",
        "carry_wait_cycles",
        "Carry payload records",
        "Carry wait cycles",
    ),
    (
        "physical_resolve_apply",
        "m_phys_records",
        "resolve_app_active_cycles",
        "Physical edge records",
        "Resolve + apply active cycles",
    ),
    (
        "seed",
        "m_seed_records",
        "seed_schedule_cycles",
        "Dirty-source seeds",
        "Seed schedule cycles",
    ),
    (
        "drain_sync",
        "source_and_reactivation_work",
        "sync_cycles",
        "Source services + reactivations",
        "Drain/sync cycles",
    ),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def copy_csv_lf(source: Path, destination: Path) -> None:
    rows = read_csv(source)
    with source.open(encoding="ascii", newline="") as stream:
        fieldnames = list(csv.DictReader(stream).fieldnames or ())
    with destination.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def copy_json_canonical(source: Path, destination: Path) -> None:
    payload = json.loads(source.read_text(encoding="ascii"))
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def normalize_generated_svg(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in (None, "") else 0.0


def compact_cycles(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "sans-serif"],
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.linewidth": 1.1,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "hatch.linewidth": 0.9,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


def style_axis(axis: Any, *, grid: bool = True) -> None:
    axis.tick_params(direction="in", top=True, right=True, length=4)
    if grid:
        axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(1.1)


def render_breakdown(rows: list[dict[str, str]], output: Path) -> None:
    plt = configure_matplotlib()
    from matplotlib.patches import Patch

    by_class = {row["case_class"]: row for row in rows}
    missing = [case for case in CASE_ORDER if case not in by_class]
    if missing:
        raise ValueError(f"RQ3 representative coverage is incomplete: {missing}")
    selected = [by_class[case] for case in CASE_ORDER]

    figure, axis = plt.subplots(figsize=(7.2, 3.15))
    bottoms = [0.0] * len(selected)
    x_positions = list(range(len(selected)))
    legend: list[Any] = []
    for key, label, color, hatch in COMPONENTS:
        percentages = []
        for row in selected:
            total = number(row, "total_cycles")
            percentages.append(100.0 * number(row, key) / total if total else 0.0)
        axis.bar(
            x_positions,
            percentages,
            bottom=bottoms,
            width=0.58,
            facecolor="white",
            edgecolor=color,
            linewidth=0.0,
            hatch=hatch,
            zorder=2,
        )
        axis.bar(
            x_positions,
            percentages,
            bottom=bottoms,
            width=0.58,
            facecolor="none",
            edgecolor="black",
            linewidth=0.8,
            zorder=3,
        )
        bottoms = [left + right for left, right in zip(bottoms, percentages, strict=True)]
        legend.append(Patch(facecolor="white", edgecolor=color, hatch=hatch, label=label))

    for position, row in zip(x_positions, selected, strict=True):
        axis.text(
            position,
            102.0,
            f"{compact_cycles(number(row, 'total_cycles'))} cyc",
            ha="center",
            va="bottom",
            fontsize=7.5,
        )
    axis.set_xticks(x_positions, [CASE_LABELS[case] for case in CASE_ORDER])
    axis.set_ylabel("Share of end-to-end cycles (%)")
    axis.set_ylim(0.0, 112.0)
    axis.set_yticks((0, 20, 40, 60, 80, 100))
    style_axis(axis)
    axis.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.30),
        ncol=4,
        frameon=False,
        handlelength=1.8,
        columnspacing=0.9,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.90))
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    normalize_generated_svg(output.with_suffix(".svg"))
    plt.close(figure)


def fit_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        row["mechanism"]: row
        for row in rows
        if row["role"] == "all" and row.get("r2", "") != ""
    }


def work_value(row: dict[str, str], key: str) -> float:
    if key == "resolve_app_active_cycles":
        return number(row, "resolve_active_cycles") + number(row, "app_active_cycles")
    if key == "source_and_reactivation_work":
        return number(row, "source_services") + number(row, "reactivations")
    return number(row, key)


def render_correlations(
    work_rows: list[dict[str, str]], fit_rows: list[dict[str, str]], output: Path
) -> None:
    plt = configure_matplotlib()
    fits = fit_lookup(fit_rows)
    figure, axes = plt.subplots(2, 2, figsize=(7.2, 5.5))
    role_style = {
        "synthetic_calibration": ("#1f77b4", "s", "Calibration"),
        "trace_holdout": ("#d62728", "o", "Holdout"),
    }
    for axis, (mechanism, x_key, y_key, x_label, y_label) in zip(
        axes.flat, REGRESSIONS, strict=True
    ):
        plotted: list[tuple[float, float]] = []
        for role, (color, marker, label) in role_style.items():
            points = [
                (work_value(row, x_key), work_value(row, y_key))
                for row in work_rows
                if row["role"] == role
                and work_value(row, x_key) > 0.0
                and work_value(row, y_key) > 0.0
            ]
            if not points:
                continue
            plotted.extend(points)
            axis.scatter(
                [point[0] for point in points],
                [point[1] for point in points],
                s=24,
                marker=marker,
                facecolors="white",
                edgecolors=color,
                linewidths=1.1,
                label=label,
                zorder=3,
            )
        fit = fits[mechanism]
        slope = float(fit["slope"])
        intercept = float(fit["intercept"])
        if plotted:
            x_min = min(point[0] for point in plotted)
            x_max = max(point[0] for point in plotted)
            ratio = x_max / x_min if x_min > 0.0 else 1.0
            samples = 100
            if ratio > 1.0:
                xs = [
                    x_min * math.exp(math.log(ratio) * index / (samples - 1))
                    for index in range(samples)
                ]
            else:
                xs = [x_min]
            line = [(x, slope * x + intercept) for x in xs if slope * x + intercept > 0]
            axis.plot(
                [point[0] for point in line],
                [point[1] for point in line],
                color="black",
                linewidth=1.0,
                zorder=2,
            )
            if ratio >= 20.0:
                axis.set_xscale("log")
            y_values = [point[1] for point in plotted]
            if min(y_values) > 0.0 and max(y_values) / min(y_values) >= 20.0:
                axis.set_yscale("log")
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        axis.text(
            0.04,
            0.94,
            f"$R^2$={float(fit['r2']):.4f}, n={int(fit['samples'])}",
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
        )
        style_axis(axis)
    axes[0, 0].legend(loc="lower right", frameon=False)
    figure.tight_layout()
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    normalize_generated_svg(output.with_suffix(".svg"))
    plt.close(figure)


def tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def write_tex_tables(
    representatives: list[dict[str, str]], regressions: list[dict[str, str]], data_dir: Path
) -> None:
    by_class = {row["case_class"]: row for row in representatives}
    lines = []
    for case in CASE_ORDER:
        row = by_class[case]
        lines.append(
            " & ".join(
                (
                    tex_escape(CASE_LABELS[case].replace("\n", " ")),
                    ALGORITHM_LABELS.get(row["algorithm"], tex_escape(row["algorithm"])),
                    f"{int(number(row, 'total_cycles')):,}",
                    f"{int(number(row, 'maintenance_cycles')):,}",
                    f"{int(number(row, 'integrated_resolve_app_cycles')):,}",
                    f"{int(number(row, 'sync_cycles')):,}",
                )
            )
            + r" \\"
        )
    representative_table = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Case & Algorithm & E2E cyc & Maint. & Integrated R/A & Sync \\",
        r"\midrule",
        *lines,
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (data_dir / "representative_table.tex").write_text(
        "\n".join(representative_table) + "\n", encoding="ascii"
    )

    fits = fit_lookup(regressions)
    lines = []
    for mechanism, *_ in REGRESSIONS:
        row = fits[mechanism]
        lines.append(
            f"{tex_escape(mechanism)} & {int(row['samples'])} & "
            f"{float(row['slope']):.3f} & {float(row['r2']):.4f} \\\\"
        )
    regression_table = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Mechanism & Samples & Slope & $R^2$ \\",
        r"\midrule",
        *lines,
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (data_dir / "regression_table.tex").write_text(
        "\n".join(regression_table) + "\n", encoding="ascii"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, default=Path("docs/figures"))
    parser.add_argument("--data-dir", type=Path, default=Path("docs/paper/data/rq3"))
    args = parser.parse_args()
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    args.data_dir.mkdir(parents=True, exist_ok=True)

    input_names = (
        "rq3_representative_rows.csv",
        "rq3_work_rows.csv",
        "rq3_latency_rows.csv",
        "rq3_regression_rows.csv",
        "rq3_coverage_rows.csv",
        "rq3_summary.json",
    )
    for name in input_names:
        source = args.analysis_dir / name
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = args.data_dir / name
        if source.suffix == ".csv":
            copy_csv_lf(source, destination)
        elif source.suffix == ".json":
            copy_json_canonical(source, destination)
        else:
            raise ValueError(f"unsupported RQ3 evidence format: {source}")

    representatives = read_csv(args.analysis_dir / "rq3_representative_rows.csv")
    work_rows = read_csv(args.analysis_dir / "rq3_work_rows.csv")
    latency_rows = {
        row["execution_id"]: row
        for row in read_csv(args.analysis_dir / "rq3_latency_rows.csv")
    }
    joined_rows = [
        {**row, **latency_rows[row["execution_id"]]}
        for row in work_rows
        if row["execution_id"] in latency_rows
    ]
    if len(joined_rows) != len(work_rows):
        raise ValueError("RQ3 work and latency execution IDs do not close")
    regressions = read_csv(args.analysis_dir / "rq3_regression_rows.csv")
    render_breakdown(representatives, args.figure_dir / "rq3_latency_breakdown")
    render_correlations(joined_rows, regressions, args.figure_dir / "rq3_work_correlations")
    write_tex_tables(representatives, regressions, args.data_dir)
    print(
        f"PASS RQ3 figures: representatives={len(representatives)} "
        f"work_rows={len(work_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
