# Empty-Helper Wait Sensitivity

This standalone K4-only fixture reuses the immutable SSSP real-input loader,
whole-graph output writer, and production `RoutedReGraphSystem`. It does not
change the frozen A4/K4 harness, v4 profile, numerical sources, or default SST
plugin. Configure into a fresh, uniquely named build directory:

```sh
cmake -S cpp/tests/routed_regraph/empty_segment -B /absolute/unique/build -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build /absolute/unique/build --target routed_regraph_empty_segment_round -j 2
/absolute/unique/build/routed_regraph_empty_segment_round INPUT OUTPUT LATENCY REVERSE MAX_CYCLES EMPTY_EXIT
```

`OUTPUT` must be an existing empty directory. `REVERSE` is 0 or 1; latency and
cycle budget must be positive. `EMPTY_EXIT` accepts only 73 (legacy v4 control)
or 0 (explicitly uncalibrated, unfitted empty-helper-bypass sensitivity).
Zero removes only the visited empty-row helper wait, justified by the
caller-guarded extracted-helper candidate RTL, not the earlier ineffective
inline guard. It does not remove row reads, row control, occupied or all-dummy
segments, or downstream backpressure. It is not a complete candidate RTL timing
model and admits neither FPGA calibration nor hardware/publication performance.

The resident one-round configuration matches frozen `run_k4`: 150 MHz,
32-channel Mock memory, 32 outstanding/response credits per channel, issue
interval 1, independent read/write credits, depth-32 adapter/Gather/mux streams,
and apply window 16. The actual routed model is unchanged; only the explicitly
selected invocation wait differs. It retains nine physical masters, unlike
original four-Little A4; AXI resources and the three-versus-four state-copy
publication costs are not resource matched.

The fixture verifies every aligned word in the primary and both source replicas
against the shared one-round oracle, active bits, request/beat completion, and
read/write traffic conservation (including the four-byte status write). It
emits the same `REAL_ROUND` actual-K4 fields as the frozen harness and a separate
`SENSITIVITY` line. Admission belongs to the runner: enforce exact four-partition
input identities, compare all three full-state files and every noncycle counter
across 73/0, and require 73 to reproduce frozen cycles/counters exactly. Preserve
the full declared matrix and failures. No speedup or additive cycle saving is
assumed from the removed wait.
