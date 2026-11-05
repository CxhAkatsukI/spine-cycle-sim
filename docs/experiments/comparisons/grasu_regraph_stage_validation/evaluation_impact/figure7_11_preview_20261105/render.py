"""Render the dated handoff without modifying or mixing its evidence sets."""

import argparse
import csv
import hashlib
import importlib.util
from math import isclose, log10
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator, NullLocator


ROOT = Path(__file__).resolve().parent
HANDOFF = ROOT.parent / "figure7_11_handoff_20261103" / "data"
REPAIR = ROOT.parent / "hardware_validation" / "r_retention_repair_20261103"
STYLE = ROOT.parents[4] / "evaluation_refresh_20260810" / "figure7_10_handoff_v1"
ARCHIVE_HASH = "a1b053bbd7c20cd9ce5c79d44a11027327da1c72a402487f5c8c659b71c18a27"
DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHMS = {"weighted_sssp": "SSSP", "connected_components": "CC", "residual_pagerank": "ResPR"}
INK = "#202428"
BLUE, ORANGE, GREEN = "#1f77b4", "#ff7f0e", "#2ca02c"
SERIES = ((GREEN, "|" * 8), (BLUE, "\\" * 8), (ORANGE, "/" * 8))
ALGORITHM_COLORS = dict(zip(ALGORITHMS.values(), (GREEN, BLUE, ORANGE), strict=True))


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def numbers(rows, field):
    return [float(row[field]) for row in rows]


def prior_renderer():
    archive = STYLE / "reference" / "GraphyFlow_Plot.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_HASH:
        raise ValueError("unexpected GraphyFlow reference archive")
    spec = importlib.util.spec_from_file_location("handoff_style", STYLE / "render_all.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bars(axis, x, y, series, *, width=0.65, bottom=0, label=None):
    # GraphyFlow's grouped-bar template separates the fill, hatch and border.
    color, hatch = series
    heights = [value - bottom for value in y]
    for face, edge, line, pattern, order in (
        ("white", "none", 0, None, 2),
        ("none", color, 0, hatch, 3),
        ("none", INK, 0.45, None, 4),
    ):
        axis.bar(x, heights, width=width, bottom=bottom, facecolor=face,
                 edgecolor=edge, linewidth=line, hatch=pattern, zorder=order)
    if label:
        from matplotlib.patches import Patch

        return Patch(facecolor="white", edgecolor=color, hatch=hatch, linewidth=0.55, label=label)


def style_axis(axis, *, parity=False, categorical=True):
    axis.grid(axis="y", color="#c8cdd0", linestyle="--", linewidth=0.4, zorder=0)
    if parity:
        axis.axhline(1, color=INK, linestyle=(0, (3, 2)), linewidth=0.6, zorder=5)
    axis.tick_params(direction="in", right=True)
    axis.yaxis.set_major_formatter(FuncFormatter(
        lambda value, _: f"1e{round(log10(value))}" if value >= 1000 else f"{value:g}"
    ))
    if categorical:
        axis.tick_params(axis="x", length=0, pad=2.5)
    for spine in axis.spines.values():
        spine.set_color(INK)
        spine.set_zorder(8)


def legend(axis, handles=None, *, ncol=1, height=1.045):
    axis.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, height),
                ncol=ncol, frameon=False, handlelength=1.45, columnspacing=0.85)


def log_axis(axis, lower, upper, ticks):
    axis.set_yscale("log")
    axis.set_ylim(lower, upper)
    axis.set_yticks(ticks)
    axis.yaxis.set_minor_locator(NullLocator())


def save(figure, output, stem):
    for suffix in ("pdf", "png"):
        metadata = {"CreationDate": None, "ModDate": None} if suffix == "pdf" else None
        figure.savefig(output / f"{stem}.{suffix}", dpi=300, bbox_inches="tight",
                       pad_inches=0.035, metadata=metadata)
    plt.close(figure)


def grouped(axis, groups, keys, values, *, bottom=0):
    width = 0.23
    handles = []
    for i, (key, series) in enumerate(zip(keys, SERIES, strict=True)):
        offsets = [x + (i - 1) * width for x in range(len(groups))]
        handles.append(bars(axis, offsets, [values[group, key] for group in groups],
                            series, width=width, bottom=bottom, label=key))
    axis.set_xticks(range(len(groups)), groups)
    return handles


