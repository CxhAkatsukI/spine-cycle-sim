# Simulator throughput milestone 6: AXI and DRAM command hot paths

## Scope

This milestone removes repeated host work from two shared timing paths while
preserving the frozen Candidate10 architecture and every observable simulator
result. It does not change clocks, ports, FIFO capacities, AXI widths,
outstanding limits, HBM mappings, arbitration winners, DRAM commands, or
algorithm behavior.

The implementation changes are:

- a fixed-channel AXI master recognizes a registered arbitration intent that
  cannot change before commit and bulk-accounts the remaining same-cycle
  retries; the read-only case uses the maintained issueable-burst count, while
  the mixed read/write case retains ordered per-burst stall classification;
- an AXI commit with no staged state change skips seven empty commit helpers,
  but still advances the round-robin pointer exactly once as in the baseline;
- DRAMSim3 visits only set bits in the nonempty per-bank command-queue mask
  instead of testing every queue, and erases the selected read/write command
  through its already-known iterator; and
- DRAM bank timing is embedded in a fixed array and its tiny max-update is
  inlined at the call site.

The DRAM changes are carried by
`patches/dramsim3_command_timing_hotpath.patch`; the isolated backend build
script applies and hashes it after the three earlier exact-idle hot-path
patches.

## Fresh controlled result

The backend and SST memHierarchy element were rebuilt from their frozen source
revisions into new directories. The frozen residual PageRank probe was then
run sequentially for both systems.

| System | Frozen baseline host s | Candidate host s | Cumulative speedup | Simulated cycles |
|---|---:|---:|---:|---:|
| Spine | 7.884 | 4.609 | 1.711x | 4,778,979 |
| GraSU+ReGraph | 105.218 | 53.461 | 1.968x | 15,310,428 |

The two-system geometric-mean cumulative speedup is **1.835x**. Relative to
the immediately preceding fresh Candidate12 build, this milestone is 1.082x
faster for Spine and 1.172x faster for GraSU+ReGraph, or 1.126x by geometric
mean. This remains a single frozen probe, not the final medium/large-suite
claim and not completion of the 10x target.

## Exactness evidence

`scripts/analyze_exact_idle_equivalence.py` reports PASS:

- all 356 pre-existing result fields are identical;
- both complete result JSON files are byte-identical;
- all 26 DRAMSim3 JSON files are byte-identical; and
- the DRAM idle-advance harness independently closes after 1,010,000 cycles
  with 21 completions and 1,009,323 skipped cycles.

Committed evidence is under
`docs/evidence/simulator_throughput_candidate13_axi_dram_hotpath_20260728`.
Raw runs remain outside Git:

- fresh candidate: `/data/tmp/chuxiao/simulator_throughput_candidate13_fresh_reproduction_20260728`
- fresh equivalence: `/data/tmp/chuxiao/simulator_throughput_candidate13_fresh_reproduction_20260728_equivalence`
- fresh backend build: `/data/tmp/chuxiao/candidate13-reproduction-build-20260728`
- fresh backend install: `/data/tmp/chuxiao/candidate13-reproduction-install-20260728`

The candidate SST plugin SHA-256 is
`240e3625d889656bd15fe4f5828ae0f4d96f8539dc048a5fa14f6dfe252bbfc2`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/build_exact_idle_dramsim3_backend.py \
  --work-root /data/tmp/chuxiao/candidate13-reproduction-build \
  --install-prefix /data/tmp/chuxiao/candidate13-reproduction-install \
  --jobs 8

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate13-reproduction-build/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate13-reproduction-install
export SPINE_CYCLE_ELEMENT_DIR=$PWD/build/sst

make -C cpp/sst -j8
python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_k1_multipart_v4_20260728.json \
  --run-id syn_spread_e512__residual_pagerank \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate13_reproduction \
  --jobs 1 --timeout-seconds 600 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh \
  --lib-dir build/sst --no-build

python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/simulator_throughput_baseline_spread_residual_20260728 \
  --candidate-dir /data/tmp/chuxiao/simulator_throughput_candidate13_reproduction \
  --out-dir /data/tmp/chuxiao/simulator_throughput_candidate13_reproduction_equivalence
```

Validation at this milestone: 585 Python tests passed with 5 expected skips;
the 102-test shared-core and 29-test GraSU C++ suites passed; and
`git diff --check` was clean.
