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
board access. This per-vertex comparison covers Flickr only.

### Frozen Eight-Graph Inputs

A separate scan verified the graph hash in each October matrix
`respr-<case>/manifest.json`, checked record counts, vertex bounds and
insert-only operations, and counted zero-outdegree vertices before and
after the batch. All eight exact inputs are sink-free at both points:

| Case | Vertices | Old directed edges | Insert records | Old/new sinks |
| --- | ---: | ---: | ---: | ---: |
| AU | 515,281 | 826,848 | 8 | 0 / 0 |
| SU | 567,316 | 1,075,035 | 8 | 0 / 0 |
| WK | 1,140,149 | 2,190,639 | 8 | 0 / 0 |
| SO | 6,024,271 | 28,299,669 | 8 | 0 / 0 |
| PK | 1,632,803 | 44,603,928 | 8 | 0 / 0 |
| LJ | 4,847,571 | 85,703,436 | 8 | 0 / 0 |
| LJ08 | 5,363,260 | 99,028,616 | 8 | 0 / 0 |
| R19 | 524,288 | 15,672,181 | 8 | 0 / 0 |

The inputs are indexed under
`/data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix/`.
The command, input hashes and raw counts are in the trifoliate user journal
under invocation `2fe79fd5aa454c9ba1ca430b1d6578b0` (380.8 MiB peak, 2 GiB
cap, no swap, no board). The scan rules out dangling residual as a source
of divergence for these exact fixtures, not differences in rank values,
correction, convergence, or timing. On other graphs with sinks, G+R's CPU
reference redistributes dangling residual during propagation and this Spine
reference does not; sharing a correction threshold is not enough.

### Remaining Seven Board Pairs

The matrix continuation uses the exact October AU, SU, WK, SO, PK, LJ and
LJ08 inputs. It does not repeat R19, Flickr, or the AU propagation slice.
It waits for the pinned R19/Flickr invocation and replays the raw
same-clock public A4 R controls and isolated G control against the selected
image before starting any child. This qualifies the selected baseline for
those controls, not for arbitrary native ResPR workloads.

Each case has one run per arm, zero timing warmups, and no automatic retry.
The window starts with the uploaded batch on resident state and ends at
final readback, including host orchestration but excluding initial graph
and batch upload. The graph, hardware, and comparator pins are checked;
each arm must pass its own correctness oracle. Propagation rounds and
elapsed milliseconds are kept for both arms. Correction-only cases remain
separate from cases with propagation on both arms.

The coordinator runs with a 1 GiB cap and does not open the board. Children
run serially with their frozen 16, 24, or 32 GiB cap, a 2 GiB high-watermark
margin, zero swap, shared FPGA locks, and a 32 GiB machine reserve. Each
arm has a 30-minute runtime limit after admission. Failed children and
their logs remain in the journal; this is not a figure-data release.

From the simulator checkout, queue while the parent invocation is live:

```bash
checks=/data/chuxiao/checks/source-retention-repair-20261104
parent_service=gr-retention-resident-joint-v3-20261104.service
parent_invocation=$(systemctl --user show "$parent_service" -p InvocationID --value)
systemd-run --user --unit=gr-retention-respr-matrix-v2-20261104 \
  --working-directory="$PWD" -p MemoryMax=1G -p MemoryHigh=768M \
  -p MemorySwapMax=0 -p OOMPolicy=kill -p RuntimeMaxSec=78h \
  python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.respr_matrix \
    --unit "$parent_service" --invocation "$parent_invocation" \
    --parent "$checks/resident-joint-board-v3/results.json" \
    --previous /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix \
    --child-prefix gr-retention-respr-matrix-v2-child-20261104 \
    --output "$checks/respr-matrix-v2"
```

### AU: Correction-Only Versus Propagation

All eight October FPGA rows reported zero propagation rounds on both arms.
Those runs reached the configured threshold, but timed correction and result
publication without subsequent propagation. On the unchanged October AU
input, the two CPU references independently reproduced an empty seed set
and identical per-vertex states. This is not a correctness failure or
evidence about the performance of propagation.

