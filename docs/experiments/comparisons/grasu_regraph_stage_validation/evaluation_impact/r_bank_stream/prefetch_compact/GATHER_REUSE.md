# Destructive Gather Reuse Control

## Question And Contract

Simulator only. This control tests whether repeated initialization, despite
a destructive output scan, contributes to the remaining complete-R gap in
the [preceding wrapper control](WRAPPER_SCHEDULE.md). No FPGA tool is run;
HLS, the paper and figure packages are unchanged.

The original ReGraph source supplies two complementary facts:

- `acc_template/kernel_little_gs/acc_gather.h` clears every temporary-property
  row while publishing its result. Its storage is simple dual-port URAM.
- `host/host.cpp` selects `reset_tmp_prop` only on the first superstep.
  The non-`SW_EMU` Gather respects that input; the software-emulation branch
  deliberately resets every invocation and is not the schedule modeled here.

Our existing Gather engine already erases each bank's row on successful
output publication, retaining backpressure and the complete output scan.
The routed caller nevertheless requests initialization on every invocation.
The default-off `experimental_gather_reuse` control resets each physical
frontend on its first invocation, then reuses the already-cleared storage.
A guard rejects reuse if the destructive scan left any stored row. Pending
update writes and the existing pipeline drain must still complete before
publication; no output row or memory request is removed.

The new `prefetch_gather_reuse` arm inherits the latest finite reader,
source loading, addressed output, Apply and wrapper controls unchanged.
Default profiles and every earlier arm retain their old behavior. The
optimization is a source-backed simulator control, not a claim that the
current routed FPGA binary implements it.

## Predeclared Comparison

Use the same Amazon real-ID slice: 258,046 vertices, 1,450,899 weighted edges
and four destination shards. All arms begin with identical old converged
SSSP state, resident post-update PMA and the same prepared seed after three
source-0 weight decreases. All run through complete synchronous convergence,
not one hop. The boundary excludes G, host preparation, DMA and launch on
both sides.

The matrix has three arms (A4-io16, preceding wrapper candidate and Gather
reuse), mock memory latencies 64/128 and both registration orders: twelve
complete executions. Eight old controls must replay exactly. Full padded
state replicas, active trajectories, physical reads/writes and request/beat
closure must agree. Retention requires candidate/A4 cycles in [0.9, 1.1]
at both latencies; correctness alone is not a pass.

For each used frontend the candidate must pay one 32,768-cycle reset and
continue to publish 32,768 rows on **every** invocation. The old control
pays the reset on every invocation. Core regression also covers empty and
throttled paths, source-window crossings, more than four partitions, and
forward/reverse registration. A numerical change requires a fresh core
build/test and a fresh default SST software-compatibility replay.

All physical resources and memory timings are unchanged from the preceding
candidate: sixteen masters/three state copies versus A4's thirteen/four.
This is not strict resource equivalence or original-publication reproduction.

## Execution Record

All twelve complete executions pass correctness and conservation. Eight old
controls replay exactly, and all six forward/reverse pairs agree. Every
execution finishes the same 46 synchronous rounds, complete padded state and
replicas, and active trajectory. The complete retention gate **still fails**:

| Arm or observation | 64-cycle memory | 128-cycle memory |
| --- | ---: | ---: |
| Original A4-io16 cycles | 10,904,254 | 15,840,606 |
| Previous wrapper candidate cycles | 11,828,118 | 19,699,546 |
| Gather reuse candidate cycles | 10,395,723 | 18,331,456 |
| Candidate/A4 | 0.953364 | 1.157245 |
| Cycle reduction from previous candidate | 12.11% | 6.94% |
| Within declared [0.9, 1.1] band | Yes | **No** |

The low-latency prediction is 4.66% faster than A4; the high-latency
prediction remains 15.72% slower. This is not a match of the full matrix.
The unchanged production bank stream remains 2.951 / 3.635 times A4; the
candidate does not silently replace that historical result or a default
profile.

