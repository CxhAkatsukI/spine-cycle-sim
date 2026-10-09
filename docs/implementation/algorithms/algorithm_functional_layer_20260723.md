# Shared algorithm functional layer

Date: 2026-07-23  
Branch: `codex/fine-grained-cycle-sim`

## Scope

The functional layer defines graph-update and algorithm semantics independently
from accelerator timing. It supplies the mathematical and architecture-numeric
oracles used to validate the later Spine and GraSU+ReGraph cycle models. This
commit does not claim that algorithm work is connected to timed FIFO, AXI, or
HBM components yet.

Implemented policies:

- weighted SSSP over a directed simple graph with non-negative integer weights;
- full PageRank with damping 0.85 and dangling-mass redistribution;
- thresholded residual PageRank with an `epsilon / N` activation threshold and
  dangling-mass redistribution.

All policies use the same `Map -> Reduce -> Apply -> Activate/Converge`
interface. Float64 is the high-precision mathematical path. Float32 rounds each
modeled arithmetic operation and is the architecture-numeric path. Exact HLS
bit-equivalence still depends on connecting the policy to the architecture's
actual reduction order and floating-point implementation.

## Dynamic graph semantics

`DynamicGraph` stores a directed simple graph. A batch is coalesced using
last-write-wins semantics. Upserts classify insert, weight decrease, weight
increase, or no change; deletion of a missing edge is a no-op. Weights are
non-negative integers.

`load_spine_edge_list()` loads real `.slice` files produced by
`scripts/extract_real_graph_slices.py`. Edge IDs in these files are already
zero-normalized. The `id_offset` metadata records how the original dataset was
normalized and must not be applied a second time.

The committed real-workload smoke fixture is
`tests/data/amazon_top1_exact.slice`, extracted from `amazon-2008.mtx`. It has
735,323 vertices and ten actual edge records from one active source; it is not
a synthetic edge count supplied only as a command-line parameter.

## Counters

The functional engine reports iterations, frontier sizes, mapped edges,
reduced updates, and vertices visited by Apply. Apply work is returned by each
policy through `IterationResult`; the engine does not infer it from an
algorithm name.

These are functional-work counters. They become timing evidence only after the
same operations generate requests and transfers through the C++ cycle core.

## Reproduction

From the repository root:

```bash
python3 -m unittest tests.test_algorithms -v
python3 -m unittest discover -s tests
cmake --build build/cycle-core
ctest --test-dir build/cycle-core --output-on-failure
dot -Tsvg docs/figures/fine_grained_cycle_sim_architecture.dot \
  -o docs/figures/fine_grained_cycle_sim_architecture.svg
git diff --check
```

The focused suite covers graph update coalescing, weighted relaxation, fixed
iteration work, dangling PageRank, residual PageRank convergence, float32
versus float64 comparison, and a file-backed Amazon workload.

## Deliberate follow-up

The next vertical slice must connect real edge payloads and algorithm work to
the stable Spine profile's maintenance, reader, AXIS, compute, AXI, and online
SST-HBM components. Incremental SSSP fallback rules, PageRank warm start, and
signed residual initialization are validated batch-by-batch in that path;
static functional correctness alone is not sufficient evidence for dynamic
execution correctness or performance.
