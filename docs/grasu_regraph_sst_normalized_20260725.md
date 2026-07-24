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
- apply state on HBM[30] and ping-pong source-state copies on HBM[1]/HBM[3].

The input and update are real `.slice` files, not command-line edge counts.
The initial graph has three edges; the ordered batch inserts one edge and
deletes one edge. GraSU mutates payload-backed PMA first. A completion barrier
then creates the ReGraph compute system on the same scheduler and backend.

## Normalized Evidence

```text
result:                    PASS
correctness mismatches:       0
total cycles:            115012
GraSU update cycles:          62
ReGraph compute cycles:   114950
supersteps:                   2
DRAMSim3 backend requests: 32816
backend max outstanding:     32
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
apply reads / writes:      8192 / 8192 (64 B each)
source-state writes:            16384 (two copies, 64 B each)
apply max read / write in-flight: 32 / 32
apply max pipeline occupancy:    100
apply read / pipeline / write stalls: 12 / 7944 / 7942
compute read / write bytes: 525056 / 1572864
```

DRAMSim3 independently records 8192 writes on each of HBM[1], HBM[3], and
HBM[30]. This closes the previous memory-ledger omission: the old model counted
only the local apply-state copy and therefore missed two thirds of ReGraph's
state-write traffic. Backend requests rise from 16432 to 32816, but total
cycles remain 115012 because the three HBM channels accept the writes in
parallel. The correction changes traffic, channel utilization, and future
energy estimates even though it does not change this workload's critical path.

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

This closes the known single-flight and missing-state-copy errors. The explicit
AXIS path from gather output through the merger and apply to the HBM wrapper is
still collapsed into phase barriers. In particular, the synthesized
`write_out` loop has II=1 and iteration latency 71, but its stream latency and
tail are not yet represented. The dominant modeled term is now the 98304-cycle
gather reset and output/merge work. Its phase ordering and inter-kernel stream
overlap must be validated before a Spine speedup claim.

Other open boundaries remain unit-only PMA weights, idealized gather RAW
forwarding, no PageRank controllers on the comparator, and no HLS synthesis of
the PMA-native reader.

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