For each of the four used frontends, initialization falls from 1,507,328
cycles (46 resets) to 32,768 (one reset), while **both** output and merge
still account for 1,507,328 rows. These observations are checked against raw
progress CSVs. Initialization overlaps other work, so removed reset cycles
are not additive end-to-end savings.

Physical traffic is unchanged from the previous candidate: 2,021,232,640
read bytes and 144,703,672 write bytes. A4 reads 802,534,400 and writes
192,937,984 bytes, with a fourth state copy. No physical PMA read, output
row, response, barrier or final-state comparison is omitted.

The fresh numerical core passes all **37 CTest targets**, including 80
compact convergence executions. Twenty explicit configuration arms, 144
finite-input executions and four storage/backpressure probes pass. Python
ReGraph discovery passes 158 tests. A freshly built SST software plugin
exactly replays all five legacy cases; this is compatibility, not hardware
timing calibration. Its bounded service takes 507.784 s, with a sampled
peak of 1,048,584,192 bytes and zero swap.

The independent artifact recheck passes 2,426 core pins, 2,787 SST pins,
40 progress files and 40 full-state files. It also checks all 2,401 current
source-archive members and 2,400 pre-edit members, independently reparses
all twelve raw outputs, recomputes the analysis and checks initialization
and output rows. The portable [evidence index](gather_reuse.json) records
the report, freeze, archive, retained interruption and verification hashes.

Raw work is isolated under
`/data/chuxiao/experiments/r_gather_reuse_20261022/`. The immutable pre-edit
freeze is `before/freeze.json`. `convergence-v1/` retains an interrupted
attempt with one completed configure step and zero convergence rows; it is
not a result. A fresh directory is used for every subsequent attempt.
The completed core is `convergence-v2/`; the fresh software-plugin replay
is `sst-v1/`; `verification.json` records the independent checks. No FPGA
compiler, route or board job is part of this study.

The core ran under a 6-GiB hard/5-GiB high limit and zero swap, with a
24-GiB live reserve and four workers pinned to CPUs 124--127. Its sampled
peak was 1,312,694,272 bytes; complete service wall time was 1,381.463 s.
The peer's finite 16-GiB limit was reserved at admission; no foreign limit
was changed.

## Owners And Reproduction

The C++ control is in `routed_regraph.hpp` and `routed_regraph/rounds.cpp`;
`grasu_regraph_gather.cpp` owns the destructive-clear invariant. Existing
`compact_input_tests.cpp` covers reset counts, all output rows and full
convergence. Python `r_bank_stream/gather_reuse.py` owns freeze, execution
and analysis through the shared convergence runner. Focused rejection and
resource tests live in `tests/test_regraph_gather_reuse.py`.

Use a new output directory/unit name from the repository root:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-gather-reuse-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=100min -p 'CPUAffinity=124 125 126 127' \
  -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.gather_reuse \
  --output /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-NEW \
  --reference /data/chuxiao/experiments/r_sssp_wrapper_schedule_20261022/convergence-v1/results.json \
  --before /data/chuxiao/experiments/r_gather_reuse_20261022/before/freeze.json \
  --core-reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --cpus 124 125 126 127

python3 -m unittest tests.test_regraph_gather_reuse \
  tests.test_regraph_compact_convergence tests.test_regraph_cached_core -q

systemd-run --user --wait --pipe --collect \
  --unit=spine-r-gather-reuse-sst-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=45min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.software_compatibility \
  --output /data/chuxiao/experiments/r_gather_reuse_20261022/sst-NEW \
  --core-result /data/chuxiao/experiments/r_gather_reuse_20261022/convergence-NEW/results.json \
  --baseline /data/chuxiao/experiments/r_prefetch_capacity_20261022/sst-v1/legacy \
  --memory-profile cpu-fresh-core-6g-reserve24-v1
```

The fresh-core profile has a 6-GiB hard/5-GiB high limit, zero swap, a
24-GiB live reserve and an 8-GiB background budget. Atomic admission reserves
every competing build's full finite limit. A peer swap allowance is accepted
only after verifying that the host has no swap; unknown/unbounded peers
remain disallowed. The watchdog stops only owned work on a reserve breach.
