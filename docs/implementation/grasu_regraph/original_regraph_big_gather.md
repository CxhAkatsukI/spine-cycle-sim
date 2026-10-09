# Original Big Routing And Gather

These components extend the isolated `original_regraph_cycle` library. They
do not replace Little, change production Spine/G+R/SST, or establish original
ReGraph publication timing. The [study checkpoint](../../experiments/comparisons/grasu_regraph_stage_validation/BIG_ROUTING_GATHER.md)
owns numerical evidence and remaining work.

## Ownership

| Boundary | Public header / implementation |
| --- | --- |
| Big geometry and declared timing | `original_regraph/big_types.hpp` |
| PR dispatch and 2x2 sender/receiver switch | `big_routing.hpp` / `big_routing.cpp` |
| One independently drained destination bank | `big_gather.hpp` / `big_gather.cpp` |
| Eight-bank result packing and multi-Big global merge | `big_merge.hpp` / `big_merge.cpp` |
| Test topology and fixture/oracle | `cpp/tests/original_regraph/big_network.hpp` |
| Functional, resource, reuse and port tests | `big_tests.cpp` |
| Complete original-source word comparison | `big_comparison.cpp` |
| Independent unmodified author-function capture | `cpp/tests/publication_sources/regraph_big_gather_probe.cpp` |

The Python owner is
[original_regraph_validation/big](../../../spine_cycle_sim/experiments/original_regraph_validation/big/README.md).
Preparation, execution, analysis, regression and delivery remain separate.

## Data And Control

The selected original PR application defines `IS_ACTIVE_VERTEX` as true.
Dispatch therefore sends all eight tuples, including zero-valued and dummy
ones, followed by one explicit end token per lane. It does not silently use
an SSSP activity predicate.

Three omega layers inspect destination bits 2, 1 and 0, respectively. Each
layer has four 2x2 switches with original inputs `(0,4)`, `(1,5)`, `(2,6)`,
`(3,7)` and consecutive output pairs. Each switch has four independent
sender-to-receiver FIFOs. The receiver gives its first input priority over
its third and its second over its fourth, exactly as the author C function.
Two input ends become four route ends and then two output ends; no end token
is mistaken for an update or a dummy.

Bank `d & 7` holds destinations with that low-three-bit identity. Its row is
`d / 16`; bit 3 selects the low/high 32-bit value of a 64-bit row. The eight
banks together cover 524,288 destinations using 2 MiB of logical storage,
not eight private copies of a 524,288-value array. Dummy bit 19 suppresses
the memory update. Wrong-bank tuples and destinations outside the admitted
20-bit local format are rejected.

Each bank has four forwarding entries, a finite update pipeline and delayed
URAM writes. After its end token, it waits for accepted updates/writes to
complete, drains all 32,768 rows and clears each row. Banks progress and
backpressure independently. The packer emits low values for banks 0..7 then
high values for banks 0..7, matching the author's `writeResults`. The global
merger adds corresponding words from the configured Big paths.

## Explicit Assumptions

The default routing-layer and switch-internal queues have depth two;
dispatch queues have depth sixteen, bank-pair queues four and packed/output
queues eight. The latter is an explicit finite AXIS assumption, not a
recovered original wrapper/controller depth. All queues are registered:
same-edge retirement does not create same-edge acceptance capacity.

The switches reserve output capacity before popping their inputs and use
an atomic four-way end broadcast. The author C functions use blocking
writes; exact synthesized global-stall/partial-write timing is not modeled
by this transaction-reservation rule. PR addition is order-independent in
the admitted, non-overflowing fixture domain, but that functional agreement
does not prove exact RTL scheduling.

Declared pipeline `(latency, II, capacity)` values are Gather `(6,1,7)`,
URAM write `(3,1,4)`, drain `(3,1,4)`, pack `(1,1,2)` and global merge
`(4,1,5)`. These are transparent finite-model assumptions informed by source
and prior HLS schedules, not calibrated FPGA cycles. A nominal 210-MHz clock
does not admit the original paper's graph-selected routed clock or topology.

The boundary starts at already prepared PR update bursts and ends at one
complete 524,288-value global-merger partition. Edge/source AXI service,
Big cacheline request/response protocol, original mixed scheduling, Apply,
writeback and host work are excluded. The original free-running merger is
observed for one partition prefix; the source probe does not claim it
terminated. `SW_EMU` initializes the author's local arrays on each call;
separate model reuse checks and the source's explicit drain/clear loop are
the evidence for the modeled clear behavior, not an RTL reset test.
