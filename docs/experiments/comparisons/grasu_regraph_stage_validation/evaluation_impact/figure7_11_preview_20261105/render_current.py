"""Render only the separately replayed current FPGA stage controls."""

import argparse
import math
from pathlib import Path

import render as style
from matplotlib import pyplot as plt
from matplotlib.ticker import FixedLocator, FormatStrFormatter


LABELS = {"weighted_sssp": "SSSP", "cc": "CC", "residual_pagerank": "ResPR"}
EXPECTED = [(algorithm, stage, workload)
            for algorithm in LABELS
            for stage, workload in [("G", "AU-131K"), *[("R", case) for case in (
                ("skewed_sources", "amazon") if algorithm == "residual_pagerank" else ("AM", "AM+", "AU"))]]]


def checked_rows(path):
    rows = style.read_csv(path)
    keys = [(row["algorithm"], row["stage"], row["workload"]) for row in rows]
    if keys != EXPECTED:
        raise ValueError("need all eleven current stage controls in replayed order")
    for row in rows:
        ratio = float(row["current_over_public"])
        times = [float(row[key]) for key in ("public_ms", "current_ms")]
        if (not all(math.isfinite(value) and value > 0 for value in (*times, ratio))
                or not math.isclose(times[1] / times[0], ratio)
                or ratio > 1.15 or row["at_most_15_percent_slower"] != "True"
                or row["repetitions_per_arm"] != "1"
                or row["publication_throughput_reproduced"] != "False"):
            raise ValueError("invalid measured stage control")
        expected = (140, 500, 430) if row["algorithm"] == "residual_pagerank" else (150, 500, 450)
        if tuple(int(row[key]) for key in ("data_mhz", "kernel_mhz", "hbm_mhz")) != expected:
            raise ValueError("unexpected control clocks")
    return rows


def draw(rows, output):
    figure, axes = plt.subplots(1, 2, figsize=(5.3, 1.9),
                                width_ratios=(1, 2.35), layout="constrained")
    for axis, stage in zip(axes, ("G", "R"), strict=True):
        selected = [row for row in rows if row["stage"] == stage]
        for i, row in enumerate(selected):
            series = style.SERIES[tuple(LABELS).index(row["algorithm"])]
            ratio = float(row["current_over_public"])
            style.bars(axis, [i], [ratio], series, width=0.62)
            if stage == "G":
                axis.annotate(f"{ratio:.2f}x", (i, ratio), (0, 4),
                              textcoords="offset points", ha="center", fontsize=5.5)
        axis.set_xticks(range(len(selected)), [
            LABELS[row["algorithm"]] if stage == "G" else
            {"amazon": "AM", "skewed_sources": "Skew"}.get(row["workload"], row["workload"])
            for row in selected])
        axis.set_xlim(-0.55, len(selected) - 0.45)
        axis.set_ylim(0 if stage == "G" else 0.85, 1.22)
        axis.yaxis.set_major_locator(FixedLocator((0, 0.5, 1) if stage == "G" else (0.9, 1, 1.1, 1.2)))
        style.style_axis(axis, parity=True)
        axis.yaxis.set_major_formatter(FormatStrFormatter("%g"))
        axis.axhline(1.15, color="#70777b", linestyle=":", linewidth=0.55, zorder=5)
        axis.set_title("(a) G: AU 131K updates" if stage == "G" else "(b) Adapter + R", pad=7)
        if stage == "R":
            for center, name in ((1, "SSSP"), (4, "CC"), (6.5, "ResPR")):
                axis.text(center, -0.16, name, ha="center", va="top",
                          transform=axis.get_xaxis_transform())
    axes[0].set_ylabel("Elapsed / public source")
    style.save(figure, output, "gr_current_source_controls")


def draw_resident(path, output):
    datasets = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
    rows = style.read_csv(path)
    lookup = {(row["algorithm"], row["dataset"]): row for row in rows}
    if len(lookup) != 24 or set(lookup) != {(algorithm, ds) for algorithm in LABELS for ds in datasets}:
        raise ValueError("all twenty-four measured or pending slots required")
    figure, axis = plt.subplots(figsize=(5.3, 2.0), layout="constrained")
    handles = []
    for index, (algorithm, label) in enumerate(LABELS.items()):
        positions, ratios, pending = [], [], []
        for i, dataset in enumerate(datasets):
            row = lookup[(algorithm, dataset)]
            position = i + (index - 1) * 0.24
            if row["status"] != "MEASURED":
                if any(row.get(field) for field in ("spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine")):
                    raise ValueError("unmeasured slot contains a fabricated timing")
                pending.append(position)
                continue
            ratio = float(row["speedup_gr_over_spine"])
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError("invalid resident speedup")
            positions.append(position)
            ratios.append(ratio)
        handles.append(style.bars(axis, positions, ratios, style.SERIES[index], width=0.24, label=label))
        for position in pending:
            axis.text(position, 0.56, "-", ha="center", va="center", fontsize=6)
    axis.set_yscale("log")
    measured = [float(row["speedup_gr_over_spine"]) for row in rows if row["status"] == "MEASURED"]
    axis.set_ylim(min(0.5, min(measured) * 0.8), max(40, max(measured) * 1.3))
    axis.set_xlim(-0.6, 7.6)
    axis.set_xticks(range(8), datasets)
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.yaxis.set_major_locator(FixedLocator((1, 2, 5, 10, 20)))
    style.style_axis(axis, parity=True)
    axis.yaxis.set_major_formatter(FormatStrFormatter("%g"))
    style.legend(axis, handles, ncol=3, height=1.06)
    style.save(figure, output, "fig7_resident_checkpoint")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "current_fpga/gr_controls.csv")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "current_fpga/figures")
    parser.add_argument("--resident-checkpoint", type=Path)
    args = parser.parse_args()
    rows = checked_rows(args.data)
    style.prior_renderer().configure_matplotlib()
    args.output.mkdir(parents=True, exist_ok=True)
    draw(rows, args.output)
    if args.resident_checkpoint:
        draw_resident(args.resident_checkpoint, args.output)


if __name__ == "__main__":
    main()
