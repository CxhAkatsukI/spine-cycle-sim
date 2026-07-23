# Fine-grained Spine Phase 2 acceptance

Date: 2026-07-23  
Branch: `codex/fine-grained-cycle-sim`  
Stable HLS revision: `9c08763148644df262c0d374e782bc834f4c0f4f`  
Architecture profile: `spine_shared_engine_9c08763`  
Profile SHA-256: `aba0d6bbcbaa64240897ed3efc555d6ce6d6455d2f10e77e0ccdb77fa46466a7`

## Accepted scope

This milestone completes the requested stable-profile Spine mechanisms:

1. cold/hot maintenance with independent binary target selection;
2. lower-level carry, signed-differential coalescing, and level retirement;
3. fixed cold/hot graph layouts and all-32-family/all-11-level reading;
4. finite forward/reverse AXIS streams and fixed HBM port mappings;
5. tiny gather/relax/sparse-store and online 4,096-edge threshold selection;
6. full-tile vertex load, buffered replay, overflow edge, stream tail, and
   conditional full store;
7. persistent multi-round weighted SSSP to an empty frontier;
8. online SST StandardMem plus 32-channel DRAMSim3 evidence;
9. mathematical and uint32-saturating architecture oracles.

These changes are fidelity fixes. No simulator-only speedup is promoted as a
new hardware architecture in this milestone.

## Milestone commits

| commit | delivery |
| --- | --- |
| `aade0b7` | stable HLS mechanism/address mapping |
| `7e0a687` | hot/carry levels and all-level reader |
| `156add5` | online full-tile compute and real Amazon evidence |
| `bd13e1e` | persistent multi-round weighted SSSP and dual oracle |

## Formal evidence

Every committed summary identifies the profile hash above, profile evidence
tier `hardware_validated`, and simulator tier
`structural_execution_driven`. The latter is the claim tier of these runs.

| scenario | scope | cycles | backend requests | correctness |
| --- | --- | ---: | ---: | --- |
| Amazon L0 | B + all-level reader + tiny compute | 4,608 | 546 | PASS |
| carry/hot | cold L1 carry + hot L0 + reader + tiny compute | 4,805 | 598 | PASS |
| Amazon full compute | 11 tiny tiles + one 49,982-edge full tile | 355,100 | 35,548 | PASS |
| weighted SSSP | one maintenance + six reader/compute rounds | 22,630 | 2,413 | PASS |

For every scenario, `backend_requests == dram_reads + dram_writes`. The formal
summaries are:

- `docs/evidence/sst_spine_levels_20260723_summary.json`;
- `docs/evidence/sst_spine_carry_hot_20260723_summary.json`;
- `docs/evidence/sst_spine_full_compute_20260723_summary.json`;
- `docs/evidence/sst_spine_weighted_sssp_20260723_summary.json`.

## HLS fidelity matrix

| stable HLS mechanism | simulator status | acceptance evidence |
| --- | --- | --- |
| first globally empty cold/hot target | implemented | independent L1/L0 case |
| carry reads all occupied lower levels | implemented | cold L0 to L1 case |
| min-weight + signed-diff merge/drop | implemented | cancellation test |
| fixed cold then hot level layout | implemented | address-layout test |
| probe 32 families x 11 levels | implemented structurally | reader metadata bytes |
| source-value reverse protocol | implemented, simplified markers | request/response closure |
| depth-32 forward AXIS | implemented | transfer/occupancy/stall counters |
| tiny per-edge gather | implemented | duplicate-destination read test |
| edge 4,097 selects full online | implemented | 4095/4096/4097/4098 tests |
| full load/replay/tail/store | implemented | Amazon full-tile SST run |
| repeated frontier rounds | implemented | six-round weighted SSSP |
| AXI beats/bursts/4-KiB split/outstanding | implemented | backend/DRAM closure |
| online HBM timing/row activity | implemented with DRAMSim3 | ACT/PRE/row-hit/energy |

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake -S . -B build/cycle-core -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests

make -C cpp/sst -j2
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 \
  --out-dir results/sst_spine_vertical_levels_20260723_acceptance
python3 scripts/run_sst_spine_vertical.py \
  --scenario carry_hot \
  --out-dir results/sst_spine_carry_hot_20260723_acceptance
python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_full_compute \
  --out-dir results/sst_spine_full_compute_20260723_acceptance
python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --out-dir results/sst_spine_weighted_sssp_20260723_acceptance
```

Accepted gate on this branch: 21 C++ core tests and 143 Python tests pass;
`git diff --check` is clean. SST builds with only warnings originating in the
installed SST headers (GNU variadic macros and `__int128`).

## Remaining fidelity gaps

The milestone is not an RTL-equivalent or hardware-cycle-calibrated model.
Remaining gaps, in priority order:

1. **Payload-backed memory.** AXI/HBM requests carry exact addresses, sizes,
   ordering, and completion timing, but functional edge/vertex payloads still
   live in C++ containers. A memory response does not supply the value used by
   relax or carry. This can validate traffic/timing structure, not memory-data
   corruption or every ordering bug.
2. **HLS overlap and outstanding issue.** Reader and maintenance high-level
   memory tasks are often issued serially and wait for a parent response. The
   stable HLS uses pipelining, independent ports, and compiler scheduling. This
   is the largest blocker for absolute cycle accuracy.
3. **On-chip BRAM/URAM timing.** Generic banked memory primitives exist, but
   Spine's tiny buffer, full vertex tile, bypass registers, active bitmap, and
   metadata cache are still logical containers/counters rather than fully
   banked port-conflict models.
4. **Exact protocol surface.** Source count/generation markers, diagnostic
   words, forced-dense tiles, overflow/error paths, and every metadata packing
   address are not all represented bit for bit.
5. **Clock crossing and controller details.** The C++ core supports multiple
   clocks, while formal SST runs sample memory responses on core ticks and use
   DRAMSim3 behind 1 ns links. U55C CDC/crossbar/controller behavior remains a
   configurable approximation.
6. **Host round overhead.** Multi-round SSSP restarts immediately after a full
   drain. Vitis launch, host polling, PCIe, and runtime overhead are excluded.
7. **Hardware holdout calibration.** No new hw/hw_emu holdout run has yet
   established median/p90 cycle error for these fine-grained paths. Compiler
   burst formation, including active-output coalescing, is unverified.
8. **Dynamic SSSP deletes/increases.** Signed edge removal is correct in level
   maintenance, but automatic invalidation/active-source discovery and exact
   full-recompute fallback are not connected to the multi-round timed path.
9. **Publication comparison.** GraSU+PMA-native ReGraph, common resource
   normalization, total logic/on-chip-memory energy, area/timing, and the large
   dataset/runtime matrix remain outside this Spine milestone.

## Claim gate

Safe claims now:

- functional correctness for the accepted workloads and mechanisms;
- exact modeled work/traffic ledgers and finite-queue behavior;
- DRAMSim3-relative row activity and memory-only energy under the pinned
  profile;
- mechanism-level bottleneck and what-if exploration, with each proposal
  explicitly labeled.

Unsafe claims until the gaps above close:

- absolute FPGA/ASIC latency accuracy;
- line-by-line HLS or RTL equivalence;
- total accelerator energy/area;
- publication-quality Spine versus GraSU+ReGraph performance superiority.

The next implementation priority is payload-backed memory plus pipelined,
outstanding reader/maintenance issue. Those two changes must precede a fair
competitor comparison because they can materially change both absolute latency
and contention.
