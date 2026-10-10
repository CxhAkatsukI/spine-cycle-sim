# Original GraSU DDR RTL Validation

Read the [study report](../../experiments/comparisons/grasu_regraph_stage_validation/GRASU_DDR_RTL.md)
for the admitted matrix, raw evidence and limitations. This is an optional
XSim control, not a new mode of the production G+R model.

## Review Order

1. [Contract](../../../configs/experiments/original_grasu_ddr_rtl_v1.json):
   source16 geometry, source hashes, 12 cases, memory assumptions and exclusions.
2. [Package ownership](../../../spine_cycle_sim/experiments/grasu_ddr_rtl/README.md):
   preparation, execution, trace checks, state analysis and delivery are separate.
3. [Shared memory](../../../cpp/tests/grasu_ddr_rtl/shared_memory.sv): four AXI
   ports alias one store; finite request queues and one global beat-service
   arbiter. Read data is sampled at service, not at request acceptance.
4. [Independent memory selftest](../../../cpp/tests/grasu_ddr_rtl/memory_test.sv):
   delayed AW/W pairing, cross-port aliasing, response stability under pressure,
   queue saturation, single-service conservation and illegal transactions.
5. [Kernel bench](../../../cpp/tests/grasu_ddr_rtl/bench.sv): unchanged generated
   RTL, AXI-lite start, real stream handshakes, all memory events and full state.
6. [Source probe](../../../cpp/tests/grasu_ddr_rtl/source_probe.cpp): original
   C++ function, four aliased pointers, independent oracle, prefix/end guards
   and normal/repeated/UBSan execution.

## Timing Interpretation

The original inner loop polls sixteen streams with `II=1`; that does not mean
successive updates to one segment can finish one cycle apart. The enclosing
controller waits for the inner pipeline to complete before another sweep.
Use the actual AR/read/write/ack event trace to constrain a finite G model.
Do not replace it with a fitted multiplier on the number of updates.

`kernel_cycles` is observed `ap_done - ap_start`. `cycles` is the later
settled-state capture window and includes three declared bench-settling
cycles after completion/drain. Neither field is a measured FPGA cycle count.
The declared 5-ns synthesis target and finite test memory are not admission
of original-paper board frequency, DDR timing or achieved post-route timing.

The ordinary C++ core, SST plugin, old G/R controls and accepted A4/B model
are not edited or rebuilt by this control. HLS/XSim/GMP are optional external
dependencies; ordinary core tests remain usable without them.
