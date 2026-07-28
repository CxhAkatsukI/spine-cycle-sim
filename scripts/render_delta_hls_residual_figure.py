#!/usr/bin/env python3
"""Render the frozen Delta.hls residual screening evidence as an SVG."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCREENING = (
    ROOT / "docs/evidence/deltahls_residual_k1_screening_v2/summary.json"
)
DEFAULT_SENSITIVITY = (
    ROOT
    / "docs/evidence/deltahls_residual_threshold_sensitivity_u8_v1/summary.json"
)
DEFAULT_OUTPUT = ROOT / "docs/figures/deltahls_residual_k1_screening.svg"
DEFAULT_SCALABILITY = (
    ROOT / "docs/evidence/deltahls_residual_p4_scalability_v1/summary.json"
)
DEFAULT_SCALABILITY_OUTPUT = (
    ROOT / "docs/figures/deltahls_residual_p4_scalability.svg"
)
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _svg_element(tag: str, **attributes: object) -> ET.Element:
    return ET.Element(
        f"{{{SVG_NS}}}{tag}", {key: str(value) for key, value in attributes.items()}
    )


def _add(parent: ET.Element, tag: str, **attributes: object) -> ET.Element:
    child = _svg_element(tag, **attributes)
    parent.append(child)
    return child


def _text(
    parent: ET.Element, value: str, x: float, y: float, **attributes: object
) -> None:
    element = _add(parent, "text", x=f"{x:.2f}", y=f"{y:.2f}", **attributes)
    element.text = value


def _scale_log(value: float, low: float, high: float, left: float, right: float) -> float:
    position = (math.log10(value) - math.log10(low)) / (
        math.log10(high) - math.log10(low)
    )
    return left + position * (right - left)


def _panel(
    root: ET.Element,
    *,
    x: float,
    title: str,
    x_label: str,
    points: list[tuple[float, float, str, bool]],
) -> None:
    top, bottom = 94.0, 390.0
    left, right = x + 78.0, x + 490.0
    y_max = max(3.5, max(speedup for _, speedup, _, _ in points) * 1.12)
    x_low = min(value for value, _, _, _ in points)
    x_high = max(value for value, _, _, _ in points)

    def y_position(value: float) -> float:
        return bottom - value / y_max * (bottom - top)

    _text(
        root,
        title,
        x + 284,
        42,
        fill="#18212a",
        **{"font-size": 20, "font-weight": 700, "text-anchor": "middle"},
    )
    _add(
        root,
        "rect",
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
        fill="#ffffff",
        stroke="#c8d0d8",
        **{"stroke-width": 1},
    )
    for tick in range(1, math.ceil(y_max) + 1):
        y = y_position(float(tick))
        _add(
            root,
            "line",
            x1=left,
            y1=y,
            x2=right,
            y2=y,
            stroke="#e4e8ec",
            **{"stroke-width": 1},
        )
        _text(
            root,
            str(tick),
            left - 12,
            y + 5,
            fill="#4b5560",
            **{"font-size": 13, "text-anchor": "end"},
        )
    baseline_y = y_position(1.0)
    _add(
        root,
        "line",
        x1=left,
        y1=baseline_y,
        x2=right,
        y2=baseline_y,
        stroke="#4b5560",
        **{"stroke-width": 1.5, "stroke-dasharray": "7 6"},
    )
    coordinates: list[tuple[float, float, str, bool]] = []
    for value, speedup, label, primary in points:
        px = (
            (left + right) / 2
            if x_low == x_high
            else _scale_log(value, x_low, x_high, left, right)
        )
        py = y_position(speedup)
        coordinates.append((px, py, label, primary))
        _add(
            root,
            "line",
            x1=px,
            y1=bottom,
            x2=px,
            y2=bottom + 6,
            stroke="#4b5560",
            **{"stroke-width": 1},
        )
        _text(
            root,
            label,
            px,
            bottom + 25,
            fill="#303943",
            **{"font-size": 13, "text-anchor": "middle"},
        )
    _add(
        root,
        "polyline",
        points=" ".join(f"{px:.2f},{py:.2f}" for px, py, _, _ in coordinates),
        fill="none",
        stroke="#147d92",
        **{"stroke-width": 3},
    )
    for (px, py, _, primary), (_, speedup, _, _) in zip(
        coordinates, points, strict=True
    ):
        color = "#c34d3f" if primary else "#147d92"
        _add(root, "circle", cx=px, cy=py, r=6, fill=color, stroke="#ffffff")
        _text(
            root,
            f"{speedup:.2f}x",
            px,
            py - 13,
            fill=color,
            **{"font-size": 13, "font-weight": 700, "text-anchor": "middle"},
        )
    _text(
        root,
        x_label,
        (left + right) / 2,
        bottom + 55,
        fill="#303943",
        **{"font-size": 14, "font-weight": 600, "text-anchor": "middle"},
    )


def render(screening: Path, sensitivity: Path, output: Path) -> None:
    screening_data = json.loads(screening.read_text(encoding="utf-8"))
    sensitivity_data = json.loads(sensitivity.read_text(encoding="utf-8"))
    if not screening_data.get("all_correct") or not sensitivity_data.get("all_correct"):
        raise ValueError("refusing to plot evidence that failed correctness gates")
    screening_points = sorted(
        (
            float(pair["user_mutations"]),
            float(pair["spine_speedup_over_grasu"]),
            str(pair["user_mutations"]),
            False,
        )
        for pair in screening_data["pairs"]
    )
    sensitivity_points = sorted(
        (
            float(pair["epsilon"]),
            float(pair["spine_speedup_over_grasu"]),
            f"1e{round(math.log10(float(pair['epsilon'])))}",
            math.isclose(float(pair["epsilon"]), 1.0e-6),
        )
        for pair in sensitivity_data["pairs"]
    )
    root = _svg_element(
        "svg",
        width=1120,
        height=500,
        viewBox="0 0 1120 500",
        role="img",
        **{"aria-labelledby": "title description"},
    )
    title = _add(root, "title", id="title")
    title.text = "Delta.hls residual PageRank K1 screening"
    description = _add(root, "desc", id="description")
    description.text = (
        "Spine speedup over GraSU plus ReGraph by update batch and per-vertex "
        "residual threshold. Values above one favor Spine."
    )
    _add(root, "rect", x=0, y=0, width=1120, height=500, fill="#f7f8fa")
    _panel(
        root,
        x=0,
        title="Small-batch screening (epsilon = 1e-6)",
        x_label="Logical insertions per batch (log scale)",
        points=screening_points,
    )
    _panel(
        root,
        x=560,
        title="Threshold sensitivity (u8)",
        x_label="Per-vertex residual threshold (log scale)",
        points=sensitivity_points,
    )
    _text(
        root,
        "Speedup = GraSU+ReGraph time / Spine time; values above 1 favor Spine",
        560,
        482,
        fill="#59636e",
        **{"font-size": 13, "text-anchor": "middle"},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def render_scalability(summary: Path, output: Path) -> None:
    data = json.loads(summary.read_text(encoding="utf-8"))
    if data.get("status") != "PASS" or not all(data.get("checks", {}).values()):
        raise ValueError("refusing to plot scalability evidence that failed gates")
    labels = ("Spine", "GraSU K1", "GraSU K4 direct", "GraSU K4 shared")
    rows = data["rows"]
    cycles = [float(row["cycles"]) for row in rows]
    root = _svg_element(
        "svg",
        width=920,
        height=500,
        viewBox="0 0 920 500",
        role="img",
        **{"aria-labelledby": "title description"},
    )
    title = _add(root, "title", id="title")
    title.text = "Delta.hls residual PageRank four-partition scalability"
    description = _add(root, "desc", id="description")
    description.text = (
        "Cycle counts for Spine and GraSU plus ReGraph K1, direct K4, and "
        "shared K4 on a balanced four-partition sink-free workload."
    )
    _add(root, "rect", x=0, y=0, width=920, height=500, fill="#f7f8fa")
    _text(
        root,
        "Four-partition residual PageRank scalability",
        460,
        42,
        fill="#18212a",
        **{"font-size": 22, "font-weight": 700, "text-anchor": "middle"},
    )
    left, right, top, bottom = 88.0, 880.0, 82.0, 390.0
    y_max = math.ceil(max(cycles) / 5_000_000.0) * 5_000_000.0
    for tick in range(0, int(y_max) + 1, 5_000_000):
        y = bottom - tick / y_max * (bottom - top)
        _add(
            root,
            "line",
            x1=left,
            y1=y,
            x2=right,
            y2=y,
            stroke="#dfe4e8",
            **{"stroke-width": 1},
        )
        _text(
            root,
            f"{tick / 1_000_000:.0f}",
            left - 12,
            y + 5,
            fill="#4b5560",
            **{"font-size": 13, "text-anchor": "end"},
        )
    bar_width = 118.0
    centers = [170.0, 360.0, 560.0, 760.0]
    colors = ("#c34d3f", "#68737d", "#147d92", "#3f8b68")
    for center, label, value, color in zip(
        centers, labels, cycles, colors, strict=True
    ):
        height = value / y_max * (bottom - top)
        _add(
            root,
            "rect",
            x=center - bar_width / 2,
            y=bottom - height,
            width=bar_width,
            height=height,
            fill=color,
        )
        _text(
            root,
            f"{value / 1_000_000:.2f}M",
            center,
            bottom - height - 12,
            fill=color,
            **{"font-size": 14, "font-weight": 700, "text-anchor": "middle"},
        )
        _text(
            root,
            label,
            center,
            bottom + 28,
            fill="#303943",
            **{"font-size": 13, "font-weight": 600, "text-anchor": "middle"},
        )
    _text(
        root,
        "Cycles (millions)",
        24,
        238,
        fill="#303943",
        transform="rotate(-90 24 238)",
        **{"font-size": 14, "font-weight": 600, "text-anchor": "middle"},
    )
    metrics = data["metrics"]
    _text(
        root,
        (
            f"K1 to direct K4: {metrics['k1_to_direct_k4_speedup']:.2f}x   |   "
            f"K1 to shared K4: {metrics['k1_to_shared_k4_speedup']:.2f}x   |   "
            f"shared penalty: {(metrics['shared_k4_penalty_over_direct'] - 1) * 100:.2f}%"
        ),
        460,
        472,
        fill="#59636e",
        **{"font-size": 13, "text-anchor": "middle"},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screening", type=Path, default=DEFAULT_SCREENING)
    parser.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--scalability", type=Path, default=DEFAULT_SCALABILITY)
    parser.add_argument(
        "--scalability-output", type=Path, default=DEFAULT_SCALABILITY_OUTPUT
    )
    args = parser.parse_args()
    render(args.screening.resolve(), args.sensitivity.resolve(), args.output.resolve())
    render_scalability(
        args.scalability.resolve(), args.scalability_output.resolve()
    )
    print(f"wrote {args.output} and {args.scalability_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