def source_comparison(output):
    rows = read_csv(ROOT / "gr_source_comparison.csv")
    figure, axes = plt.subplots(1, 2, figsize=(5.3, 1.88), width_ratios=(1, 2.35),
                                layout="constrained")
    for axis, stage in zip(axes, ("G", "R"), strict=True):
        selected = [row for row in rows if row["stage"] == stage]
        ratios = [float(row["integrated_ms"]) / float(row["public_ms"]) for row in selected]
        for i, row in enumerate(selected):
            axis.scatter(i, ratios[i], s=15, zorder=6, linewidth=0.65,
                         color=ALGORITHM_COLORS[row["algorithm"]],
                         edgecolor=INK)
        if stage == "G":
            axis.set_xticks(range(3), ["SSSP", "CC", "ResPR"])
            log_axis(axis, 0.3, 11.5, (0.5, 1, 2, 4, 8))
            for i, ratio in enumerate(ratios):
                axis.annotate(f"{ratio:.2f}x", (i, ratio), (0, 4), textcoords="offset points",
                              ha="center", fontsize=5.5)
            axis.set_title("(a) G: AU 131K updates", pad=7)
        else:
            axis.set_xticks(range(len(selected)), [row["workload"] for row in selected])
            for center, name in ((1, "SSSP"), (4, "CC"), (6.5, "ResPR")):
                axis.text(center, -0.15, name, ha="center", va="top",
                          transform=axis.get_xaxis_transform())
            axis.set_ylim(0.88, 1.30)
            axis.set_yticks((0.9, 1, 1.1, 1.2, 1.3))
            axis.set_title("(b) Adapter + R: resident R control", pad=7)
        axis.set_xlim(-0.55, len(selected) - 0.45)
        style_axis(axis, parity=True)
    axes[0].set_ylabel("Elapsed / public source")
    save(figure, output, "gr_source_comparison")


def fig7(output):
    rows = read_csv(HANDOFF / "fig7_fpga_speedup.csv")
    assert len(rows) == 24 and all(row["status"] == "RESIDENT_PAIR_PASS" for row in rows)
    values = {(row["dataset"], ALGORITHMS[row["algorithm"]]): float(row["speedup_gr_over_spine"])
              for row in rows}
    floor = 0.1 if min(values.values()) < 1 else 1
    figure, axis = plt.subplots(figsize=(3.55, 1.65), layout="constrained")
    handles = grouped(axis, DATASETS, tuple(ALGORITHMS.values()), values, bottom=floor)
    log_axis(axis, floor, 115, tuple(tick for tick in (0.1, 1, 10, 100) if tick >= floor))
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.set_title("Oct. 26 FPGA; ResPR: zero propagation rounds", fontsize=6, pad=4)
    legend(axis, handles, ncol=3)
    style_axis(axis, parity=floor < 1)
    save(figure, output, "fig7_oct26_fpga")

    newer = read_csv(REPAIR / "sssp-resident-followup" / "figure7.csv")
    measured = {row["dataset"]: float(row["gr_over_spine"]) for row in newer
                if row["algorithm"] == "weighted_sssp" and row["status"] == "MEASURED_RESIDENT_PAIR"}
    figure, axis = plt.subplots(figsize=(3.55, 1.5), layout="constrained")
    positions = {dataset: i for i, dataset in enumerate(DATASETS)}
    bars(axis, [positions[dataset] for dataset in measured], list(measured.values()), SERIES[0])
    axis.set_xticks(range(len(DATASETS)), DATASETS)
    for dataset in DATASETS:
        if dataset not in measured:
            axis.text(positions[dataset], 1.45, "n/m", ha="center", va="bottom", fontsize=5)
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.set_ylim(0, 16)
    axis.set_title("Nov. 4 FPGA; six SSSP pairs on earlier image", pad=7)
    style_axis(axis, parity=True)
    save(figure, output, "fig7_nov04_sssp_diagnostic")

    legacy = read_csv(HANDOFF / "fig7_fullpr_legacy_not_refreshed.csv")
    figure, axis = plt.subplots(figsize=(3.55, 1.44), layout="constrained")
    values = numbers(legacy, "speedup_median")
    x = range(len(legacy))
    bars(axis, x, values, SERIES[2], bottom=0.01)
    axis.errorbar(x, values, yerr=[
        [value - float(row["speedup_min"]) for value, row in zip(values, legacy, strict=True)],
        [float(row["speedup_max"]) - value for value, row in zip(values, legacy, strict=True)],
    ], fmt="none", ecolor=INK, elinewidth=0.55, capsize=1.6, zorder=7)
    axis.set_xticks(x, [row["dataset"] for row in legacy])
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.set_title("Legacy compact FPGA FullPR", pad=7)
    log_axis(axis, 0.01, 1.3, (0.01, 0.1, 1))
    style_axis(axis, parity=True)
    save(figure, output, "fig7_fullpr_legacy")


