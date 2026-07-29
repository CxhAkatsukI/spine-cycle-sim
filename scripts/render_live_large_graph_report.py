#!/usr/bin/env python3
"""Render the correctness-gated live large-graph campaign as TeX and CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/live_publication_analysis"
)
DEFAULT_DATA_DIR = ROOT / "docs/paper/data/large_graph_campaign"
DEFAULT_TEX = ROOT / "docs/paper/large_graph_campaign_results.tex"

DATASET_ORDER = (
    "sx_askubuntu",
    "sx_superuser",
    "wiki_talk_temporal",
    "sx_stackoverflow",
    "soc_bitcoin",
    "hollywood_2009",
    "soc_pokec",
    "soc_orkut",
    "soc_livejournal1",
    "ljournal_2008",
    "uk_2002",
    "rmat_19_32",
)
DATASET_LABEL = {
    "sx_askubuntu": "AU",
    "sx_superuser": "SU",
    "wiki_talk_temporal": "WK",
    "sx_stackoverflow": "SO",
    "soc_bitcoin": "BC",
    "hollywood_2009": "HW",
    "soc_pokec": "PK",
    "soc_orkut": "OK",
    "soc_livejournal1": "LJ",
    "ljournal_2008": "LJ08",
    "uk_2002": "UK",
    "rmat_19_32": "R19",
}
ALGORITHM_ORDER = (
    "weighted_sssp",
    "connected_components",
    "full_pagerank",
    "thresholded_residual_pagerank",
)
ALGORITHM_LABEL = {
    "weighted_sssp": "SSSP",
    "connected_components": "CC",
    "full_pagerank": "FullPR",
    "thresholded_residual_pagerank": "ResPR",
}
SYSTEM_LABEL = {
    "spine": "Spine",
    "grasu_regraph_k1": "G+R K1",
    "grasu_regraph_k4_shared": "G+R K4-shared",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _float(row: Mapping[str, str], key: str) -> float:
    return float(row[key])


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else float("nan")


def headline_pair_rows(
    rows: Iterable[Mapping[str, str]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Mapping[str, str]]] = {}
    for row in rows:
        if row.get("scenario") != "insert" or row.get("batch_size") != "8":
            continue
        dataset = str(row["dataset_id"])
        algorithm = str(row["algorithm"])
        if dataset not in DATASET_LABEL or algorithm not in ALGORITHM_LABEL:
            continue
        grouped.setdefault((dataset, algorithm), {})[str(row["competitor"])] = row

    dataset_rank = {value: index for index, value in enumerate(DATASET_ORDER)}
    algorithm_rank = {value: index for index, value in enumerate(ALGORITHM_ORDER)}
    output = []
    for index, ((dataset, algorithm), competitors) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: (
                dataset_rank[item[0][0]],
                algorithm_rank[item[0][1]],
            ),
        )
    ):
        row: dict[str, Any] = {
            "index": index,
            "label": f"{DATASET_LABEL[dataset]}-{ALGORITHM_LABEL[algorithm]}",
            "dataset_id": dataset,
            "algorithm": algorithm,
        }
        for system, prefix in (
            ("grasu_regraph_k1", "k1"),
            ("grasu_regraph_k4_shared", "k4"),
        ):
            pair = competitors.get(system)
            if pair is None:
                for metric in (
                    "speedup",
                    "memory_ratio",
                    "energy_ratio",
                    "update_speedup",
                ):
                    row[f"{prefix}_{metric}"] = "nan"
                continue
            row[f"{prefix}_speedup"] = _float(pair, "spine_speedup")
            row[f"{prefix}_memory_ratio"] = _ratio(
                _float(pair, "competitor_memory_bytes"),
                _float(pair, "spine_memory_bytes"),
            )
            row[f"{prefix}_energy_ratio"] = _float(
                pair, "spine_energy_advantage"
            )
            row[f"{prefix}_update_speedup"] = _float(
                pair, "spine_update_speedup"
            )
        output.append(row)
    return output


def runtime_summary(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("scenario") != "insert" or row.get("batch_size") != "8":
            continue
        grouped.setdefault(str(row["system"]), []).append(
            _float(row, "host_wall_seconds")
        )
    output = []
    for system in ("spine", "grasu_regraph_k4_shared", "grasu_regraph_k1"):
        values = grouped.get(system, [])
        if not values:
            continue
        output.append(
            {
                "system": system,
                "label": SYSTEM_LABEL[system],
                "runs": len(values),
                "median_seconds": statistics.median(values),
                "max_seconds": max(values),
            }
        )
    return output


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty report data: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _latex_escape(value: object) -> str:
    text = str(value)
    for source, replacement in (
        ("\\", r"\textbackslash{}"),
        ("_", r"\_"),
        ("%", r"\%"),
        ("&", r"\&"),
        ("#", r"\#"),
    ):
        text = text.replace(source, replacement)
    return text


def render_tex(
    *,
    summary: Mapping[str, Any],
    runtime: Sequence[Mapping[str, Any]],
    pair_count: int,
) -> str:
    runtime_lines = []
    for row in runtime:
        runtime_lines.append(
            "    "
            + " & ".join(
                (
                    _latex_escape(row["label"]),
                    str(row["runs"]),
                    f"{float(row['median_seconds']):.1f}",
                    f"{float(row['max_seconds']):.1f}",
                )
            )
            + r" \\"
        )
    runtime_table = "\n".join(runtime_lines)
    template = r"""\documentclass[10pt]{article}
