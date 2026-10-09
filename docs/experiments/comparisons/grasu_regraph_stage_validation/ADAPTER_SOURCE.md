# Existing Adapter Source And A4 Wiring Control

## Conclusion

The existing sharded, destination-only HLS PMA adapter emits the complete
expected edge stream for all three admitted original-A4 graph inputs. Each
input passes two normal executions and one UBSan execution, with identical
complete packet captures and counters. The downstream A4 wiring extraction
also preserves all eight previously accepted executions exactly, including
state, cycles, memory/stall ledgers and task lifecycle; all three graph inputs
pass the A4 UBSan regression.

This is a **source-functional input control**, not the complete finite B
experiment. The adapter was not timed feeding A4. Device cycles, A4/B overhead
and publication-performance error are null. No approximately 10% publication
match, FPGA adapter-overhead result or system C conclusion follows from this
checkpoint. See the [current study status](README.md) for the remaining gates.

Accepted run: `results/upstream_stage_controls/adapter_source_final_v1`.
The [implementation guide](../../../implementation/grasu_regraph/original_regraph_adapter_source.md)
maps preparation, execution, independent validation, regression and delivery
to separate owners.

## Fixed Source And Input Boundary

The function is an unchanged copy of the integration repository's
`kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp`, matching frozen
revision `d886f42a730c5b75666fc51d8c1c246023b0f5cb`. Its SHA-256 is
`19fb4eb83c5495cbf8946463b21411fdaba6c9e6f6e0f867d4eeff4adc5a4404`.
This is the sharded CC destination-only source, not the different older
weighted SSSP adapter. The original HLS checkout is not edited.

The [contract](../../../../configs/experiments/original_regraph_adapter_source_v1.json)
fixes weighted mode off, destination-only and sharded modes on, and shared
memory ports on. Original-host graph loading, DBG, task order, destination
partitions, degrees, initial PR state and logical edges remain unchanged.
Within each original A4 task, source-grouped PMA rows store local destinations
in sixteen-slot segments, padded with the empty-slot marker.

Two input compatibility conditions are explicit:

- Boundary ring contains 64 repeated edge entries. The read-only PMA control
  preserves their multiplicity; it is not an admission of duplicate-edge
  updates through original GraSU host preparation.
- Three boundary tasks contain only original dummy entries. Each receives
  one empty reserved segment at its original dummy source, preserving task
  termination without adding a logical edge.

The PMA is constructed for this input-isolation experiment, not produced by
the original G host/kernel chain. Its task assignment follows A4, not the
routed K4 implementation's shard ownership or 23-channel placement.

## Complete Source Results

Counts below are per execution, not hardware service cycles or measured AXI
traffic. Physical entries include empty PMA slots emitted as dummy edges.

| Input | Vertices | Tasks | Logical edges | Physical entries | Row-read bytes | PMA-read bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Boundary ring | 131,073 | 12 | 131,137 | 2,097,216 | 12,583,104 | 8,388,864 |
| Skewed sources | 65,537 | 4 | 8,193 | 65,552 | 2,097,216 | 262,208 |
| Amazon | 735,324 | 48 | 5,158,388 | 43,560,256 | 282,364,800 | 174,241,024 |

All current tasks fit within the hot cache regions. Cold DDR routing and
selection between genuinely different current/stale physical copies are
**not covered** by these inputs and remain required stress cases before a
broad finite-adapter admission. The buffers currently contain identical
initialized copies.

C++ checks every data lane, keep/strb mask and TLAST, and independently compares
the complete logical multiset to the original tasks. Python separately
validates every row bound, slot, packet value/order, counter and full extent.
The Amazon packet capture alone contains 348,482,048 bytes; a final checksum
is not used as a substitute for these full comparisons.

## Extraction And Validation

`ComputeWiring<InputSource>` now owns the shared four-Little downstream.
`CompactSource` supplies only the original edge reader, input initialization
and task-start information; the existing `Wiring` name remains compatible.
The extraction preserves construction/registration order, queue capacities,
AXI credits, memory placement, independent task progress and drain checks.
Production numerical components and SST sources are unchanged.

