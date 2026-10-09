# Cycle-core runtime hot-path profile

Date: 2026-07-27

Branch: `codex/runtime-hotpath-audit`

Baseline: `76d9aeb`

## Method

The scheduler supports an opt-in component sampler:

```bash
SPINE_SIM_PROFILE_COMPONENT_PERIOD=1024 \
SPINE_SIM_PROFILE_COMPONENT_REPORT=1 \
python3 scripts/run_sst_spine_vertical.py \
  --out-dir /data/tmp/chuxiao/runtime_hotpath_profile_spread_residual_20260727 \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir /home/chuxiao/spine-cycle-sim-runtime-audit/build/sst \
  --no-build --scenario residual_pagerank --validation-mode generic \
  --profile configs/architectures/spine_candidate10_normalized_v1.json \
  --workload tests/data/shared_comparison/syn_spread_e512.slice \
  --source 0 --max-cycles 100000000 --max-rounds 256 \
  --pagerank-damping 0.85 --pagerank-epsilon 1e-06 \
  --residual-max-iterations 256
```

Only every 1024th scheduler event is timed. Sampling does not skip or alter a
simulated cycle. The complete result is byte-identical to the frozen formal
matrix result, SHA-256
`da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758`.
Both runs report 4,778,979 cycles, 410,621 backend/DRAM requests, and zero
correctness mismatch.

## Result

The scheduler sampled 4,667 events across 99 registered components. Grouping
the sampled component nanoseconds gives:

| Component class | Sampled time share |
| --- | ---: |
| FIFO request/response/read-beat/AXIS commit | 44.4% |
| AXI masters for graph/state/metadata/result ports | 43.2% |
| reader, compute, algorithm pipeline, maintenance, backend, other | 12.4% |

No single compute function dominates. The principal host cost is polling many
finite FIFO and AXI components on every cycle even while most ports are idle.
This is simulator host overhead, not accelerator latency.

## Safe optimization boundary

The next optimization may omit a component call only when that phase is an
exact no-op in the current state:

- a FIFO commit may sleep only when no push or pop was staged in evaluate;
- an AXI master may sleep only when its request FIFO, parent/burst/write/read
  state, ready responses, and backend outstanding count are all empty;
- a push committed on cycle N wakes the consumer for evaluate on cycle N+1,
  preserving registered FIFO semantics;
- scheduler cycle count, SST clocking, HBM events, arbitration, queue capacity,
  and global evaluate-then-commit ordering remain unchanged.

Acceptance requires byte-identical Spine and GraSU + ReGraph result JSON,
complete C++/Python regressions, and repeated host-wall improvement. This does
not authorize idle-cycle fast-forwarding.

