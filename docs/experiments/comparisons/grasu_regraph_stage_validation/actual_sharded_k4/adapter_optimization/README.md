# Adapter Optimization

This continues the [frozen hardware diagnostic](../RESULTS.md). It is not a
completed original-A4 comparison or a published-performance match.

## Reading Order

1. The parent diagnostic explains why the actual routed path, not the old
   independent PMA+A4 model, is being optimized.
2. This guide defines the candidate and the acceptance sequence.
3. The [code owner](../../../../../../spine_cycle_sim/experiments/sharded_k4_stages/README.md)
   maps each responsibility to one module. CLI commands only delegate.
4. [Pre-route gate results](pre_route.json), [raw evidence index](pre_route_raw_index.json)
   and [raw logs, RTL and source](raw_pre_route.tar.gz) freeze the completed gates.
   The still-running route job is deliberately not included in that archive.

## Candidate And Current Gates

The two independent HLS flags remain default-off:

- `GRASU_REGRAPH_STOP_AFTER_LAST`: stop scanning source rows after sending
  the known final edge packet, using the existing monotonic aligned-row ABI.
- `GRASU_REGRAPH_ROW_PREFETCH`: read eight contiguous rows into a local cache
  before consuming them. This changes scheduling, not the AXI master width
  or the update-maintained data structure.

No new sparse-source index is assumed free. The original implementation also
has burst inference; the candidate must not be described as introducing
streaming or burst support for the first time.

RTL testing found an additional zero-node boundary issue: HLS issued an
out-of-range speculative `row_offset[node_count-1]` read. Clamping that index
to zero removes the underflow; a valid row buffer is still required. Normal
graphs have positive node counts. This is separate from the performance
candidate and does not explain the existing measured trailing-row tail.

Source tests pass all six legacy formats/configurations plus three candidate
formats (243 scenarios and 1,464 packets per candidate format). Weighted,
destination-only and unit-weight RTL tests each pass both flag configurations:
13 calls and 200 exact data/keep/strb/last packets per configuration, including
zero nodes, zero edges, first/last occupied rows and cold/stale PMA banks.
All four weighted HLS ablations were rebuilt after the index fix and pass.
Test-only interface depths are enabled only by `GRASU_REGRAPH_COSIM_DEPTH`;
production XOs must not define that flag.

The shared board helper was checked on the original SSSP bitstream with one
repetition of the baseline/trace-disabled/trace-enabled host arms. Result
bytes and correctness/round records match the earlier frozen study exactly.

## Hardware Admission

The candidate SSSP link replaces only the adapter XO among the eleven frozen
XOs. Its complete kernel ABI matches the original. The connectivity section
is preserved byte-for-byte, including repeated `nk`, `sp` and stream keys;
only generated-output paths are relocated. Frequency remains 150 MHz.

Link jobs use two synthesis/implementation workers, a 40-GiB sampled aggregate
RSS budget, a live 16-GiB host-memory reserve and a four-hour timeout. Shared
pages count once per process, conservatively. Address-space limits are not
misreported as aggregate RAM limits. Logs, progress and failures are retained.

A successful link is not board admission. The next gate checks final routed
setup/hold/pulse timing, the 150-MHz data clock, kernel/control inventory and
HBM connections. Only then can the paired board runner program the candidate.
It alternates old/new order across at least three repetitions, uses the same
host, graph, source, resident initial state and convergence rule, and requires
identical result bytes and completed rounds. Kernel lifetimes overlap, so
adapter/gather/mux/apply/HBM times are not added as serial stages.

## Local Reproduction

The local run root is
`/data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/`.
Relevant children are `rtl_{weighted,destination,unit}_safe_index`,
`ablations_safe_index`, `source_safe_index`, `board_helper_regression`, and
`route_combined_sssp`. Earlier failed RTL attempts are retained separately;
they include a linker-thread failure, ignored Tcl depth directives, and the
zero-node out-of-range RTL access.

Run from the simulator worktree with fresh output paths:

```bash
python3 scripts/cosim_sharded_k4_adapter.py \
  --integration /home/chuxiao/grasu-regraph-integration \
  --mode weighted --output /data/chuxiao/experiments/fresh_k4_rtl

python3 scripts/route_sharded_k4_adapter.py prepare \
  --build /data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806 \
  --candidate /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/ablations_safe_index/combined/adapter.hw.xo \
  --synthesis /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/ablations_safe_index/summary.json \
  --cosim /data/chuxiao/experiments/sharded_k4_stage_diagnostic_20261010/rtl_weighted_safe_index/summary.json \
  --output /data/chuxiao/experiments/fresh_k4_route

taskset -c 104-109 python3 scripts/route_sharded_k4_adapter.py run \
  --output /data/chuxiao/experiments/fresh_k4_route
```

After link, use `admit_sharded_k4_bitstream.py --help`, then
`compare_sharded_k4_bitstreams.py --help`. Neither CLI can bypass its previous
gate. Board occupancy is checked before each run; another user's process must
not be reset or killed to obtain a board.

## Remaining Gates

The production simulator is not silently changed or retimed by this study.
Its current `PmaNativeReader` in `cpp/src/grasu_regraph.cpp` combines row
reading, source-cache consumption and edge emission. `ReGraphGather` drains
only after that reader is done. The actual hardware consumes a known packet
count and can finish gather before the adapter finishes trailing empty rows,
as the parent FPGA diagnostic shows. Reconciliation must represent these
distinct completion events, not merely shorten a row-read latency constant.

A candidate simulator must charge the final-row extent read, bound the
eight-entry row cache, preserve partial-block bounds and shared AXI pressure,
and leave gather/merge/apply drain and required source-state traffic intact.
It must retain legacy-profile full-result equality and use a separate
candidate profile for changed traffic/timing. No sparse-source list may be
constructed free on the host. This remaining work has not been admitted by
the RTL test or by whole-FPGA elapsed time.

Candidate board timing, optimized production-simulator synchronization and
matched original-A4 versus actual-K4 performance remain unaccepted until
their evidence is delivered. Original A4 currently models one original
fixed-point PR iteration at 210 MHz; the production FullPR host executes
three FP32 rounds with different state preparation. Their total times must not be compared as if
already matched. No new K4 speedup or publication ~10% match is claimed here.

The paper, figure package, frozen SST plugin and existing numerical models
are unchanged. The unrelated calibration-v4 worktree edits are not included.