For a larger propagation check than Flickr, the existing AU reciprocal
`insert_bridge_u8` slice was screened once with the same CPU binaries,
128 warm sweeps, damping 0.85 and per-vertex threshold `1e-6`. It is a
different input, not a replacement for the October AU row:

| Input | Vertices | Initial directed edges | Directed inserts | Seeds on each arm | G+R CPU rounds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen October AU | 515,281 | 826,848 | 8 | 0 | 0 |
| AU reciprocal bridge slice | 156,289 | 903,774 | 16 | 12 | 1 |

On both inputs the two CPU probes emitted byte-identical vertex-state TSVs.
Both inputs were sink-free before and after the batch. The AU slice CPU run
used 294 MiB peak (2 GiB cap, zero swap), and did not access a board. It is a
candidate for an additional board propagation check, not an FPGA result.
The scheduled R19/Flickr board screen remains unchanged.

To reproduce the slice input, pass the following files from
`tests/data/askubuntu_reciprocal_full/` to `resident_input`, in order:
`askubuntu_reciprocal_full_e903774.slice` and
`askubuntu_reciprocal_full_e903774_insert_bridge_u8.slice`. Then run the same
two probes and `resident_oracles` as above with vertex count `156289`.
For the October AU check, use the frozen AU graph as-is and vertex count
`515281`. No graph conversion is needed for that input.

| Evidence under `/data/chuxiao/checks/source-retention-repair-20261104/` | SHA-256 |
| --- | --- |
| `au-oracles.5fcctJxV/au-{spine,gr}.tsv` (each) | `df4a6646241db589effa407958523e26998866f2ed85f30051e734020a00c513` |
| `au-slice-u8-oracles.kz5m4cf1/au-slice-u8.graph` | `71a9bb2ae164209ca9a253211ebd0e10935bebb6644d76a21dc64e9848449c59` |
| `au-slice-u8-oracles.kz5m4cf1/{spine,gr}.tsv` (each) | `823db60824011af3fd2b3dde4ca277a2ed040f1d1845156895893b30686de258` |

The AU raw probes and offline TSV check are retained in the user journal
as `gr-retention-respr-au-oracle-20261104.service` and
`gr-retention-respr-au-oracle-replay-20261104.service`; the latter compared
the retained dumps after the former's comparison command ran outside the
checkout. The slice run is `gr-retention-respr-au-slice-u8-oracle-v2-20261104.service`.

## Board Runner

This is a bounded two-case screen, not a figure replacement. It waits for
both supported R controls and the AU G control to meet the 1.15 elapsed
ratio on the **same ResPR image**. Both tail-publication and cached-reader
routes may enter the queue. It uses the first route whose exact artifact
passes, retaining rejected route receipts without running a second Spine
pair. When both receipts become available in the same poll, tail-publication
is checked first; observed speed is not used to rank routes.

Admission recomputes the G and R event envelopes from pinned raw logs and
requires matching driver clocks against each public reference. It requires
matching candidate-image clocks again in the paired run. It records
both arms' driver frequencies and uses observed elapsed milliseconds without
clock normalization. Each arm validates against its own CPU oracle; these
hosts do not emit two arrays for direct cross-host final-rank comparison.

Board admission shares the machine-wide resource reservation and both board
locks with the existing one-shot controls. It reserves an 8 GiB cgroup with
zero swap, protects the 32 GiB machine reserve, and has a six-hour board
admission deadline before either arm can start.
The report records both iteration counts, including any difference.

In the simulator checkout, with an 8 GiB maximum, 7 GiB high watermark,
zero-swap cgroup and 32 GiB live reserve:

