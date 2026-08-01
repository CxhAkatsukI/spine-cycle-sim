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
    ("t_xfer_cycles", r"$T_{xfer}$", "#1f77b4", "///"),
    ("t_reduce_cycles", r"$T_{reduce}$", "#17becf", "\\\\\\"),
    ("t_carry_cycles", r"$T_{carry}$", "#ff7f0e", "|||"),
    ("t_directory_cycles", r"$T_{dir}$", "#bcbd22", "xxx"),
    ("t_seed_cycles", r"$T_{seed}$", "#2ca02c", "..."),
    ("t_switch_cycles", r"$T_{switch}$", "#9467bd", "++"),
    ("t_resolve_cycles", r"$T_{resolve}$", "#d62728", "ooo"),
    ("t_app_cycles", r"$T_{app}$", "#e377c2", "***"),
    ("t_drain_cycles", r"$T_{drain}$", "#8c564b", "---"),
    ("t_sync_cycles", r"$T_{sync}$", "#7f7f7f", "OO"),
)
EXPANDED_COMPONENTS = (
    (
        ("t_xfer_cycles", "t_reduce_cycles", "t_carry_cycles", "t_directory_cycles"),
        "Maint.",
        "#a8cf88",
        "xxxxxx",
    ),
    (("t_seed_cycles", "t_switch_cycles"), "Seed/pub.", "#f1a55b", "||||||"),
    (("t_resolve_cycles",), "Resolve", "#2f86bd", "//////"),
    (("t_app_cycles",), "App", "#b7d6e8", "\\\\\\\\\\\\"),
    (("t_drain_cycles", "t_sync_cycles"), "Drain", "#35a936", "xxxxxx"),
)
EXPANDED_BREAKDOWN_GROUPS = (
    (
        "ZN",
        (
            ("Syn", "rq3_zero_net_cc_u2"),
        ),
    ),
    (
        "SI",
        (
            ("A-S", "53d8ac095d6b4bb6739f"),
            ("L-S", "980c084e249992cc626c"),
            ("S-S", "b76a15fdd98228a1da6e"),
        ),
    ),
    (
        "Carry",
        (
            ("L1", "rq3_trace_carry_l1_e8"),
            ("L3", "rq3_trace_carry_l3_e8"),
            ("L5", "rq3_trace_carry_l5_e8"),
        ),
    ),
    (
        "PR-corr",
        (
            ("FL", "rq3_flickr_residual_correction_u8_eps1e6"),
            ("SU", "3f8e9fc7157d096b8488"),
            ("WK", "d310ed825d5fef3de031"),
        ),
    ),
    (
        "Del",
        (
            ("AU", "087ea93d578261400aa6"),
            ("SU", "12b7427a1e2f4185c8c9"),
            ("WK", "383e63c5d7f96cdd4774"),
        ),
    ),
)
REGRESSIONS = (
    (
        "sort_frontend",
        "w_sort_records",
        "t_xfer_reduce_cycles",
        "Physical update records",
        r"$T_{xfer}+T_{reduce}$ cycles",
    ),
    (
        "carry",
        "w_carry_records",
        "t_carry_cycles",
        "Carry payload records",
        r"$T_{carry}$ cycles",
    ),
    (
        "directory",
        "directory_requests",
        "t_directory_cycles",
        "Directory requests",
        r"$T_{dir}$ cycles",
    ),
    (
        "physical_resolve_apply",
        "m_phys_records",
        "t_resolve_app_cycles",
        "Physical edge records",
        r"$T_{resolve}+T_{app}$ cycles",
    ),
    (
        "seed",
        "m_seed_records",
        "t_seed_cycles",
        "Dirty-source seeds",
        r"$T_{seed}$ cycles",
    ),
    (
        "switch",
        "switch_work",
        "t_switch_cycles",
        "Touched pages + descriptors",
        r"$T_{switch}$ cycles",
    ),
    (
        "drain",
        "source_and_reactivation_work",
        "t_drain_cycles",
        "Source services + reactivations",
        r"$T_{drain}$ cycles",
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

    figure, axis = plt.subplots(figsize=(7.2, 3.55))
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
        bbox_to_anchor=(0.5, 1.38),
        ncol=5,
        frameon=False,
        handlelength=1.8,
        columnspacing=0.9,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.86))
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    normalize_generated_svg(output.with_suffix(".svg"))
    plt.close(figure)


