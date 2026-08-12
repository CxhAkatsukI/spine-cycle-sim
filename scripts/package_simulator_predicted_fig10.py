#!/usr/bin/env python3
"""Package the complete simulator-predicted Figure 10 breakdown."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = (
    ROOT / "docs/evaluation_refresh_20260810/data/fig10_rq3_breakdown_rows.csv"
)
DEFAULT_PROVENANCE = (
    ROOT / "docs/evaluation_refresh_20260810/provenance/fig10.json"
)
DEFAULT_SUMMARY = (
    ROOT / "docs/evaluation_refresh_20260810/data/fig10_rq3_summary.json"
)
DEFAULT_OUT = (
    ROOT
    / "docs/evaluation_refresh_20260810/simulator_predicted_fig10_v1"
)

GROUPS = (
    ("Zero-net", (("Syn", "ZN"),)),
    ("Shallow insert", (("AU", "SI"), ("SU", "SI"), ("WK", "SI"))),
    ("Deep carry", (("L1", "Carry"), ("L3", "Carry"), ("L5", "Carry"))),
    (
        "PR correction",
        (("FL", "PR-corr"), ("SU", "PR-corr"), ("WK", "PR-corr")),
    ),
    ("Deletion fallback", (("Syn", "Del"),)),
)

STAGES = (
    (
        "maintenance",
        ("t_xfer_cycles", "t_reduce_cycles", "t_carry_cycles", "t_directory_cycles"),
        "Maint.",
        "#A8CF88",
        "xxxxxxxx",
    ),
    (
        "seed_publication",
        ("t_seed_cycles", "t_switch_cycles"),
        "Seed/pub.",
        "#F1A55B",
        "||||||||",
    ),
    ("resolve", ("t_resolve_cycles",), "Resolve", "#2F86BD", "////////"),
    ("application", ("t_app_cycles",), "App", "#B7D6E8", "\\\\\\\\\\\\\\\\"),
    (
        "drain_sync",
        ("t_drain_cycles", "t_sync_cycles"),
        "Drain",
        "#35A936",
        "xxxxxxxx",
    ),
)

TEN_STAGE_KEYS = tuple(key for _name, keys, _label, _color, _hatch in STAGES for key in keys)
TXTT_PREAMBLE = (
    r"\usepackage{txfonts}"
    r"\renewcommand{\rmdefault}{txtt}"
    r"\renewcommand{\sfdefault}{txtt}"
    r"\renewcommand{\ttdefault}{txtt}"
    r"\renewcommand{\familydefault}{\ttdefault}"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="ascii", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_bool(row: dict[str, str], key: str) -> bool:
    return row.get(key, "").strip().lower() == "true"


def cycles(row: dict[str, str], key: str) -> int:
    value = row.get(key, "")
    if value == "":
        raise ValueError(f"missing {key}: {row.get('execution_id', '<unknown>')}")
    return int(value)


def validate_and_order_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    expected = [
        (source_group, tick)
        for _display_group, entries in GROUPS
        for tick, source_group in entries
    ]
    keyed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("figure_group", ""), row.get("figure_tick", ""))
        if key in keyed:
            raise ValueError(f"duplicate Figure 10 row: {key}")
        keyed[key] = row
    if set(keyed) != set(expected):
        missing = sorted(set(expected) - set(keyed))
        extra = sorted(set(keyed) - set(expected))
        raise ValueError(f"incomplete Figure 10 coverage: missing={missing} extra={extra}")

    ordered = [keyed[key] for key in expected]
    plugins = {row.get("plugin_sha256", "") for row in ordered}
    if len(plugins) != 1 or "" in plugins:
        raise ValueError(f"Figure 10 must use one identified simulator plugin: {plugins}")

    for row in ordered:
        execution_id = row["execution_id"]
        for key in ("ten_stage_supported", "ten_stage_ledger_closed", "ledger_closed"):
            if not as_bool(row, key):
                raise ValueError(f"{execution_id} failed {key}")
        total = cycles(row, "total_cycles")
        stage_sum = sum(cycles(row, key) for key in TEN_STAGE_KEYS)
        if total <= 0 or stage_sum != total:
            raise ValueError(
                f"{execution_id} stage ledger does not close: total={total} stages={stage_sum}"
            )
    zero_net = ordered[0]
    if not as_bool(zero_net, "explicit_zero_net_semantics"):
        raise ValueError("zero-net row lacks explicit target no-repair semantics")
    return ordered


def normalized_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    display_by_key = {
        (source_group, tick): display_group
        for display_group, entries in GROUPS
        for tick, source_group in entries
    }
    output: list[dict[str, object]] = []
    for row in rows:
        total = cycles(row, "total_cycles")
        record: dict[str, object] = {
            "execution_id": row["execution_id"],
            "dataset_id": row["dataset_id"],
            "algorithm": row["algorithm"],
            "case_class": row["case_class"],
            "figure_group": display_by_key[(row["figure_group"], row["figure_tick"])],
            "figure_tick": row["figure_tick"],
            "plugin_sha256": row["plugin_sha256"],
            "total_cycles": total,
        }
        percentage_sum = 0.0
        for stage_name, keys, _label, _color, _hatch in STAGES:
            stage_cycles = sum(cycles(row, key) for key in keys)
            percentage = 100.0 * stage_cycles / total
            record[f"{stage_name}_cycles"] = stage_cycles
            record[f"{stage_name}_percent"] = f"{percentage:.9f}"
            percentage_sum += percentage
        if abs(percentage_sum - 100.0) > 1e-9:
            raise ValueError(f"normalized stages do not sum to 100%: {row['execution_id']}")
        output.append(record)
    return output


def validate_summary(summary: dict[str, Any], plugin_sha256: str) -> None:
    expected_coverage = {
        "zero_net",
        "shallow_insertion",
        "deep_carry",
        "pagerank_correction",
        "deletion_fallback",
    }
    coverage = summary.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != expected_coverage:
        raise ValueError("source RQ3 summary lacks complete five-class coverage")
    if any(value != "ready" for value in coverage.values()):
        raise ValueError("source RQ3 summary contains a non-ready workload class")
    if summary.get("all_direct_ten_stage_ledgers_closed") is not True:
        raise ValueError("source RQ3 summary reports an open direct stage ledger")
    if summary.get("preferred_plugin_sha256") != [plugin_sha256]:
        raise ValueError("source RQ3 summary and selected rows use different plugins")


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "text.usetex": True,
            "text.latex.preamble": TXTT_PREAMBLE,
            "font.family": "monospace",
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.linewidth": 0.8,
            "legend.fontsize": 6.5,
            "xtick.labelsize": 6.2,
            "ytick.labelsize": 7,
            "hatch.linewidth": 0.3,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


def render(rows: list[dict[str, object]], output: Path) -> None:
    plt = configure_matplotlib()
    from matplotlib.patches import Patch

    tick_labels: list[str] = []
    x_positions: list[float] = []
    group_centers: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    row_index = 0
    for display_group, entries in GROUPS:
        start = cursor
        for tick, _source_group in entries:
            tick_labels.append(tick)
            x_positions.append(cursor)
            cursor += 1.0
            row_index += 1
        end = cursor - 1.0
        group_centers.append((display_group, (start + end) / 2.0))
        separators.append(end + 0.55)
        cursor += 0.68
    if row_index != len(rows):
        raise ValueError("plot layout and normalized row count differ")
    separators = separators[:-1]

    figure, axis = plt.subplots(figsize=(3.55, 2.08))
    bottoms = [0.0] * len(rows)
    legend: list[Any] = []
    for stage_name, _keys, label, color, hatch in STAGES:
        values = [float(row[f"{stage_name}_percent"]) for row in rows]
        axis.bar(
            x_positions,
            values,
            bottom=bottoms,
            width=0.58,
            color=color,
            edgecolor="black",
            linewidth=0.22,
            hatch=hatch,
            zorder=2,
        )
        bottoms = [left + right for left, right in zip(bottoms, values, strict=True)]
        legend.append(Patch(facecolor=color, edgecolor="black", hatch=hatch, label=label))

    for separator in separators:
        axis.axvline(
            separator,
            color="black",
            linestyle=(0, (2.0, 1.1)),
            linewidth=0.58,
            ymin=-0.12,
            ymax=1.0,
            clip_on=False,
            zorder=4,
        )
    display_labels = {
        "Zero-net": "Zero-net",
        "Shallow insert": "Shallow\ninsert",
        "Deep carry": "Deep\ncarry",
        "PR correction": "PR\ncorrection",
        "Deletion fallback": "Deletion\nfallback",
    }
    for display_group, center in group_centers:
        axis.text(
            center,
            -0.23,
            display_labels[display_group],
            transform=axis.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=6.8,
            linespacing=0.9,
            clip_on=False,
        )

    axis.set_xlim(min(x_positions) - 0.65, max(x_positions) + 0.65)
    axis.set_xticks(x_positions)
    axis.set_xticklabels(tick_labels)
    axis.set_ylabel("Simulated E2E cycles (\\%)")
    axis.set_ylim(0.0, 108.0)
    axis.set_yticks((0, 25, 50, 75, 100))
    axis.tick_params(axis="x", top=False, bottom=False, length=0, pad=1.4)
    axis.tick_params(axis="y", direction="in", right=True, length=2.8, width=0.7)
    axis.grid(
        axis="y",
        linestyle=(0, (2.0, 1.1)),
        color="0.72",
        alpha=0.65,
        linewidth=0.48,
        zorder=0,
    )
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
    axis.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.245),
        ncol=5,
        frameon=False,
        handlelength=1.35,
        handletextpad=0.3,
        columnspacing=0.48,
        borderaxespad=0.0,
    )
    figure.subplots_adjust(left=0.16, right=0.995, bottom=0.3, top=0.75)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(
        output.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02
    )
    plt.close(figure)


def readme_text(plugin_sha256: str) -> str:
    return f"""# Simulator-predicted Figure 10

