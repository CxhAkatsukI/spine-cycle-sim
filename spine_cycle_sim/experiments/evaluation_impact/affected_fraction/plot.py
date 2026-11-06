"""Plot achieved affected fractions, preserving ordinary and targeted batches."""

import argparse
import json
from pathlib import Path


def render(summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, NullLocator

    plt.rcParams.update({
        "text.usetex": True,
        "text.latex.preamble": (r"\usepackage{txfonts}\renewcommand{\rmdefault}{txtt}"
                                r"\renewcommand{\sfdefault}{txtt}\renewcommand{\ttdefault}{txtt}"),
        "font.family": "monospace", "font.size": 7, "axes.labelsize": 7,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.2,
        "axes.linewidth": .7, "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    data = json.loads(summary.read_text())
    points = [row for row in data["points"] if row["status"] == "MEASURED" and row["changed_fraction"] > 0]
    groups = sorted({(row["dataset"], row["algorithm"]) for row in points})
    names = {"weighted_sssp": "SSSP", "connected_components": "CC", "residual_pagerank": "ResPR"}
    colors = {"weighted_sssp": "#428a98", "connected_components": "#bc742e", "residual_pagerank": "#52864b"}
    figure, axis = plt.subplots(figsize=(3.5, 2.65))
    markers = dict(zip(sorted({dataset for dataset, _ in groups}), ("o", "s", "D", "v")))
    for index, (dataset, algorithm) in enumerate(groups):
        rows = [row for row in points if (row["dataset"], row["algorithm"]) == (dataset, algorithm)]
        targeted = sorted((row for row in rows if row["kind"] != "ordinary"), key=lambda row: row["changed_fraction"])
        ordinary = [row for row in rows if row["kind"] == "ordinary"]
        color = colors[algorithm]
        axis.plot([row["changed_fraction"] * 100 for row in targeted], [row["speedup"] for row in targeted],
                  marker=markers[dataset], markersize=3.5, linewidth=.8, color=color,
                  linestyle="-" if index < 3 else "--", label=dataset + " " + names[algorithm], zorder=3)
        axis.scatter([row["changed_fraction"] * 100 for row in ordinary], [row["speedup"] for row in ordinary],
                     marker=markers[dataset], s=18, facecolors="white", edgecolors=color, linewidths=.65, zorder=4)
    axis.axhline(1, color="black", linewidth=.7, linestyle="--", zorder=2)
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    axis.xaxis.set_minor_locator(NullLocator())
    axis.yaxis.set_minor_locator(NullLocator())
    axis.set_xlabel(r"Changed vertices (\%)")
    axis.set_ylabel(r"Speedup (G+R / Delta.hls)")
    axis.set_axisbelow(True)
    axis.grid(axis="y", color="#d1d1d1", linestyle="--", linewidth=.45)
    axis.tick_params(direction="in", width=.65, length=3)
    for spine in axis.spines.values():
        spine.set_zorder(10)
    handles, labels = axis.get_legend_handles_labels()
    handles.append(plt.Line2D([], [], color="#555555", marker="o", markerfacecolor="white", linestyle="None", markersize=4))
    labels.append("Open: ordinary")
    axis.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.02), frameon=False,
                ncol=2, borderaxespad=0, columnspacing=1)
    figure.subplots_adjust(left=.18, right=.98, bottom=.2, top=.76)
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".pdf", ".png"):
        figure.savefig(output.with_suffix(suffix), dpi=240, bbox_inches="tight", pad_inches=.04)
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.summary, args.output)
