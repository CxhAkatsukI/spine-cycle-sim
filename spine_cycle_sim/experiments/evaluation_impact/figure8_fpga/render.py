"""Render only the one-pass FPGA Fig. 8 table, using the existing handoff style."""

import argparse
import csv
import importlib.util
from pathlib import Path


HANDOFF = (Path(__file__).resolve().parents[4] / "docs/experiments/comparisons/"
           "grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105")


def render(table, output):
    spec = importlib.util.spec_from_file_location("fig8_handoff_style", HANDOFF / "render.py")
    style = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(style)
    plt = style.prior_renderer().configure_matplotlib()
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator

    with Path(table).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 8 or any(row["samples_per_arm"] != "1" for row in rows):
        raise ValueError("the complete eight-point one-pass table is required")
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.0))
    series = (style.BLUE, "/" * 8)
    for panel, axis in zip(("a", "b"), axes):
        selected = [row for row in rows if row["panel"] == panel]
        valid = [(index, float(row["speedup_gr_over_spine"]))
                 for index, row in enumerate(selected) if row["status"] == "MEASURED"]
        x, y = zip(*valid) if valid else ((), ())
        if panel == "a":
            handle = style.bars(axis, x, y, series, label="10-batch FPGA")
            labels = [row["dataset"] for row in selected]
            title = "(a) Dataset"
        else:
            axis.plot(x, y, color=style.ORANGE, marker="s", markersize=3, linewidth=0.8)
            handle = Line2D([], [], color=style.ORANGE, marker="s", markersize=3,
                            linewidth=0.8, label="FPGA batch sweep")
            labels = [f'{int(row["updates"]) / int(row["batches"]) / 1000:.2f}k'
                      for row in selected]
            axis.set_xlabel("updates/batch (mean)")
            title = "(b) Batch size"
        axis.set_xticks(range(len(selected)), labels)
        axis.set_xlim(-0.6, len(selected) - 0.4)
        axis.set_ylim(0, max((value for _, value in valid), default=1) * 1.22 + 0.2)
        axis.set_title(title, pad=9)
        axis.yaxis.set_major_locator(MaxNLocator(nbins=4))
        style.style_axis(axis, parity=True)
        style.legend(axis, [handle], height=1.23)
        for index, row in enumerate(selected):
            if row["status"] != "MEASURED":
                axis.text(index, 0.05, "FAIL", rotation=90, va="bottom", ha="center",
                          transform=axis.get_xaxis_transform(), color=style.ORANGE)
    axes[0].set_ylabel("Throughput speedup (G+R / Spine)")
    figure.subplots_adjust(wspace=0.34, bottom=0.25, top=0.72)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    style.save(figure, output, "fig8_fpga_update_throughput")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.data, args.output)