This packet presents a normalized cycle breakdown from the execution-driven
Spine simulator. It is not an FPGA per-stage measurement or an FPGA-calibrated
breakdown. All eleven bars use simulator plugin `{plugin_sha256}`.

## Scope

- `Zero-net / Syn`: synthetic reciprocal update reduced to no effective graph
  change; this uses the paper target's no-repair semantics.
- `Shallow insert / AU, SU, WK`: batch-8 insertion on AskUbuntu, Superuser, and
  WikiTalk traces.
- `Deep carry / L1, L3, L5`: synthetic batch-8 traces forcing carry through
  level 1, 3, or 5.
- `PR correction / FL, SU, WK`: thresholded residual PageRank correction on
  Flickr, Superuser, and WikiTalk.
- `Deletion fallback / Syn`: synthetic weighted-SSSP deletion fallback.

The ten-stage ledger is grouped for readability:

- `Maint.` = transfer + reduce + carry + directory;
- `Seed/pub.` = seed + switch/publication;
- `Resolve` = history/edge resolution;
- `App` = algorithm application;
- `Drain` = source/reactivation drain + synchronization.

Each bar is independently normalized by its own simulated end-to-end device
cycle interval. Therefore, the figure explains how the dominant stage changes
across realized-work classes; it does not compare absolute latency between
bars. The source analysis admits only correctness-passing Spine runs. This
packager additionally requires one plugin hash, complete five-class coverage,
closed direct ten-stage and aggregate ledgers, and exact cycle conservation.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \\
  scripts/package_simulator_predicted_fig10.py
