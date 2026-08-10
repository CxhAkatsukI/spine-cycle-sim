#!/usr/bin/env python3
"""Render the audited >=540k-edge three-algorithm result as SVG."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "docs/evidence/large_real_three_algorithm_v1/summary.json"
DEFAULT_OUTPUT = ROOT / "docs/figures/large_real_three_algorithm.svg"
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _element(tag: str, **attributes: object) -> ET.Element:
    return ET.Element(
        f"{{{SVG_NS}}}{tag}", {key: str(value) for key, value in attributes.items()}
    )


def _add(parent: ET.Element, tag: str, **attributes: object) -> ET.Element:
    child = _element(tag, **attributes)
    parent.append(child)
    return child


def _text(
    parent: ET.Element, value: str, x: float, y: float, **attributes: object
) -> None:
    child = _add(parent, "text", x=f"{x:.2f}", y=f"{y:.2f}", **attributes)
    child.text = value


def _x(batch: float, low: float, high: float, left: float, right: float) -> float:
    if low == high:
        return (left + right) / 2
    return left + (math.log10(batch) - math.log10(low)) / (
        math.log10(high) - math.log10(low)
    ) * (right - left)


def _panel(
    root: ET.Element,
    *,
    origin: float,
    title: str,
    subtitle: str,
    series: list[tuple[str, str, list[dict[str, object]]]],
    y_max: float,
    logarithmic_y: bool,
) -> None:
    left, right, top, bottom = origin + 64, origin + 452, 105.0, 390.0
    batches = [float(row["user_mutations"]) for _, _, rows in series for row in rows]
    low, high = min(batches), max(batches)

    def y_position(value: float) -> float:
        if logarithmic_y:
            return bottom - math.log10(value) / math.log10(y_max) * (bottom - top)
        return bottom - value / y_max * (bottom - top)

    _text(
        root,
        title,
        origin + 258,
        38,
        fill="#18212a",
        **{"font-size": 20, "font-weight": 700, "text-anchor": "middle"},
    )
    _text(
        root,
        subtitle,
        origin + 258,
        65,
        fill="#59636e",
        **{"font-size": 12, "text-anchor": "middle"},
    )
    ticks = (1, 10, 100) if logarithmic_y else (1, 5, 10, 15)
    for tick in ticks:
        y = y_position(float(tick))
        _add(
            root,
            "line",
            x1=left,
            y1=y,
            x2=right,
            y2=y,
            stroke="#dfe4e8" if tick != 1 else "#68737d",
            **{
                "stroke-width": 1.5 if tick == 1 else 1,
                "stroke-dasharray": "7 6" if tick == 1 else "none",
            },
        )
        _text(
            root,
            str(tick),
            left - 10,
            y + 5,
            fill="#4b5560",
            **{"font-size": 12, "text-anchor": "end"},
        )
    unique_batches = sorted(set(batches))
    for batch in unique_batches:
        x = _x(batch, low, high, left, right)
        _text(
            root,
            str(int(batch)),
            x,
            bottom + 25,
            fill="#303943",
            **{"font-size": 12, "text-anchor": "middle"},
        )
    for series_index, (label, color, rows) in enumerate(series):
        rows = sorted(rows, key=lambda row: row["user_mutations"])
        coordinates = [
            (
                _x(float(row["user_mutations"]), low, high, left, right),
                y_position(float(row["spine_speedup_over_grasu"])),
            )
            for row in rows
        ]
        _add(
            root,
            "polyline",
            points=" ".join(f"{x:.2f},{y:.2f}" for x, y in coordinates),
            fill="none",
            stroke=color,
            **{"stroke-width": 3},
        )
        for row, (x, y) in zip(rows, coordinates, strict=True):
            speedup = float(row["spine_speedup_over_grasu"])
            _add(root, "circle", cx=x, cy=y, r=5, fill=color, stroke="#ffffff")
            _text(
                root,
                f"{speedup:.1f}x",
                x,
                y - 11,
                fill=color,
                **{"font-size": 11, "font-weight": 700, "text-anchor": "middle"},
            )
        legend_x = origin + 100 + 155 * series_index
        legend_y = 474
        _add(
            root,
            "line",
            x1=legend_x,
            y1=legend_y,
            x2=legend_x + 24,
            y2=legend_y,
            stroke=color,
            **{"stroke-width": 3},
        )
        _text(
            root,
            label,
            legend_x + 31,
            legend_y + 5,
            fill="#303943",
            **{"font-size": 12},
        )
    _text(
        root,
        "Logical insertions per batch (log scale)",
        origin + 258,
        bottom + 52,
        fill="#303943",
        **{"font-size": 13, "font-weight": 600, "text-anchor": "middle"},
    )


def render(summary: Path, output: Path) -> None:
    data = json.loads(summary.read_text(encoding="utf-8"))
    if data.get("status") != "PASS" or not all(data.get("checks", {}).values()):
        raise ValueError("refusing to plot large-real evidence that failed checks")
    root = _element(
        "svg",
        width=1500,
        height=500,
        viewBox="0 0 1500 500",
        role="img",
        **{"aria-labelledby": "title description"},
    )
    title = _add(root, "title", id="title")
    title.text = "Large-real-graph performance by algorithm and update batch"
    description = _add(root, "desc", id="description")
    description.text = (
        "Spine speedup over K1 GraSU plus ReGraph for weighted SSSP, connected "
        "components, and per-vertex threshold residual PageRank."
    )
    _add(root, "rect", x=0, y=0, width=1500, height=500, fill="#f7f8fa")
    weighted = data["weighted_sssp"]
    cc = data["connected_components"]
    residual = data["residual_pagerank"]
    _panel(
        root,
        origin=0,
        title="Weighted SSSP",
        subtitle="157,107V / 540,000E directed near-full graph",
        series=[("540k", "#c34d3f", weighted["pairs"])],
        y_max=500,
        logarithmic_y=True,
    )
    _panel(
        root,
        origin=500,
        title="Connected Components",
        subtitle="derived-real reciprocal projections",
        series=[
            ("540k", "#147d92", cc["gate_pairs"]),
            ("904k", "#3f8b68", cc["full_pairs"]),
        ],
        y_max=15,
        logarithmic_y=False,
    )
    _panel(
        root,
        origin=1000,
        title="Residual PageRank",
        subtitle="per-vertex threshold 1e-6; sink-free projections",
        series=[
            ("540k", "#147d92", residual["gate_pairs"]),
            ("904k", "#3f8b68", residual["full_pairs"]),
        ],
        y_max=15,
        logarithmic_y=False,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(args.summary.resolve(), args.output.resolve())
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
