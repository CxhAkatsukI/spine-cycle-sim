# Sparse Residual Apply Follow-Up

## Result And Scope

This simulator-only follow-up addresses Spine's full-vertex Apply overhead on
the same three nonempty ResPR inputs as the frozen
[preceding study](../respr_propagation/README.md). It changes neither G+R nor
the activation threshold. The dense default and preceding evidence remain
unchanged. No paper, HLS source, FPGA build, or board measurement is changed.

| Case | Dense Spine cycles | Sparse Spine cycles | Unchanged G+R cycles | Dense G+R/Spine | Sparse G+R/Spine |
| --- | ---: | ---: | ---: | ---: | ---: |
| Flickr (FL) | 918,281 | 807,557 | 508,412 | 0.554 | 0.630 |
| AskUbuntu 540K | 833,591 | 46,908 | 542,821 | 0.651 | 11.572 |
| AskUbuntu 904K | 678,526 | 30,976 | 466,792 | 0.688 | 15.069 |

Ratios above one favor Spine. The optimization reduces Spine time by factors
of 1.14 / 17.77 / 21.90, respectively. It recovers a latency advantage on the
two sparsely propagating AU slices, **not on Flickr**. These compact inputs do
not establish a full-graph or universal ResPR advantage.

## What Changed

The previous ResPR Apply phase visited every vertex each round even when few
vertices received a contribution. The opt-in `dirty-bitmap` candidate marks
destinations on completed edge reductions and, when dangling share is exactly
zero, applies only those marked destinations. A nonzero dangling share still
requires dense Apply across all vertices, including tiles absent from the
edge stream. Signed contribution cancellation cannot remove a marked vertex.

The selector uses at most **8 KiB** for one 65,536-vertex tile. Bitmap clearing
and word scanning each cost one cycle per word; selection is at most one
vertex per cycle. Marks use an explicitly assumed forwarded 1R/1W bitmap
update on the existing single-result reduction path. Selected vertices still
pay the existing bounded AXI, pipeline, writeback, and publication costs.
No latency multiplier, memory coefficient, or G+R parameter was tuned.
See the [component contract](../../../../../../implementation/spine/residual_sparse_apply.md).

| Case | Dense Apply vertex visits | Sparse visits | Bitmap clear cycles | Bitmap read cycles | Computed edges / marks |
| --- | ---: | ---: | ---: | ---: | ---: |
| FL | 30,624 | 4,082 | 480 | 359 | 9,162 |
| AU540 | 189,862 | 570 | 2,968 | 2,598 | 586 |
| AU904 | 156,289 | 303 | 2,443 | 2,189 | 314 |

Flickr still performs substantial propagation over twelve rounds, whereas
AU540/AU904 finish after two/one nonempty Spine rounds. Removing dense Apply
therefore has much less effect on Flickr. The experiment does not separately
calibrate each remaining bottleneck against FPGA counters.

## Inputs And Timing Boundary

- Same old converged state, independent expected new state, and insertion
  batch on both arms. Fixed per-vertex FP32 `epsilon=1e-6`, damping
  `FP32(0.85)`; no division by vertex count.
- FL: 2,552 vertices / 8,192 initial edges. AU540: 94,931 / 540,000.
  AU904: 156,289 / 903,774. These are the exact historical materialized
  reciprocal inputs, with eight logical updates / sixteen physical records.
- The window starts from resident old convergence and includes batch
  maintenance, device preparation, and propagation through new convergence.
  Initial preload, host orchestration, DMA, launch/wait, and readback are
  excluded on both sides. These are predicted device cycles at 150 MHz.
- Both arms retain the direct DRAMSim3 model, 32-channel budget,
  512 MiB/channel, and 32 backend outstanding requests/channel. Resource
  layouts are not asserted to match original A4 exactly.

## Numerical Verification And Retained Difference

The fresh dense control exactly reproduces the preceding cycles, traffic,
energy, full rank/residual arrays, and frontier counts. G+R reproduces the
preceding values exactly in both new modes. Every real arm passes its
independent numerical gate and drains its physical request ledger.

Final Spine rank words are bitwise identical between dense and sparse on all
three inputs. Complete active vertex **sets** are identical for every round,
not merely equal-sized frontiers. AU540/AU904 also have identical residual
words and frontier order.

The first strict full-state equality check **failed on Flickr residuals**:
186 words differ, maximum absolute difference `1.1368683772161603e-13`.
The confirmation run records sixteen changed frontier-order lists while their
sets remain identical. This is consistent with timing-dependent FP32
accumulation order, but this study does not establish that causal attribution.
Both full residual arrays remain finite and satisfy the unchanged `1e-6`
activation threshold. We do not claim complete bitwise state equivalence.

After inspecting that failure, the diagnostic comparison introduced a bound
of `4 * 2^-23 * epsilon`, approximately `4.768e-13`, on dense/sparse residual
differences. This is an explicitly **post-hoc comparison tolerance**, not an
algorithm threshold, a pre-registered gate, or a timing adjustment. Initial
runs and their full state arrays remain archived under `initial/`; they were
not overwritten by the confirmation runs.

## Traffic And Modeled HBM Energy

| Case | Dense Spine accepted bytes | Sparse Spine accepted bytes | Sparse byte ratio G+R/Spine | Sparse HBM energy ratio G+R/Spine |
| --- | ---: | ---: | ---: | ---: |
| FL | 614,256 | 401,920 | 66.924 | 0.677 |
| AU540 | 1,551,828 | 37,492 | 1,075.150 | 12.582 |
| AU904 | 1,273,740 | 25,852 | 2,137.022 | 17.324 |

Energy includes all 32 channels' background/refresh over the device window;
it is DRAMSim3 HBM energy, not measured FPGA power or complete accelerator
energy. New bitmap RAM energy is not included. This change affects propagation
and Figure 9-type data; it does not rerun or change Figure 8 update-only host
measurements. No figure or paper is silently replaced by this diagnostic.

## Limits And Files

This is an explicit simulator architecture candidate, not the routed Spine
implementation or a newly calibrated FPGA result. Bitmap placement, priority
encoding, RAM energy, and achievable frequency remain unvalidated. Spine
correction remains oracle-directed **timed work replay**, not a fully
functional AXI-derived seed implementation. The exact-future-batch PMA
reservation convention and original-G/R baseline-admission limits of the
preceding study remain. The new ratios do not resolve those separate gaps.

- `data/before_after.csv`: all three controls and measured simulator ledgers.
- `data/summary.json`: model boundary, numerical comparisons, full-frontier
  checks, bitmap resources, traffic, energy, and retained Flickr loss.
- `evidence/index.json` and `evidence/evidence.tar.gz`: hash-indexed original
  package, initial and confirmation reports, sources, full numerical states,
  active vertex IDs, input files, commands, logs, and core regressions.
- [Test report](TEST_REPORT.md): completed gates, safety policy, and commands.

The pre-edit external git archive and tool/linked binaries are not embedded;
their external status is explicit. The preceding frozen capsule and current
core/harness/runner source snapshots are embedded. Portable verification
recomputes the exported tables from archived reports and raw outputs.
