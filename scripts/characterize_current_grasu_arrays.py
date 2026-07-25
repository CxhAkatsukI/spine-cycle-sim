#!/usr/bin/env python3
"""Characterize current 8-lane GraSU/ReGraph SRAM arrays with CACTI-P."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.evidence.energy import (  # noqa: E402
    build_cacti_p,
    cacti_source_identity,
    render_cacti_config,
    run_cacti,
)
from spine_cycle_sim.evidence.matched_energy import (  # noqa: E402
    CURRENT_GRASU_ARRAY_GEOMETRIES,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--cacti-source-dir", type=Path, default=Path("/data/feiyang/mcpat/cacti")
    )
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs <= 0:
        raise ValueError("jobs must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    source_identity = cacti_source_identity(args.cacti_source_dir)
    entries = []
    with tempfile.TemporaryDirectory(prefix="spine-current-cacti-") as tmp:
        tmp_root = Path(tmp)
        build = build_cacti_p(args.cacti_source_dir, tmp_root / "build", jobs=args.jobs)
        for char_id, geometry in CURRENT_GRASU_ARRAY_GEOMETRIES.items():
            config = render_cacti_config(geometry)
            run = run_cacti(build["binary"], config, tmp_root / char_id)
            config_name = f"{char_id}.cfg"
            output_name = f"{char_id}.out"
            (args.out_dir / config_name).write_text(config, encoding="utf-8")
            (args.out_dir / output_name).write_text(run["stdout"], encoding="utf-8")
            entries.append(
                {
                    "characterization_id": char_id,
                    "geometry": geometry,
                    "config_path": config_name,
                    "config_sha256": _sha256(config.encode("utf-8")),
                    "output_path": output_name,
                    "output_sha256": _sha256(run["stdout"].encode("utf-8")),
                    "result": run["result"],
                }
            )
    manifest = {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": "projected_32nm_asic_sram_not_fpga_power",
        "tool": "CACTI-P 6.5 (June 2014)",
        "source_identity": source_identity,
        "build": {
            "binary_sha256": build["binary_sha256"],
            "command": build["command"],
            "compatibility_patch": build["compatibility_patch"],
        },
        "characterizations": entries,
    }
    (args.out_dir / "cacti_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS current GraSU/ReGraph CACTI arrays: "
        + " ".join(
            f"{entry['characterization_id']}={entry['result']['area_mm2']:.6f}mm2"
            for entry in entries
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