def fig7_banked_sssp(output):
    rows = read_csv(ROOT / "fig7_sssp_banked.csv")
    if tuple(row["dataset"] for row in rows) != DATASETS or any(
        row["status"] != "MEASURED_RESIDENT_PAIR" for row in rows
    ):
        raise ValueError("expected eight admitted banked SSSP pairs")
    values = numbers(rows, "speedup_gr_over_spine")
    figure, axis = plt.subplots(figsize=(3.55, 1.52), layout="constrained")
    x = range(len(rows))
    bars(axis, x, values, SERIES[0], width=0.62)
    axis.set_xticks(x, DATASETS)
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.set_ylim(0, max(5, max(values) * 1.13))
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    axis.set_title("Weighted SSSP, banked G+R (FPGA)", pad=7)
    style_axis(axis, parity=True)
    save(figure, output, "fig7_sssp_banked")


def fig7_nov05(output):
    rows = read_csv(ROOT / "fig7_nov05_diagnostic.csv")
    by_case = {(row["algorithm"], row["dataset"]): row for row in rows}
    keys = ("weighted_sssp", "cc", "respr")
    if len(rows) != 24 or set(by_case) != {(key, dataset) for key in keys for dataset in DATASETS}:
        raise ValueError("expected a unique status for each diagnostic case")

    figure, axis = plt.subplots(figsize=(3.55, 1.85), layout="constrained")
    width = 0.23
    floor = 0.1
    handles, measured = [], []
    for i, (key, name, series) in enumerate(zip(keys, ALGORITHMS.values(), SERIES, strict=True)):
        x, y = [], []
        for j, dataset in enumerate(DATASETS):
            row = by_case[key, dataset]
            position = j + (i - 1) * width
            if row["status"] == "MEASURED_RESIDENT_PAIR":
                x.append(position)
                y.append(float(row["gr_over_spine"]))
            elif row["status"] in {"FAILED_RETAINED", "RECEIPT_REJECTED"}:
                axis.plot(position, 0.065, marker="x", color=series[0], linestyle="none",
                          markersize=2.6, markeredgewidth=0.7, transform=axis.get_xaxis_transform())
        measured.extend(y)
        handles.append(bars(axis, x, y, series, width=width, bottom=floor, label=name))
    if not measured or min(measured) <= floor:
        raise ValueError("unexpected range of diagnostic speedups")
    upper = max(12, max(measured) * 1.2)
    log_axis(axis, floor, upper, tuple(tick for tick in (0.1, 1, 10, 100, 1000) if tick < upper))
    axis.set_xticks(range(len(DATASETS)), DATASETS)
    axis.set_xlim(-0.5, len(DATASETS) - 0.5)
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.set_xlabel("x: failed or rejected; blank: no result", fontsize=5.5)
    axis.set_title(r"Nov. 5 FPGA diagnostic; AU R outside 15\%", fontsize=5.8, pad=4)
    legend(axis, handles, ncol=3)
    style_axis(axis, parity=True)
    save(figure, output, "fig7_nov05_fpga_diagnostic")