Before editing, all eight A4 cases were freshly run against the frozen
accepted results. After editing, a fresh Release build passes all eight full
observations and 13 existing C++ tests. The three graph inputs also pass the
instrumented A4 build. The normal A4 cycles remain:

| Case | Cycles |
| --- | ---: |
| Boundary, normal/reverse registration | 113,714 / 113,714 |
| Boundary, two state AXI parents | 437,317 |
| Boundary, memory latency 128 | 118,247 |
| Skewed, normal/reverse registration | 35,506 / 35,506 |
| Amazon, normal/reverse registration | 886,840 / 886,840 |

All 33 bounded steps pass their declared exit gates. Six malformed inputs
and six actual-output corruptions are rejected; nine focused adapter tests
pass. There are no runtime UBSan diagnostics. GNU g++ 15.2.0 and Vitis HLS
2024.1 headers are recorded, along with binary/dependency identities.

Summed subprocess wall time is approximately 285 seconds, not device time.
Maximum individual-process RSS is 689,568 KiB, observed during the two-job
build. Runs are sequential with a 4-GiB address-space limit, 128-MiB stack,
16-GiB available-memory reserve and bounded timeouts. The RSS measure excludes
the orchestrating Python process and is not a simultaneous process-tree sum.
Additional evidence/organization checks are recorded in
[preservation verification](adapter_source_preservation.json). The earlier
SST/Spine and FPGA matrices are preserved, not claimed to be rerun here.
The broader Python regression plus organization checks pass 169 tests.
All 2,437 protected files and the frozen SST plugin retain their hashes;
the 173-file pre-edit baseline permits only the declared wiring extraction.
Four delivery-gate corruptions are rejected, including a fabricated non-null
adapter timing-overhead claim and an incomplete step matrix.

## Reproduce And Review

First reproduce the admitted [original-host input matrix](ORIGINAL_HOST_INPUTS.md).
Verify the archive/member hashes in
[delivery verification](adapter_source_verification.json), then extract the
baseline and pinned adapter source into a fresh location:

```bash
mkdir -p results/reproduce_adapter_source
tar -xzf docs/experiments/comparisons/grasu_regraph_stage_validation/raw_adapter_source.tar.gz \
  -C results/reproduce_adapter_source \
  baseline/baseline.json adapter/source/pma_to_regraph_adapter.cpp
python3 scripts/run_original_regraph_adapter_source.py \
  --adapter-source results/reproduce_adapter_source/adapter/source/pma_to_regraph_adapter.cpp \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --input-run results/upstream_stage_controls/reproduced_original_host_inputs \
  --baseline results/reproduce_adapter_source/baseline \
  --out results/reproduce_adapter_source/run
python3 -m unittest discover -s tests -p test_original_regraph_adapter.py
```

Replace the input-run argument with the fresh original-host run's path.
[Results](adapter_source_results.json) record the full matrix, raw paths,
source/binary identities and resource observations. The
[raw package](raw_adapter_source.tar.gz) retains logs, contract, source copy,
baseline and three nonaccepted preflights. Large PMA inputs, packet captures
and complete A4 states are hash-indexed and regenerable, not copied into Git.
Every indexed accepted input, packet and A4 observation was rechecked before
delivery. The archive has 365 members, 237,978 bytes and SHA-256
`c5845d1352bea56af3c38d36b47196e215c6ecb1ea5228158eafa0a5be8b93a8`.

The first preparation attempt rejected the boundary input's repeated edges;
its failure and duplicate audit are preserved. The contract was then made
explicitly multiplicity-preserving rather than silently deduplicating. The
second source preflight and separate shared-wiring preflight are retained
but do not replace the final complete matrix.

## Next Gate: Finite B

Feed a finite PMA producer into the same `ComputeWiring` downstream; do not
substitute a preconverted edge array. Hold downstream resources and logical
work fixed, test cold/stale-copy routing and empty-task termination, and
account for row reads, padded slots, finite AXI/FIFO backpressure, shared-port
contention and adapter/compute overlap. The considerably larger physical
input cannot be assigned compact-reader timing without evidence.

Only that complete A4/B comparison can estimate integration overhead under
its declared memory/timing assumptions. It does not by itself validate G's
temporal workload, original R's publication-selected topology, host C windows
or the original papers' performance.
