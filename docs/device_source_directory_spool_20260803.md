# Device-Owned Source Directory and Spool

## Scope

This checkpoint removes the old 4,096-source host handoff from the paper
architecture path. It aligns the cycle simulator and the shared HLS reader
protocol around device-owned source records for weighted SSSP, connected
components, thresholded residual PageRank, and Full PageRank.

The legacy `HOST_ACTIVE` mode remains available as a compatibility path. It is
not the source of performance evidence for the paper-aligned profile.

## Protocol

The reader supports three device-owned source modes:

- `DEVICE_DIRTY` consumes the persistent dirty list produced by maintenance;
- `DEVICE_ACTIVE_LIST` consumes the bounded active-output records produced by
  graph compute; and
- `FULL_DOMAIN` generates source IDs `0..N-1` on device for Full PageRank.

For every source, the reader requests the current algorithm state through the
bounded reverse stream and reads the 32-bit source-to-family directory mask
from HBM16. The low 16 bits select cold families and the high 16 bits select
hot shards. A zero mask is legal and represents a dangling or edgeless source.
If the directory-valid metadata bit is clear, the reader conservatively scans
all families; this preserves the old HLS compatibility mode.

Resident levels are loaded before timed maintenance. Their directory bits are
therefore seeded into the HBM16 bootstrap image. Candidate10 maintenance then
publishes bits for later updates.

Each device source record occupies 32 bytes. Full PageRank always writes these
records to HBM18. A dirty/active frontier larger than the finite active-record
gate uses the same spool. The reader then performs:

1. one HBM18 spool read for range validation;
2. bounded range-task construction without emitting graph edges;
3. one HBM18 spool read for execution; and
4. exact graph-payload replay through the finite AXIS stream.

This is an execution-driven memory path. The directory and spool traffic is
issued through the existing finite AXI ports and is subject to outstanding
limits, request FIFOs, HBM arbitration, response queues, and backpressure.

## Evidence Counters

SST JSON now exposes these counters directly and, where applicable, per round
or per iteration:

```text
reader_family_directory_bytes
reader_family_directory_mask_reads
reader_family_directory_empty_masks
reader_source_spool_write_bytes
reader_source_spool_read_bytes
```

They are included in the existing reader request-completion ledger. No traffic
is inferred from an edge-count latency formula.

## Simulator Validation

Build and run the focused tests:

```bash
cd /home/chuxiao/spine-cycle-sim-architecture-alignment
cmake --build build/cmake -j4 --target spine_cycle_core_tests
./build/cmake/cpp/spine_cycle_core_tests \
  spine_device_dirty_4097_device_owned
./build/cmake/cpp/spine_cycle_core_tests \
  spine_convergence_4097_device_owned
./build/cmake/cpp/spine_cycle_core_tests \
  spine_full_pr_8192_device_spool
./build/cmake/cpp/spine_cycle_core_tests \
  spine_pagerank_vertical_slice
```

The 8,192-vertex Full PageRank boundary case reports:

```text
device cycles:                 334,233
source requests/responses:     8,192 / 8,192
family-directory mask reads:   8,192
empty directory masks:         8,191
source-spool write bytes:      262,144
source-spool read bytes:       524,288
graph edges emitted:           1
final rank sum:                1.0
```

The 4,097-source weighted-SSSP tests complete without a host handoff, preserve
the logical frontier separately from reader source coverage, and close the
dirty acknowledgement at generation two.

The native SST element was rebuilt from this checkpoint:

```text
build/sst/libspine_cycle.so
SHA-256: bc3a6049b03c42828dacf3875ad4d044784a7d2df5965ec5381a760974edf76e
```

A two-iteration Full PageRank smoke over the real SST/DRAMSim3 backend passes
with 1,605 issued and completed DRAM requests, 124 activations, 1,384 row hits,
zero correctness mismatches, and a final rank sum of 1.0:

```bash
python3 scripts/run_sst_spine_vertical.py \
  --scenario full_pagerank \
  --out-dir /tmp/spine-paper-alignment-fullpr-smoke-v2 \
  --no-build --pagerank-iterations 2 --max-cycles 2000000 \
  --maintenance-architecture candidate10_one_pass
```

Run the complete local regression with:

```bash
./build/cmake/cpp/spine_cycle_core_tests
./build/cmake/cpp/spine_owner_tests
./build/cmake/cpp/spine_vertex_lifecycle_tests
./build/cmake/cpp/grasu_cycle_tests
```

## HLS Validation

The HLS alignment worktree is:

```text
/home/chuxiao/spine-dynamic-graph-paper-alignment
branch: codex/paper-architecture-alignment
checkpoint: 027b831
```

Its 16 host protocol tests pass, including 4,097-source device ownership,
dangling directory masks, the 8,192-record spool, and Full PageRank traversal.
The shared reader kernel also compiles for all four algorithm policy IDs on
U55C at 150 MHz in `sw_emu` mode:

```text
SSSP:
  /data/feiyang/codex_builds/spine_paper_alignment/sssp_reader_spool/spine_partconv_rdmaint_kernel.sw_emu.xo
  SHA-256: 2362b7d3e8384f5b4e658a197d11cb0589bbb2087c73e9d0e79bd34c7a38d6dd
CC:
  /data/feiyang/codex_builds/spine_paper_alignment/cc_reader_spool/spine_partconv_rdmaint_kernel.cc.sw_emu.xo
  SHA-256: 322a45a72e3acc4a1d3a61708d928ca1769007ee47a38863f34dc0f490846d1f
Residual PageRank:
  /data/feiyang/codex_builds/spine_paper_alignment/respr_reader_spool/spine_partconv_rdmaint_kernel.respr.sw_emu.xo
  SHA-256: 342b79547aa51fe9f686a9bb56e67bd93a86881596c493628e755b1afc9c869e
Full PageRank:
  /data/feiyang/codex_builds/spine_paper_alignment/fullpr_reader_spool/spine_partconv_rdmaint_kernel.fullpr.sw_emu.xo
  SHA-256: 40648ef0f4d222532671aa03cb1db11ddb137893e76d9b1526c46404b497e4e6
```

These XOs establish shared-reader compilation, not complete routed
algorithm-specific xclbins. Full compute-kernel synthesis, link, route, timing,
and board correctness remain separate acceptance gates.

## Claim Boundary

This checkpoint supports the following claim: the paper-aligned simulator no
longer requires host construction or replay solely because a device source
domain exceeds 4,096 entries, and the same bounded directory/spool protocol is
represented in the HLS reader source.

It does not yet support a four-algorithm FPGA performance claim. The existing
refactor31 routed xclbin remains a weighted-SSSP calibration artifact, and the
new shared-reader XOs are compile evidence only.
