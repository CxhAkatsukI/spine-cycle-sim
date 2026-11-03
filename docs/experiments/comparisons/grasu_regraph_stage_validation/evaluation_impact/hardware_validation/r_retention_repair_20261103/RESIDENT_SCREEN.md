# First Paired ResPR Screen

Status: **Flickr CPU preflight passed on both arms; no new FPGA speedup.**
Run this screen only after the exact ResPR G+R image has passed the independent
[G scope](G_SCOPE.md) and R retention screens. Do not use these two runs to
admit SSSP or CC images, replace the matrix, or claim a win outside these cases.

| Case | Why this case | Preserved graph identity |
| --- | --- | --- |
| R19 | Narrowest old ResPR win (44.669267 vs 32.375100 ms, 1.380x); the old run had zero propagation on both arms. | Original full R19 fixture, SHA-256 `0c984e8c9cfff56d81732451046c2c65701b79efcea968b22bb9c241011b088a` |
| Flickr | Already used as a real-topology ResPR correction slice; adds actual thresholded propagation without changing the threshold. | 2,552 vertices, 8,192 initial directed edges, 8 reciprocal insert pairs (16 directed updates), SHA-256 `b370b2ede9d09ff7ac410fd1f1e487057dffc6468146f11ab9373362ef0d3f8b` |

One measured run per arm per case, no warmup runs. Use the same graph bytes,
same old-graph warm start (128 rank sweeps), damping 0.85, per-vertex
threshold 1e-6, and a 256 propagation-round limit. The Flickr fixture is
sink-free so dangling redistribution cannot differ between arms. Both
hosts must finish with empty active work and pass final-state validation.
Require positive *device-reported* propagation rounds on both Flickr arms;
CPU preflight is not that check. Do not require bitwise agreement or infer
matching rounds from the independent CPU oracles. Retain raw output and
report any divergence before interpreting elapsed-time ratios.

Compare resident-update wall times through the final result readback,
including post-start launch/wait, correction, propagation, and inter-round
host work on each arm. Old-rank preload, graph construction, board programming,
and final CPU oracle validation are outside this window. Pre-resident update
preparation is outside this specific scope; report what was prepared on each
arm and keep the update-preparation-inclusive Figure 8 separate. Capture the
same card/BDF, actual device clocks, artifact hashes, and host configuration.

## Reproduce The CPU Preflight

From the simulator checkout, using a new output path:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_input \
  tests/data/deltahls_real/real_soc_flickr_und_reciprocal_sinkfree.slice \
  tests/data/deltahls_real/real_soc_flickr_und_insert_u8.slice /tmp/flickr-respr.graph
sha256sum /tmp/flickr-respr.graph
```

The converter changes only the input format: no new vertex remap, no sampling,
and no change to weights, edge order, or update order. The original fixture is
already a compact real-topology slice, not a full Flickr run.

- **G+R:** Run the pinned production ResPR host from [G scope](G_SCOPE.md)
  with `GRASU_SHARDED_METADATA_REPLICAS=4` and
  `--prepare-only /tmp/flickr-respr.graph /tmp/unused.result`. The observed
  fields were `oracle_propagation_rounds=12 oracle_converged=1`,
  `final_edges=8208 destination_partitions=1`, and `_PREP status=PASS`.
- **Spine:** Use source commit `cb42376663c534f0bd0c25d271737ca34893135e`.
  From its `tests/test_integration`, use the ResPR flags in the pinned
  `default-hosts-v1/respr.compile.log`. Replace the host main translation
  unit with `resident_spine_cpu_probe.cpp` from this package's
  `source_retention` Python module directory; keep `-I.`, `xcl2.cpp` and
  the XRT link flags. Run the probe with just the graph file argument. It
  reported `active_seed=133 changed_ranks=363 converged=1` using the
  production parser, seed calculation, and CPU convergence reference.

Both preflights used CPUs 124--125, a 2 GiB cgroup limit, zero swap, and a
180-second timeout. Measured service peaks were 19.1 MiB for G+R, 478.8 MiB
for compiling the Spine probe, and 2.5 MiB for running it. No card was
programmed. None of these measurements is a benchmark.