```

Outputs:

- `fig10_simulator_predicted_breakdown.pdf` and `.png`;
- `normalized_breakdown_rows.csv`;
- `manifest.json` with source and output hashes.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    source_rows = args.rows.resolve()
    source_provenance = args.provenance.resolve()
    source_summary = args.summary.resolve()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    provenance = read_json(source_provenance)
    if provenance.get("status") not in {
        "PASS_CURRENT_MODEL_DATA",
        "INTERIM_ARCHIVED_SIMULATOR_DATA",
    }:
        raise ValueError("source Figure 10 provenance is not simulator-admitted")
    if provenance.get("data_csv_sha256") != sha256_file(source_rows):
        raise ValueError("source Figure 10 CSV does not match its provenance hash")
    ordered = validate_and_order_rows(read_csv(source_rows))
    normalized = normalized_rows(ordered)
    plugin_sha256 = ordered[0]["plugin_sha256"]
    validate_summary(read_json(source_summary), plugin_sha256)

    rows_path = output / "normalized_breakdown_rows.csv"
    figure_path = output / "fig10_simulator_predicted_breakdown"
    readme_path = output / "README.md"
    write_csv(rows_path, normalized)
    render(normalized, figure_path)
    readme_path.write_text(readme_text(plugin_sha256), encoding="ascii")

    output_paths = (
        rows_path,
        figure_path.with_suffix(".pdf"),
        figure_path.with_suffix(".png"),
        readme_path,
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "status": "PASS_SIMULATOR_PREDICTED",
            "claim_scope": "normalized execution-driven simulator stage attribution",
            "not_claimed": [
                "FPGA per-stage measurement",
                "FPGA-calibrated stage percentages",
                "absolute-latency comparison between normalized bars",
            ],
            "plugin_sha256": plugin_sha256,
            "rows": len(normalized),
            "groups": [display_group for display_group, _entries in GROUPS],
            "normalization": (
                "each bar is normalized to 100% of its own simulated E2E device cycles"
            ),
            "gates": {
                "single_plugin": True,
                "complete_five_class_coverage": True,
                "source_correctness_admitted": True,
                "ten_stage_supported": True,
                "ten_stage_ledger_closed": True,
                "aggregate_ledger_closed": True,
                "stage_cycle_conservation": True,
                "explicit_target_zero_net_semantics": True,
            },
            "sources": [
                {"path": str(source_rows), "sha256": sha256_file(source_rows)},
                {
                    "path": str(source_provenance),
                    "sha256": sha256_file(source_provenance),
                },
                {
                    "path": str(source_summary),
                    "sha256": sha256_file(source_summary),
                },
            ],
            "outputs": {
                path.name: sha256_file(path)
                for path in output_paths
            },
        },
    )
    print(
        f"SIMULATOR_FIG10_PASS rows={len(normalized)} plugin={plugin_sha256} "
        f"out={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