```bash
checks=/data/chuxiao/checks/source-retention-repair-20261104
tail=/data/chuxiao/builds/gr-tail-publication-20261104
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_board \
  --route "$tail/route-respr-v2" \
  --r-report "$checks/tail-follow-v1/results.json" \
  --g-report "$checks/g-tail-board-v1/results.json" \
  --gr-host "$tail/native-host-v1/sharded_k4_residual_pagerank_native_host" \
  --frozen-r-board "$checks/before-once/results.json" \
  --alternate /data/chuxiao/builds/gr-directory-spans-20261103/route-respr-cached-v2 \
    "$checks/after-cached-respr-v2/results.json" "$checks/after-cached-respr-v2/g/results.json" \
    /data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/hosts/respr/sharded_k4_residual_pagerank_native_host \
  --spine-host /data/chuxiao/checks/spine-cc-respr-host-20261026/default-hosts-v1/thresholded_residual_pagerank.host \
  --spine-image /data/chuxiao/builds/grasu-cache-extent-20261025/spine-respr-zfs-v1/build/respr/xclbin/spine_partitioned_split_e2e.respr.hw.xclbin \
  --comparator /home/chuxiao/grasu-regraph-sim-aligned/scripts/compare_resident_fpga_logs.py \
  --r19 /data/tmp/chuxiao/fullgraph_fpga_workloads_20260806/r19_residual_pagerank_insert_u8.graph \
  --flickr "$checks/resident-preflight.QnpgS8/flickr.graph" \
  --output "$checks/resident-board-reproduction" --wait-seconds 21600
```

Use a fresh output directory. The report records the exact commands and
whether any board launch was attempted. There are no automatic retries.
It holds both the original matrix lease and the PCI-addressed control lease.
Any non-admitted gate leaves the board untouched; a started run preserves
stdout/stderr even if correctness or clock validation fails. The historical
R19 logs replay at 44.669267 ms for G+R and 32.375100 ms for Spine. That
replay tests the parser; it is not a measurement of the repaired image.

### Additional AU Bridge Board Pair

The AU slice follows the exact R19/Flickr service invocation. It requires
both original pairs to pass correctness and Flickr to report device
propagation on both arms. It independently replays G and R admission for
the *same* G+R image, then uses the same pinned Spine host/image and the
same board lease and eight-GiB cap. Neither original pair is repeated.
The AU board pair itself must report positive propagation on both arms.
A failed gate or zero-round result remains visible in its separate receipt.

From the simulator checkout, in the same zero-swap eight-GiB containment:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.respr_au_follow \
  --unit "$parent_service" --invocation "$parent_invocation" \
  --parent "$checks/resident-joint-board-v3/results.json" \
  --graph "$checks/au-slice-u8-oracles.kz5m4cf1/au-slice-u8.graph" \
  --output "$checks/resident-au-bridge-v2"
```

Enqueue while the declared parent service is live, using a new output
directory. Offline replay below also accepts the separate AU receipt with
the same strict G/R audit. This is an additional screen, not a replacement
for the old AU row or a completed large-graph matrix.

## Offline Acceptance

The joint run writes `resident-joint-board-v3/results.json`. It waits for
the returned tail route's `tail-follow-seele-v1` and `g-tail-seele-v1`
receipts or the separately screened cached route. The previous joint,
AU bridge, and matrix journals were retained with no board attempts.
Before using
its ratios, run the strict same-clock G/R replay in [G_SCOPE.md](G_SCOPE.md)
with the inputs for the report's `selected_route`,
and then replay the saved board screen without rerunning either arm:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.respr_resident_replay \
  --resident "$checks/resident-joint-board-v3/results.json" \
  --strict-stage "$checks/respr-directory-strict-audit.json" \
  --output "$checks/respr-directory-resident-audit.json"
```

This binds the screen to the independently admitted image and host, checks
the one-run commands and driver clocks, and recomputes the paired result
from pinned logs without replacing any raw output. Both ResPR legacy timers
start after batch upload and include algorithm-specific correction through
final readback. They do not measure batch packing or initial graph setup.
R19 remains a correction screen; Flickr must propagate on both arms to
qualify as a propagating screen. Even a pass is not the full Fig. 7 matrix.
