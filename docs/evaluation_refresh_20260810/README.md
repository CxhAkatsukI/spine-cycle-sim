# Evaluation Figure Refresh

This directory is a review packet, not an in-paper replacement. It addresses
the open questions about Figures 7--10 while keeping the TeX repository
unchanged until the revised evidence is accepted.

## Frozen decisions

- Figure 7 is hardware-only. Panels (a)--(c) use three correctness-admitted
  U55C repetitions on eight complete graphs under the setup-inclusive dynamic
  latency boundary. Panel (d) temporarily uses the existing three compact
  Full PageRank FPGA rows and is explicitly labeled as compact evidence.
- Projected values, timeout lower bounds, and missing bars are removed from
  Figure 7.
- Figures 8--10 will be regenerated only after the current sharded-K4
  simulator passes the frozen calibration and holdout gates.
- Figure 8 gives each panel a symbol-appropriate legend and expands the batch
  sensitivity sweep to at least five points.
- Figure 9 removes vertical separators and groups AU, SU, and WK by algorithm,
  with dataset color encoded once in a shared legend.
- Figure 10 uses reader-facing workload labels and explicitly states that each
  stacked bar is normalized to 100% of its own device-cycle interval.

## Current contents

- `figures/fig7_fpga_speedup_candidate.{pdf,png}`: first hardware-only
  candidate.
- `data/fig7_fpga_speedup.csv`: frozen medians and observed min/max values.
- `provenance/fig7.json`: hashes of every input evidence table.

Figures 8--10, the calibration report, and the final handoff archive remain
pending. A failed calibration row will be retained under `diagnostics/` and
will not be promoted into a candidate figure.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3
python3 -m venv /data/tmp/chuxiao/spine-cycle-sim-eval-venv
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/pip install -e '.[plots]'
/data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/render_evaluation_refresh.py
```
