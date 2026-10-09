# ReGraph Gather Forwarding and Source Cache

> Historical unit-weight milestone. The weighted PMA closure is documented in
> `grasu_regraph_weighted_dynamic_sssp_20260725.md`; the timing below remains
> the unit-weight regression baseline.

Date: 2026-07-25

## Result

This milestone closes two known structural gaps in the PMA-native GraSU +
ReGraph comparator:

1. ReGraph Gather now uses lane-local URAM banks and the HLS `L+1` RAW
   forwarding state rather than a synthetic `destination % bank` conflict
   model.
2. Source properties now travel through a finite request stream, an AXI/HBM
   reader, a finite 64-byte response stream, and two ping-pong BRAM windows.
   The PMA reader consumes the returned words; it does not inspect Python or
   C++ adjacency/state side data.

The updated architecture is shown in
`docs/figures/grasu_regraph_gather_source_cache.svg`.

## HLS Mapping

### Gather

`acc_gather.h` instantiates `dst_tmp_prop_buffer[GATHER_PE_NUM][rows]` with the
lane dimension fully partitioned. Unrolled lane `u` always reads and writes
bank `u`; destination only selects the row and 32-bit half. The simulator now
uses the same mapping, so `gather_bank_conflict_cycles` is structurally zero.

Each lane has `last_value[u][L+1]` and `last_index[u][L+1]`. The target build
defines `L=6`. The simulator searches the seven entries for the newest matching
row, reduces the new candidate, shifts only that lane's history for a valid
active tuple, and delays the physical URAM update by six cycles. The synthesis
report records gather-loop II=1 and iteration latency 9; the simulator therefore
also drains eight cycles before the output/clear sweep.

The targeted RAW workload forces:

```text
lane-local updates:       7
forwarding hits:          1
forwarding misses:        6
cross-bank reductions:    1
pipeline drain cycles:   24 (3 supersteps * 8)
SSSP oracle:           PASS
```

### Source cache

`acc_scatter.h` declares eight lane-duplicated, two-way BRAM buffers. Its
controller requests while `request_round - read_round <= 1`, receives one
512-bit line per response, duplicates that line into every lane, and blocks an
edge burst while `read_round >= write_round`.

`littleKernelReadMemory` handles each request with a fixed
`SRC_BUFFER_SIZE / 16` loop. For `SRC_BUFFER_SIZE=4096`, one request transfers
256 lines or 16384 bytes. Its synthesis report records iteration latency 331
and achieved interval 256. The simulator submits one 16384-byte AXI parent
read, receives its 64-byte beats online from `FixedAxiPort` and SST/DRAMSim3,
and cannot accept the next source-window request until the parent response
retires. Finite request and response FIFOs propagate backpressure.

A 4097-vertex component test forces the reader across the ping-pong boundary:

```text
supersteps:                 3
source-window requests:     9
64-byte response lines:  2304
source-cache wait cycles: 861
SSSP distance 0->4096->1:   2 (PASS)
```

The three requests per superstep are current window 0, lookahead window 1,
and window 2 after the read pointer crosses vertex 4096. This is deliberately
larger than a tiny-only test and proves that alternating slots are refilled and
consumed in order.

## Normalized SST Evidence

The same profile-pinned real `.slice` input/update pair used by the previous
finite-stream milestone gives:

```text
result:                         PASS
correctness mismatches:            0
total cycles:                  99379
GraSU update cycles:               62
ReGraph compute cycles:         99317
supersteps:                        2
source-window requests:            4
source bytes read:              65536
source response lines:           1024
lane-local BRAM writes:           4096
source-cache wait cycles:          559
gather pipeline drain cycles:       16
DRAMSim3 backend requests:        33838
backend max outstanding:             33
```

Compared with the previous 98970-cycle finite-stream result, cycles increase by
409 (0.41%). Backend requests increase by 1022 and compute reads increase by
65408 bytes because the old implementation read only two 64-byte aggregate
source chunks. The fixed source-window traffic is mostly hidden under the
98304-cycle partition reset/output sweep in this sparse workload. That is a
result of execution overlap, not a post-hoc subtraction: all source requests
now enter the same online memory backend and can contend with other traffic.

The normalized workload has no same-lane RAW recurrence, so it records three
bypass misses and zero hits. The dedicated RAW workload above is the positive
forwarding test.

## Claim Boundary

This closes the known source-cache-controller and gather-forwarding omissions
for the current unit-weight ReGraph path. It does not make the complete
comparator publication-ready.

The PMA payload still carries destinations only, so comparator SSSP uses unit
weights. Full PageRank and thresholded residual PageRank are not yet connected
to this PMA/ReGraph execution controller. The PMA-native reader is a normalized
architecture proposal and has not been synthesized as HLS. Real graph-suite
comparison, wall-clock simulator throughput, energy/PPA, and hardware
calibration also remain open.

The source HLS has eight Scatter/Gather lanes, while the normalized profile has
four lanes to match the pinned comparison resource budget. Both values remain
explicit parameters; results must state which profile is used.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
./build/cycle-core/cpp/grasu_cycle_tests
ctest --test-dir build/cycle-core --output-on-failure
python3 -m unittest discover -s tests
make -C cpp/sst -j2
python3 scripts/run_sst_grasu_regraph.py --no-build \
  --out-dir results/grasu_regraph_sst_gather_source_final_20260725
```

Regenerate the architecture figure with:

```bash
dot -Tsvg docs/figures/grasu_regraph_gather_source_cache.dot \
  -o docs/figures/grasu_regraph_gather_source_cache.svg
```
