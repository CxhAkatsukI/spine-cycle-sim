# Active-min A4 Board Control

This host runs **one superstep**, not old-to-new convergence. It keeps
the author host's four-Little task order and per-lane edge layout. It
expects an explicitly selected min-label CC or weighted SSSP device
build with `HAVE_VERTEX_PROP=1` and `HAVE_APPLY_OUTDEG=0`. The archived
PR bitstream has the opposite Apply flags; do not use it here.

- `input.hpp` checks exact task/CSR edge multiplicity (including weights),
  preserves the author's source order and padding, and validates that each
  eight-edge burst reads only one 4096-vertex source window. An independent
  CSR traversal computes one round from a caller-supplied state and verifies
  the strict-improvement active bit. It does not certify that the initial
  state is converged on a particular old graph.
- `control.cpp` reuses the guarded A4 launch and event clocks. Apply reads
  and writes its own old-state buffer in HBM 30. Readback verifies that
  buffer and each published wrapper replica against the same CSR oracle,
  and checks all source replicas and resident edge buffers unchanged.
- The binary input is the same A4 descriptor and pristine CSR/tasks as
  the PR host. CC adds `cc_initial.u32le`. SSSP uses the
  [weighted overlay format](../../../../../spine_cycle_sim/experiments/original_regraph_execution/sssp_real_round/README.md) (three
  files: `sssp_initial.u32le`, `sssp_weights.u32le`, `sssp_tasks.u32le`).
  State includes padding up to the complete publication extent.

## Offline Checks

From the repository root, with an existing, fresh `OUT` directory and
`ARCHIVED_A4` pointing to an admitted author capture:

```bash
src=cpp/tests/original_regraph/hardware/active_min
g++ -std=c++20 -O2 -Wall -Wextra -Wpedantic -Werror "$src/input_tests.cpp" -o "$OUT/input_tests"
"$OUT/input_tests" "$ARCHIVED_A4" "$OUT/fixture"
g++ -std=c++20 -O2 -DNDEBUG -Wall -Wextra -Wpedantic -Werror \
  -isystem /opt/xilinx/xrt/include "$src/control.cpp" -L/opt/xilinx/xrt/lib \
  -Wl,-rpath,/opt/xilinx/xrt/lib -lOpenCL -o "$OUT/control"
"$OUT/control" offline cc "$OUT/fixture" "$OUT/cc"
"$OUT/control" offline weighted_sssp "$OUT/fixture" "$OUT/sssp"
```

The archived Amazon A4 task set passed the exact layout check (735,324
vertices, 5,158,388 logical edges, 48 tasks). Both synthetic algorithm
fixtures passed; a board invocation without a lease was rejected before
programming. The legacy PR host produced byte-identical expected
publication for archived Amazon. This is input/host readiness, not a
timing or board result. The appropriate routed images and a supervisor
that pins their source, ABI and clocks are still required.