\usepackage[margin=0.7in]{geometry}
\usepackage{booktabs}
\usepackage{pgfplots}
\usepackage{pgfplotstable}
\usepackage{xcolor}
\usepackage[hidelinks]{hyperref}
\pgfplotsset{compat=1.18}
\definecolor{spine}{HTML}{176B87}
\definecolor{kfour}{HTML}{237A57}
\definecolor{kone}{HTML}{B44C43}
\IfFileExists{data/large_graph_campaign/headline_pairs.csv}{
  \newcommand{\datadir}{data/large_graph_campaign}
}{
  \newcommand{\datadir}{docs/paper/data/large_graph_campaign}
}
\pgfplotstableread[col sep=comma]{\datadir/headline_pairs.csv}\pairdata
\hypersetup{pdftitle={Spine Large-Graph Campaign Results}}
\title{\textbf{Spine Large-Graph Campaign Results}\\
\large Correctness-Gated Spine vs. GraSU+ReGraph K1/K4-shared}
\author{Chuxiao Han}
\date{Live campaign snapshot, July 2026}
\begin{document}
\maketitle
\begin{abstract}
This report is generated directly from correctness-gated campaign artifacts.
The snapshot is \textbf{@@STATUS@@}: @@OBSERVED@@ of @@EXPECTED@@ planned
physical executions are currently admitted, with @@TRIPLETS@@ complete
three-system groups. Missing bars are unexecuted comparisons, not zero-valued
measurements. All plotted rows use insertion batch 8 and exact cross-system
final-state agreement.
\end{abstract}

\section{End-to-end performance}
\begin{figure}[ht]
\centering
\begin{tikzpicture}
\begin{semilogyaxis}[
  ybar, bar width=7pt, width=0.98\linewidth, height=64mm,
  ylabel={Spine speedup (higher is better)},
  xtick=data, xticklabels from table={\pairdata}{label},
  x tick label style={rotate=28,anchor=east},
  ymin=0.5, grid=major,
  legend style={at={(0.5,1.14)},anchor=south,legend columns=2}]
\addplot[fill=kfour] table[x=index,y=k4_speedup] {\pairdata};
\addplot[fill=kone] table[x=index,y=k1_speedup] {\pairdata};
\addplot[black,dashed,sharp plot] coordinates {(0,1) (@@MAX_INDEX@@,1)};
\legend{G+R K4-shared,G+R K1}
\end{semilogyaxis}
\end{tikzpicture}
\caption{Device-cycle speedup after both architecture and independent
mathematical correctness gates. K4-shared is the primary GraSU baseline.}
\end{figure}
\clearpage

\section{Memory traffic and HBM energy}
\begin{figure}[ht]
\centering
\begin{tikzpicture}
\begin{semilogyaxis}[
  ybar, bar width=7pt, width=0.98\linewidth, height=60mm,
  ylabel={G+R / Spine ratio},
  xtick=data, xticklabels from table={\pairdata}{label},
  x tick label style={rotate=28,anchor=east}, ymin=0.5, grid=major,
  legend style={at={(0.5,1.14)},anchor=south,legend columns=2}]
