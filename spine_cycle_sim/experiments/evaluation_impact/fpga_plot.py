"""Render a terminal bounded-cache FPGA delivery without changing the paper."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
STYLES = (
    ("respr", "ResPR", "#F2C49B", "/" * 8),
    ("cc", "CC", "#B9D5E6", "\\" * 8),
    ("sssp", "SSSP", "#BCDDAE", "|" * 8),
)
TERMINAL = {
    "RESIDENT_PAIR_PASS", "FAILED_RETAINED", "BLOCKED_BY_INVALID_ARTIFACT",
    "BLOCKED_BY_FAILED_BUILD", "BLOCKED_BY_FAILED_AU_GATE", "TIMED_OUT_WAITING_FOR_BUILD",
}
BOUNDARY = "resident_update_to_final_readback_wall_including_host_relaunch"
PREAMBLE = (
    r"\usepackage{txfonts}\renewcommand{\rmdefault}{txtt}"
    r"\renewcommand{\sfdefault}{txtt}\renewcommand{\ttdefault}{txtt}"
    r"\renewcommand{\familydefault}{\ttdefault}"
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_delivery(directory: Path) -> list[dict]:
    """Reject pending evidence or a CSV that differs from the admitted matrix."""
    matrix = json.loads((directory / "matrix.json").read_text())
    plan = json.loads((directory / "plan.json").read_text())
    index = json.loads((directory / "files.json").read_text())
    if matrix["status"] not in {"FPGA_MATRIX_PASS", "FPGA_MATRIX_INCOMPLETE_RETAINED"}:
        raise ValueError("terminal FPGA delivery required")
    if plan["boundary"] != BOUNDARY or plan["repeats"] != {
        "warmup_pairs": 1, "measured_pairs": 3,
    }:
        raise ValueError("unexpected resident measurement contract")
    indexed = set()
    for item in index:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or relative in indexed:
            raise ValueError("invalid or duplicate delivery index path")
        indexed.add(relative)
        if digest(directory / relative) != item["sha256"]:
            raise ValueError("changed delivery file: " + str(relative))
    if not {Path("matrix.json"), Path("plan.json")} <= indexed:
        raise ValueError("unindexed matrix or plan")
    with (directory / "summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {(algorithm, dataset) for algorithm, *_ in STYLES for dataset in DATASETS}
    keys = [(row["algorithm"], row["dataset"]) for row in rows]
    cases = matrix["cases"]
    case_keys = [(row["algorithm"], row["dataset"]) for row in cases]
    if len(keys) != 24 or set(keys) != expected or len(case_keys) != 24 or set(case_keys) != expected:
        raise ValueError("exactly 24 unique declared cases required")
    by_key = dict(zip(case_keys, cases, strict=True))
    passed = 0
    for row in rows:
        case = by_key[row["algorithm"], row["dataset"]]
        if row["status"] not in TERMINAL or row["status"] != case["status"]:
            raise ValueError("CSV status differs from terminal evidence")
        fields = ("gr_ms", "spine_ms", "speedup_gr_over_spine")
        if row["status"] != "RESIDENT_PAIR_PASS":
            if any(row.get(key) for key in fields):
                raise ValueError("failed cases cannot contain speedups")
            continue
        passed += 1
        values = [float(row[key]) for key in fields]
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("positive finite measured times and speedup required")
        gr_ms, spine_ms, ratio = values
        summary = case["summary"]
        expected_values = (
            summary["walls"]["gr"]["median_ms"], summary["walls"]["spine"]["median_ms"],
            summary["speedup_ratio_of_median_walls"],
        )
        if any(not math.isclose(value, expected_value, rel_tol=1e-12)
               for value, expected_value in zip(values, expected_values, strict=True)) or \
                not math.isclose(ratio, gr_ms / spine_ms, rel_tol=1e-12):
            raise ValueError("CSV medians or speedup differ from admitted evidence")
    if passed != matrix["passed_cases"] or (matrix["status"] == "FPGA_MATRIX_PASS") != (passed == 24):
        raise ValueError("inconsistent passing-case count")
    if not passed:
        raise ValueError("no measured pairs; do not render a performance figure")
    return rows


def render(directory: Path, output: Path) -> dict:
    rows = load_delivery(directory)
    if output.exists():
        raise ValueError("use a fresh output directory")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, LogLocator, NullLocator

    plt.rcParams.update({
        "text.usetex": True, "text.latex.preamble": PREAMBLE, "font.family": "monospace",
        "font.size": 6.4, "axes.labelsize": 6.6, "xtick.labelsize": 6,
        "ytick.labelsize": 6, "legend.fontsize": 6, "axes.linewidth": 0.7,
        "hatch.linewidth": 0.38, "pdf.fonttype": 42, "ps.fonttype": 42,
    })
    figure, axis = plt.subplots(figsize=(3.55, 1.95))
    by_key = {(row["algorithm"], row["dataset"]): row for row in rows}
    ratios = [float(row["speedup_gr_over_spine"]) for row in rows if row["status"] == "RESIDENT_PAIR_PASS"]
    low, high = min(1.0, *ratios) / 1.35, max(1.0, *ratios) * 1.35
    axis.set_yscale("log")
    axis.set_ylim(low, high)
    axis.set_xlim(-0.5, 7.5)
    axis.set_axisbelow(True)
    axis.yaxis.set_major_locator(LogLocator(base=10, numticks=5))
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: format(value, "g")))
    axis.yaxis.set_minor_locator(NullLocator())
    axis.grid(axis="y", linestyle="--", linewidth=0.45, color="#CFD3D5")
    axis.axhline(1, color="#333333", linewidth=0.65, linestyle="--", zorder=2)
    missing = []
    for index, (algorithm, label, color, hatch) in enumerate(STYLES):
        for center, dataset in enumerate(DATASETS):
            row, position = by_key[algorithm, dataset], center + (index - 1) * 0.23
            if row["status"] == "RESIDENT_PAIR_PASS":
                ratio = float(row["speedup_gr_over_spine"])
                axis.bar(position, ratio - 1, bottom=1, width=0.23, facecolor=color,
                         edgecolor="black", linewidth=0.45, hatch=hatch, zorder=3)
            else:
                axis.plot(position, 0.035, marker="x", markersize=3, color="#777777",
                          transform=axis.get_xaxis_transform(), clip_on=False, zorder=5)
                missing.append({"algorithm": algorithm, "dataset": dataset, "status": row["status"]})
    axis.set_xticks(range(8), DATASETS)
    axis.set_ylabel("Speedup (G+R / Spine)")
    axis.tick_params(axis="x", which="both", length=0, top=False, bottom=False)
    axis.tick_params(axis="y", direction="in", width=0.65, length=2.3)
    for spine in axis.spines.values():
        spine.set_color("black")
        spine.set_zorder(10)
    handles = [Patch(facecolor=color, edgecolor="black", linewidth=0.45, hatch=hatch, label=label)
               for _, label, color, hatch in STYLES]
    axis.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.06), ncol=3,
                frameon=False, columnspacing=1.1, handlelength=1.4, handletextpad=0.3)
    if missing:
        figure.text(0.5, -0.04, "x: no admitted measurement", ha="center", fontsize=6)
    output.mkdir(parents=True)
    for extension in ("pdf", "png"):
        options = {"dpi": 500} if extension == "png" else {"metadata": {"CreationDate": None, "ModDate": None}}
        figure.savefig(output / ("fpga_speedup." + extension), bbox_inches="tight", pad_inches=0.03, **options)
    plt.close(figure)
    provenance = {
        "boundary": BOUNDARY, "metric": "ratio_of_median_resident_FPGA_wall_times",
        "source": str(directory), "passed_cases": len(ratios), "missing": missing,
        "source_sha256": {name: digest(directory / name) for name in
                          ("summary.csv", "matrix.json", "plan.json", "files.json")},
        "renderer_sha256": digest(Path(__file__)), "font": "TX Typewriter (txtt)",
        "style_reference": "figure7_10_handoff_v1/render_all.py", "paper_modified": False,
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.delivery.resolve(), args.output.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
