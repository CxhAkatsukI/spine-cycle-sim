# Weighted SSSP FPGA Stage Admission

The returned sharded K4 image passed the independent update (G) gate and both
weighted gather/apply (R) gates. Each row contains one measured run per arm,
without warmup or averaging.

| Stage and input | Public-source control (ms) | Integrated image (ms) | Integrated/control |
| --- | ---: | ---: | ---: |
| G: AskUbuntu, 131,072 updates | 18.413633 | 7.064731 | 0.38367 |
| R: Amazon, sparse weighted frontier | 10.404206 | 9.843290 | 0.94609 |
| R: Amazon, alternate weighted frontier | 10.591011 | 10.054087 | 0.94930 |

Both arms of each row used the same U55C and driver-reported clocks
`[150, 500, 450, 0]` MHz. G used `0000:c1:00.1`; both R rows used
`0000:82:00.1`. Time runs from the first participating CU start through the
last CU completion, including internal gaps. Setup/staging before that span
and final oracle readback are excluded. G's native oracle checked 716,992
packed words with zero mismatches. The independent public-source GraSU
control also checked its full PMA state.

The R reference is the public-source four-Little A4 implementation with the
weighted active-min algorithm and matching publication semantics. It is not
an unmodified ReGraph paper run or proof of identical physical resources.
Both R rows use the same Amazon graph (735,324 vertices, 5,158,388 logical
edges) with different matched weighted state and edge inputs. They produced
10 and 315,863 active outputs, respectively. They are separate workload
controls, not repeats or independent graph topologies. The R gate measures
one nonempty resident superstep, not convergence. Every candidate replica
and apply output matched the reference oracle after omitting the A4 guard
line (16 extra words); both reference and candidate retain their full
separate output dumps.

The integrated bitstream SHA-256 used for all three rows is
`1bb1532fd7b1bcb182ed9093e6640f6ab0fa6ae27707dcc509a7cc3881b61c25`.
The public R control SHA-256 is
`5185d9be6f0b889f8da107fb3a6d9b5d3d62d4affe4cfc6a1910833ddcfda3b4`.

## Evidence

[Raw evidence archive](sssp-stage-admission.tar.gz) preserves both R queue
and pair receipts, FPGA event logs, device and clock records, exact output
buffers and host provenance, plus both G receipts and logs. Absolute
paths in the captured reports refer to the run host; the archive
directories retain their original basenames. The reports pin the
external graph/fixture, hosts and bitstreams by SHA-256 rather than
duplicating them here. The production audit code is in
`spine_cycle_sim/experiments/original_regraph_execution/hardware/board_execution/`.

For a simple byte-level R replay after extracting the archive, run this in
each R evidence directory:

```sh
cmp pair/offline/expected.u32le pair/reference/expected.u32le
for output in pair/candidate/*.u32le; do
    cmp -n "$(wc -c < "$output")" pair/offline/expected.u32le "$output"
done
```

The exact same G/R image is now eligible for the weighted-SSSP paired
old-converged-to-new-converged matrix. This stage admission does not validate
the CC or ResPR images, establish an end-to-end speedup, or supersede the
existing figure data.
