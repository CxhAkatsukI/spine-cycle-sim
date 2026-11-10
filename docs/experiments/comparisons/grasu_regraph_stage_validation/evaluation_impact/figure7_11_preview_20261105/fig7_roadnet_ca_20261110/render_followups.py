"""Render RN supplements without altering the frozen handoff figures."""

import argparse
import importlib.util
import json
import math
import subprocess
from pathlib import Path

from matplotlib.ticker import FixedLocator, FormatStrFormatter, FuncFormatter, LogLocator, NullLocator


HERE = Path(__file__).resolve().parent
DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19", "RN")
ALGORITHMS = ("weighted_sssp", "connected_components", "residual_pagerank")
LABELS = ("SSSP", "CC", "ResPR")
MEASURED = ("MEASURED", "MEASURED_WITHOUT_RAW_SKEW_REPORT")


def handoff_style():
    spec = importlib.util.spec_from_file_location("handoff_render", HERE.parent / "render.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(plt, figure, output):
    # Rasterize the same PDF so the preview needs no separate dvipng install.
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=.04,
                   metadata={"CreationDate": None, "ModDate": None})
    plt.close(figure)
    subprocess.run(["pdftoppm", "-png", "-r", "300", "-singlefile",
                    str(output.with_suffix(".pdf")), str(output)], check=True)


def headline(plt, style, directory):
    rows = style.read_csv(directory / "fig7_nine_datasets.csv")
    pairs = {(row["dataset"], row["algorithm"]): row for row in rows}
    expected = {(dataset, algorithm) for dataset in DATASETS for algorithm in ALGORITHMS}
    if len(rows) != len(expected) or pairs.keys() != expected:
        raise ValueError("expected exactly one row per dataset and algorithm")

    figure, axis = plt.subplots(figsize=(5.3, 2.15), layout="constrained")
    handles = []
    for index, (algorithm, label) in enumerate(zip(ALGORITHMS, LABELS, strict=True)):
        ratios = []
        for dataset in DATASETS:
            row = pairs[dataset, algorithm]
            spine, gr, ratio = (float(row[key]) for key in
                                ("spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine"))
            if (row["status"] not in MEASURED
                    or not all(math.isfinite(x) and x > 0 for x in (spine, gr, ratio))
                    or not math.isclose(gr / spine, ratio)):
                raise ValueError(f"invalid measured pair: {dataset} {algorithm}")
            ratios.append(ratio)
        offset = (index - 1) * .23
        handles.append(style.bars(axis, [i + offset for i in range(len(DATASETS))],
                                  ratios, style.SERIES[index], width=.23, bottom=1, label=label))
    axis.set_xticks(range(len(DATASETS)), DATASETS)
    axis.set_xlim(-.55, len(DATASETS) - .45)
    values = [float(row["speedup_gr_over_spine"]) for row in rows]
    style.log_axis(axis, min(values) * .7, max(values) * 1.45,
                   [x for x in (.03, .1, .3, 1, 3, 10, 30, 100)
                    if min(values) * .7 < x < max(values) * 1.45])
    style.style_axis(axis, parity=True)
    axis.set_ylabel("Speedup (G+R / Delta.hls)")
    style.legend(axis, handles, ncol=3, height=1.02)
    save(plt, figure, directory / "fig7_nine_datasets")


def impact(plt, style, directory):
    data = json.loads((directory / "rn_impact_summary.json").read_text())
    rows = [row for row in data["points"] if row["status"] == "MEASURED"
            and row["changed_fraction"] > 0]
    if not any(row["kind"] != "ordinary" for row in rows):
        return
    figure, axis = plt.subplots(figsize=(3.55, 2.48), layout="constrained")
    for algorithm, label, (color, _), marker in zip(
            ALGORITHMS, LABELS, style.SERIES, ("o", "s", "D"), strict=True):
        cases = sorted((row for row in rows if row["algorithm"] == algorithm),
                       key=lambda row: row["changed_fraction"])
        controlled = [row for row in cases if row["kind"] != "ordinary"]
        ordinary = [row for row in cases if row["kind"] == "ordinary"]
        if controlled:
            axis.plot([100 * row["changed_fraction"] for row in controlled],
                      [row["speedup"] for row in controlled], marker=marker, markersize=3.3,
                      color=color, linewidth=.8, label=f"{label}: controlled", zorder=3)
        if ordinary:
            axis.scatter([100 * row["changed_fraction"] for row in ordinary],
                         [row["speedup"] for row in ordinary], marker=marker, s=15,
                         facecolors="white", edgecolors=color, linewidths=.8,
                         label=f"{label}: ordinary", zorder=4)
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.xaxis.set_minor_locator(NullLocator())
    axis.yaxis.set_minor_locator(NullLocator())
    axis.yaxis.set_major_locator(FixedLocator((.01, .03, .1, .3, 1, 3, 10, 30, 100)))
    style.style_axis(axis, parity=True, categorical=False)
    axis.xaxis.set_major_formatter(FormatStrFormatter("%g"))
    axis.set_xlabel(r"Changed vertices (\%)")
    axis.set_ylabel("Speedup (G+R / Delta.hls)")
    style.legend(axis, ncol=2, height=1.02)
    save(plt, figure, directory / "rn_affected_fraction")


def batch_size(plt, style, directory):
    sizes = (8, 64, 512, 4096)
    rows = {(row["algorithm"], int(row["logical_insertions"])): row
            for row in style.read_csv(directory / "rn_fpga_sweep.csv")
            if row["kind"] == "ordinary" and row["status"] == "MEASURED"}
    if not any((algorithm, size) in rows for algorithm in ALGORITHMS for size in sizes[1:]):
        return
    figure, axes = plt.subplots(1, 3, figsize=(5.3, 1.87), layout="constrained")
    for axis, algorithm, label in zip(axes, ALGORITHMS, LABELS, strict=True):
        measured = []
        for field, system, marker, color in (
            ("spine_ms", "Delta.hls", "o", style.BLUE),
            ("gr_ms", "G+R", "s", style.ORANGE),
        ):
            values = [float(rows[algorithm, size][field]) if (algorithm, size) in rows
                      else math.nan for size in sizes]
            measured.extend(value for value in values if math.isfinite(value))
            axis.plot(range(len(sizes)), values, label=system, marker=marker,
                      color=color, linewidth=.85, markersize=3.3, zorder=3)
        axis.set_yscale("log")
        if measured:
            subs = (1,) if max(measured) / min(measured) >= 40 else (1, 2, 5)
            axis.yaxis.set_major_locator(LogLocator(base=10, subs=subs))
        axis.yaxis.set_minor_locator(NullLocator())
        axis.set_xlim(-.24, len(sizes) - .76)
        axis.set_xticks(range(len(sizes)), [str(size) for size in sizes])
        axis.set_title(label, pad=5)
        style.style_axis(axis)
        axis.yaxis.set_major_formatter(FuncFormatter(latency_tick))
    axes[0].set_ylabel("Wall time (ms)")
    figure.supxlabel("Logical insertions per batch", fontsize=6.6)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside upper center", ncol=2, frameon=False)
    save(plt, figure, directory / "rn_batch_size")


def latency_tick(value, _):
    if value < 1000:
        return f"{value:g}"
    mantissa, exponent = f"{value:.2e}".split("e")
    return f"{float(mantissa):g}e{int(exponent)}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=HERE / "followup")
    args = parser.parse_args()
    style = handoff_style()
    plt = style.prior_renderer().configure_matplotlib()
    headline(plt, style, args.directory)
    impact(plt, style, args.directory)
    batch_size(plt, style, args.directory)
