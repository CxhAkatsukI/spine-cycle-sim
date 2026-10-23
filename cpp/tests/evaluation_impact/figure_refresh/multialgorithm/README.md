# Three-Algorithm Figure-Data Harness

This directory owns the test-only direct-DRAMSim3 comparison harness, not a
production FPGA host or a new timing calibration. Review it together with the
[Python runner and validation guide](../../../../../spine_cycle_sim/experiments/evaluation_impact/figure_refresh/multialgorithm/README.md).

| File | Responsibility |
| --- | --- |
| `component.cpp` | SST lifecycle, shared memory backend, arm dispatch and final physical ledger |
| `sssp.hpp` | Thin reuse of the existing common-warm SSSP executor and independent Dijkstra inputs |
| `input.hpp` | CC union-find and double-precision PR oracles, shared old state, update projection and PR correction plan |
| `integrated.hpp` | Physical G-to-R PMA handoff, finite routed CC/PR execution, replica and byte conservation |
| `spine.hpp` | Existing Spine CC/PR systems, convergence/owner checks and explicit correction-replay disclosure |

Both arms start from the same converged old state and must reach the new
graph's independent oracle. All selected cases use eight user insertions;
CC requires reciprocal input and therefore sixteen physical update records.
Initial loading and independent oracles are outside the device window on both
arms. G updates the resident PMA that R subsequently reads, without rebuilding
the graph on the host.

For residual PR, routed R charges degree/state preparation and uses a banked
FP32 dangling reduction. The existing Spine correction path consumes an
oracle-generated correction plan and replays its timed memory work. Its
correctness and request checks do not establish functional AXI-derived seed
generation or FPGA timing equivalence. Keep this qualification in every export.

The Python runner freezes all C++ sources, runner sources, core libraries,
compiler, memory configuration, input identities and complete output states.
Its verifier rejects incomplete pairs and mixed model identities. It does not
infer CC/PR original-ReGraph performance parity from a passing SSSP control.
