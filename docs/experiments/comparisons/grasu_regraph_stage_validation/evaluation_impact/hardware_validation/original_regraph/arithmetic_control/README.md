# ReGraph Arithmetic Control

## Question And Boundary

The original author 11+3 and A4 board controls run one static **fixed-point**
PR superstep (`arg=0`). Current production K4 uses binary32 PR, normally with
damping 0.85, base and dangling correction. They are not interchangeable
algorithms or bitwise-equal outputs. Original R's measured times alone cannot
establish current adapter/K4 performance retention.

This separate offline audit defines a narrower candidate control: the same
nonnegative integer input contributions, interpreted numerically as floats;
one FullPR round; damping `108/128`; zero base and zero dangling share. Compare
the resulting **source payload**, not the rank-state output, with the author's
integer output. Production sources/defaults are not modified or executed.

For gathered sum `S` and explicit divisor `d > 0`:

| Path | Formula |
| --- | --- |
| Original integer UDF | `floor(floor(108*S/128)*floor(65536/d)/65536)` |
| Candidate binary32 payload | `float32(float32((108/128)*float32(S))/float32(d))` |

Both return zero payload at `d=0`. Source word encodings differ even where
numeric outputs happen to match. The audit rejects signed intermediate
overflow, nonzero padding and sums/divisors beyond the exact binary32 integer
domain. With nonnegative integer contributions and sum at most `2^24`, any
reduction order has exact integer partial sums. The original output's gap
from the unrounded formula is independently bounded by
`1 + 1/d + floor(108*S/128)/65536`, excluding floating-point rounding.

## Fixed Matrix And Evidence

Recheck all six frozen layouts: 11+3 and A4 on boundary-ring, skewed-source
and Amazon, each with the original host's initial-property divisor and the
separate CSR-degree divisor. Recompute CSR/task conservation and the existing
fixed-point oracle hashes; do not regenerate the host layouts or conflate the
two bindings. Capture identities, reviewed source files and transitive runner
identities are recorded. The complete audit must retain all twelve bindings.

Terminal arithmetic admission is **not** hardware, performance, publication
match, default-semantic equivalence or an admission of any Fig. 7--11 value.
The pending FPGA control must independently verify the actual gathered values,
payload/rank outputs, topology, clocks, resource budget and event boundary.
Eight focused regressions cover arithmetic, domain/overflow/padding rejection,
source-anchor changes, full reference admission and memory-event rejection.

## Reproduce

Run the immutable committed Python owner from `hardware/semantics/`, with
the original source snapshot, clean production HLS checkout and unchanged
inputs available. Use a new output directory; existing failures stay intact.

```bash
systemd-run --user --wait --pipe --unit=original-r-arithmetic-fresh \
  -p MemoryMax=2G -p MemoryHigh=1792M -p MemorySwapMax=0 -p OOMPolicy=kill \
  -p CPUQuota=100% -p AllowedCPUs=123 -p RuntimeMaxSec=900 \
  --working-directory=/absolute/immutable-runner \
  /usr/bin/python3 -m spine_cycle_sim.experiments.original_regraph_execution.hardware.semantics.study \
  --inputs /absolute/admitted/input_results.json \
  --audit /absolute/original-r-preflight-v2 \
  --original /absolute/clean-author-regraph \
  --production /absolute/clean-production-hls \
  --output /absolute/fresh-arithmetic-audit
```

The owner requires the finite cgroup, zero swap, group OOM handling, a 32-GiB
available-memory reserve and zero memory-limit/OOM events. It cannot program
a board or change a compiler, simulator timing model, paper or frozen figure.
