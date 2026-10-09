# Scheduler latched-commit bitmap

## Purpose

The cycle scheduler previously visited every commit-capable component on every
cycle, including finite FIFOs with no pending push or pop. This change keeps the
same evaluate/commit ordering but lets components with a latched commit guard
notify the scheduler on the false-to-true readiness transition. The scheduler
stores those notifications in an ordered bitmap and commits only set entries.

Unconditional components and components with a dynamic readiness predicate keep
their previous behavior. Multi-clock notifications remain pending until the
component's own clock edge. Commit callbacks are still invoked in component
registration order, and notifications raised during commit cannot pass through
in the same cycle.

## Correctness tests

`scheduler_latched_commit_bitmap` covers 130 fast-clock components across three
64-bit bitmap words, reverse notification order, a slow-clock component, and
slot rebasing after component removal. The existing FIFO no-fallthrough and
latched-readiness tests remain enabled.

```bash
cmake --build build -j2
ctest --test-dir build/cpp --output-on-failure
make -C cpp/sst -j2
```

## A/B evidence

The A/B workload was `syn_spread_e512.slice` with thresholded residual PageRank
and the frozen `spine_candidate10_normalized_v1` profile. Runs were serial and
interleaved old/new/old/new. The baseline library is preserved at
`/data/tmp/chuxiao/scheduler_latched_bitmap_baseline_lib_20260727`, and raw runs
are under `/data/tmp/chuxiao/scheduler_latched_bitmap_abba_20260727_v3`.

| implementation | host seconds A | host seconds B | mean seconds |
| --- | ---: | ---: | ---: |
| previous scheduler | 60.116147 | 60.321624 | 60.218886 |
| latched bitmap | 58.197531 | 59.031848 | 58.614689 |

The mean host-runtime reduction is 2.664% (1.027x throughput). All four
`result.json` files have SHA-256
`da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758`.
The modeled result remains 4,778,979 cycles, 410,621 backend requests, 410,621
DRAM commands, and 76,228 activates. This is a simulator host-runtime
optimization only; it does not change or claim accelerator performance.