def fig8_persistent(output, data=ROOT, stem="fig8_ten_batch_partial"):
    rows = read_csv(data / "fig8_ten_batch.csv")
    if any(row["status"] != "PERSISTENT_PAIRED_SETUP_PREDICTION" or row["baseline_admitted"] != "False"
           or (int(row["updates"]), int(row["batches"])) != (4096, 10) for row in rows):
        raise ValueError("expected ten-batch update-only predictions")
    figure, (axis, right) = plt.subplots(1, 2, figsize=(3.55, 1.92), layout="constrained")
    datasets = ("AU", "SU", "WK", "SO", "PK")
    positions = {dataset: i for i, dataset in enumerate(datasets)}
    values = [float(row["gr_setup_inclusive_seconds"]) / float(row["spine_setup_inclusive_seconds"])
              for row in rows]
    handle = bars(axis, [positions[row["dataset"]] for row in rows], values, SERIES[0], label="10 batches")
    for dataset in set(datasets) - {row["dataset"] for row in rows}:
        axis.text(positions[dataset], 0.4, "n/m", ha="center", va="bottom", fontsize=5.5)
    axis.set_xticks(range(len(datasets)), datasets)
    axis.set_xlim(-0.6, len(datasets) - 0.4)
    axis.set_ylim(0, max(1.2, max(values) * 1.15))
    axis.set_title("(a) Datasets", pad=7)
    axis.set_ylabel("Throughput speedup")
    axis.yaxis.set_major_locator(MaxNLocator(nbins=4))
    style_axis(axis, parity=True)
    legend(axis, [handle], height=1.18)
    sweep_path = data / "fig8_batch_sensitivity.csv"
    if sweep_path.is_file():
        sweep = read_csv(sweep_path)
        if tuple(int(row["batches"]) for row in sweep) != (10, 100, 1000) or any(
            row["status"] != "PERSISTENT_PAIRED_SETUP_PREDICTION"
            or row["baseline_admitted"] != "False" or int(row["updates"]) != 131072 for row in sweep
        ):
            raise ValueError("expected fixed-total AU sensitivity predictions")
        values = numbers(sweep, "speedup_gr_over_spine")
        right.plot(range(3), values, "-s", color=ORANGE, linewidth=0.8, markersize=2.9,
                   label="AU, 131K total", zorder=6)
        right.set_xticks(range(3), ("13.1K", "1.31K", "131"))
        right.set_ylim(0, max(values) * 1.18)
        right.yaxis.set_major_locator(MaxNLocator(nbins=4))
        legend(right, height=1.18)
    else:
        right.text(0.5, 0.5, "Not measured", transform=right.transAxes, ha="center")
    right.set_title("(b) Batch size", pad=7)
    right.set_xlabel("Updates/batch")
    style_axis(right, parity=True)
    save(figure, output, stem)


def fig8_portable(output):
    rows = read_csv(ROOT / "fresh_simulator/portable_fig8/fig8_ten_batch.csv")
    datasets = ("AU", "SU", "WK", "SO", "PK")
    if tuple(row["dataset"] for row in rows) != datasets or any(
        row["baseline_admitted"] != "False" or (int(row["updates"]), int(row["batches"])) != (4096, 10)
        for row in rows
    ):
        raise ValueError("expected the complete portable five-case status table")
    figure, axis = plt.subplots(figsize=(3.55, 1.70), layout="constrained")
    measured = []
    for i, row in enumerate(rows):
        if row["status"] == "PERSISTENT_PAIRED_SETUP_PREDICTION":
            value = float(row["speedup_gr_over_spine"])
            if value <= 0 or not isclose(value, float(row["gr_setup_inclusive_seconds"]) /
                                         float(row["spine_setup_inclusive_seconds"])):
                raise ValueError("portable comparison differs from elapsed-time ratio")
            measured.append(value)
            bars(axis, [i], [value], SERIES[0])
        elif row["status"] == "FAILED_RETAINED" and not row["speedup_gr_over_spine"] and row["error"]:
            axis.text(i, 0.3, "Failed", ha="center", va="bottom", fontsize=5.5)
        else:
            raise ValueError("unrecognized portable outcome")
    if not measured:
        raise ValueError("portable preview has no completed pairs")
    axis.set_xticks(range(len(datasets)), datasets)
    axis.set_ylim(0, max(measured) * 1.15)
    axis.set_xlim(-0.6, len(datasets) - 0.4)
    axis.set_ylabel("Throughput speedup")
    axis.set_title("Ten batches, 4,096 updates; CPU + simulator", pad=7, fontsize=6)
    axis.yaxis.set_major_locator(MaxNLocator(nbins=4))
    style_axis(axis, parity=True)
    save(figure, output, "fig8_ten_batch_portable")


