# Hardware Comparison Contract

This is a scope audit for the active repair, not a passing performance result.
The [repair README](README.md) owns measurements, gates and execution status.
No earlier figure checkpoint establishes current baseline-performance parity.

## What The Initial R Control Measures

Both arms consume the same logical edges, source contributions and CSR degrees
from the frozen A4 inputs. Amazon has 735,324 vertices and 5,158,388 logical
edges. Vertex mapping in the PMA arm is reversed for correctness checks; it
does not change the logical graph. The skewed-source fixture is also declared
before measurement. The boundary-ring input has 64 duplicate edges and stays
unsupported; it is not deduplicated to obtain a passing row.

Each supported arm executes one resident gather/apply superstep. The timer
runs from first CU start to last CU end and includes gaps inside that envelope.
Initial input upload, restoring the initial state and final readback are
outside both arms. An adapter stalled by downstream backpressure remains in
the measured interval; overlapping event durations must not be summed.

This is not old-converged-state to updated-batch convergence, nor is it a
standalone measurement of adapter latency. The later Spine comparison must
independently enforce the former boundary and initial/stopping-state checks.

## Resources And Arithmetic

| Property | Public-source A4 control | Actual integrated R control |
| --- | --- | --- |
| Little frontends | Four; no Big | Four; no Big |
| Edge input | Compact task arrays on HBM 0/2/4/6 | Destination-sharded PMA through four adapters, graph banks 0--22 |
| State reader | Four independent source-bank paths on HBM 1/3/5/7 | Two shared paths on HBM 23/24, each serving two frontends |
| State publication | Four source/output replicas | Two source/output replicas |
| Amazon tasks | 48 original tasks | 12 destination shards, assigned modulo four |
| Merge path | Original four-input Little merger | Frontend mux and the integrated shared merger/apply path |
| Apply arithmetic | Public-source signed/fixed-point integer operations | Binary32 degree/correction path |

The initial controls restrict contributions and sums to exactly representable
integers at most 2^24. They check the same gathered work but retain separate
integer and floating-point Apply oracles; published outputs are not generally
bit-identical across those two arithmetic policies. The candidate checks the
unrounded gather sum in residual state as well as its degree-scaled output.
This supports a bounded gather/apply implementation screen, not equivalence
of all original PageRank numerical behavior or all algorithms.

The actual ResPR design has 32 AXI-master instances: four search, two cache,
eight DDR-update, one degree-update, eight adapter, two shared-state, three
Apply and four source-prepare masters. Its checked platform budget is 32.
The state-path sharing is therefore an implementation/resource difference,
not merely a bank-number rename. The current adapter-only repair preserves
all these counts and the other eleven production XOs. Increasing resources
or changing the reference must be a separately declared experiment.

Resource evidence is the frozen original control's
`a4-source-route-v2/build/placement/connectivity.cfg`, the production
`route-zfs-v2/respr/{link.cfg,master-budget.json}`, and
`kernels/regraph_k4_shared_hbm_wrapper/kernel_hbm_wrapper.cpp` in HLS commit
`24519a6`. Full absolute artifact roots are in the repair README and manifests.

## Admission Limits

- A measured ratio at most 1.15 on both supported R controls would establish
  performance retention only for those declared controls and configurations.
  It would not establish identical resources or reproduce the original
  publication's graph-selected 11-Little/3-Big performance.
- Actual image UUID and driver clocks must accompany each new timing. Raw
  elapsed time is not silently normalized to the requested clock. Different
  measured frequencies remain visible in the evidence.
- Independent G rows use the earlier frozen weighted-SSSP four-control
  campaign, whose per-run driver clocks were not captured. They do not
  certify the CC or ResPR images; see [G scope](G_SCOPE.md).
- Passing the repaired ResPR screen does not admit unbuilt SSSP/CC images.
  Algorithm-specific functional gates, routed images and convergence tests
  are still required before replacing their evaluation data.
- A one-superstep retention result alone cannot bound changes to every
  convergence run, host-inclusive throughput, memory/energy ledger or fitted
  stage model in Figures 7--11. Each affected figure needs matched measured
  bounds or newly generated data with the appropriate evidence label.

If the 1.15 gate fails, retain that failure and repair a demonstrated remaining
bottleneck. Neither matching a total system time nor a simulator prediction
can waive this hardware-performance gate.
