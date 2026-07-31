#!/usr/bin/env python3
"""Render the trace-aware persistent update-only comparison."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/evidence/persistent_update_only_20260731"
DEFAULT_OUTPUT = ROOT / "docs/figures/persistent_update_only_20260731"
SIZES = (64, 1024, 16384, 131072)


def _load_rows(evidence: Path) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for size in SIZES:
        path = evidence / f"au_u{size}" / "comparison.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        by_system = {row["system"]: row for row in data["rows"]}
        spine = by_system["spine"]
        grasu = by_system["grasu_regraph"]
        rows.append(
            {
                "logical_updates": size,
                "batch_count": int(data["batch_count"]),
                "spine_device_mups": float(spine["device_updates_per_second"])
                / 1e6,
                "grasu_device_mups": float(grasu["device_updates_per_second"])
                / 1e6,
                "spine_setup_inclusive_mups": float(
                    spine["modeled_host_inclusive_updates_per_second"]
                )
                / 1e6,
                "grasu_setup_inclusive_mups": float(
                    grasu["modeled_host_inclusive_updates_per_second"]
                )
                / 1e6,
                "device_spine_speedup": float(
                    data["spine_speedup"]["device_only"]
                ),
                "setup_inclusive_spine_speedup": float(
                    data["spine_speedup"]["modeled_host_inclusive"]
                ),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, float | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "docs/paper/data/persistent_update_only_20260731.csv",
    )
    args = parser.parse_args()
    rows = _load_rows(args.evidence)
    _write_csv(args.csv, rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tex_path = args.output.with_suffix(".tex")
    data_path = args.csv.resolve()
    tex_path.write_text(
        rf"""\documentclass[tikz,border=2pt]{{standalone}}
\usepackage{{pgfplots}}
\usepgfplotslibrary{{groupplots}}
\pgfplotsset{{compat=1.18}}
\definecolor{{spineblue}}{{HTML}}{{1F77B4}}
\definecolor{{grasuorange}}{{HTML}}{{D95F02}}
\begin{{document}}
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 1,horizontal sep=1.25cm}},
  width=7.2cm,height=5.3cm,
  xmode=log,log basis x=2,ymode=log,
  xtick={{64,1024,16384,131072}},
  xticklabels={{64,1K,16K,131K}},
  xlabel={{Mutations in trace (10 batches)}},
  grid=major,grid style={{dashed,gray!35}},
  tick align=inside,
  legend style={{draw=none,at={{(0.02,0.98)}},anchor=north west}},
  every axis plot/.append style={{thick}},
]
\nextgroupplot[
  title={{Device-only update path}},
  ylabel={{Successful mutations/s (million)}},
]
\addplot[spineblue,mark=square*] table[x=logical_updates,y=spine_device_mups,col sep=comma] {{{data_path}}};
\addlegendentry{{Spine}}
\addplot[grasuorange,mark=*] table[x=logical_updates,y=grasu_device_mups,col sep=comma] {{{data_path}}};
\addlegendentry{{GraSU}}
\nextgroupplot[title={{Trace setup-inclusive}}]
\addplot[spineblue,mark=square*] table[x=logical_updates,y=spine_setup_inclusive_mups,col sep=comma] {{{data_path}}};
\addplot[grasuorange,mark=*] table[x=logical_updates,y=grasu_setup_inclusive_mups,col sep=comma] {{{data_path}}};
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
            f"-output-directory={args.output.parent}",
            str(tex_path),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "pdftocairo",
            "-svg",
            str(args.output.with_suffix(".pdf")),
            str(args.output.with_suffix(".svg")),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