def fig8(output):
    cross = read_csv(HANDOFF / "fig8_update_cross_dataset.csv")
    sweep = read_csv(HANDOFF / "fig8_update_batch_sensitivity.csv")
    assert all(row["batch_count"] == "1" for row in cross + sweep)
    figure, (left, right) = plt.subplots(1, 2, figsize=(3.55, 1.75), layout="constrained")
    positions = range(len(cross))
    handle = bars(left, positions, numbers(cross, "spine_speedup"), SERIES[1], label="512 updates")
    left.set_xticks(positions, [row["dataset"] for row in cross])
    left.set_ylabel("Throughput speedup")
    left.set_title("(a) Datasets")
    legend(left, [handle], height=1.17)
    right.plot(range(len(sweep)), numbers(sweep, "spine_speedup"), "-s", color="#c45d00",
               linewidth=0.8, markersize=2.9, label="AU", zorder=6)
    right.set_xticks(range(len(sweep)), [row["updates_per_batch"] for row in sweep])
    right.set_xlabel("Updates per batch")
    right.set_title("(b) Batch size")
    legend(right, height=1.17)
    for axis, rows in ((left, cross), (right, sweep)):
        axis.set_ylim(0, max(numbers(rows, "spine_speedup")) * 1.18)
        axis.yaxis.set_major_locator(MaxNLocator(4, integer=True))
        style_axis(axis, parity=True)
    save(figure, output, "fig8_one_batch_model")

    checkpoint = read_csv(REPAIR / "paired-board-checkpoint" / "figure8.csv")
    latest = {(row["dataset"], row["updates"]): float(row["g_ms"]) / float(row["spine_ms"])
              for row in read_csv(ROOT / "fig8_direct_metadata.csv")}
    figure, (left, right) = plt.subplots(1, 2, figsize=(3.55, 1.75), layout="constrained")
    for axis, rows, labels, title in (
        (left, [row for row in checkpoint if row["updates"] == "512"], "dataset", "(a) 512 updates"),
        (right, [row for row in checkpoint if row["dataset"] == "AU"], "updates", "(b) AU batch size"),
    ):
        for i, row in enumerate(rows):
            if row["status"] == "FAILED_RETAINED":
                axis.text(i, 0.04, "Cap.", ha="center", va="bottom", fontsize=5.5)
                continue
            ratio = float(row["g_over_spine"])
            bars(axis, [i], [ratio], SERIES[1 if ratio >= 1 else 2])
            axis.scatter(i, latest[row["dataset"], row["updates"]], s=12, facecolor=INK,
                         edgecolor="white", linewidth=0.35, zorder=7)
        axis.set_xticks(range(len(rows)), [row[labels] for row in rows])
        axis.set_title(title, pad=7)
        axis.set_ylim(0, 2.6)
        axis.set_yticks((0, 1, 2))
        style_axis(axis, parity=True)
    left.set_ylabel("Throughput speedup")
    figure.suptitle("FPGA, one batch: initial host (bars), revised host (dots)", fontsize=5.8)
    save(figure, output, "fig8_one_batch_fpga_diagnostic")


def fig9(output, data=HANDOFF, stem="fig9_memory_hbm_model", fresh=False):
    rows = read_csv(data / "fig9_memory_energy_rows.csv")
    figure, axes = plt.subplots(1, 2, figsize=(3.55, 1.75), layout="constrained")
    for axis, (field, title) in zip(axes, (
        ("accepted_bytes_ratio" if fresh else "memory_ratio_gr_over_spine", "(a) Accepted bytes"),
        ("hbm_energy_ratio" if fresh else "hbm_energy_ratio_gr_over_spine", "(b) HBM energy"),
    ), strict=True):
        values = {(row["algorithm"], row["dataset"]): float(row[field]) for row in rows}
        lower = 10 ** int(log10(min(values.values()) * 0.8)) if fresh else 1
        upper = max(values.values()) * 1.35
        handles = grouped(axis, tuple(ALGORITHMS.values()), ("AU", "SU", "WK"), values, bottom=lower)
        log_axis(axis, lower, upper, tuple(t for t in (1, 10, 100, 1000, 10000) if lower <= t < upper))
        axis.set_title(title, pad=7)
        style_axis(axis)
    axes[0].set_ylabel("Ratio (G+R / Spine)")
    figure.legend(handles=handles, ncol=3, loc="lower center", bbox_to_anchor=(0.54, 1.13),
                  frameon=False, handlelength=1.3, columnspacing=0.9)
    save(figure, output, stem)


