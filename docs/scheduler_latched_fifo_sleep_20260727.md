# Scheduler latched FIFO commit sleep (2026-07-27)

## Scope

This host-runtime optimization omits `Fifo::commit()` only when no successful
push or pop was staged during the current evaluate phase.  The scheduler still
advances every clock edge, every finite queue retains registered one-cycle
visibility, and all components still share the global
`prepare -> evaluate -> commit` boundary.

A successful `try_push()` or `try_pop()` sets a readiness bit stored directly
in the `Component` base.  The scheduler snapshots that bit after every
component has evaluated and before any component commits.  `Fifo::commit()`
applies the staged operations and clears the bit.  This avoids a per-cycle
virtual readiness call, which made the earlier broad dynamic-guard experiment
slower than unconditional empty FIFO commits.

Failed push/pop attempts update their stall counters immediately but stage no
state, so they do not need a FIFO commit.  Skipping an unchanged queue's
`max_occupancy` update is also exact because occupancy can change only in a
successful FIFO commit, where the maximum is still recorded.

## Evidence

All C++ tests pass after the change.  Their combined host time fell from about
14.25 s with AXI-only sleep to 11.07 s on the shared machine.

An interleaved Spine `syn_spread_e512/full_pagerank` ABBA run measured:

| order | AXI-only baseline (s) | AXI + FIFO sleep (s) |
|---|---:|---:|
| A/B | 3.161 | 3.124 |
| B/A | 3.178 | 3.059 |

The geometric-mean improvement is about 2.5%.  A longer 4,778,979-cycle
residual PageRank profile measured 63.97 s before and 62.34 s after the FIFO
change, about 2.6%.  Relative to the pre-AXI profile's 66.64 s, the two accepted
optimizations together reduce host time by about 6.5% on this case.

The sampled FIFO commit count on the long case fell from 340,691 to 1,812
across 73 finite request/response/read-beat/AXIS queues.  This confirms that the
guard removes empty polling rather than graph work.

Both cross-architecture result files remain byte-identical to the frozen
Candidate10 baseline:

| architecture/case | cycles | result SHA-256 |
|---|---:|---|
| Spine `syn_spread_e512/residual_pagerank` | 4,778,979 | `da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758` |
| GraSU+ReGraph `syn_gather_bank_fanin_e1024/weighted_sssp` | 825,749 | `f6fa85947588c29488d6097387c7788cfd952d89cb859d12fca50f00a91374c1` |

Raw evidence is retained under:

```text
/data/tmp/chuxiao/runtime_fifo_guard_abba_20260727/
/data/tmp/chuxiao/runtime_hotpath_profile_fifo_guard_20260727/
/data/tmp/chuxiao/runtime_fifo_guard_grasu_verify_20260727/
```

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-runtime-audit
cmake --build build/cycle-core -j8
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j2
python3 -m unittest discover -s tests
git diff --check
```

## Claim boundary

This changes simulator host cost only.  It does not change simulated hardware
performance and does not close the large-real-graph runtime gate.  Further
work must target the still-active algorithm/backend paths or use an exact
wake-up structure; coarse cycle skipping remains outside the accepted model.
