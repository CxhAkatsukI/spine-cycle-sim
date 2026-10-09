# Scheduler dynamic AXI phase sleep (2026-07-27)

## Scope

This change reduces simulator host time without changing simulated time.  The
global scheduler still visits every clock edge and preserves the strict
`prepare -> evaluate -> commit` ordering.  Only an `AxiMaster` whose persistent
state is completely idle may omit its evaluate and commit calls for that edge.

This is a host-runtime optimization, not an architectural what-if.  It must not
change cycle counts, memory traffic, stalls, queue occupancy, algorithm output,
or any other simulated result.

## Wake contract

An AXI master is awake when any of the following state is non-empty:

- request input FIFO;
- parent transaction table;
- pending-address or active-burst queues;
- backend request/response mappings;
- ready parent-response queue;
- write child-input, store, bridge, or throttle state.

The scheduler records at registration time whether a component has a dynamic
guard.  Unguarded components do not pay a virtual readiness call.  Commit
readiness for every guarded component is snapshotted after all evaluate calls
and before any commit call.  This matters because otherwise an earlier
component's commit could make a later component visible in the same cycle.

## Rejected broader optimization

The first implementation also guarded FIFO commit calls.  It was functionally
correct after adding the commit-readiness snapshot, but a host ABBA comparison
on `syn_chain_e256/weighted_sssp` was slower: baseline runs were 3.272 s and
3.297 s, while guarded runs were 3.406 s and 3.488 s.  The FIFO virtual checks
cost more than the empty commits they removed, so that behavior was removed.

## Accepted AXI-only evidence

The same ABBA case with AXI-only guards produced:

| order | baseline wall time (s) | guarded wall time (s) |
|---|---:|---:|
| A/B | 3.284 | 3.087 |
| B/A | 3.254 | 3.145 |

This is a 4.7% reduction using the geometric means.  It is deliberately
reported as a small host-runtime improvement, not as evidence that the current
large-graph runtime gate is closed.

Two end-to-end cross-architecture checks were then rerun with the optimized
plugin:

| architecture/case | simulated cycles | optimized result SHA-256 |
|---|---:|---|
| Spine `syn_spread_e512/residual_pagerank` | 4,778,979 | `da33883dd1f6c4f01ca1c1826e348e57bd7c02b07111e1e82169f92114e2c758` |
| GraSU+ReGraph `syn_gather_bank_fanin_e1024/weighted_sssp` | 825,749 | `f6fa85947588c29488d6097387c7788cfd952d89cb859d12fca50f00a91374c1` |

Each `result.json` is byte-identical to the frozen Candidate10 baseline.  These
cases exercise different architectures, algorithms, request patterns, and
cycle lengths.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-runtime-audit
cmake --build build/cycle-core -j8
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
git diff --check
```

The representative rerun evidence is outside Git because it contains raw SST
output:

```text
/data/tmp/chuxiao/dynamic_axi_sleep_verify_v2_20260727/
```

## Claim boundary

The optimization is accepted only because it preserves every scheduler edge
and all observable result bytes.  It does not permit coarse idle-cycle jumps,
does not infer inactivity from an edge-count formula, and does not close the
remaining requirement that a large real graph finish in tens of minutes.
