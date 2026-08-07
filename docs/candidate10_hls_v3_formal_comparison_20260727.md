# Candidate10 HLS-Derived v3 Formal Comparison

## Scope

This is the complete frozen Candidate10 normalized, conversion-free Spine
versus GraSU+ReGraph simulator matrix. Both systems run at 150 MHz and use the
same execution-driven finite FIFO, AXI, registered pseudo-channel arbitration,
and DRAMSim3-backed HBM framework.

The result is labeled
`candidate10_hls_derived_normalized_structural_execution_driven`. It is a
simulator architecture comparison, not native FPGA measurement,
cycle-for-cycle hardware calibration, or an iso-resource result. Exact HLS
PPA/timing evidence is a separate acceptance layer and cannot retroactively
change this matrix's frozen parameters.

## Coverage and correctness

The matrix contains 23 hash-pinned file-backed fixtures and 73 paired cases:

- 23 weighted SSSP pairs;
- 23 Full PageRank pairs;
- 23 thresholded residual PageRank pairs;
- four additional dynamic weighted SSSP pairs covering insert, delete,
  increased weight, and mixed updates;
- 64 synthetic stress pairs and nine compact real-dataset validation pairs
  from Amazon-2008, Web-Google, and soc-Flickr-und.

All 146 system runs and all 73 pairs passed. Every row has zero architecture,
mathematical, and combined correctness mismatches. The analyzer independently
reloaded every raw result and DRAMSim3 channel record and verified profile
identity, request completion conservation, channel binding, and pair timing.

One output directory was initially rejected because a terminated late child
overwrote `result.json` and DRAM files after a valid manifest had been written.
That case was quarantined and rerun. The runner now verifies raw evidence before
reusing any cache, and the final 146-row rebuild passed this stronger gate.

## Performance result

`Spine speedup` is `GraSU+ReGraph cycles / Spine cycles`; values above one
favor Spine.

| Group | Pairs | Spine wins | GraSU wins | Geomean | Median |
|---|---:|---:|---:|---:|---:|
| All | 73 | 39 | 34 | 1.184x | 1.187x |
| Weighted SSSP | 23 | 12 | 11 | 1.030x | 1.682x |
| Full PageRank | 23 | 11 | 12 | 1.199x | 0.845x |
| Thresholded residual PageRank | 23 | 12 | 11 | 1.288x | 1.152x |
| Dynamic weighted SSSP | 4 | 4 | 0 | 1.507x | 1.546x |
| Synthetic | 64 | 38 | 26 | 1.272x | 1.662x |
| Compact real validation | 9 | 1 | 8 | 0.709x | 0.691x |
| Holdout only | 32 | 16 | 16 | 1.094x | 1.022x |

The overall result is close, not a universal Spine win. In particular, Full
PageRank has a Spine-favoring geometric mean but a GraSU-favoring median: a few
large Spine wins on tiny dynamic/fixed-overhead cases outweigh twelve losses.
Both statistics and the per-case distribution are required for an honest
interpretation.

The four dynamic SSSP update scenarios are the cleanest current Spine result:
all favor Spine by 1.32--1.64x. The strongest Spine cases are tiny or dynamic
PageRank workloads where GraSU+ReGraph pays its partition gather/apply sweep;
the maximum is 4.26x.

That E2E result must not be confused with pure structure-update throughput.
Only four of the 73 pairs contain a nonempty update, all under dynamic weighted
SSSP. Across their eight input differential records, Spine sustains a 25.2K
records/s geometric mean in its timed maintenance window, while GraSU+ReGraph
sustains 3.81M records/s in its timed PMA-update window. Equivalently, Spine's
pure-update speedup is 0.00661x, so GraSU+ReGraph is about 151x faster for this
narrow structure-only operation. GraSU emits 1.189 physical PMA updates per
input record on geometric average.

