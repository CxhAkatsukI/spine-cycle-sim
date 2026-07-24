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
- 65536-word ReGraph destination partition.

The input and update are real `.slice` files, not command-line edge counts.
The initial graph has three edges; the ordered batch inserts one edge and
deletes one edge. GraSU mutates payload-backed PMA first. A completion barrier
then creates the ReGraph compute system on the same scheduler and backend.

## Normalized Evidence

```text
result:                    PASS
correctness mismatches:       0
total cycles:            272100
GraSU update cycles:          62
ReGraph compute cycles:   272038
supersteps:                   2
DRAMSim3 backend requests: 16432
backend max outstanding:      2
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
gather reset + merge cycles: 131072
apply reads / writes:      8192 / 8192 (64 B each)
compute read / write bytes: 525056 / 524288
```

The update ledger is two PMA 64-byte read-modify-writes plus update and row
records: 160 read bytes and 128 write bytes.

## Claim Boundary

This run is a normalized, execution-driven structural result. It is not yet a
publication-ready performance number.

The most important remaining timing error is now explicit. ReGraph's compiled
`Apply` loop is annotated `PIPELINE II=1`; the available HLS report gives a
pipeline depth of 100. The current simulator apply component is single-flight:
it waits for one 64-byte vertex-state read, computes, then waits for its write
before issuing the next read. Consequently `backend_max_outstanding=2` and the
272100-cycle total conservatively overestimates apply time. The next model must
use bounded outstanding reads, a finite depth-100 apply pipeline, and
overlapped writes before this timing is used against Spine.

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
