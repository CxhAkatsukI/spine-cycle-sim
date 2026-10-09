# Spine persistent dirty RMW pipeline

Date: 2026-07-24

## Scope

This milestone makes the maintenance dirty-source path follow the persistent
read/modify/write behavior of the current HLS source at
`afb8199a2ca8d3fd208b985324bf4d8719e2b839` on
`origin/reduce-levels-for-routing`.

The previous simulator scanned all sorted edges first and then synthesized a
new dirty bitmap and list from zero. It therefore appended every source again
on a later update batch and could not represent an already dirty source. The
new path reads the persistent count, generation, and hashes from HBM, advances
the generation, and processes each unique adjacent source through the actual
bitmap/list dependency chain.

This is `structural_execution_driven` evidence. The accepted synthesis bundle
predates this HLS dirty implementation and contains no dirty-loop csynth
report, so this milestone does not claim calibrated dirty-loop control latency.

## Source-following execution

The maintenance controller now executes the following order:

1. Read persistent dirty count, generation, hash sum, and hash xor as four
   scalar metadata accesses.
2. Scan sorted edges at `II=1` to validate source order and count unique and
   adjacent-duplicate sources.
3. Advance the generation and publish generation/valid metadata.
4. Read one sorted edge and, for each new adjacent source, read its persistent
   bitmap word.
5. If the source bit is already set, suppress the bitmap write and list append.
6. Otherwise, write the set bitmap word, read the current dirty-list entry,
   write the appended source, and update count and hashes.
7. Publish final count, hashes, mode, and status metadata.

Only one dirty source dependency chain is active at a time. The next scalar
edge read is issued after the preceding source has either been suppressed or
fully appended. This preserves the dependent source order in the HLS code.
Other maintenance passes retain the request-scoped streamed sorted-array path
described in `spine_streamed_maintenance_scans_20260724.md`.

The persistent data is authoritative. Bitmap and list writes are derived from
the payload returned by HBM, rather than reconstructed from Python or C++ host
containers.

## Persistent-state validation

The focused C++ test preloads HBM16 with source 2 already present in the dirty
bitmap and list, count 1, and generation 7. The next update contains sources 2
and 3. It completes in 1,949 simulator cycles with:

| Counter | Value |
| --- | ---: |
| Bitmap reads | 2 |
| Bitmap writes | 1 |
| List reads | 1 |
| List appends | 1 |
| Persistent duplicates suppressed | 1 |
| Final dirty count | 2 |
| Final generation | 8 |

The test also reads HBM back and verifies that the bitmap contains sources 2
and 3, the list contains `[2, 3]`, and all final metadata payloads match the
computed count and hashes.

## SST-HBM evidence

These runs use the source-shaped 32-channel AXI profile, online SST StandardMem
requests, DRAMSim3 HBM timing, finite request/response queues, and workload
correctness oracles.

| Scenario | Unique sources | Adjacent duplicates | Cycles | Backend requests | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Amazon L0 | 1 | 9 | 7,139 | 1,382 | exact |
| Carry + hot | 1 | 1 | 8,402 | 1,899 | exact |
| Weighted SSSP | 5 | 3 | 33,794 | 4,179 | exact |

Every unique source performs one bitmap read, one fresh-source bitmap write,
one list read, and one list append in these fresh-state runs. All three report
zero result and frontier mismatches. Relative to the preceding streamed-scan
Amazon baseline, scalar persistent metadata reads add exactly four backend
beats and increase the total from 6,962 to 7,139 cycles. In the carry case the
four extra beats are hidden by the existing critical path, so the total remains
8,402 cycles.

## Claim boundary

This milestone establishes source-ordered persistent dirty behavior and makes
its memory traffic contend through the shared AXI/HBM model. It does not yet
establish full maintenance-kernel cycle equivalence. The principal remaining
Spine timing gaps are:

- carry merge issue/consume and graph-write sub-pipelines at beat granularity;
- BRAM/URAM banking, port conflicts, and arbitration;
- split-CU controller, AXIS framing details, CDC, and host/runtime boundaries;
- a dirty-loop synthesis or hardware timestamp calibration point;
- overflow/error-path and empty-update validation.

The dirty access structure can be used for architecture what-ifs, but its
absolute loop-control overhead must remain labeled source-derived rather than
hardware-calibrated.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
build/cycle-core/cpp/spine_cycle_core_tests spine_dirty_persistent_state
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --out-dir results/sst_spine_dirty_rmw_scalar_meta_amazon_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot --no-build \
  --out-dir results/sst_spine_dirty_rmw_scalar_meta_carry_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp --no-build \
  --out-dir results/sst_spine_dirty_rmw_scalar_meta_weighted_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_dirty_rmw_pipeline_20260724_summary.json`.
