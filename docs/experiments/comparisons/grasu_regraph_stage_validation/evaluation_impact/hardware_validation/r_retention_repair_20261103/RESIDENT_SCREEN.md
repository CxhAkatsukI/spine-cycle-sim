# First Paired ResPR Screen

Status: **Flickr CPU references agree per vertex; paired board runner
prepared, no new FPGA speedup.**
Run this screen only after the exact ResPR G+R image has passed the independent
[G scope](G_SCOPE.md) and R retention screens. Do not use these two runs to
admit SSSP or CC images, replace the matrix, or claim a win outside these cases.

| Case | Why this case | Preserved graph identity |
| --- | --- | --- |
| R19 | Narrowest old ResPR win (44.669267 vs 32.375100 ms, 1.380x); the old run had zero propagation on both arms. | Original full R19 fixture, SHA-256 `0c984e8c9cfff56d81732451046c2c65701b79efcea968b22bb9c241011b088a` |
| Flickr | Already used as a real-topology ResPR correction slice; adds actual thresholded propagation without changing the threshold. | 2,552 vertices, 8,192 initial directed edges, 8 reciprocal insert pairs (16 directed updates), SHA-256 `b370b2ede9d09ff7ac410fd1f1e487057dffc6468146f11ab9373362ef0d3f8b` |

One measured run per arm per case, no warmup runs. Use the same graph bytes,
same old-graph warm start (128 rank sweeps), damping 0.85, per-vertex
threshold 1e-6, and a 256 propagation-round limit. Both exact fixtures are
sink-free before and after insertion, so dangling redistribution cannot
differ between arms on these cases. Both
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

### Cross-Host Oracle Check

On the exact Flickr input above, the Spine host at `cb42376663c5` and
the G+R host at `24519a66d732` also agree on old/new degree and initial
active membership at every vertex. Both have zero sinks and activate the
same 133 vertices. Warm rank, correction residual, and final rank agree
at the emitted round-trip float precision. Final residual differs by at
most `2.28e-13` (`2.15e-11` summed absolute difference); G+R's CPU
reference reports 12 propagation rounds. This does not assert equality
of the FPGA results or of the hardware's execution schedules.

For this check use the optional second argument of the Spine CPU probe
to write its state TSV. Compile `resident_gr_cpu_probe.cpp` with the
pinned G+R ResPR host flags (`-O2`, `--pipeline-mode sharded-k4`,
`--prefetch-compact` and the ResPR algorithm define from the native
host build script), replacing its main translation unit and adding
`-I"$GR_ROOT/tools"`. Invoke both probes as `PROBE GRAPH OUTPUT.tsv`,
then from the simulator checkout run:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_oracles \
  flickr-spine.tsv flickr-gr.tsv 2552
```

The dumps are ordered by external vertex ID. Columns are old and new
out-degree, warm rank, correction residual, final rank, final residual,
and initial active bit. The one-shot dumps are indexed under
`/data/chuxiao/checks/source-retention-repair-20261104/respr-oracles.ky4pDrLE/`:

| Dump | SHA-256 |
| --- | --- |
| `flickr-spine.tsv` | `c1a576e7c64eb0d8a727a8cc437c4ffcf07dbc41d8d3f2afd49102942bfae0e5` |
| `flickr-gr.tsv` | `cede1588aeef2b672d313874bbbbe411f774fb7c362359447fae4faa38cbc511` |

Both probes used CPUs 124--125, a 2 GiB memory cap, zero swap and no
board access. This per-vertex check covers Flickr only. A separate
out-degree scan of the hash-verified R19 graph found zero sinks before
and after its eight insertions across all 524,288 vertices; this was
not a comparison of R19 ranks. For a graph
with sinks, G+R's CPU reference redistributes dangling residual during
propagation and this Spine reference does not. A shared correction
threshold alone does not establish equivalent propagation on such a
graph. Do not generalize the Flickr result to all eight graphs.

## Board Runner

This is a bounded two-case screen, not a figure replacement. It waits for
both supported R controls and the AU G control to meet the 1.15 elapsed
ratio on the **same ResPR image**. It replays their measured clocks and
requires matching candidate-image clocks again in the paired run. It records
both arms' driver frequencies and uses observed elapsed milliseconds without
clock normalization. Each arm validates against its own CPU oracle; these
hosts do not emit two arrays for direct cross-host final-rank comparison.
The report records both iteration counts, including any difference.

In the simulator checkout, with an 8 GiB maximum, 7 GiB high watermark,
zero-swap cgroup and 32 GiB live reserve:

```bash
checks=/data/chuxiao/checks/source-retention-repair-20261104
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_board \
  --route /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-v1 \
  --r-report "$checks/after-follow-v2/results.json" \
  --g-report "$checks/g-candidate-board-v1/results.json" \
  --gr-host /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/hosts/respr/sharded_k4_residual_pagerank_native_host \
  --spine-host /data/chuxiao/checks/spine-cc-respr-host-20261026/default-hosts-v1/thresholded_residual_pagerank.host \
  --spine-image /data/chuxiao/builds/grasu-cache-extent-20261025/spine-respr-zfs-v1/build/respr/xclbin/spine_partitioned_split_e2e.respr.hw.xclbin \
  --comparator /home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py \
  --r19 /data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/r19_residual_pagerank_insert_u8.graph \
  --flickr "$checks/resident-preflight.QnpgS8/flickr.graph" \
  --output "$checks/resident-board-v1" --wait-seconds 21600
```

Use a fresh output directory. The report records the exact commands and
whether any board launch was attempted. There are no automatic retries.
It holds both the original matrix lease and the PCI-addressed control lease.
Any non-admitted gate leaves the board untouched; a started run preserves
stdout/stderr even if correctness or clock validation fails. The historical
R19 logs replay at 44.669267 ms for G+R and 32.375100 ms for Spine. That
replay tests the parser; it is not a measurement of the repaired image.
