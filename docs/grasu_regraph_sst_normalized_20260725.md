# GraSU + ReGraph Normalized SST Vertical Slice

Date: 2026-07-25

## Result

The GraSU update system and PMA-native ReGraph unit-weight SSSP system now run
inside SST with online DRAMSim3 responses. The simulator does not generate and
replay a fixed memory trace. Each component advances on the SST clock, submits
requests through the shared `SstMemoryBackend`, and waits for the returned
response before dependent work becomes eligible.

The runner loads the pinned
`configs/architectures/grasu_regraph_normalized_spine23.json` profile and sets:

- 150 MHz core;
- 32 HBM pseudo-channel interfaces;
- four PMA edge lanes and four gather banks;
- 32 outstanding bursts per AXI port;
- 4096-word source cache;
- 65536-word ReGraph destination partition;
- depth-16 gather/merger, merger/apply, and apply/wrapper streams;
- apply state on HBM[30] and ping-pong source-state copies on HBM[1]/HBM[3].

The input and update are real `.slice` files, not command-line edge counts.
The initial graph has three edges; the ordered batch inserts one edge and
deletes one edge. GraSU mutates payload-backed PMA first. A completion barrier
then creates the ReGraph compute system on the same scheduler and backend.

## Normalized Evidence

```text
result:                    PASS
correctness mismatches:       0
total cycles:             98970
GraSU update cycles:          62
ReGraph compute cycles:    98908
supersteps:                   2
DRAMSim3 backend requests: 32816
backend max outstanding:      9
```

The compute ledger is:

```text
row reads:                     32
source-cache refills:           2
PMA segment reads:              6
four-lane edge batches:        24
PMA slots scanned:             96
live edges scanned:             6
active edges mapped:            3
gather reset + merge cycles: 98304 (32768 + 65536)
gather rows / merger bursts: 65536 / 8192
apply reads / writes:      8192 / 8192 (64 B each)
source-state writes:            16384 (two copies, 64 B each)
apply max read / write in-flight: 8 / 7
apply max pipeline occupancy:     20
wrapper max pipeline / writes:  15 / 6
finite stream max occupancies:  1 / 1 / 1
backend submit stalls:          130
compute read / write bytes: 525056 / 1572864
```

DRAMSim3 independently records 8192 writes on each of HBM[1], HBM[3], and
HBM[30]. This closes the previous memory-ledger omission: the old model counted
only the local apply-state copy and therefore missed two thirds of ReGraph's
state-write traffic. Backend requests rise from 16432 to 32816, but total
cycles are unchanged by the three-copy correction because the HBM channels
accept the writes in
parallel. The correction changes traffic, channel utilization, and future
energy estimates even though it does not change this workload's critical path.

The explicit stream refactor changes the normalized total from 115012 to 98970
cycles, a 13.95% reduction, without changing the graph result, request count,
or byte ledger. Gather emits one 64-bit row per cycle; the free-running merger
packs eight rows into one 512-bit burst. Apply therefore receives one burst
every eight cycles and overlaps its HBM work with the 32768-cycle output/clear
sweep. The old phase barrier incorrectly issued Apply traffic as a separate,
one-burst-per-cycle phase, inflating backend maximum outstanding from 9 to 32
and submit stalls from 130 to 233932.

The update ledger is two PMA 64-byte read-modify-writes plus update and row
records: 160 read bytes and 128 write bytes.

## Claim Boundary

This run is a normalized, execution-driven structural result. It is not yet a
publication-ready performance number.

The ReGraph apply model now follows the strongest available HLS evidence:
bounded 32-request read/write windows, an explicit 100-cycle/capacity pipeline,
and three concurrent state-write paths. `kernelApply` writes local state to
HBM[30], while `kernelHBMWrapper` mirrors the streamed result to HBM[1] and
HBM[3] for the next ping-pong superstep. The HLS source marks `Apply` as
`PIPELINE II=1`; its synthesis report records pipeline depth 100. Compared with
the superseded single-flight revision, total cycles fall from 272100 to 147593
(45.8%) and backend max outstanding rises from 2 to 29.

The host sets `reset_tmp_prop` only for superstep zero because each completed
output sweep clears the gather URAM. Modeling that protocol reduces the same
run from 147593 to 115012 cycles (22.1%), changes reset work from two sweeps to
one, and leaves all HBM bytes and requests unchanged. The original ReGraph host
and the integrated host independently use this first-superstep-only rule.

This closes the known single-flight, missing-state-copy, and inter-kernel phase
barrier errors. The three external stream boundaries are registered finite
queues and propagate backpressure. The HBM-wrapper pipeline uses the
synthesized `write_out` iteration latency 71 and II=1 as a structural profile;
its AXI requests still receive timing online from SST/DRAMSim3.

The largest remaining ReGraph timing boundaries are the exact six-stage gather
RAW bypass/register behavior and the source-cache request controller whose HLS
report achieves II=256. Other open boundaries remain unit-only PMA weights, no
PageRank controllers on the comparator, and no HLS synthesis of the PMA-native
reader. These prevent a final Spine speedup claim, but the finite stream chain
itself is no longer a known gap.

## Reproduction

Fast component smoke with a 16-word partition:

```bash
cd /home/chuxiao/spine-cycle-sim
python3 scripts/run_sst_grasu_regraph.py \
  --smoke \
  --out-dir results/grasu_regraph_sst_smoke
```

Pinned normalized run:

```bash
python3 scripts/run_sst_grasu_regraph.py \
  --out-dir results/grasu_regraph_sst_normalized
```

The runner writes `result.json`, `manifest.json`, `sst.log`, and per-channel
DRAMSim3 output. `manifest.json` records profile and workload SHA-256 hashes.
