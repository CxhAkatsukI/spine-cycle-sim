# Phase 3A.0 D-stage Measurement Readiness - 2026-07-19

This note records the first D-stage/CONV measurement readiness check for the
current Spine split-kernel hardware build.

## Goal

Phase 3A.0 checks whether the current host/HW stack can produce stable and
separable D-stage measurements before we build a calibrated D-stage simulator
model.

This phase does not calibrate simulator coefficients.

## Artifacts

Simulator repo:

```text
/home/chuxiao/spine-cycle-sim
base commit a204183 Validate maintenance timing on holdout cases
```

HLS repo:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels
base commit 05584dab254b29639402889a375a273eedcec49f
branch codex/phase3a-dstage-readiness
```

HW xclbin:

```text
/data/feiyang/spine-dynamic-graph-builds/stream_sparse_carry_cursors_local_20260716_160954/compact_validation_20260717/hw_134_routed_accepted/xclbin/spine_partitioned_split_e2e.hw.xclbin
sha256 57f1459e53145f63e89845d7a694e52db548f90611d9d8cd665a413f67bf12a0
```

Instrumented host executable:

```text
/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke
sha256 f62915a0001d40a7b8415449a9b2c87ea6657037b71fab24e1569bbd723908a9
```

Final output directory:

```text
/home/chuxiao/spine-cycle-sim/results/dstage_readiness_instrumented_hw_20260719_005302
```

Important files:

```text
matrix.json
commands.sh
runs.csv
summary.csv
raw/<case>/run_N.stdout
raw/<case>/run_N.stderr
raw/<case>/run_N.command.sh
```

## Host Instrumentation

The original host already created both OpenCL events in split CONV:

```text
compute CU event: conv_event
readmaint CONV CU event: reader_event
```

However, stdout only exposed:

```text
conv_ms
```

It did not expose the readmaint-side CONV time. The first readiness run
confirmed that `reader_ms` was missing from all rows.

The host-only instrumentation added two fields to the final
`PARTITIONED_CSR_E2E_SMOKE` line:

```text
reader_ms
conv_span_ms
```

Definitions:

```text
conv_ms      = compute CU event duration
reader_ms    = readmaint(mode=CONV) CU event duration
conv_span_ms = wall-clock event span covering both concurrent split CONV CUs
```

No kernel/HLS logic was changed. The xclbin was not rebuilt.

## Runner

The runner added in this phase is:

```text
/home/chuxiao/spine-cycle-sim/scripts/run_hw_dstage_readiness.py
```

It defines the Phase 3A.0 matrix, preserves raw logs, and writes `runs.csv` and
`summary.csv`.

Dry-run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_dstage_readiness.py \
  --out-dir results/dstage_readiness_dry_run_check \
  --dry-run
```

Output:

```text
cases=5 repeats=3 total_runs=15
```

Final HW run:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_hw_dstage_readiness.py \
  --host-exe /home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/host_partitioned_csr_e2e_smoke \
  --out-dir results/dstage_readiness_instrumented_hw_20260719_005302 \
  --repeats 3 \
  --timeout 180
```

## Matrix

| case | purpose |
| --- | --- |
| `tiny_default` | Minimal graph; fixed overhead and small-counter path. |
| `star_e512` | One active source with moderate fanout across partitions. |
| `fanout_e4096_s64` | Many active sources with a larger edge stream. |
| `repeat_fanout_e512_b3_s64` | Multiple update batches before CONV; exposes mixed L0/L1 level state. |
| `fallback_forced` | Forces the non-tiny tile path and broad tile scheduling counters. |

## Result Summary

All 15 instrumented HW runs completed with `PASS`.

```text
runs: 15
pass: 15 / 15
reader_ms present: yes
conv_span_ms present: yes
```

| case | sweep | pass | conv ms | reader ms | span ms | jitter | traversed edges | active records | fast tiles | full tiles |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tiny_default` | `tiny` | 3 | 0.330899 | 0.246627 | 0.334990 | 18.51% | 7 | 7 | 3 | 0 |
| `star_e512` | `single_source_fanout` | 3 | 0.992827 | 0.876414 | 0.995677 | 3.33% | 512 | 16 | 16 | 0 |
| `fanout_e4096_s64` | `multi_source_fanout` | 3 | 15.384400 | 15.278900 | 15.388200 | 0.18% | 4096 | 1024 | 16 | 0 |
| `repeat_fanout_e512_b3_s64` | `multi_batch_level_state` | 3 | 20.220400 | 20.124300 | 20.224700 | 0.17% | 1536 | 1536 | 16 | 0 |
| `fallback_forced` | `full_path_tile` | 3 | 417.235000 | 416.278000 | 417.235000 | 0.01% | 4112 | 4097 | 0 | 16 |

## Interpretation

The current host/HW stack is ready for the next D-stage calibration step after
the host-only instrumentation.

What is now measurable:

```text
B-stage maintenance time
D-stage compute CU time
D-stage readmaint(mode=CONV) CU time
split CONV event span
active source/record counts
traversed edge count
next-active count
tiny/full tile path counters
vertex-state gather/sweep/scatter counters
level occupancy before CONV
```

The split CONV stage is stream-coupled. In these runs, `conv_span_ms` is usually
very close to `conv_ms`; `reader_ms` is slightly smaller but follows the same
scale. For D-stage calibration, the safest hardware target metric is
`conv_span_ms`, while `conv_ms` and `reader_ms` should be retained to diagnose
which side is limiting.

The `tiny_default` case has high relative jitter because the absolute time is
sub-millisecond. It is useful as a fixed-overhead smoke test but should not be
used as a strong calibration anchor without more repeats.

## Readiness Decision

Ready for Phase 3A.1 D-stage calibration matrix design.

No kernel instrumentation is required yet.

Host instrumentation is required and has been added:

```text
reader_ms
conv_span_ms
```

## Next Step

Phase 3A.1 should design a calibration and holdout matrix around these observed
features:

```text
traversed_edges
active_records
fast_path_tiles
full_path_tiles
gathered_vertex_words
swept_vertex_words
scattered_vertex_words
level occupancy
conv_span_ms
```

The next model should not claim D-stage accuracy until it passes a holdout
validation analogous to Phase 2D.
