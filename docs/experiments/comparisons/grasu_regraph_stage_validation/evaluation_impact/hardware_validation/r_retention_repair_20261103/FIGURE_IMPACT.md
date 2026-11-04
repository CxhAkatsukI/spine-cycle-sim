# Figure Dependency Audit

## Figure 7 Receipt Export

From the simulator repository, use the current SSSP, CC and ResPR journals
to produce a new evidence snapshot.
Run this offline; it does not launch FPGA jobs or modify existing packages.

```bash
run=/data/chuxiao/checks/source-retention-repair-20261104
snapshot="$run/figure7-receipt-snapshot-$(date -u +%Y%m%dT%H%M%SZ)"
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure7_receipts \
  --sssp-matrix "$run/sssp-burst-matrix-v1/matrix.json" \
  --sssp-au "$run/sssp-burst-resident-au-v1/queue.json" \
  --cc-matrix "$run/cc-singlepass-matrix-physical-v3-final/matrix.json" \
  --respr-matrix "$run/respr-matrix-v6-final/results.json" \
  --respr-screen "$run/resident-joint-board-v8-final/results.json" \
  --output "$snapshot.json" \
  --csv "$snapshot.csv"
```

See [remote builds and board queues](REMOTE_LINKS.md#november-4-physical-retries)
for the pending candidates. Do not substitute a superseded queue when a
current result is pending. The old `sssp-singlepass-matrix-resume-v5/matrix.json`
journal is for diagnostics. Its `RUNNING_SINGLE_PASS` and LJ's `REQUESTED`
are last-written statuses before shutdown. LJ made no board attempt;
LJ08 was not requested. The six measured rows document the old image only:
it missed the AskUbuntu R retention gate.

The current SSSP uses a separate AU screen and the CC matrix includes R19.
`--sssp-au` and `--cc-r19` are used only when the corresponding matrix
does not already contain that case. The export rejects duplicate sources.
The export has eight rows each for SSSP, CC, and ResPR. FullPR is outside
this campaign. The optional CSV keeps all 24 statuses and leaves timings
and ratios blank for pending or failed rows. It does not replace the old
handoff CSV. If a live journal changes during export, rerun rather than
mixing snapshots. Admitted rows bind the original graph file (including
its ordered batch), vertex/edge/update counts, and source ID to the raw
comparison. The JSON carries the full evidence links: original logs,
verified clock receipts, the predeclared images for both arms, wall-time
comparison, and independent G and R ratios.
The `same_driver_clocks` field states whether the arms reported the same
clock configuration; Figure 7 uses measured wall time at those native
clocks, with no frequency rescaling. Independent R retention requires
matched clocks. The export indexes existing correctness/stage admission; it does not rerun
the correctness oracles or establish results for figures 8--11. CC starts
at host pack; SSSP and ResPR start at a resident batch. ResPR rows report
whether both arms performed propagation. The separate JSON field
`respr_propagation_screen` records the compact Flickr control, outside the
24 figure rows. It accepts a speedup only if both arms propagated and the
large-graph matrix pinned that exact screen, G/R admission and image.
Pending or failed screens retain their status without a speedup. Do not
pool these scopes or interpret a correction-only result as propagation
evidence. The two Amazon
R receipts referenced by the SSSP matrix do not supersede the later
[AskUbuntu topology control](SSSP_STAGE_ADMISSION.md#askubuntu-topology-control),
which missed the 15% gate on the same older candidate image. The current
CC and SSSP matrices require a passing AskUbuntu topology control on the
image used for the resident measurements. The export includes its receipt
and ratio alongside the two Amazon controls; older measured SSSP rows
without cross-topology admission are labeled `amazon_only_diagnostic`.

## Figure 7: R-Only Bound On Two New SSSP Pairs

In the pinned [G+R host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/57888d605a19eee2b429a9d6e91d119a1348c9ab/tools/sharded_k4_native_host.cpp),
the timed GraSU update loop completes before launching ReGraph. Its reported
`grasu_ms` is the first update CU start to the last update CU completion,
including gaps between update launches, entirely inside the resident wall
timer. Do not add `barrier_ms` to it: those event windows can overlap.

| Dataset | Measured G event span (ms) | Complete Spine wall time (ms) |
| --- | ---: | ---: |
| R19 | 6.121 | 4.157 |
| PK | 16.497 | 8.306 |

Thus, even setting post-update R time to zero cannot reverse these two
measured comparisons if G's measured path, clock and sequential execution
are unchanged. This is a bound on the new pairs only, not a general
15% result, a bound on a redesigned G path, or validation of the
November 3 handoff. The other four measured SSSP rows do not satisfy
this sufficient condition. The raw `gr.stdout.txt` and pair receipts are
in the [follow-up checkpoint](sssp-resident-followup/README.md).

## November 3 Handoff Dependencies

This audit inspects the [frozen November 3 handoff](../../figure7_11_handoff_20261103/README.md),
not new measurements or an admission decision. A ratio from any of the R controls
cannot be applied as a correction factor to other graphs, algorithms, or
total resident latency. The controls measure a single gather/apply execution;
the Figure 7 comparisons include the actual update and convergence path.

| Figure | What the directory-span repair can affect | Evidence needed before reuse |
| --- | --- | --- |
| 7, SSSP/CC | All 16 timed G+R runs execute the adapter: SSSP has 1--3 supersteps, CC 1--2. | Retest on the admitted algorithm-specific images unless a matched, measured bound establishes the claimed advantage. |
| 7, ResPR | All eight timed G+R runs execute one full correction pipeline. Neither arm takes a later propagation round on these batches. | Retest after R admission; explicitly keep these eight results separate from nonempty propagation. |
| 8 | No R execution in the update-only boundary. Its G configuration is nevertheless older than the cached/replicated hardware G. | Do not rerun because of R alone. To call it a comparison against current G, regenerate or demonstrate equivalence of the G device, host and transfer inputs. It remains one batch, not ten. |
| 9 | It uses simulated G+R and Spine requests. Identical adapter outputs do not establish identical accepted requests, request order, or background HBM energy. The directory alone gives a conditional floor for the direction of the byte comparison. | See the byte floor below. Verify the current implementation's request ledger against the intended simulator profile for new byte ratios and rerun the DRAMSim3 trace for energy. |
| 10/11 | Spine-only stage attribution and a fit to Spine simulator outputs; neither consumes R measurements. | Retain as predictions for the exact frozen Spine model. Re-execute/refit only if a relevant Spine model or workload changes. R admission does not calibrate them. |

### Frozen Figure 7: Zero-Cost R Bound

An offline audit checked all 24 November 3 handoff rows against the original
one-shot FPGA pair receipts and both raw host logs. The pinned G+R source
matches [`bbb08cb`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/bbb08cb).
Its [SSSP/CC host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/bbb08cb/tools/sharded_k4_native_host.cpp#L776-L850)
and [ResPR host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/bbb08cb/tools/sharded_k4_pagerank_native_host.cpp#L528-L570)
finish the timed G update CUs before launching the first R traversal.
Keep the measured G event span and give every other G+R cost, including
all of R, zero time. This bounds what an R-only acceleration can change
if G's measured execution and the Spine arm remain fixed. The host's
`setup_inclusive_ms` is the timed resident window here: initial graph and
property upload finish before the timer starts.

| Frozen case | G event span (ms) | Complete Spine wall (ms) | Minimum G+R / Spine |
| --- | ---: | ---: | ---: |
| SSSP / PK | 15.825373 | 9.60819 | 1.647x |
| SSSP / R19 | 5.548182 | 4.27175 | 1.299x |

Only these two rows satisfy the bound. The other 22 are **undetermined**,
not losses: their G event span alone is below Spine's complete wall time.
This neither preserves the old bar heights nor establishes 15% R parity.
A faster or overlapping G path, a different clock or a different Spine
implementation would require a new comparison. These are the frozen runs,
not the separate newer PK and R19 pairs above.

Replay from the simulator root using the [raw archive](fig7-frozen-r-only-bound-raw.tar.gz)
(`6e0fda2381b273010b1a3f6281ad0082e1c5966356938bbca10594c143f8def1`).
It contains the original 24 JSON receipts and 48 stdout logs, not FPGA
images or graph inputs. The CSV includes hashes of each receipt and raw log and
`remaining_budget_to_tie_ms = Spine wall - G event span`. For a positive
budget, the new R time **plus all other cost not in the G span** must fit
within it for G+R to tie or win. No FPGA job is launched.

```bash
handoff=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_handoff_20261103
archive=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/r_retention_repair_20261103/fig7-frozen-r-only-bound-raw.tar.gz
matrix=$(mktemp -d)
tar -xzf "$archive" -C "$matrix"
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure7_r_only_bound \
  "$handoff/data/fig7_fpga_speedup.csv" "$matrix"
```

## Figures 10 And 11: Frozen Spine Replay Scope

The frozen [`fig10_11_matrix.json`](../../figure7_11_handoff_20261103/provenance/fig10_11_matrix.json)
records 42 commands: 38 call `run_sst_spine_vertical.py` and four call
`run_sst_connected_components.py --architecture spine`. All use `--no-build`
and the same pinned SST plugin directory. They instantiate
`spine_cycle.OnlineMemoryProbe` through `sst/spine_vertical_slice.py`, not
the separate routed ReGraph probe. The shared library can contain both
implementations without the Spine commands exercising the R repair.

Against `6df1481`, 445 of the 459 files listed in the frozen
[`fig10_11_identity.json`](../../figure7_11_handoff_20261103/provenance/fig10_11_identity.json)
match their SHA-256. The 14 differences are seven routed ReGraph
input/admission sources and seven C++ test files. The recorded SST Spine
component and runner sources match. This is a dependency check for the
R repair, not a claim that a newly linked plugin is bit-identical or that
a new Spine FPGA image implements the frozen timing model.

From the repository root, verify the original package without rerunning
its workloads:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.verify \
  --package docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_handoff_20261103 \
  --repository "$PWD"
```

The verifier passed for 11 normalized stage rows and 41 realized-work
rows, including the archived evidence. This establishes package integrity.
Use the plots only as Spine simulator predictions (including the frozen
dense residual-apply mode); the fit compares predictions with simulated
release cycles, not FPGA measurements. Neither the stage shares nor the
fit should be described as newly calibrated against hardware.

## Figure 8: Exact Inputs For A Native G Check

The independent G gate uses AU with 131,072 inserts and measures the
device update event span. It cannot stand in for Figure 8: the latter uses
AU at 64, 512, and 4,096 updates and SU/WK/SO/PK at 512, and includes
preparation and upload. Its frozen arm table records the row counts and the
case directory; `config.json` in that directory names the two raw slices.
For example, prepare the exact AU 512-update row from the simulator checkout:

```bash
input=/data/tmp/chuxiao/large_graph_campaign_v1/workloads/sx_askubuntu
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure8_inputs \
  "$input/graphs/directed_weighted.slice" \
  "$input/updates/directed/insert_u512.slice" \
  /tmp/au_fig8_u512.graph --vertices 515281 --edges 390847 --batch-size 512
```

The converter keeps IDs, weights, record order and operation; it does not
remap vertices or sample edges. After converting the seven cases, verify
the native files against both original arms before measuring:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure8_manifest \
  /path/to/figure7_11_handoff_20261103/data/fig8_arms.csv \
  /path/to/native-graphs /path/to/native-graphs/identity.json
```

The command checks that both arms used the same source inputs, reproduces
the expected native content from the original slices, and records content
identities for all seven pairs. It does not allocate a board or time a host.
All seven historical cases passed; see the
[input identity receipt](fig8-native-input-identity.json). On AU
512 the current candidate host's CPU preflight accepted 390,847 old edges,
512 physical inserts and eight shards. The native AU 512 file has SHA-256
`092a84ab17b564cab854875e544f420635fe63cca5056e10c3842be912501e70`.
Conversion is offline input preparation, not a timed operation. A native
`--update-only` board run can validate
the actual G update and report its device events, but cannot on its own
replace the setup-inclusive panel. The frozen panel uses a different
host/layout implementation and modeled upload, while the current native
host's `--prepare-only` command also runs convergence oracles that do not
belong in an update-only setup timer. For a measured replacement, time
layout construction, batch preparation, initial/batch upload, and update
through completion on both arms under the same exclusions. Keep the
device-only evidence separately labeled.

The [candidate native G host](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/81cbe8f)
adds a separate `--update-setup-once` mode for the sharded SSSP/CC host.
It emits layout/packing, initial/batch upload, and update-through-barrier
wall times, and checks PMA contents after the timed window. CPU preflight
checked the one-batch and board-lease guards and preserved the AU 512
prepare-only output. This is build and preflight evidence only.

The [Spine native host](https://github.com/jayfeather9/spine-dynamic-graph/commit/fb1ed35)
now times graph layout, buffer setup and upload, batch packing and upload,
and the maintenance launch through completion. One AU 512 insertion run on
U55C (`0000:c1:00.1`, 150 MHz data clock) recorded 2.008968934 s for that
sum, including 0.459553 ms for maintenance launch through completion. The
device readback exactly matched all 391,359 expected weighted edges outside
the timer. The raw receipt on trifoliate is
`/data/chuxiao/checks/source-retention-repair-20261104/fig8-spine-au512-board-v1/results.json`.
The matching AU 512 G run is queued by
`source_retention.figure8_au_pair`. It replays the independent G gate on
the returned SSSP image, reuses the checked Spine run, and runs G once
on the same card and primary clock. It records a ratio only after G's
PMA readback and the disjoint setup and update timers validate. Its
receipt is `fig8-au512-pair-return-v2/results.json` under the same check
root. The first waiting task (`v1`) was retired before any G board launch
after a missing algorithm argument was identified in the gate replay.

After AU/512 is measured and its raw receipts replay, run
`source_retention.figure8_matrix` with `--manifest` pointing to
[`fig8-native-input-identity.json`](fig8-native-input-identity.json),
`--manifest-sha256 520b7bc64eb16cd7e8f4cee50179aa8ba8ca71b27771111b0a4e303187d82012`,
`--anchor` pointing to the v2 result, and `--output` pointing to a new directory.
For an unattended continuation, add `--wait-for-anchor UNIT INVOCATION`
and optionally `--anchor-wait-seconds`. The waiting process does not acquire
a board lease or reserve experiment memory. If the predecessor fails, changes
invocation, or does not produce a valid pair receipt, no continuation sample
starts.
Use a dedicated cgroup (`MemoryMax=24G`, `MemoryHigh=22G`, `MemorySwapMax=0`,
`OOMPolicy=kill`), or `--memory-gib 40` with 40/36 GiB caps if the workload
requires it. The runner also checks live memory reserve and board availability.
It reuses AU/512 and makes at most one attempt per arm for each remaining
case. It preserves missing or invalid results without a ratio and records
setup speedups separately from device maintenance. Do not mix native arms
with the older maintenance-only or modeled-setup results.

The first continuation stopped before Spine timing because the child was
not given the device index. The corrected 24 GiB continuation
(`gr-retention-fig8-native-matrix-return-20261104-v2.service`, invocation
`266a90fb8ace4bf6ae5faa25229fa52b`) retained six valid pairs including
the reused AU/512 anchor. The SO/512 G arm failed before measurement
because replicated metadata did not fit the lane-aware HBM placement.
See the [paired board checkpoint](paired-board-checkpoint/README.md) for
the data and raw logs. The service's recorded peak was 13,110,181,888 bytes.

### AU/64 Spine Host Revision

Spine [host revision `e4054b8`](https://github.com/jayfeather9/spine-dynamic-graph/commit/e4054b8)
reserves graph serialization storage once per bank, transfers ownership of
the cold image, and skips the unused host frontier allocation in update-only
mode. The xclbin, device buffer extent, timer, workload, and exact graph
readback check are unchanged. Off-board AU/64 and SU/512 checks matched
the old graph and metadata fingerprints and checked all initial edges.

| AU/64, setup-inclusive | Old Spine | Revised Spine | Frozen G |
|---|---:|---:|---:|
| Host graph layout (ms) | 1,033.510 | 461.018 | 587.554 |
| Initialization/upload (ms) | 893.373 | 913.697 | 222.978 |
| Total (ms) | 1,927.194 | 1,375.165 | 818.456 |

This was one new Spine timing on the same U55C and image/clocks, with the
previously checked four-copy G sample reused. All 390,911 final weighted
edges matched; there was no memory throttling or OOM. Spine setup latency
dropped by 28.6%, but G remains 1.68x faster on this case. The remaining
Spine cost is in initialization/upload; the revision does not establish
a ten-batch speedup or change the resident-convergence Figure 7 results.
The [new raw archive](paired-board-checkpoint/fig8-au64-spine-host-revision.tar.gz)
contains the one-shot receipt, stdout/stderr, clocks, image metadata, and
both off-board fingerprints. The [original paired checkpoint](paired-board-checkpoint/README.md)
retains the old Spine and G logs.

The [next host revision `67e8df1`](https://github.com/jayfeather9/spine-dynamic-graph/commit/67e8df1)
populates the existing device directory image directly instead of creating
and copying a second dense directory on the host. The new path is limited
to the one-shot update benchmark. The off-board directory test matched
the old directory word for word across cold/hot rows, levels, lanes, and
pages, and the resident benchmark driver test passed separately.

| AU/64, single measured Spine run | Time (ms) |
|---|---:|
| Host graph layout | 462.552 |
| Bootstrap host buffer and metadata preparation | 633.207 |
| Bootstrap XRT migration | 214.871 |
| Bootstrap lifecycle call | 4.738 |
| Batch preparation | 0.177 |
| Update call | 0.311 |
| Total | 1,315.856 |

The bootstrap subphases sum to 852.816 ms. The same U55C, xclbin, clocks,
CPU affinity, input and timer were used; the frozen G arm was not repeated.
All 390,911 final weighted edges matched. The board run peaked at
2,290,442,240 bytes with zero memory high, max, or OOM events. Relative to
the first host revision, the observed total dropped by 59.309 ms (4.3%);
the frozen 818.456 ms G result is still 1.61x faster. These are individual
runs, not an estimate of repeat-to-repeat variation. The remaining gap is
497.400 ms and is not a kernel-update gap. The November 3 Figure 8 handoff
also used one batch, but modeled upload and launch and timed different
host layouts. This check does not replace that panel or establish a
resident ten-batch result.
The [raw revision archive](paired-board-checkpoint/fig8-au64-spine-bootstrap-v4.tar.gz)
contains the timing breakdown, device and input receipts, and directory test
log. Its SHA-256 is
`f0a50534397b003a4e06c70e38ccad1d4ac8765bcff28f8cf29cb3decf3a253e`.

The [aligned graph host revision `e1ddff2`](https://github.com/jayfeather9/spine-dynamic-graph/commit/e1ddff2)
serializes each graph bank directly into page-aligned host memory and
transfers ownership to the XRT runtime instead of copying it again.
The off-board driver test checked exact graph bytes, metadata, and alignment;
the resident benchmark still uses its existing graph staging path.
The one new AU/64 measurement used the same graph, card, clocks, image,
CPU affinity and timing boundary, and reused the same checked G arm.

| AU/64, single measured Spine run | Time (ms) |
|---|---:|
| Host graph layout | 472.019 |
| Bootstrap host buffer and metadata preparation | 438.593 |
| Bootstrap XRT migration | 94.765 |
| Bootstrap lifecycle call | 4.681 |
| Batch preparation | 0.057 |
| Update call | 0.235 |
| Total | 1,010.350 |

All 390,911 weighted edges passed the final readback. Peak process-group
memory was 1,870,712,832 bytes with no high, max, or OOM events. The
observed total decreased by 305.506 ms versus the preceding host run
(23.2%); the time change cannot all be assigned to the removed copy from
one sample. G still took 818.456 ms and was 1.23x faster in this one-shot
setup window. See the [raw board archive](paired-board-checkpoint/fig8-au64-spine-aligned-v5.tar.gz)
with SHA-256
`9be926d749cd3416599128f5c5391d57aafa31e4e039ce97a5f5d9244211e91f`.

The next Spine host revision (`e6e26fc`) builds the directory and sets
its publication flag directly in the aligned metadata buffer used by
XRT, removing the extra staging copy. The host and off-board driver
test built under a 6 GiB cap (1.2 GiB peak), and the driver test passed.
The FPGA image, input, clocks, oracle, and timing window were unchanged;
only the changed Spine arm ran, once. It passed the check of all 390,911
weighted edges.

| Metric | Aligned graph banks (ms) | Aligned metadata too (ms) |
| --- | ---: | ---: |
| Graph layout | 472.019 | 472.817 |
| Bootstrap host | 438.593 | 341.344 |
| Bootstrap migration | 94.765 | 92.132 |
| Bootstrap lifecycle | 4.681 | 4.662 |
| Batch preparation | 0.057 | 0.061 |
| Update wall | 0.235 | 0.240 |
| Setup-inclusive total | 1010.350 | 911.256 |

The frozen G measurement was 818.456 ms, still 1.11x faster in this
one-shot window. The 99.094 ms decrease is an observation from two
single runs, not an estimate of run-to-run variation. Peak cgroup memory
was 1,710,845,952 bytes with zero high, max, or OOM events. The
[raw board archive](paired-board-checkpoint/fig8-au64-spine-meta-v6.tar.gz)
has SHA-256
`05e2a0caa7fd3d417eb240c26e3e028dd353aa98caa46921fe90d1a194e9715b`.

The [next host revision `aa0af47`](https://github.com/jayfeather9/spine-dynamic-graph/commit/aa0af47)
reuses the cold directory instead of allocating a second directory and
copying slice records, epochs and page lists into it. The cold graph image
and all metadata words passed a byte comparison; the host driver and the
full partitioned CSR model tests also passed. The board rerun changed only
the Spine host binary and checked all 390,911 final weighted edges.

| Metric | Aligned metadata (ms) | Reused cold directory (ms) |
| --- | ---: | ---: |
| Graph layout | 472.817 | 366.647 |
| Bootstrap host | 341.344 | 341.682 |
| Bootstrap migration | 92.132 | 83.260 |
| Bootstrap lifecycle | 4.662 | 4.623 |
| Batch preparation | 0.061 | 0.061 |
| Update wall | 0.240 | 0.221 |
| Setup-inclusive total | 911.256 | 796.494 |

The unchanged G arm took 818.456 ms. Spine was 1.028x faster on this
single AU/64 pair, a 21.963 ms lead with no estimate of run-to-run
variation. This is a one-batch, setup-inclusive check, not the resident
throughput panel or evidence for other datasets. Peak cgroup memory was
1,711,144,960 bytes with no high, max or OOM events. The
[raw board archive](paired-board-checkpoint/fig8-au64-spine-cold-v7.tar.gz)
has SHA-256
`08fe266388fb313ac2f728a527a7dcf28ddfbdaea5937bc109fc49c3350d21e3`.

The same Spine binary was screened once on each remaining row with an
admitted four-copy G measurement. The continuation reused each frozen G
arm after checking its input, clocks, timings and PMA oracle; AU/512 uses
the separately verified anchor. All six Spine readbacks passed. Neither
side was repeated to estimate measurement variation.

| Input | Updates | G (ms) | Spine (ms) | G / Spine |
| --- | ---: | ---: | ---: | ---: |
| AU | 64 | 818.456 | 796.494 | 1.028x |
| AU | 512 | 975.557 | 780.264 | 1.250x |
| AU | 4,096 | 770.908 | 847.809 | 0.909x |
| SU | 512 | 992.363 | 876.150 | 1.133x |
| WK | 512 | 1,872.880 | 965.586 | 1.940x |
| PK | 512 | 37,380.861 | 15,702.802 | 2.381x |

G still leads AU/4096 by 76.901 ms: only 2.411 ms of Spine's
847.809 ms was the update call. SO/512 is not in this table because
the four-copy G configuration has no paired timing. This is a check
of the exact native one-batch SSSP inputs, not a replacement for all
Figure 8 data or a new R retention result. Peak cgroup memory across
the added runs was 9,175,027,712 bytes (PK); all runs reported zero high,
max or OOM events. The [five additional board records](paired-board-checkpoint/fig8-spine-cold-matrix-v7.tar.gz)
have SHA-256
`f7ef8ac946e6a7aeda2a427560611ff378b4c1c869d65fed95d0983e73524bc9`.

### Latest Spine Host: Direct Metadata Ownership

[Host revision `475edca`](https://github.com/jayfeather9/spine-dynamic-graph/commit/475edca)
serializes metadata into a page-aligned vector and passes its ownership
to the runtime. The off-board test passed byte and alignment checks.
AU/4096 bootstrap host time fell from 386.444 to 267.299 ms in the two
single runs; the previous revision's 76.901 ms deficit became a
31.112 ms lead. This comparison does not estimate timing variation.

| Input | Updates | Frozen G (ms) | Latest Spine (ms) | G / Spine |
| --- | ---: | ---: | ---: | ---: |
| AU | 64 | 818.456 | 748.727 | 1.093x |
| AU | 512 | 975.557 | 739.572 | 1.319x |
| AU | 4,096 | 770.908 | 739.797 | 1.042x |
| SU | 512 | 992.363 | 789.324 | 1.257x |
| WK | 512 | 1,872.880 | 908.332 | 2.062x |
| PK | 512 | 37,380.861 | 15,584.863 | 2.399x |

All six rows use the same new Spine host, the same images and clocks as
their frozen pairs, and one new Spine run each. All graph oracles passed.
There were no memory high, max or OOM events; peak was 9,166,168,064 bytes.
This is the latest native setup-inclusive SSSP checkpoint. It does not
admit SO/512 or the CC/ResPR baseline. The [raw board archive](paired-board-checkpoint/fig8-spine-dma-matrix-v8.tar.gz)
includes the input and host digests, clocks, breakdowns and correctness
records. Its SHA-256 is
`e70ece19a42f6f255093c44d76835841b2c6e73ea311ac874ed339813a358103`.

### SO/512 Metadata Capacity

The board log fails in the host placement planner, before a timed G update.
The pinned SO native file has 6,024,271 vertices and 512 insertions in 86 of
its 92 destination shards. The existing layout allocates a dense
`(vertices + 1) * 8`-byte row directory per copy, rounded up to 4 KiB
(48,197,632 bytes here). It duplicates the row and binary-search tables
for all four search lanes on each updated shard.

Even if the planner dropped every copy for an idle lane, 86, 75, 66 and
58 updated shards still have work on lanes 0 through 3, respectively.
These 285 active copies alone need 13,736,325,120 bytes (12.79 GiB).
The full graph placement has only 23 * 512 MiB = 11.5 GiB, before
allocating the PMA, binary tables or directories for untouched shards.
Reordering the allocation or skipping idle lanes cannot fix this case
while retaining dense per-active-lane row copies. It is a capacity
result for this policy, not a measured update slowdown or a constraint
on the separate eight-insert Fig. 7 workload.

To reproduce the active-copy count from the pinned SO input, pass its
native graph path as `$graph`. The input identity and the offline G
probe establish that each frozen insertion is one physical insertion.
The host assigns the physical updates within each destination shard
round-robin to four lanes.

```bash
tail -n 512 "$graph" | awk '
    { n[int($2 / 65536)]++ }
    END {
        for (shard in n)
            for (lane = 0; lane < 4; lane++)
                active[lane] += (n[shard] > lane)
        for (lane = 0; lane < 4; lane++) print lane, active[lane]
    }'
```

A one-copy shared directory **did** fit. With the same host, graph and
bitstream, the offline preparation reported 6,240,301,056 allocated
bytes across 23 graph channels, with a maximum of 327,008,256 bytes in
any one channel. The offline run did not program a card.

The follow-up used one timed G run, no warmup, and replayed the existing
correct Spine measurement without running it again. PMA readback passed
with zero mismatches across 7,856 words from 491 touched segments. The
setup-inclusive totals were **67.237386044 s for G** and **6.031149426 s
for Spine** (11.15x in favor of Spine). G spent 64.145107256 s in host
layout, 3.039428828 s uploading, and 0.052849960 s in update wall time.
The timed G cgroup peaked at 19,302,576,128 bytes with no throttling or
OOM events. This is a **capacity diagnostic only**: it does not fill the
four-copy matrix, reproduce the ten-batch figure, or validate the
one-copy policy against the public G stage. The
[receipt](so512-single-directory-diagnostic.json) and
[raw logs](so512-single-directory-raw.tar.gz) preserve both arms and the
original four-copy capacity error.

### Offline Spine Layout Check

The source probe
[`spine_update_setup_layout.cpp`](../../../../../../../cpp/tests/publication_sources/source_retention/spine_update_setup_layout.cpp)
invokes the weighted host's input parser and initial layout builders from
`fb1ed352c9378e7870093050b7a89859bf7b23f7` without constructing an XRT
runtime. To build it, use the pinned host compile command from
`fig8-spine-host-v2/weighted_sssp.compile.log` under the check root. Replace
the main source path with the probe path and write to a new executable.
Run the probe with the native input paths from the manifest.

The six unmeasured cases passed an exact comparison of the serialized
initial image against the old weighted edges: AU/64 and AU/4096 had 390,847
each, SU 616,118, WK 1,142,352, SO 23,724,166, and PK 44,603,928. They ran
sequentially in one CPU-only service (12 GiB hard limit, 10 GiB high,
zero swap, 9.1 GiB peak). Its output is
`fig8-spine-layout-preflight-v1/layout.log` under the check root, SHA-256
`b23fdc79a99071aec67ed389dbe8c7741e9c71faac47a8fa1c4f79c830fab37a`.
This does not check update execution, device allocation or timing.

### Offline G Layout Check

The [G layout probe](../../../../../../../cpp/tests/publication_sources/source_retention/gr_update_setup_layout.cpp)
uses the parser, sharded PMA builder, replicated metadata plan and buffer
packer from the pinned [G host at `81cbe8f`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/81cbe8f).
Compile it with the native SSSP host's flags (`--pipeline-mode sharded-k4
--prefetch-compact` in `scripts/build_weighted_pma_native_host.sh`), adding
the host checkout's `tools/` include path and substituting the probe for the
host source. Run the resulting probe once per native graph. It does not
program a device or execute updates.

All six continuation inputs matched the frozen manifest hashes, vertex and
old-edge counts, and logical update counts. Each logical insertion mapped
to one physical insertion. SO used the largest planned allocation (5.81
GiB of graph buffers, with the busiest channel at 312 of 512 MiB); PK had
the most edges (44,603,928, across 25 shards). The sequential CPU-only run
peaked at 11.8 GiB (20 GiB cap, 18 GiB high, zero swap). The raw `layout.log`
is in `fig8-g-layout.EKkfFdtw/` under the same check root, SHA-256
`25d893a7edc5926f0b5245f9357550f800ba4e48ee7a28757d53cc556b66e416`,
service invocation `54bd5ce654ea49b2a4b7e69d8ba5f828`. These checks do not
bound the full board host's peak after XRT buffer allocation and readback;
keep the live board memory guard and require the final PMA readback check.

## Figure 9: One-Shard Directory Byte Floor

For the same nine inputs, keep the frozen Spine read/write ledger fixed and
substitute the directory-span G+R design. If a resident run completes at
least one traversal with the same vertex domain, the revised adapter reads
at least `64 * ceil(V / 8)` HBM bytes: the directory of just one nonempty
shard. The [native SSSP/CC host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/tools/sharded_k4_native_host.cpp#L883-L907)
and [ResPR host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/tools/sharded_k4_pagerank_native_host.cpp#L749-L773)
pass the full vertex count to each shard. The
[directory reader](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/kernels/pma_prefetch_compact/readers.hpp#L15-L48)
reads all `ceil(V / 8)` 512-bit words for a nonempty extent. Its empty-extent
early return cannot apply to every shard of these nonempty graphs. The
[span join](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/kernels/pma_prefetch_compact/join.hpp#L43-L78)
does not remove those directory reads. ResPR round-zero correction counts
as a traversal even when no later propagation round is needed.

| Algorithm | Dataset | One G+R shard directory, B | Frozen Spine total, B | G+R / Spine floor |
| --- | --- | ---: | ---: | ---: |
| Weighted SSSP | AU | 4,122,304 | 25,640 | 160.78x |
| Weighted SSSP | SU | 4,538,560 | 23,780 | 190.86x |
| Weighted SSSP | WK | 9,121,216 | 33,512 | 272.18x |
| CC | AU | 4,122,304 | 43,552 | 94.65x |
| CC | SU | 4,538,560 | 25,752 | 176.24x |
| CC | WK | 9,121,216 | 59,564 | 153.13x |
| ResPR | AU | 4,122,304 | 14,672 | 280.96x |
| ResPR | SU | 4,538,560 | 12,996 | 349.23x |
| ResPR | WK | 9,121,216 | 24,580 | 371.08x |

This counts no other G+R reads, writes, shards or rounds. It establishes the
direction of Fig. 9(a) for this adapter change with the frozen denominator;
it is neither a measured FPGA traffic counter nor a replacement bar height.
It does not cover a change to the Spine ledger, an adapter that avoids the
dense row directory, or an execution with no R traversal. It gives no
corresponding ratio for Fig. 9(b): command order, activation, and background
energy can all change independently of this byte floor.

To reproduce, from the November 3 handoff directory:

```bash
awk -F, 'NR>1 && $6=="spine" {
  gr=int(($7+7)/8)*64; spine=$12+$13;
  printf "%s %s %d %d %.2f\n", $2,$1,gr,spine,gr/spine
}' data/fig9_arms.csv
```

### Dense Directory Simulator Diagnostic

The frozen finite compact reader can stop issuing directory requests after
consuming its last live PMA segment. The span-reader HLS consumes the whole
directory for a nonempty physical extent. The optional simulator switch
`--gr-drain-directory` keeps requesting and consuming directory tiles through
the end of the vertex domain. It retains the existing DRAMSim3 backend and
does not change the G or Spine model. It matches this HLS byte rule when the
same nonzero physical extents are presented. It does not reproduce the HLS
descriptor FIFO schedule or change the simulator's synthetic nonzero extent
for an empty logical shard. Leave the switch off to replay the frozen model.

With 2,051 vertices and the last live source at vertex 0, the throttled core
test sees 256 -> 514 directory beats with one tile and 512 -> 514 with two
tiles. The 514 beats are two invocations of `ceil(2051 / 8)` 64-byte reads.
All additional beats are directory reads; edge packets, slot reads and the
SSSP oracle result are unchanged, including under reversed registration.

One bounded AU weighted-SSSP run used the original eight inserts and compared
each simulator arm once. Both matched the independent expected state bit for
bit. G+R logged 16 extent beats and 1,030,576 directory beats
(`16 * ceil(515281 / 8)`), or 65,956,864 directory bytes, plus 242,258 slot
beats. These are diagnostics, not FPGA traffic counters or revised bars.

| AU weighted SSSP, simulator | Frozen run | Dense-directory diagnostic |
| --- | ---: | ---: |
| G+R accepted bytes | 131,533,104 | 131,533,104 |
| Spine accepted bytes | 25,640 | 25,640 |
| G+R / Spine accepted bytes | 5,130.00x | 5,130.00x |
| G+R / Spine DRAMSim3 HBM energy | 21.344389x | 21.344385x |

The two runs used different source snapshots. The tiny energy difference is
not isolated to the switch; the identical accepted totals and full-directory
ledger show that the frozen byte total for this one row was not changed by
charging the directory tail in the diagnostic. This is not an equivalence
test of the nine rows or the new native G+R image. `baseline_admitted` stays
false; use a matched current traffic model before replacing the panel.

On trifoliate the raw receipt is
`/data/chuxiao/checks/source-retention-repair-20261104/fig9-directory-au-sssp-v2/results.json`
(SHA-256 `c20287c200d8b14832b552fa443b9a88c55f461e992ea895f5eda5392ee67f3a`).
Its adjacent `sources.tar.gz` pins the diagnostic source snapshot based on
`bf6ae13` with the switch applied. The frozen AU row is in
`/data/chuxiao/experiments/figure9_multialgorithm_20261023/matrix-v5/results.json`
at `91c85cbe`. To reproduce with a fresh output directory, run the
`spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm.study`
module with `--datasets AU --algorithms SSSP --gr-drain-directory`, a configured
Release core, an allowed CPU, and the fresh profile (6 GiB hard, 5 GiB high,
zero swap, group OOM kill and 24 GiB host reserve).

### Nine-Case Directory Impact

All nine pairs ran once per arm and passed the state oracle and ledger
checks. The old, final and expected state hashes match the respective
frozen arm in all nine cases. ResPR uses the frozen fixed `1e-6` threshold,
not the historical vertex-normalized threshold. Ratios below are G+R /
Spine; energy is the same DRAMSim3 HBM estimate, including background and
refresh.

| Algorithm | Dataset | Frozen bytes ratio | Directory diagnostic | Frozen energy ratio | Directory diagnostic |
| --- | --- | ---: | ---: | ---: | ---: |
| SSSP | AU | 5,130.00 | 5,130.00 | 21.34 | 21.34 |
| SSSP | SU | 6,916.25 | 6,916.25 | 28.14 | 28.14 |
| SSSP | WK | 1,265.31 | 5,922.99 | 18.78 | 45.33 |
| CC | AU | 1,695.61 | 1,695.61 | 9.79 | 9.79 |
| CC | SU | 3,587.30 | 3,587.30 | 13.71 | 13.71 |
| CC | WK | 1,854.29 | 7,065.34 | 19.98 | 53.01 |
| ResPR | AU | 7,375.10 | 7,375.10 | 105.44 | 105.44 |
| ResPR | SU | 9,830.78 | 9,830.78 | 143.29 | 143.29 |
| ResPR | WK | 9,349.88 | 12,278.17 | 142.99 | 200.84 |

On WK/SSSP, turning off the switch at the same commit reproduced the
frozen bytes and energy ratios exactly. Turning it back on changed G+R
accepted bytes from 42,402,972 to 198,491,164 (2,565,342 directory beats
after the correction); Spine stayed at 33,512 bytes. This isolates the
switch effect for WK/SSSP. The table compares snapshots for the other
rows. The directory correction does not reverse the traffic or modeled
energy conclusion, but the three old WK bar heights should not be reused
for the dense-directory model. It does not admit the current FPGA baseline
or certify its exact traffic. Every row remains `PREDICTION_ONLY` with
`baseline_admitted=false`.

The [diagnostic CSV](fig9-directory-diagnostic.csv) contains the absolute
accepted bytes and DRAMSim3 energy of both arms, the unrounded ratios,
and the graph, update and receipt hashes for all nine rows. It is a
diagnostic export, separate from the figure handoff. To regenerate it
on trifoliate without rerunning the simulator:

```bash
python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure9_directory_receipts \
  --frozen /data/chuxiao/experiments \
  --directory /data/chuxiao/checks/source-retention-repair-20261104 \
  --output /tmp/fig9-directory-diagnostic.csv
```

The export checks the archived receipts against their pinned hashes and
rejects changed inputs, different state hashes, duplicate or missing
cases, failed ledgers, and ratios inconsistent with the per-arm totals.

Additional raw receipts are under the same trifoliate check root. They pin
simulator commit `95fb905`, the build inputs, memory configuration and the
graph and batch identities:

| Receipt | SHA-256 |
| --- | --- |
| `fig9-directory-sssp-remaining-v1/results.json` | `a9910cfa451a47bff6da2536f7a805bcb9a2acf1913004d42d83b5ded4e70f23` |
| `fig9-directory-cc-remaining-v1/results.json` | `133c0dca01a331cbe16df098d264a122f679b0de442ce767f626a821cbdc00bd` |
| `fig9-directory-respr-remaining-v1/results.json` | `6386dbf87d601f3ab44edf72b015be3bd76197a9277a83c3482d531cd39f0186` |
| `fig9-directory-wk-sssp-off-v1/results.json` | `0e0b1f21671b37f0437cedbc60835db504b15209f6f3f4496601c1646892a63c` |

The frozen ResPR source is
`/data/chuxiao/experiments/respr_fixed_epsilon_20261023/matrix/results.json`.
Use the AU reproduction command above with the corresponding algorithm and
dataset lists; omit `--gr-drain-directory` only for the WK/SSSP off control.

### Source-Property Burst Scope

The Figure 9 routed simulator already requests one 16 KiB block of source
state at a time. Its AXI model splits each aligned block into sixteen
16-beat bursts. The source-service test checks the burst count, issued and
completed beats, and exact payload under finite backpressure. This is the
burst shape now synthesized by the
[SSSP source-property retry](SSSP_STAGE_ADMISSION.md#source-property-read-burst-repair).
The earlier SSSP wrapper instead issued single-beat reads for the same
block. Do not add a second block/burst speedup to the simulator to account
for the HLS repair.

These facts cover the request shape, not which blocks each complete
execution reads, their issue times, or channel and controller occupancy.
Equal bytes are not evidence of equal DRAMSim3 energy. The directory
diagnostic stays a simulator prediction; actual clocks, scheduling, and
G+R performance retention must be checked separately on the returned image.

## Figure 7: The Smallest Observed Margins

Holding the old Spine wall time fixed, the break-even reduction of the old
G+R wall is `1 - T_spine / T_gr`. This is a sensitivity calculation, not a
prediction of the repair's effect. All values below are from one measured
run per arm in the old matrix.

| Algorithm | Dataset | Old G+R ms | Old Spine ms | G+R wall reduction to tie |
| --- | --- | ---: | ---: | ---: |
| Weighted SSSP | AU | 18.418303 | 5.694790 | 69.08% |
| CC | AU | 11.919385 | 3.316460 | 72.18% |
| ResPR | R19 | 44.669267 | 32.375100 | 27.52% |

In particular, the R19 ResPR win could disappear with a 27.52% reduction in
the old G+R wall alone. Passing the 15% R retention gate cannot establish
that the **improvement relative to the old G+R** is smaller than 27.52%.
The two denominators differ. Do not sum the old per-CU adapter/gather/apply
times to estimate a removable fraction: those events overlap across CUs.

### Sensitivity To Removing All R Time

In the 24 old runs, the logged G update event time alone exceeds the matched
Spine wall time in two cases. For this counterfactual, freeze the measured
G update duration and the measured Spine wall time; set every other G+R
cost to zero, including R, host work and readback. This yields an optimistic
G+R latency floor, not a prediction of the new image's G timings.

| Algorithm | Dataset | Frozen G update ms | Frozen Spine wall ms | Floor / Spine |
| --- | --- | ---: | ---: | ---: |
| Weighted SSSP | PK | 15.825373 | 9.608190 | 1.65x |
| Weighted SSSP | R19 | 5.548182 | 4.271750 | 1.30x |

The other 22 runs remain undecided by this test, including every CC and
ResPR row. For example, R19 ResPR has 4.524463 ms of G update events versus
32.375100 ms of Spine wall time. None of these rows is admitted for the
repaired image by this calculation. Relinking changes placement, and keeping
the G XOs unchanged does not guarantee unchanged elapsed time on the board.

The integrated [ResPR host](https://github.com/CxhAkatsukI/grasu-regraph-integration/blob/24519a6/tools/sharded_k4_pagerank_native_host.cpp#L699)
uses round zero for correction and enqueues the adapter, gather and mux for
every destination shard before checking the active count. The old G+R hardware
logs record `pipeline_executions=1 propagation_rounds=0` in all eight cases;
the corresponding Spine logs record `iterations=0` with host correction
inside the resident timer. These are sparse update-and-correction results.
They neither establish an advantage for nonempty propagation nor imply that
R was idle. The separate [Flickr screen](RESIDENT_SCREEN.md) is for a batch
with nonempty thresholded propagation.

## Reproduce From The Old Raw Logs

Use the raw FPGA archive indexed by the frozen handoff, or the matching
original matrix on trifoliate:

```bash
matrix=/data/chuxiao/checks/grasu-replicated-host-singlepass-20261026-v1/matrix
rg '^RESIDUAL_PR_PMA_NATIVE_SHARDED_RESULT ' "$matrix"/respr-*/sample-1/gr/run.log
rg '^SPINE_RESIDENT_BENCHMARK_PASS ' "$matrix"/respr-*/sample-1/spine.stdout.txt
jq -s -r 'map({case:(.config.graph|split("/")[-1]),summary})
  | group_by(.summary.algorithm)[] | min_by(.summary.speedup_gr_over_spine)
  | [.summary.algorithm,.case,.summary.gr_wall_ms,.summary.spine_wall_ms,
     (100*(1-.summary.spine_wall_ms/.summary.gr_wall_ms))] | @tsv' \
  "$matrix"/{sssp,cc,respr}-*/results.json
```

To reproduce the G-only floor, join each single-pass `results.json` to its
`sample-1/gr/run.log`. Use `grasu_ms` from the weighted/CC timing line and
`update_ms` from the ResPR timing line, divided by
`summary.spine_wall_ms`. Keep only ratios above one. Do not include
`barrier_ms` or sum individual CU event times: they can overlap.

Revisit these decisions after the hardware controls complete. In particular,
do not merge a corrected R control with the old matrix and label the result
as newly measured end to end.