def render_expanded_breakdown(rows: list[dict[str, str]], output: Path) -> None:
    plt = configure_matplotlib()
    from matplotlib.patches import Patch

    plt.rcParams.update(
        {
            "font.family": "monospace",
            "font.monospace": ["DejaVu Sans Mono", "Consolas", "monospace"],
            "axes.linewidth": 0.8,
            "hatch.linewidth": 0.3,
            "legend.fontsize": 6.8,
            "xtick.labelsize": 6.2,
            "ytick.labelsize": 7.0,
            "axes.labelsize": 8.0,
        }
    )
    by_execution = {row["execution_id"]: row for row in rows}
    selected: list[dict[str, str]] = []
    tick_labels: list[str] = []
    x_positions: list[float] = []
    group_centers: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    for group_label, entries in EXPANDED_BREAKDOWN_GROUPS:
        start = cursor
        for tick_label, execution_id in entries:
            if execution_id not in by_execution:
                raise ValueError(f"missing expanded RQ3 execution: {execution_id}")
            selected.append(by_execution[execution_id])
            tick_labels.append(tick_label)
            x_positions.append(cursor)
            cursor += 1.0
        end = cursor - 1.0
        group_centers.append((group_label, (start + end) / 2.0))
        separators.append(end + 0.55)
        cursor += 0.68
    separators = separators[:-1]

    figure, axis = plt.subplots(figsize=(3.55, 2.05))
    bottoms = [0.0] * len(selected)
    legend: list[Any] = []
    for keys, label, color, hatch in EXPANDED_COMPONENTS:
        percentages = []
        for row in selected:
            total = number(row, "total_cycles")
            component_cycles = sum(number(row, key) for key in keys)
            percentages.append(100.0 * component_cycles / total if total else 0.0)
        axis.bar(
            x_positions,
            percentages,
            bottom=bottoms,
            width=0.58,
            color=color,
            edgecolor="black",
            linewidth=0.22,
            hatch=hatch,
            zorder=2,
        )
        bottoms = [left + right for left, right in zip(bottoms, percentages, strict=True)]
        legend.append(Patch(facecolor=color, edgecolor="black", hatch=hatch, label=label))

    for separator in separators:
        axis.axvline(
            separator,
            color="black",
            linestyle=(0, (2.0, 1.1)),
            linewidth=0.65,
            ymin=-0.11,
            ymax=1.0,
            clip_on=False,
            zorder=4,
        )
    for group_label, center in group_centers:
        axis.text(
            center,
            -0.24,
            group_label,
            transform=axis.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=8.2,
            clip_on=False,
        )

    axis.set_xlim(min(x_positions) - 0.65, max(x_positions) + 0.65)
    axis.set_xticks(x_positions, tick_labels)
    axis.set_ylabel("E2E cycles (%)")
    axis.set_ylim(0.0, 108.0)
    axis.set_yticks((0, 25, 50, 75, 100))
    axis.tick_params(direction="in", top=False, right=True, length=3, width=0.7)
    axis.grid(
        axis="y",
        linestyle=(0, (2.0, 1.1)),
        color="0.72",
        alpha=0.65,
        linewidth=0.48,
        zorder=0,
    )
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
    axis.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.24),
        ncol=5,
        frameon=False,
        handlelength=1.5,
        handletextpad=0.35,
        columnspacing=0.58,
        borderaxespad=0.0,
    )
    figure.subplots_adjust(left=0.15, right=0.995, bottom=0.27, top=0.76)
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
    if key == "t_xfer_reduce_cycles":
        return number(row, "t_xfer_cycles") + number(row, "t_reduce_cycles")
    if key == "t_resolve_app_cycles":
        return number(row, "t_resolve_cycles") + number(row, "t_app_cycles")
    if key == "source_and_reactivation_work":
        return number(row, "source_services") + number(row, "reactivations")
    return number(row, key)


