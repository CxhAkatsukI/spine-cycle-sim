# Explicit Two-Port Reader Diagnostic

## Decision

Simulator only. Eight real-input reader executions pass correctness and
conservation; four old one-port observations replay exactly. Fresh Release
core checks and all five default SST software regressions pass. **Complete R
performance retention has not passed.** The extra-port reader is not connected
to a new complete-convergence candidate or a new Spine comparison. No FPGA,
HLS or paper change is part of this checkpoint.

The portable [evidence index](reader_ports.json) pins source, compiler, inputs,
outputs and the retained failed attempt. The previous
[complete source-loading result](SOURCE_LOADING.md) remains the last complete
candidate: 2.519 / 2.150 times the unchanged A4 cycles.

## Scope And Results

The frozen Amazon real-ID slice has 258,046 vertices, 1,450,899 weighted edges
and four destination shards. This diagnostic reads its resident post-update
PMA once, through drained weighted packet sinks. It excludes compute, G,
host preparation, DMA and orchestration. The prior warm SSSP reference takes
46 synchronous rounds after three source-0 weight decreases.

| Memory latency | Masters per reader | One scan cycles | Parent requests | Beats per parent |
| --- | ---: | ---: | ---: | ---: |
| 64 | 1 | 424,166 | 44,268 | 13.659 |
| 64 | 2 | 292,040 | 224,669 | 2.691 |
| 128 | 1 | 432,565 | 42,050 | 14.379 |
| 128 | 2 | 452,891 | 100,040 | 6.044 |

Both component registration orders agree exactly. Every row reads 38,696,960
physical bytes (604,640 beats), emits all 1,450,899 live weighted edges in
181,464 packets, and preserves per-shard slots and dummy counts. The new
reader reduces cycles by 31.15% at latency 64 but increases them by 4.70% at
latency 128. Extra ports alone therefore do not solve the mismatch.

| Memory latency | Two-port reader, 46 scans | Unchanged complete A4 | Reader floor / complete A4 |
| --- | ---: | ---: | ---: |
| 64 | 13,433,840 | 10,904,254 | 1.232 |
| 128 | 20,832,986 | 15,840,606 | 1.315 |

Multiplication by 46 is a **reader-only floor conditional on using this same
reader unchanged every round**, not a measured complete R execution. Both
floors already exceed the 1.1 retention threshold before the rest of R is
included. They cannot replace an integrated convergence result.

## What The Counters Explain

The reader immediately issues the smaller of 16 beats, remaining bank extent
and free ring space. Releasing only a few ring entries can therefore create
many short parents. At latency 64, requests increase about fivefold despite
unchanged bytes. At latency 128, backend capacity-blocked cycles rise from
104,540 to 997,938. Worker 0 carries 848,130 live edges and 211,765 read beats,
so unequal shard work also remains relevant.

These are overlapping observations, not additive exclusive stage times.
No coefficient or memory-latency change has been used to make the candidate
match A4. Neither these counters nor the isolated transport probe establish
hardware burst timing.

## Explicit Resources

- Four frontends, with two distinct physical masters each. Metadata and even
  PMA segments use port 0; odd segments use port 1.
- At most 16 parents per master and 16 beats per parent; combined maximum 32
  parents per reader. Each port accepts at most one returned beat per cycle.
- The same 1024-row directory and two 256-line reserved rings per frontend;
  pending and returned lines both occupy ring capacity.
- The same depth-two segment pipeline, 32-lane compactor and finite 16/32-entry
  segment/packet FIFOs. The pipeline is not claimed to sustain II=1.
- Unchanged physical PMA, padding, 71-cycle minimum issue-to-use delay,
  64/128-cycle mock latencies, finite backend credits and registered arbiter.

This standalone reader uses eight masters instead of four. A hypothetical
complete integration would use eleven instead of seven; original A4 has
thirteen masters. This is not a strict resource-matched experiment and the
two-port reader has not been promoted to the integrated default.

## Validation And Remaining Gates

