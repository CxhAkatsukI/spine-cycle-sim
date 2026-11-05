# PK Capacity Failure Diagnostic

This is a failed follow-up, not a fifth accepted Fig. 8 point. The four
completed points and original PK failure in the parent package are unchanged.

## Finding

The ten-batch trace fails on batch index 3 (the fourth batch, 410 updates),
with `Spine cold level hierarchy has no capacity-safe free target`.
The failure-only observation reports 74,875 cycles for that failed batch;
this is **not** a completed-batch latency or a speedup measurement.

Cold family 0 has physical records in every level 2--10. Levels 3--10 are
full; level 2 contains 32,746 of its 32,768 slots. The carry selector requires
a free, capacity-safe target and cannot use these occupied levels. Most
other cold families are empty; this is a per-family placement/headroom
problem, not host RAM exhaustion or proof that all aggregate HBM is full.

The resident classifier and preloader (`cpp/src/spine_l0.cpp`,
`classify_spine_resident_snapshot` and `preload_spine_resident_snapshot`)
can initially occupy all levels 2--10 of a cold family. That does not reserve
enough carry headroom for this update sequence. A valid repair must change
the explicit bootstrap placement/headroom policy, preserve finite per-level
capacity and correctness, and be reflected in the corresponding HLS host
layout. No extra capacity, free retry or timing multiplier was added here.

## Evidence

- [Complete run receipt](results.json), including compiler/plugin/input pins,
  commands, smoke results and the failed step's exit status.
- [Raw stderr](raw/trace_spine.stderr.txt): the first line is structured JSON
  prefixed `WARM_BATCH_FAILURE`; the remainder retains the SST fatal report.
- [Raw stdout](raw/trace_spine.stdout.txt) and [trace configuration](trace_spine/config.json).
- [Frozen failure call site](update.hpp), [observer](update_failure.hpp) and
  [observer unit test](update_failure_tests.cpp). The observer reads state
  only after maintenance has already failed, then preserves the original throw.
- [Selected artifact hashes](index.json); all build/smoke logs are in `raw/`.

The diagnostic rebuilt in a fresh directory from base commit
`58fe479c2e39df64bb3ac87b377c3af7d1927b2c`, with the failure observer and its
test added. Its plugin hash differs from the earlier accepted cohort; it is
not silently admitted as source-equivalent timing evidence. Both smoke arms
still match the frozen device outputs exactly: Spine 11,008 cycles,
9,552 read bytes and 6,784 write bytes; G+R 259 cycles, 240 read bytes and
192 write bytes. The large trace failed after about 35.5 seconds, without
timeout; maximum-process RSS was about 4.02 GiB under a 32-GiB cgroup cap
and 128-GiB host reserve. This diagnostic never ran the large G+R arm.

The indexed graph is the same 1,632,803-vertex PK input; the graph and update
files remain at their hash-pinned remote paths rather than being duplicated.
All receipt paths are original absolute run paths, not paths to this copy.
Re-run the recorded `steps.trace_spine.command` only with those pinned
sources, runtime, plugin and inputs present. A new success requires a new
receipt and a fresh declared cohort; it must not overwrite this failure.
