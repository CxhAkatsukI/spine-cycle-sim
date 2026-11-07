"""Render measured FPGA cycles versus SST cycles without changing any row."""

import argparse
import csv
from pathlib import Path


def render(data, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import LogLocator, NullLocator

    plt.rcParams.update({
        "text.usetex": True,
        "text.latex.preamble": (r"\usepackage{txfonts}"
                                r"\renewcommand{\rmdefault}{txtt}"
                                r"\renewcommand{\sfdefault}{txtt}"
                                r"\renewcommand{\ttdefault}{txtt}"
                                r"\renewcommand{\familydefault}{\ttdefault}"),
        "font.family": "monospace", "font.size": 7,
        "axes.linewidth": .7, "xtick.major.width": .65,
        "ytick.major.width": .65, "pdf.fonttype": 42,
    })
    with data.open() as stream:
        rows = list(csv.DictReader(stream))
    values = [float(row[key]) for row in rows for key in ("fpga_cycles", "simulator_cycles")]
    lo, hi = min(values) * .75, max(values) * 1.3
    fig, ax = plt.subplots(figsize=(3.45, 2.65))
    ax.fill_between([lo, hi], [.8 * lo, .8 * hi], [1.2 * lo, 1.2 * hi],
                    color=".88", label=r"$\pm20\%$", zorder=0)
    ax.plot([lo, hi], [lo, hi], color=".25", lw=.8, zorder=1)
    for role, label, marker, color in (("development", "Development", "s", "#2D88A2"),
                                       ("holdout", "Holdout", "o", "#C66A24")):
        subset = [row for row in rows if row["split"] == role]
        ax.scatter([float(row["fpga_cycles"]) for row in subset],
                   [float(row["simulator_cycles"]) for row in subset],
                   s=26, marker=marker, facecolors="white", edgecolors=color,
                   linewidths=.9, label=label, zorder=3)
    held = [float(row["abs_error_percent"]) for row in rows if row["split"] == "holdout"]
    ax.text(.035, .96, f"Holdout max error: {max(held):.1f}\\%\n"
            f"{len(held)} holdout cases", transform=ax.transAxes, va="top", fontsize=6.5)
    ax.set(xscale="log", yscale="log", xlim=(lo, hi), ylim=(lo, hi),
           xlabel="Measured FPGA cycles", ylabel="Simulated device cycles")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        axis.set_minor_locator(NullLocator())
    ax.grid(axis="y", color=".82", ls="--", lw=.45)
    ax.tick_params(direction="in", top=True, right=True)
    ax.legend(loc="lower right", frameon=False, fontsize=6)
    fig.tight_layout(pad=.7)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output.with_suffix(".pdf"), metadata={"CreationDate": None, "ModDate": None})
    fig.savefig(output.with_suffix(".png"), dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.data, args.output)
