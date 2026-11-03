# A4 Minimum-Label CC UDF Control

This is an **offline algorithm-interface check**, not a routed control or a
performance measurement. The public ReGraph A4 topology and source kernels
are the proposed reference; the local UDF is required because public CC
propagates OR masks rather than component labels.

- `l2.h` supplies the public template's UDF interface using the integrated
  CC active bit, zero gather identity and unsigned minimum label. The public
  Little scatter calls `preprocessProperty`, so this hook maps an inactive
  source to zero before the public gather's `IS_ACTIVE_VERTEX` filter.
- `verify.cpp` uses the pinned author's actual `fpga_application.h` macros.
  It checks active label zero, extreme labels, equality and quiescence,
  a long propagation chain, and 64 deterministic reciprocal insertion
  graphs. It starts each case from the old graph's minimum component
  labels and uses a separate graph traversal for the updated-graph oracle.
  The optional differential check directly compiles the integrated UDF and
  checks scatter, gather and apply across representative bit patterns.

Run from the simulator repository with the unchanged ReGraph checkout at
`365456826cef495285383d939907f847e05ad74b`:

```bash
cc_control=cpp/tests/original_regraph/hardware/cc_min_label
g++ -std=c++17 -O2 -Wall -Wextra -Werror \
  -fsanitize=undefined -fno-sanitize-recover=all \
  -I "$cc_control" -I "$AUTHOR_REGRAPH/acc_template/common" \
  "$cc_control/verify.cpp" -o "$OUTPUT/a4-cc-verify"
"$OUTPUT/a4-cc-verify"
```

For the integrated-UDF comparison, add `-DCOMPARE_INTEGRATED_CC
-Wno-unknown-pragmas -I "$INTEGRATED_REGRAPH/include" -isystem "$VITIS_HLS_HEADERS"`
and omit the sanitizer flags for that separate invocation. The checked
integrated source was commit `24519a6`, using Vitis HLS 2024.1 headers.

A hardware build needs separate pinning and a CC-capable host. Retain the
four-Little compact-edge topology and the public CC macros (unsigned vertex
property, no edge property or out-degree Apply input). Independently verify
the resulting Apply ABI, buffer bounds, convergence and published labels.
The existing PR-only board host and PR xclbin do not admit this test. The
offline harness does not validate HLS II, RTL scheduling, memory ports or
FPGA performance. A weighted-SSSP control needs a weight-bearing input path;
it cannot be obtained from this UDF change.
