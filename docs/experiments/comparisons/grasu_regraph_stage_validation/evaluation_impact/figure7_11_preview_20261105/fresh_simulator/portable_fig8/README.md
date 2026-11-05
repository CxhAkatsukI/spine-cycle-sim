# Same-Host Portable Fig. 8 Cohort

November 5, 2026. Five declared cases, four completed comparisons and one
retained failure. This is measured CPU preparation plus simulated device and
transfer time, **not FPGA timing or hardware-baseline admission**. Neither the
paper nor the earlier local CPU cohort has been overwritten.

| Dataset | Spine seconds | G+R seconds | G+R / Spine | Status |
| --- | ---: | ---: | ---: | --- |
| AU | 0.064894 | 0.248357 | 3.827x | Complete prediction |
| SU | 0.098389 | 0.378412 | 3.846x | Complete prediction |
| WK | 0.126993 | 1.154529 | 9.091x | Complete prediction |
| SO | 4.308395 | 30.134219 | 6.994x | Complete prediction |
| PK | - | - | - | Failed: Spine cold hierarchy has no capacity-safe free target |

## Files And Boundary

- [Five-case table](fig8_ten_batch.csv): failed PK has no invented latency or ratio.
- [Scope, host/compiler identities and numerical pins](scope.json).
- [Raw receipts and frozen reference](receipts.tar.gz).
- [PNG preview](figures/fig8_ten_batch_portable.png) and [PDF](figures/fig8_ten_batch_portable.pdf).

Both arms ran on the same Xeon Platinum 8375C host, with one Release host
sample per arm and per-case pinned CPU affinity. Each case retains its graph
state across ten chronological batches, with 4,096 total updates. Initial
preparation/upload is paid once. Elapsed prediction is host preparation plus
device cycles / 150 MHz, logical H2D bytes / 12 GB/s, and 10 us launch per batch.
Parsing, oracle computation, runtime allocation, XRT and final readback are
excluded. This is update-only, not propagation to convergence. G uses shared
metadata and future-batch-union reservation, not the routed four-copy layout.

Keep this host cohort separate from the local EPYC batch-size sweep. The
older local 1,000-batch point still favors G+R; this new cross-dataset cohort
does not invalidate or replace that loss. SO's totals are mainly measured
preparation: Spine 4.281 s and G+R 29.713 s. Its device terms are only 0.00829 s
and 0.000803 s, respectively; the setup speedup is not device speedup.

PK passed both smoke arms but failed in its trace Spine execution with
`Spine cold level hierarchy has no capacity-safe free target`. Its raw stderr
is retained in the archive. This is a model/hierarchy-capacity failure, not
an accepted pair, timeout or missing-runtime error. No timing conclusion for
PK follows from this run.

## Equivalence Gate

The exporter reparsed all completed raw per-batch/device/host counters and the
setup formula, rehashed the transferred inputs, and checked that relocation
changed only graph/update paths. All five cases exactly match the earlier
local smoke's device cycles and read/write ledgers, for both arms. Host
nanoseconds are deliberately not compared across CPUs.

The reference is `fig8-persistent-su-v1/results.json`, whose recorded build
artifacts remain unchanged. The earlier AU-v4 build directory's compilation
database was regenerated after its run and no longer matches its frozen hash;
that file was not silently repinned or used as the portable reference.

All reference numerical source and DRAM identities match. The newer source
inventory adds 155 uncompiled test files; CMake adds a test target only.
The exporter separately compares the complete compiled core-unit list,
per-unit flags, and plugin command after normalizing runtime paths. It does
not excuse a new numerical unit, changed model flag or changed source hash.
The remote GCC 15.2 binary is separately pinned; this is source/recipe and
smoke equivalence, not a claim that different compiler builds have identical
host timing. These gates do not calibrate large-trace latency against FPGA.

## Reproduction

From the repository root, redraw using the supplied GraphyFlow style and TXTT:

```sh
bundle=docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure7_11_preview_20261105
python "$bundle/render.py" --portable-fig8
```

To replay the evidence export on the recorded hosts, retain the source/input
paths in the receipt archive. The reusable exporter is
`spine_cycle_sim.experiments.evaluation_impact.figure_refresh.portable_evidence`.
First freeze the local reference (explicit directories support older reports
that predate environment-path recording):

```sh
python -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.portable_evidence freeze \
  --reference /data/chuxiao/checks/source-retention-repair-20261104/fig8-persistent-su-v1/results.json \
  --reference-sst-include /data/feiyang/sst/include \
  --reference-dram /data/tmp/chuxiao/candidate73-dramsim3-pgo-src-20260729 \
  --output /tmp/portable-reference.json
```

Transfer that reference to the remote host and export to a new directory:

```sh
base=/data/chuxiao/fig8-portable-20261105
python -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.portable_evidence export \
  --reference /tmp/portable-reference.json \
  --case AU "$base/au-v3/results.json" --case SU "$base/su-v3/results.json" \
  --case WK "$base/wk-v3/results.json" --case SO "$base/so-v3/results.json" \
  --case PK "$base/pk-v3/results.json" --output /tmp/portable-export
```

The recorded export ran the same checked-in exporter outside the frozen
runner checkout. Large inputs, compiler/runtime binaries and build products
are hash-indexed, not embedded. The archive includes raw stdout/stderr,
configurations, compilation databases, both manifests and result receipts.
The [remote execution protocol](../../REMOTE_CPU.md) describes memory limits
and unchanged numerical parameters.
