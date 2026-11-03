# Weighted SSSP A4 Frontend Control

This is a **source adaptation and offline check**, not a routed control or
evidence of a timing ratio. The public ReGraph A4 checkout at
`365456826cef495285383d939907f847e05ad74b` has no weighted-SSSP UDF. Its Little
scatter also drops the high destination bits after localization and never
calls the weight-aware scatter hook. Reusing its PR, BFS or OR-mask CC
bitstream would not run the same weighted problem.

The adaptation retains the public A4 four-Little dataflow, the compact
64-bit edge record, eight edges per 512-bit read, stream depths, source
cache, gather/merger and Apply templates, and bank assignments. It changes
only the Little frontend's decoding and selects the weighted UDF used by
the integrated image. The source word is unchanged. The host must supply
the destination word as partition-local destination in bits 18:0, positive
weight in bits 30:19, and padding flag in bit 31. Scatter moves that flag
to bit 19 in the gather-facing word, stripping the weight. The task's
global destination offset still goes to the original publication path.
No extra edge array, read port, or transfer is introduced.

| File | Responsibility |
| --- | --- |
| `prepare.py` | Check pinned source/UDF hashes, derive two frontend files in a fresh directory, and record input/output hashes |
| `edge_word.hpp` | Shared word layout for host packing and scatter decoding |
| `verify.cpp` | Execute the derived scatter with Vitis C-simulation headers and compare warm insertion convergence against independent Dijkstra |

The checked UDF is the local weighted extension in the integrated build's
`REGRAPH_ROOT/acc_udfs/sssp/l2.h`, not a public-author file. The SHA-256 is
checked by the derivation script. From the simulator repository:

```bash
ctrl=cpp/tests/original_regraph/hardware/sssp_weighted
python3 "$ctrl/prepare.py" "$AUTHOR_REGRAPH" "$INTEGRATED_SSSP_UDF" "$OUTPUT"
flags=(-std=c++17 -I "$OUTPUT" -I "$AUTHOR_REGRAPH/acc_template/common"
       -I "$AUTHOR_REGRAPH/acc_template/kernel_little_gs"
       -isystem "$VITIS_HLS_HEADERS" -isystem "$VITIS_HLS_HEADERS/etc"
       -DHAVE_UNSIGNED_PROP=1 -DHAVE_EDGE_PROP=1 -DHAVE_VERTEX_PROP=1
       -DHAVE_APPLY_OUTDEG=0 -DPARTITION_SIZE=65536
       -DLITTLE_KERNEL_DST_BUFFER_SIZE=65536 -DSRC_BUFFER_SIZE=4096
       -DLOG2_SRC_BUFFER_SIZE=12)
g++ -fsyntax-only "${flags[@]}" "$OUTPUT/kernel_scatter_gather.cpp"
g++ -O2 "${flags[@]}" "$ctrl/verify.cpp" -o "$OUTPUT/verify"
timeout 10s "$OUTPUT/verify"
```

Use the Vitis HLS 2024.1 distribution's `include/` directory. The test
executes the derived scatter, not an independent copy, then composes the
public UDF hooks for gather/merge/apply. It checks eight distinct lanes,
weight bounds, dummy, unreachable and saturated updates, and propagation
from an old converged distance vector after a batch of insertions. It does
not exercise the actual HBM wrapper, HLS scheduling or routed streams.

A separate host must pack the full task input and reject out-of-partition
destinations, weights outside 1--4095, or invalid burst/source-window
alignment. Use the original A4 task layout and independently verify packed
task edge/weight equality against the logical graph. The route still needs
a fresh variant manifest, verified port bindings and compiled Apply ABI,
timing, per-replica correctness, and a one-shot board measurement. The
existing PR board control cannot launch this variant.
