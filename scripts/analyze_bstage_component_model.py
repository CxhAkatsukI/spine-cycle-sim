#!/usr/bin/env python3
"""Analyze the Phase 4C current-HW B-stage / maintenance component model.

Reads the four default evidence directories (phase2b calibration synthetic,
phase4c one-partition synthetic, phase2d holdout synthetic, and the phase4a
real exact Amazon slices), fits the L0 four-term model plus the carry residual
correction from the *calibration* rows only, and emits a per-case component
breakdown, what-if estimates, and a grouped error summary.

This is an analysis-only tool: it does not touch the HLS kernel and does not
rebuild the xclbin.

Usage:
    python3 scripts/analyze_bstage_component_model.py --out-dir <DIR>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration import (  # noqa: E402
    DEFAULT_EVIDENCE,
    fit_component_model,
    group_summary,
    group_summary_field_order,
    load_default_evidence,
    model_to_dict,
    prediction_field_order,
    prediction_row,
    write_json,
    write_rows_csv,
)
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=ROOT,
        help="Root directory that the default relative evidence paths resolve against.",
    )
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    for group in DEFAULT_EVIDENCE:
        parser.add_argument(
            f"--{group.replace('_', '-')}-dir",
            dest=f"{group}_dir",
            type=str,
            default=None,
            help=f"Override the evidence directory for the {group} group.",
        )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    overrides = {
        group: getattr(args, f"{group}_dir")
        for group in DEFAULT_EVIDENCE
        if getattr(args, f"{group}_dir")
    }

    records = load_default_evidence(
        root=args.evidence_root, freq_mhz=args.freq_mhz, overrides=overrides
    )
    model = fit_component_model(records, freq_mhz=args.freq_mhz)

    predictions = [model.predict(record) for record in records]
    predictions.sort(key=lambda p: (p["role"], p["group"], p["mode"], p["batch_edges"]))

    rows = [prediction_row(prediction) for prediction in predictions]
    summaries = group_summary(predictions)

    model_json = model_to_dict(model)
    model_json["evidence"] = {
        group: {
            "path": overrides.get(group, spec["path"]),
            "role": spec["role"],
            "kind": spec["kind"],
        }
        for group, spec in DEFAULT_EVIDENCE.items()
    }
    model_json["record_count"] = len(records)

    write_json(args.out_dir / "component_model.json", model_json)
    write_rows_csv(args.out_dir / "component_predictions.csv", rows, prediction_field_order())
    write_rows_csv(args.out_dir / "group_summary.csv", summaries, group_summary_field_order())

    print(f"records={len(records)} fitted_l0=({model.l0.fixed:.1f},{model.l0.c_part:.2f},"
          f"{model.l0.c_edge:.3f},{model.l0.c_edge_part:.3f}) "
          f"carry_residual={model.carry.fixed_residual:.1f}")
    print(f"wrote {args.out_dir / 'component_model.json'}")
    print(f"wrote {args.out_dir / 'component_predictions.csv'}")
    print(f"wrote {args.out_dir / 'group_summary.csv'}")
    print()
    print("group_summary:")
    header = group_summary_field_order()
    print("  " + "  ".join(header))
    for summary in summaries:
        print("  " + "  ".join(_fmt(summary[key]) for key in header))
    return 0


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