def render_correlations(
    work_rows: list[dict[str, str]], fit_rows: list[dict[str, str]], output: Path
) -> None:
    plt = configure_matplotlib()
    fits = fit_lookup(fit_rows)
    figure, axes = plt.subplots(4, 2, figsize=(7.2, 9.0))
    role_style = {
        "synthetic_calibration": ("#1f77b4", "s", "Calibration"),
        "trace_calibration": ("#1f77b4", "^", "Calibration trace"),
        "trace_holdout": ("#d62728", "o", "Holdout"),
    }
    for axis, (mechanism, x_key, y_key, x_label, y_label) in zip(
        axes.flat, REGRESSIONS
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
    for axis in axes.flat[len(REGRESSIONS) :]:
        axis.axis("off")
    axes[0, 0].legend(loc="best", frameon=False)
    figure.tight_layout()
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(output.with_suffix(".svg"), bbox_inches="tight")
    normalize_generated_svg(output.with_suffix(".svg"))
    plt.close(figure)


def render_e2e_model(
    prediction_rows: list[dict[str, str]],
    metric_rows: list[dict[str, str]],
    output: Path,
) -> None:
    plt = configure_matplotlib()
    real_holdout = [
        row
        for row in prediction_rows
        if row.get("model_role") == "trace_holdout"
        and row.get("dataset_kind") == "real"
    ]
    if len(real_holdout) < 30:
        raise ValueError("RQ3 E2E model requires at least 30 real trace holdout rows")
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.25))
    styles = (
        (
            [row for row in prediction_rows if row["model_role"] == "calibration"],
            "#1f77b4",
            "s",
            "Calibration",
        ),
        (real_holdout, "#d62728", "o", "Real trace holdout"),
    )
    all_values: list[float] = []
    for rows, color, marker, label in styles:
        if not rows:
            continue
        observed = [number(row, "observed_cycles") for row in rows]
        predicted = [number(row, "predicted_cycles") for row in rows]
        errors = [number(row, "absolute_percent_error") for row in rows]
        all_values.extend(observed + predicted)
        axes[0].scatter(
            observed,
            predicted,
            s=24,
            marker=marker,
            facecolors="white",
            edgecolors=color,
            linewidths=1.1,
            label=label,
            zorder=3,
        )
        axes[1].scatter(
            observed,
            errors,
            s=24,
            marker=marker,
            facecolors="white",
            edgecolors=color,
            linewidths=1.1,
            label=label,
            zorder=3,
        )
    positive = [value for value in all_values if value > 0.0]
    if not positive:
        raise ValueError("RQ3 E2E model has no positive predictions")
    lower, upper = min(positive), max(positive)
    axes[0].plot((lower, upper), (lower, upper), color="black", linewidth=1.0)
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Measured E2E cycles")
    axes[0].set_ylabel("Predicted E2E cycles")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Measured E2E cycles")
    axes[1].set_ylabel("Absolute error (%)")
    by_role = {row["role"]: row for row in metric_rows}
    holdout = by_role["real_trace_holdout"]
    axes[0].text(
        0.04,
        0.95,
        f"Holdout $R^2$={float(holdout['r2']):.3f}",
        transform=axes[0].transAxes,
        va="top",
    )
    axes[1].text(
        0.04,
        0.95,
        f"median={float(holdout['median_ape_percent']):.1f}%\n"
        f"mean={float(holdout['mape_percent']):.1f}%\n"
        f"max={float(holdout['max_ape_percent']):.1f}%",
        transform=axes[1].transAxes,
        va="top",
    )
    for axis in axes:
        style_axis(axis)
    axes[0].legend(frameon=False)
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
                    f"{int(number(row, 't_resolve_cycles') + number(row, 't_app_cycles')):,}",
                    f"{int(number(row, 't_drain_cycles') + number(row, 't_sync_cycles')):,}",
                )
            )
            + r" \\"
        )
    representative_table = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Case & Algorithm & E2E cyc & Maint. & Resolve+App & Drain+Sync \\",
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
        "rq3_e2e_prediction_rows.csv",
        "rq3_e2e_metric_rows.csv",
        "rq3_e2e_model.json",
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
    predictions = read_csv(args.analysis_dir / "rq3_e2e_prediction_rows.csv")
    model_metrics = read_csv(args.analysis_dir / "rq3_e2e_metric_rows.csv")
    render_breakdown(representatives, args.figure_dir / "rq3_latency_breakdown")
    render_expanded_breakdown(joined_rows, args.figure_dir / "rq3_latency_breakdown_expanded")
    render_correlations(joined_rows, regressions, args.figure_dir / "rq3_work_correlations")
    render_e2e_model(predictions, model_metrics, args.figure_dir / "rq3_e2e_cost_model")
    write_tex_tables(representatives, regressions, args.data_dir)
    print(
        f"PASS RQ3 figures: representatives={len(representatives)} "
        f"work_rows={len(work_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
