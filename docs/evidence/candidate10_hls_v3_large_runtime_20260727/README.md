# Candidate10 50K-edge large-real runtime evidence

This bundle records one complete, correctness-gated Candidate10 normalized
Full PageRank comparison on a deterministic Amazon-2008 real-edge slice. The
workload has 19,399 compact vertices, 50,000 initial edges, eight source-spread
insertions, and three Full PageRank iterations at 150 MHz.

## Acceptance result

Both systems pass their architecture and mathematical oracles, and their final
rank vectors match within the frozen tolerance. The simulation is complete,
but the combined runtime gate is `COMPLETE_RUNTIME_GATE_FAILED` because Spine
exceeds the 1,800-second per-system host limit.

| System | Simulated E2E | Core cycles | Backend requests | Host wall time | Runtime gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Spine | 1,788.219 ms | 268,232,904 | 13,202,166 | 9,381.996 s | FAIL |
| GraSU+ReGraph | 16.440 ms | 2,466,008 | 227,376 | 22.596 s | PASS |

For this one workload, GraSU+ReGraph is 108.772x faster in simulated E2E time.
It issues 58.063x fewer backend requests and transfers 19.404x fewer backend
bytes. This is a workload-specific result, not a universal speedup claim.

## Bottleneck interpretation

Spine maintenance takes 2,831,816 cycles and reports
`maintenance_publication_fallback=false`. The three compute iterations take
91,300,900, 88,465,416, and 88,466,588 cycles. Therefore this endpoint is not
explained by the B-stage update path or publication fallback: the dominant gap
is the D/compute memory path. Spine records 13,036,440 compute backend requests
and 13,711,185 backend submit stalls, versus 227,328 compute requests for the
normalized GraSU+ReGraph system.

The result motivates a targeted audit of Spine's source-window/tile state
traffic on large one-partition graphs. It does not by itself prove that every
reported request is unavoidable in an optimized HLS implementation.

## Integrity

`runtime_acceptance.json` was generated after the long-running process ended.
The fail-closed finalizer verifies complete system/pair coverage, all
correctness gates, matrix table hashes, and both raw-result hashes. It records
`performance_results_modified=false`; no SST process is launched during
finalization.

Verify this bundle with:

```bash
cd docs/evidence/candidate10_hls_v3_large_runtime_20260727
sha256sum -c SHA256SUMS
```

Re-run the workload from the repository root with a timeout that exceeds the
observed Spine host time:

```bash
python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/hls_full_pagerank_real_large_runtime_20260726.json \
  --profile-set candidate10_hls_v3 \
  --out-dir /data/tmp/chuxiao/candidate10_hls_v3_large_runtime_reproduction \
  --jobs 1 --timeout-seconds 14400 --max-cycles 500000000 --no-build

python3 scripts/finalize_large_real_runtime.py \
  --result-dir /data/tmp/chuxiao/candidate10_hls_v3_large_runtime_reproduction
```

The committed raw summaries are sufficient to inspect cycles, request and
locality ledgers, stalls, correctness, and DRAM aggregates. Per-epoch DRAMSim3
files are retained under `/data/tmp/chuxiao/` rather than Git.