The pre-edit source at `df30bbe67a731efc25f6d1d26676916cce7f468a`, compiler,
inputs, binaries and 16-row convergence reference were frozen before edits
in `/data/chuxiao/experiments/r_dual_reader_20261022/before/`.

1. Fresh Release build and all 36 CTest targets pass.
2. Sixteen old and sixteen dual-port synthetic executions pass. They exercise
   live/all-dummy input, long rows, directory tiles, ring wrap, bank boundaries,
   throttled sinks and both registration orders. Two transport probes remain
   unchanged.
3. All eight real-input observations pass independent weighted-CSR equality,
   terminal markers, request/beat closure, bounded storage and physical traffic
   conservation. Four old observations replay exactly.
4. Fresh SST plugin build and all five default regression cases replay exactly.
   This is software compatibility, not candidate stage-timing calibration.
5. Independent completion checks verified 2,381 core pins, 2,742 SST pins and
   sixteen pre-edit artifact/external records; all matched their SHA-256 values.
6. **The sixteen old complete-convergence executions have not been rerun in
   this reader checkpoint.** That frozen integration gate remains open. Reader
   replay and default SST compatibility do not satisfy it.

Complete R retention, broader inputs, resource controls, G+R host timing,
publication reproduction and a new common-state Spine demo remain open.

## Next Simulator Experiment

Proposed, not implemented by this checkpoint: an explicit default-off
full-burst refill policy. It would wait until a complete burst fits in the
existing ring, permit a short final/bank-boundary burst, and retain directory
progress. Test both policies, one/two ports, both latencies and both component
orders; require the eight old observations to replay exactly. Physical PMA
bytes, finite credits, backpressure, padding and the A4 reference must remain
unchanged. A faster reader would still require full integration and convergence
checks; no performance pass is promised.

## Safety And Reproduction

Both completed services used a 6-GiB hard / 5-GiB high cgroup, zero swap,
24-GiB live reserve, full peer-budget admission, one CPU and bounded runtime.
The core service took 752.292 seconds; SST took 517.865 seconds. Watchdog
samples recorded peaks of 840,478,720 and 1,041,973,248 bytes respectively,
with zero swap. Samples are not substituted for authoritative lifetime peaks.
No numerical source was edited while either campaign was running.

The reader and request/join owners are in `cpp/src/detail/prefetch_compact/`.
The thin Python runner and analysis are `reader_ports.py` and
`reader_ports_analysis.py` in `spine_cycle_sim/experiments/evaluation_impact/r_bank_stream/`.
`software_compatibility.py` owns the separate fresh-plugin replay.

From the repository root, use fresh output and service names:

```bash
systemd-run --user --wait --pipe --collect \
  --unit=spine-r-reader-ports-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=60min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.reader_ports \
  --output /data/chuxiao/experiments/r_dual_reader_20261022/diagnostic-NEW \
  --before /data/chuxiao/experiments/r_bank_stream_comparison_20261022/prefetch-compact-v2/results.json \
  --a4-reference /data/chuxiao/experiments/r_bank_stream_comparison_20261022/cpu-core-matrix-v2/results.json \
  --cpu 124

systemd-run --user --wait --pipe --collect \
  --unit=spine-r-reader-ports-sst-NEW \
  -p MemoryMax=6G -p MemoryHigh=5G -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p RuntimeMaxSec=45min -p CPUAffinity=124 -p WorkingDirectory="$PWD" \
  python3 -m spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.software_compatibility \
  --output /data/chuxiao/experiments/r_dual_reader_20261022/sst-NEW \
  --core-result /data/chuxiao/experiments/r_dual_reader_20261022/diagnostic-NEW/results.json \
  --baseline /data/chuxiao/experiments/sharded_k4_bank_stream_profile_20261019/gates-v1/legacy_final
```

The retained `diagnostic-v1` attempt passed all 36 CTest targets but failed in
the Python driver before producing a real-input row: a dictionary was passed
where the cached-core link helper expected a library directory. Version 2
fixes that argument and adds a focused driver regression. The failed report
is retained; its subsequently edited source pins are not claimed unchanged.
