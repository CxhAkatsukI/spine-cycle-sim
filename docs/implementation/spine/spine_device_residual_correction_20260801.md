# Spine device-timed residual correction

## Scope

This revision closes the dynamic residual PageRank timing gap between accepted
updates and the first propagation round.  The old resident PageRank vector is
still an untimed pre-existing graph state, but update maintenance, correction,
seed publication, active-list publication, and propagation are now inside the
measured device window.

The immutable host-side `SpineResidualCorrectionPlan` is an oracle/work trace.
It supplies the expected old rank, old/new degree, seed, touched-source, and
active-vertex values used to validate the device execution.  It does not remove
the corresponding device work: the simulator issues and retires the rank,
degree, physical-edge, residual, and active-output AXI transactions before the
reader or compute pipeline can start.

## Timed path

For every dynamic Delta.hls residual PageRank run, the simulator executes:

1. preload the accepted old graph and old rank as resident state at zero time;
2. execute update maintenance and publish the new level state;
3. read old rank and old degree for each touched source;
4. read every post-maintenance physical edge record for those sources;
5. read the resident residual destinations, write new degree and seed words,
   and publish threshold-admitted active records;
6. release the reader and compute pipelines only after all correction AXI
   responses retire and the request ledger closes;
7. propagate to convergence and compare both architecture and mathematical
   oracles.

The graph reads use the actual family/level HBM addresses in the maintained
`SpineL0State`.  The correction and compute stages share the vertex-state AXI
master, so `SpineSplitPageRankCompute` has an explicit initial start gate.  This
prevents the compute stage from consuming a correction response and models the
serial port handoff without inventing a second memory master.

## Evidence and conservation

The SST result reports the correction cycles, touched sources, physical edge
records, seeded vertices, byte counts by state class, arithmetic operations,
and issued/completed requests.  A Delta.hls result is admitted only when:

- device correction is enabled;
- issued requests equal completed requests;
- the request total equals
  `3*touched + physical_edges + 2*seeded + active`;
- every byte ledger matches its corresponding record count;
- the active and touched sets match the oracle trace;
- propagation converges with zero architecture and mathematical mismatches.

The focused C++ test uses one touched source, one physical edge, one seeded
vertex, and one active record.  It closes 7/7 requests in 57 Mock-HBM cycles.
The SST insertion smoke closes 11 requests in 73 correction cycles and then
converges with zero mismatches:

```bash
cmake --build build -j8
./build/cpp/spine_cycle_core_tests spine_delta_hls_warm_residual
make -C cpp/sst -j8

python3 scripts/run_sst_spine_vertical.py \
  --out-dir /tmp/spine_device_correction_insert_smoke_20260801 \
  --scenario residual_pagerank \
  --workload tests/data/deltahls_sink_free_cycle8_base.slice \
  --update-workload tests/data/deltahls_sink_free_cycle8_insert_only.slice \
  --residual-contract deltahls_sink_free_linf_warm \
  --pagerank-epsilon 1e-6 \
  --validation-mode generic \
  --max-cycles 10000000 \
  --no-build
```

The frozen SST element hash for this evidence is:

```text
7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6
```

## Limitations

The correction arithmetic is execution-trace driven: memory requests,
finite queues, HBM timing, and port handoff are simulated, while the host
oracle trace supplies expected seed values.  The simulator does not parse HLS
source or execute the HLS C++ implementation directly.

The repository's existing delete-plus-insert eight-cycle fixture still exposes
the separate physical tombstone propagation limitation.  It is not accepted as
correction evidence.  Formal residual PageRank rows in this revision use the
paper's insertion-batch contract; SSSP/CC deletion fallback remains a separate
experiment and correctness gate.
