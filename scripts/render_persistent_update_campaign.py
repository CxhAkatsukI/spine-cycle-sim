#!/usr/bin/env python3
"""Render the expanded persistent update-only experiment campaign."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/persistent_update_campaign_20260731"
DATA = ROOT / "docs/paper/data"
FIGURE = ROOT / "docs/figures/persistent_update_campaign_20260731"
CROSS_DATASETS = (
    ("au", "AU", 515281),
    ("su", "SU", 567316),
    ("wk", "WK", 1140149),
    ("so", "SO", 6024271),
    ("pk", "PK", 1632803),
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _systems(comparison: dict[str, object]) -> tuple[dict[str, object], ...]:
    rows = comparison["rows"]
    assert isinstance(rows, list)
    by_system = {row["system"]: row for row in rows}
    return by_system["spine"], by_system["grasu_regraph"]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    cross_rows: list[dict[str, object]] = []
    for key, label, vertices in CROSS_DATASETS:
        base = EVIDENCE / "cross_dataset" / key
        comparison = _load(base / "comparison.json")
        host = _load(base / "host.json")
        manifest = _load(base / "manifest.json")
        if "vertices" in manifest and int(manifest["vertices"]) != vertices:
            raise ValueError(f"{key} manifest vertex count changed")
        spine, grasu = _systems(comparison)
        cross_rows.append(
            {
                "dataset": label,
                "vertices": vertices,
                "initial_edges": host["graph_edges"],
                "spine_device_mups": float(spine["device_updates_per_second"])
                / 1e6,
                "grasu_device_mups": float(grasu["device_updates_per_second"])
                / 1e6,
                "device_spine_speedup": comparison["spine_speedup"][
                    "device_only"
                ],
                "setup_spine_speedup": comparison["spine_speedup"][
                    "modeled_host_inclusive"
                ],
                "spine_backend_requests": spine["backend_requests"],
                "grasu_backend_requests": grasu["backend_requests"],
                "host_repeats": manifest["host_repeats"],
            }
        )

    batch_rows: list[dict[str, object]] = []
    for batches in (10, 100, 1000):
        comparison = _load(
            EVIDENCE / "batch_sensitivity" / f"b{batches}" / "comparison.json"
        )
        spine, grasu = _systems(comparison)
        batch_rows.append(
            {
                "batch_count": batches,
                "records_per_batch": int(comparison["logical_updates"])
                / batches,
                "spine_device_mups": float(spine["device_updates_per_second"])
                / 1e6,
                "grasu_device_mups": float(grasu["device_updates_per_second"])
                / 1e6,
                "device_spine_speedup": comparison["spine_speedup"][
                    "device_only"
                ],
                "setup_spine_speedup": comparison["spine_speedup"][
                    "modeled_host_inclusive"
                ],
                "spine_backend_requests": spine["backend_requests"],
                "grasu_backend_requests": grasu["backend_requests"],
            }
        )

    operation_rows: list[dict[str, object]] = []
    for scenario in ("insert", "delete"):
        comparison = _load(EVIDENCE / "operation" / scenario / "comparison.json")
        spine, grasu = _systems(comparison)
        operation_rows.append(
            {
                "scenario": scenario,
                "logical_updates": comparison["logical_updates"],
                "batch_count": comparison["batch_count"],
                "spine_device_mups": float(spine["device_updates_per_second"])
                / 1e6,
                "grasu_device_mups": float(grasu["device_updates_per_second"])
                / 1e6,
                "device_spine_speedup": comparison["spine_speedup"][
                    "device_only"
                ],
                "setup_spine_speedup": comparison["spine_speedup"][
                    "modeled_host_inclusive"
                ],
            }
        )

    cross_path = DATA / "persistent_update_cross_dataset_20260731.csv"
    batch_path = DATA / "persistent_update_batch_sensitivity_20260731.csv"
    operation_path = DATA / "persistent_update_operation_20260731.csv"
    _write_csv(cross_path, cross_rows)
    _write_csv(batch_path, batch_rows)
    _write_csv(operation_path, operation_rows)

    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    tex = FIGURE.with_suffix(".tex")
    tex.write_text(
        rf"""\documentclass[tikz,border=2pt]{{standalone}}
\usepackage{{pgfplots}}
\usepgfplotslibrary{{groupplots}}
\pgfplotsset{{compat=1.18}}
\definecolor{{spineblue}}{{HTML}}{{1F77B4}}
\definecolor{{grasuorange}}{{HTML}}{{D95F02}}
\definecolor{{setupgreen}}{{HTML}}{{2E8B57}}
\begin{{document}}
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 1,horizontal sep=1.35cm}},
  width=5.65cm,height=5.3cm,
  grid=major,grid style={{dashed,gray!35}},
  tick align=inside,
  every axis plot/.append style={{thick}},
]
\nextgroupplot[
  title={{Device-only insertion throughput}},
  ymode=log,ybar=1pt,bar width=7pt,
  symbolic x coords={{AU,SU,WK,SO,PK}},xtick=data,
  ylabel={{Successful updates/s (million)}},
  legend style={{draw=none,at={{(0.03,0.97)}},anchor=north west}},
]
\addplot[spineblue,fill=spineblue!22] table[x=dataset,y=spine_device_mups,col sep=comma] {{{cross_path.resolve()}}};
\addlegendentry{{Spine}}
\addplot[grasuorange,fill=grasuorange!22] table[x=dataset,y=grasu_device_mups,col sep=comma] {{{cross_path.resolve()}}};
\addlegendentry{{GraSU}}
\nextgroupplot[
  title={{Cross-dataset speedup}},
  ymode=log,ybar=1pt,bar width=7pt,
  symbolic x coords={{AU,SU,WK,SO,PK}},xtick=data,
  legend style={{draw=none,at={{(0.5,-0.15)}},anchor=north,legend columns=2,font=\scriptsize}},
]
\addplot[spineblue,fill=spineblue!22] table[x=dataset,y=device_spine_speedup,col sep=comma] {{{cross_path.resolve()}}};
\addlegendentry{{Device-only}}
\addplot[setupgreen,fill=setupgreen!22] table[x=dataset,y=setup_spine_speedup,col sep=comma] {{{cross_path.resolve()}}};
\addlegendentry{{Trace setup-inclusive}}
\addplot[black,dashed] coordinates {{(AU,1) (PK,1)}};
\nextgroupplot[
  title={{Batch sensitivity (fixed 131K)}},
  xmode=log,log basis x=10,ymode=log,
  xtick={{10,100,1000}},
  xlabel={{Persistent batches}},
]
\addplot[spineblue,mark=square*] table[x=batch_count,y=device_spine_speedup,col sep=comma] {{{batch_path.resolve()}}};
\addplot[setupgreen,mark=*] table[x=batch_count,y=setup_spine_speedup,col sep=comma] {{{batch_path.resolve()}}};
\addplot[black,dashed,domain=10:1000,samples=2] {{1}};
\end{{groupplot}}
\end{{tikzpicture}}
\end{{document}}
""",
        encoding="ascii",
    )
    subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={FIGURE.parent}",
            str(tex),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "pdftocairo",
            "-svg",
            str(FIGURE.with_suffix(".pdf")),
            str(FIGURE.with_suffix(".svg")),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
