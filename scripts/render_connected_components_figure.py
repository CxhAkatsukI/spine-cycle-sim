#!/usr/bin/env python3
"""Render correctness-gated connected-components publication evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = (
    ROOT / "docs/evidence/connected_components_publication_v1/summary.json"
)
DEFAULT_OUTPUT = ROOT / "docs/figures/connected_components_publication.svg"
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


def _screening_panel(root: ET.Element, data: dict[str, object]) -> None:
    left, right, top, bottom = 78.0, 520.0, 90.0, 385.0
    pairs = sorted(data["screening_pairs"], key=lambda row: row["user_mutations"])
    y_max = 2.25

    def x_position(batch: float) -> float:
        low, high = math.log10(1), math.log10(4096)
        return left + (math.log10(batch) - low) / (high - low) * (right - left)

    def y_position(speedup: float) -> float:
        return bottom - speedup / y_max * (bottom - top)

    _text(
        root,
        "Real-topology batch boundary (K1)",
        299,
        48,
        fill="#18212a",
        **{"font-size": 20, "font-weight": 700, "text-anchor": "middle"},
    )
    for tick in (0.5, 1.0, 1.5, 2.0):
        y = y_position(tick)
        _add(
            root,
            "line",
            x1=left,
            y1=y,
            x2=right,
            y2=y,
            stroke="#dfe4e8",
            **{
                "stroke-width": 1.5 if tick == 1.0 else 1,
                "stroke-dasharray": "7 6" if tick == 1.0 else "none",
            },
        )
        _text(
            root,
            f"{tick:.1f}",
            left - 12,
            y + 5,
            fill="#4b5560",
            **{"font-size": 13, "text-anchor": "end"},
        )
    coordinates = []
    for row in pairs:
        batch = float(row["user_mutations"])
        speedup = float(row["spine_speedup_over_grasu"])
        x, y = x_position(batch), y_position(speedup)
        coordinates.append((x, y))
        _text(
            root,
            f"{int(batch)}",
            x,
            bottom + 26,
            fill="#303943",
            **{"font-size": 13, "text-anchor": "middle"},
        )
    _add(
        root,
        "polyline",
        points=" ".join(f"{x:.2f},{y:.2f}" for x, y in coordinates),
        fill="none",
        stroke="#147d92",
        **{"stroke-width": 3},
    )
    for row, (x, y) in zip(pairs, coordinates, strict=True):
        speedup = float(row["spine_speedup_over_grasu"])
        color = "#147d92" if speedup >= 1.0 else "#c34d3f"
        _add(root, "circle", cx=x, cy=y, r=6, fill=color, stroke="#ffffff")
        _text(
            root,
            f"{speedup:.2f}x",
            x,
            y - 13,
            fill=color,
            **{"font-size": 13, "font-weight": 700, "text-anchor": "middle"},
        )
    _text(
        root,
        "Logical insertions per batch (log scale)",
        299,
        bottom + 57,
        fill="#303943",
        **{"font-size": 14, "font-weight": 600, "text-anchor": "middle"},
    )


def _scalability_panel(root: ET.Element, data: dict[str, object]) -> None:
    left, right, top, bottom = 626.0, 1082.0, 90.0, 385.0
    rows = data["scalability_rows"]
    labels = ("Spine", "GraSU K1", "K4 direct", "K4 shared")
    cycles = [float(row["cycles"]) for row in rows]
    y_max = 25_000_000.0
    centers = (690.0, 805.0, 925.0, 1040.0)
    colors = ("#c34d3f", "#68737d", "#147d92", "#3f8b68")
    _text(
        root,
        "Four-partition scalability",
        854,
        48,
        fill="#18212a",
        **{"font-size": 20, "font-weight": 700, "text-anchor": "middle"},
    )
    for tick in range(0, 25_000_001, 5_000_000):
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
    for center, label, value, color in zip(
        centers, labels, cycles, colors, strict=True
    ):
        height = value / y_max * (bottom - top)
        _add(
            root,
            "rect",
            x=center - 42,
            y=bottom - height,
            width=84,
            height=height,
            fill=color,
        )
        _text(
            root,
            f"{value / 1_000_000:.2f}M",
            center,
            bottom - height - 11,
            fill=color,
            **{"font-size": 13, "font-weight": 700, "text-anchor": "middle"},
        )
        _text(
            root,
            label,
            center,
            bottom + 26,
            fill="#303943",
            **{"font-size": 12, "font-weight": 600, "text-anchor": "middle"},
        )
    metrics = data["scalability_metrics"]
    _text(
        root,
        (
            f"K1 to direct: {metrics['k1_to_direct_k4_speedup']:.2f}x | "
            f"K1 to shared: {metrics['k1_to_shared_k4_speedup']:.2f}x"
        ),
        854,
        bottom + 57,
        fill="#303943",
        **{"font-size": 14, "font-weight": 600, "text-anchor": "middle"},
    )


def render(summary: Path, output: Path) -> None:
    data = json.loads(summary.read_text(encoding="utf-8"))
    if data.get("status") != "PASS" or not all(data.get("checks", {}).values()):
        raise ValueError("refusing to plot CC evidence that failed admission")
    root = _element(
        "svg",
        width=1160,
        height=500,
        viewBox="0 0 1160 500",
        role="img",
        **{"aria-labelledby": "title description"},
    )
    title = _add(root, "title", id="title")
    title.text = "Connected-components screening and four-partition scalability"
    description = _add(root, "desc", id="description")
    description.text = (
        "Spine speedup over GraSU plus ReGraph by insertion batch and cycle "
        "counts for K1, direct K4, and shared K4."
    )
    _add(root, "rect", x=0, y=0, width=1160, height=500, fill="#f7f8fa")
    _screening_panel(root, data)
    _scalability_panel(root, data)
    _text(
        root,
        "Speedup = GraSU+ReGraph cycles / Spine cycles; values above 1 favor Spine",
        580,
        480,
        fill="#59636e",
        **{"font-size": 13, "text-anchor": "middle"},
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