def fig10(output, reference, data=HANDOFF):
    rows = read_csv(data / "fig10_normalized_breakdown_rows.csv")
    assert len(rows) == 11 and all(isclose(
        sum(float(row[key]) for key, *_ in reference.FIG10_STAGES), 100, abs_tol=1e-6
    ) for row in rows)
    def save_breakdown(figure, path):
        figure.axes[0].yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        save(figure, output, path.name)

    reference.save_figure = save_breakdown
    reference.render_fig10(plt, rows)


def fig11(output, data=HANDOFF):
    rows = read_csv(data / "fig11_e2e_prediction_rows.csv")
    metrics = {row["role"]: row for row in read_csv(data / "fig11_e2e_metric_rows.csv")}
    figure, axis = plt.subplots(figsize=(3.55, 2.14), layout="constrained")
    for label, expected, color, marker, selected in (
        ("Fit", 24, BLUE, "s", [row for row in rows if row["model_role"] == "calibration"]),
        ("Carry holdout", 10, GREEN, "^", [row for row in rows if row["model_role"] == "trace_holdout"
                                           and row["dataset_kind"] == "trace_holdout"]),
        ("Real holdout", 7, ORANGE, "o", [row for row in rows if row["model_role"] == "trace_holdout"
                                          and row["dataset_kind"] == "real"]),
    ):
        assert len(selected) == expected
        axis.scatter(numbers(selected, "observed_cycles"), numbers(selected, "predicted_cycles"),
                     s=14, marker=marker, facecolors="white", edgecolors=color,
                     linewidths=0.75, label=f"{label} ({expected})", zorder=4)
    extent = numbers(rows, "observed_cycles") + numbers(rows, "predicted_cycles")
    bounds = min(extent) / 1.4, max(extent) * 1.4
    axis.plot(bounds, bounds, color=INK, linewidth=0.55)
    axis.set(xscale="log", yscale="log", xlim=bounds, ylim=bounds,
             xlabel="Simulated cycles", ylabel="Predicted cycles")
    holdout, real = (float(metrics[key]["median_ape_percent"])
                     for key in ("trace_holdout", "real_trace_holdout"))
    axis.text(0.035, 0.965, f"Median APE: all {holdout:.1f}\\%\nReal only: {real:.1f}\\%",
              transform=axis.transAxes, va="top", fontsize=5.8)
    axis.legend(loc="lower right", frameon=False, fontsize=5.4, handletextpad=0.3)
    style_axis(axis, categorical=False)
    for coordinate in (axis.xaxis, axis.yaxis):
        coordinate.set_major_formatter(FuncFormatter(lambda value, _: f"1e{round(log10(value))}"))
        coordinate.set_minor_locator(NullLocator())
    save(figure, output, "fig11_realized_work_model")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fresh", action="store_true", help="use the independently replayed Nov. 5 simulator experiments")
    mode.add_argument("--portable-fig8", action="store_true", help="draw the separate same-host remote Fig. 8 cohort")
    args = parser.parse_args()
    default = ("fresh_simulator/portable_fig8/figures" if args.portable_fig8 else
               "fresh_simulator/figures" if args.fresh else "figures")
    output = args.output or ROOT / default
    output.mkdir(parents=True, exist_ok=True)
    reference = prior_renderer()
    reference.configure_matplotlib()
    if args.portable_fig8:
        fig8_portable(output)
        return
    if args.fresh:
        data = ROOT / "fresh_simulator"
        fig8_persistent(output, data, "fig8_update_prediction")
        fig9(output, data, "fig9_memory_hbm_prediction", fresh=True)
        fig10(output, reference, data)
        fig11(output, data)
        return
    for draw in (source_comparison, fig7, fig7_nov05, fig7_banked_sssp, fig8, fig8_persistent, fig9, fig11):
        draw(output)
    fig10(output, reference)


if __name__ == "__main__":
    main()
