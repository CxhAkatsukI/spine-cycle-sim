# Original ReGraph Whole-Graph Execution

This package owns the fixed A4 validation over admitted author-host inputs.
It is separate from production SST, the ported K4 implementation, and the
original-publication performance-match gate. Whole-graph correctness does
not establish realistic HBM timing or the original mixed topology's speed.

| Module | Responsibility |
| --- | --- |
| `preparation.py` | Admit delivered input identities and encode bounded binary task descriptors |
| `resource_evidence.py` | Resolve instantiated original HLS AXI capacities, not template defaults |
| `study.py` | Fixed cases, isolated build, bounded execution and immutable run identities |
| `analysis.py` | Complete state/work/memory/path gates, repetitions and resource sensitivity |
| `regression.py` | Exact old component and full original-source comparison outputs |
| `negative_controls.py` | Deliberately damaged copies with required rejection diagnostics |
| `instrumentation.py` | One independent UBSan build over all three graph inputs |
| `delivery.py` | Recheck raw evidence and package logs/indexes without large captures |

The thin CLI is `scripts/run_original_regraph_a4.py`. C++ input decoding,
wiring/partition progress, and execution/observation are separate units in
`cpp/tests/original_regraph/whole_graph/`; existing numerical components are
reused unchanged. Read the [study results](../../../docs/experiments/comparisons/grasu_regraph_stage_validation/A4_GRAPH_EXECUTION.md)
and [implementation contract](../../../docs/implementation/grasu_regraph/original_regraph_a4_execution.md)
before changing resources or interpreting cycles. The accepted report, not
a `final` suffix, determines whether a run passed.

The separate [mixed owner](mixed/README.md) connects the artifact's 11+3
example. It audits original output allocation and explicitly declares any
zero-extension control; it does not change this A4 executor or establish
publication timing by comparing two model totals.
