# Candidate10 exact-idle 50K-edge runtime evidence

This bundle records the Candidate10 normalized Full PageRank large-real gate
using the exact DRAMSim3 idle-advance backend. The deterministic Amazon-2008
slice has 19,399 compact vertices, 50,000 initial edges, eight source-spread
insertions, and three Full PageRank iterations at 150 MHz.

## Acceptance result

Both systems pass architecture and mathematical correctness checks, and their
rank vectors match within the frozen tolerance. Both host runtimes are below
the fail-closed 1,800-second per-system limit.

| System | Simulated E2E | Core cycles | Backend requests | Host wall | Gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Spine | 1,788.219 ms | 268,232,904 | 13,202,166 | 389.088 s | PASS |
| GraSU+ReGraph | 16.440 ms | 2,466,008 | 227,376 | 7.873 s | PASS |

The exact-idle backend changes host execution time only. It does not change the
workload-specific simulated result: GraSU+ReGraph remains 108.772x faster in
E2E simulated time and issues 58.063x fewer backend requests on this slice.

## Equivalence to the always-clocked backend

The reference is the complete always-clocked bundle in
`../candidate10_hls_v3_large_runtime_20260727`.

- All 122 GraSU+ReGraph result fields are identical.
- All 149 pre-existing Spine result fields are identical. The new result adds
  48 reader/compute observability fields and changes none of the old values.
- All final and epoch DRAMSim3 JSON files are byte-identical: 46 JSON files for
  23 bound Spine channels and 10 for five bound GraSU+ReGraph channels.
- Spine host wall falls from 9,381.996 seconds to 389.088 seconds (24.11x on
  these two observations). GraSU+ReGraph falls from 22.596 to 7.873 seconds
  (2.87x). Host speedup is not simulated hardware performance.

This field-superset comparison is necessary because the exact-idle run used the
newer Full PageRank memory-ledger instrumentation. The added fields are
diagnostic only; simulated cycles, requests, stalls, algorithm state, and DRAM
statistics all retain their old values.

## Integrity and reproduction

`runtime_acceptance.json` was produced by the offline fail-closed finalizer. It
verifies complete pair coverage, correctness, table hashes, raw-result hashes,
and `performance_results_modified=false` without launching another simulator.

Verify the committed bundle:

```bash
cd /home/chuxiao/spine-cycle-sim-publication/docs/evidence/candidate10_hls_v3_large_runtime_idle_optimized_20260727
sha256sum -c SHA256SUMS
```

Build and activate the isolated backend as documented in
`../../dramsim3_exact_idle_advance_20260727.md`, then run:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-repro/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-repro-install

python3 scripts/run_hls_pagerank_real_comparison.py \
  --input-manifest configs/experiments/hls_full_pagerank_real_large_runtime_20260726.json \
  --profile-set candidate10_hls_v3 \
  --out-dir /data/tmp/chuxiao/candidate10-idle-large-reproduction \
  --jobs 2 --timeout-seconds 14400 --max-cycles 500000000 --no-build \
  --sst scripts/run_sst_exact_idle_dramsim3.sh

python3 scripts/finalize_large_real_runtime.py \
  --result-dir /data/tmp/chuxiao/candidate10-idle-large-reproduction
```

The raw summaries committed here retain cycles, request/locality ledgers,
stalls, correctness, and DRAM aggregates. Individual per-channel epoch files
remain under `/data/tmp/chuxiao/`; their byte-equivalence result is recorded in
the prototype evidence JSON.
