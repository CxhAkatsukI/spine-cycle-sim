# Persistent update-only campaign (2026-07-31)

This evidence compares persistent structure updates with graph computation
disabled. Spine sees each arriving batch; the official-style GraSU baseline
uses the complete trace once to build its update-density order and reserved
PMA. Device-only and trace-setup-inclusive times are separate metrics.

## Reproduce one point

Build the simulator and SST element first, then run:

```bash
cmake --build build -j4
make -C cpp/sst -j2
python3 scripts/run_persistent_update_only.py \
  --dataset sx_askubuntu \
  --scenario insert \
  --graph /data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/workloads/sx_askubuntu/graphs/directed_weighted.slice \
  --updates /data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu/updates/directed/insert_u4096.slice \
  --batch-count 10 \
  --out-dir /tmp/persistent-update-au
```

The runner refuses graphs above the frozen Spine `MAX_N=2^24` and refuses
weight-increase update-only runs, whose current differential semantics require
the separately measured full-rebuild fallback.

## Regenerate tables and figures

```bash
python3 scripts/render_persistent_update_campaign.py
pdflatex -interaction=nonstopmode -halt-on-error \
  -output-directory=docs/paper \
  docs/paper/persistent_update_campaign_results.tex
```

Every admitted `comparison.json` has zero correctness mismatches for both
architectures. `exclusions.json` records cases that are not admitted to the
performance results. The manifests freeze channels, PMA partition size,
memory backend, vertex count, trace mode, and host repeat count.
