#!/usr/bin/env python3
"""Export the frozen paper architecture contract as an HLS header."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine_cycle_sim.alignment_contract import (  # noqa: E402
    load_alignment_contract,
    render_hls_contract_header,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/contracts/spine_paper_architecture_alignment_v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = load_alignment_contract(args.contract)
    rendered = render_hls_contract_header(contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="ascii")
    print(f"contract_id={contract.contract_id}")
    print(f"contract_sha256={contract.sha256}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
