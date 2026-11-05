"""Render the hash-checked current review selection, never historical defaults."""

import argparse
import importlib.util
from pathlib import Path

import render as style
import render_current as current


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[5]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    source = REPOSITORY / "spine_cycle_sim/experiments/evaluation_impact/figure_refresh/review_bundle.py"
    spec = importlib.util.spec_from_file_location("review_bundle", source)
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    manifest = bundle.verify_files(REPOSITORY)
    if args.verify_only:
        print(manifest["checkpoint"])
        return
    args.output.mkdir(parents=True, exist_ok=False)
    reference = style.prior_renderer()
    reference.configure_matplotlib()
    current.draw(current.checked_rows(ROOT / "current_fpga/gr_controls.csv"), args.output)
    current.draw_resident(ROOT / "current_fpga/resident_checkpoint_v2/fig7_resident_checkpoint.csv", args.output)
    style.fig8_headroom(args.output)
    fresh = ROOT / "fresh_simulator"
    style.fig9(args.output, fresh, "fig9_memory_hbm_prediction", fresh=True)
    style.fig10(args.output, reference, fresh)
    style.fig11(args.output, fresh)
    print("Rendered six plots: controls and Figs. 7--11; incomplete FPGA matrix remains incomplete.")


if __name__ == "__main__":
    main()