\addplot[fill=kfour] table[x=index,y=k4_memory_ratio] {\pairdata};
\addplot[fill=kone] table[x=index,y=k1_memory_ratio] {\pairdata};
\addplot[black,dashed,sharp plot] coordinates {(0,1) (@@MAX_INDEX@@,1)};
\legend{K4-shared requested bytes,K1 requested bytes}
\end{semilogyaxis}
\end{tikzpicture}
\caption{Accepted backend bytes. Ratios above one mean GraSU+ReGraph moves
more data than Spine; request and DRAM completion ledgers close on every row.}
\end{figure}

\begin{figure}[ht]
\centering
\begin{tikzpicture}
\begin{semilogyaxis}[
  ybar, bar width=7pt, width=0.98\linewidth, height=60mm,
  ylabel={G+R / Spine HBM energy},
  xtick=data, xticklabels from table={\pairdata}{label},
  x tick label style={rotate=28,anchor=east}, ymin=0.5, grid=major,
  legend style={at={(0.5,1.14)},anchor=south,legend columns=2}]
\addplot[fill=kfour] table[x=index,y=k4_energy_ratio] {\pairdata};
\addplot[fill=kone] table[x=index,y=k1_energy_ratio] {\pairdata};
\addplot[black,dashed,sharp plot] coordinates {(0,1) (@@MAX_INDEX@@,1)};
\legend{G+R K4-shared,G+R K1}
\end{semilogyaxis}
\end{tikzpicture}
\caption{All-controller DRAMSim3 energy ratio. This is HBM energy, not total
accelerator or board energy.}
\end{figure}
\clearpage

\section{Update-only tradeoff}
\begin{figure}[ht]
\centering
\begin{tikzpicture}
\begin{semilogyaxis}[
  ybar, bar width=7pt, width=0.98\linewidth, height=58mm,
  ylabel={Spine update-phase speedup},
  xtick=data, xticklabels from table={\pairdata}{label},
  x tick label style={rotate=28,anchor=east}, ymin=0.001, ymax=2,
  grid=major, legend style={at={(0.5,1.14)},anchor=south,legend columns=2}]
\addplot[fill=kfour] table[x=index,y=k4_update_speedup] {\pairdata};
\addplot[fill=kone] table[x=index,y=k1_update_speedup] {\pairdata};
\addplot[black,dashed,sharp plot] coordinates {(0,1) (@@MAX_INDEX@@,1)};
\legend{G+R K4-shared,G+R K1}
\end{semilogyaxis}
\end{tikzpicture}
\caption{Update-phase cycles only. Values below one expose Spine's current
maintenance cost even when end-to-end execution favors Spine.}
\end{figure}

\section{Simulator engineering runtime}
\begin{table}[ht]
\centering
\begin{tabular}{lrrr}
\toprule
System & Completed runs & Median host s & Maximum host s \\
\midrule
@@RUNTIME_TABLE@@
\bottomrule
\end{tabular}
\caption{Observed host wall time under concurrent campaign load. These values
measure simulator throughput and are not accelerator performance.}
\end{table}

\paragraph{Claim boundary.}
Only complete correctness-gated pairs enter the figures. Current FPGA/RTL
evidence supports feasibility and PPA separately; this report does not claim
cycle-for-cycle FPGA calibration or ASIC total power.
\end{document}
"""
    replacements = {
        "@@STATUS@@": _latex_escape(summary["status"]),
        "@@OBSERVED@@": str(summary["observed_executions"]),
        "@@EXPECTED@@": str(summary["expected_executions"]),
        "@@TRIPLETS@@": str(summary["complete_triplets"]),
        "@@MAX_INDEX@@": str(max(0, pair_count - 1)),
        "@@RUNTIME_TABLE@@": runtime_table,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--tex", type=Path, default=DEFAULT_TEX)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = json.loads(
        (args.analysis_dir / "summary.json").read_text(encoding="utf-8")
    )
    pairs = headline_pair_rows(read_csv(args.analysis_dir / "pair_rows.csv"))
    runtime = runtime_summary(read_csv(args.analysis_dir / "system_rows.csv"))
    write_csv(args.data_dir / "headline_pairs.csv", pairs)
    write_csv(args.data_dir / "runtime_summary.csv", runtime)
    args.tex.parent.mkdir(parents=True, exist_ok=True)
    args.tex.write_text(
        render_tex(
            summary=summary,
            runtime=runtime,
            pair_count=len(pairs),
        ),
        encoding="ascii",
    )
    print(
        f"rendered {len(pairs)} headline groups and {len(runtime)} runtime rows "
        f"to {args.tex}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
