"""Render the measured source-port retention comparison in the handoff style."""

import argparse
import json
import math
from pathlib import Path


def render(summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams.update({
        "text.usetex": True,
        "text.latex.preamble": (r"\usepackage{txfonts}\renewcommand{\rmdefault}{txtt}"
                                r"\renewcommand{\sfdefault}{txtt}\renewcommand{\ttdefault}{txtt}"),
        "font.family": "monospace", "font.size": 7, "axes.titlesize": 7.4,
        "axes.labelsize": 7, "xtick.labelsize": 6.2, "ytick.labelsize": 6.5,
        "legend.fontsize": 6.8, "axes.linewidth": 0.7, "hatch.linewidth": 0.38,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    report = json.loads(summary.read_text())
    figure, axes = plt.subplots(1, 2, figsize=(6.9, 2.35), gridspec_kw={"width_ratios": [1.55, 1]})
    color, hatch = "#428a98", "////"
    for axis, stage, title in zip(axes, ("G", "R"), ("(a) GraSU update", "(b) Adapter + ReGraph")):
        rows = [r for r in report["pairs"] if r["stage"] == stage]
        if not rows:
            raise ValueError(f"no admitted timing rows for {stage}")
        values = [r["current_over_reference"] for r in rows]
        # Whiskers show independently observed extrema, not confidence intervals.
        low = [v - r["current_min_ms"] / r["reference_max_ms"] for v, r in zip(values, rows)]
        high = [r["current_max_ms"] / r["reference_min_ms"] - v for v, r in zip(values, rows)]
        axis.bar(range(len(rows)), values, width=0.57, facecolor="white", edgecolor=color,
                 hatch=hatch, linewidth=0.5, yerr=[low, high], capsize=2,
                 error_kw={"elinewidth": 0.55, "capthick": 0.55, "ecolor": "black"}, zorder=3)
        axis.bar(range(len(rows)), values, width=0.57, fill=False, edgecolor="black", linewidth=0.55, zorder=4)
        axis.axhline(1, color="black", linestyle="--", linewidth=0.65, zorder=2)
        maximum = max(v + h for v, h in zip(values, high))
        axis.set_ylim(0, max(1.4, math.ceil(maximum * 1.2 * 2) / 2))
        axis.set_ylabel("Time / public-code port")
        labels = ([f"1K / {p}\nAU" if "-1024-" in r["case"] else f"131K / {p}\nAU"
                   for r in rows for p in ["1P" if r["case"].endswith("-524288") else "8P"]]
                  if stage == "G" else ["Skewed" if r["case"] == "skewed_sources" else "Amazon" for r in rows])
        axis.set_xticks(range(len(rows)), labels)
        axis.set_title(title, pad=10)
        axis.set_axisbelow(True)
        axis.grid(axis="y", linestyle="--", color="#d1d1d1", linewidth=0.5)
        axis.tick_params(axis="x", which="both", length=0, pad=5)
        axis.tick_params(axis="y", direction="in", width=0.65, length=3)
        for spine in axis.spines.values():
            spine.set_zorder(10)
        for x, value in enumerate(values):
            axis.annotate(f"{value:.2f}", (x, value + high[x]), xytext=(0, 4),
                          textcoords="offset points", ha="center", fontsize=6.5)
    figure.legend(handles=[Patch(facecolor="white", edgecolor=color, hatch=hatch, label="Current / source port"),
                           plt.Line2D([], [], color="black", linestyle="--", linewidth=0.65, label="Source port = 1")],
                  loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.01))
    figure.subplots_adjust(left=0.08, right=0.99, bottom=0.24, top=0.74, wspace=0.4)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.04,
                   metadata={"Creator": __name__, "CreationDate": None, "ModDate": None})
    figure.savefig(output.with_suffix(".png"), dpi=240, bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.summary, args.output)