There is no contradiction: the post-update computation dominates these tiny
E2E cases and reverses the final ranking. The update-only result covers four
tiny synthetic batches, not all 73 pairs or real-dataset updates. It is an
optimization signal for Spine's repeated maintenance scan, not yet a general
update-throughput claim. The analyzer records no-update rows explicitly and
will not turn their nonzero setup phase into fictitious records/s.

The strongest GraSU+ReGraph cases are the 4,095/4,096/4,097 source-window
stress graphs. Weighted SSSP reaches 0.109--0.119x Spine speedup, so Spine is
about 8.4--9.2x slower there. Full and residual PageRank on the same topology
also favor GraSU+ReGraph by roughly 3--4x. These are not outliers to discard:
they expose Spine dirty-source, fallback, and level-reader work as concrete
optimization targets.

## Real-graph caution

Only Amazon residual PageRank favors Spine among the nine compact real pairs,
at 1.187x. The other eight favor GraSU+ReGraph. Web-Google weighted SSSP is the
largest real-slice loss at 0.386x Spine speedup.

These compact slices validate real topology, execution, and correctness, but
they are not full datasets. The `0.709x` real-group geometric mean therefore
prevents a synthetic-only claim while not yet establishing full-dataset
performance. The separate dense Full PageRank sweep also favors GraSU+ReGraph
by 4.33--5.01x, reinforcing that dense compute is currently a Spine weakness.

## Memory and energy

Across all pairs, `GraSU requests / Spine requests` has a 4.197x geometric
mean: Spine generally emits fewer backend requests. This does not imply lower
energy. `GraSU active-channel DRAM energy / Spine active-channel DRAM energy`
has a 0.906x geometric mean, so GraSU+ReGraph is slightly lower on this partial
energy measure overall.

The reason request and energy rankings can differ is that request width, row
locality, activation/precharge behavior, and the simulated interval all matter.
The energy number includes only instantiated active DRAMSim3 channels. It
excludes unbound-channel idle/background energy, on-chip memories, logic,
clocking, and host/board energy. It must not be reported as total accelerator
energy.

## Bottleneck implication

The coarse phase ledger classifies Spine as compute-dominant in 67 of 73 rows,
maintenance-dominant in five, and balanced in one. GraSU+ReGraph is
compute-dominant in all 73 rows.

This means a faster Spine B-stage scan remains valuable for the five
maintenance-heavy cases, but it is not the dominant general E2E lever in this
matrix. The first broad optimization priority is Spine's reader/compute path,
especially source-window fallback and dense Full PageRank. Lower-level stall
and activity counters, rather than this coarse phase label alone, must be used
to estimate a specific what-if speedup.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/prepare_shared_comparison_workloads.py \
  --manifest configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json \
  --verify-only
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_formal_matrix_20260727 \
  --jobs 2 --timeout-seconds 7200 \
  --max-cycles-run \
    syn_gather_bank_fanin_e1024__residual_pagerank/spine=450000000 \
  --resume --claim-scope structural_exploratory --no-build
python3 scripts/analyze_shared_comparison_matrix.py \
  --matrix-dir /data/tmp/chuxiao/candidate10_hls_v3_formal_matrix_20260727 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_formal_analysis_update_20260727
```

The compact evidence bundle is
`docs/evidence/candidate10_hls_v3_formal_matrix_20260727/`. It includes the
parent manifest, fail-closed analysis outputs, deterministic raw JSON/DRAM
archive, and `SHA256SUMS`.

## Remaining gates

- Complete and archive matching Full/residual PageRank HLS resources and
  timing beside the existing weighted SSSP implementation.
- Combine simulator component activity with HLS/CACTI/DRAM evidence for
  on-chip plus HBM energy; do not extrapolate from active DRAM alone.
- Close the large real-slice host-runtime requirement. A partial or timed-out
  run never enters a performance aggregate.
- Run larger real file-backed datasets once runtime and normalized capacity
  permit; the current real rows are validation slices.
