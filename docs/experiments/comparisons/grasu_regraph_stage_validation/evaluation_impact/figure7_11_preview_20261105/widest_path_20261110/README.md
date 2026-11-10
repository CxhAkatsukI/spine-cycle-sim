# Widest-path AU and roadNet-CA Pilot

**CPU reference complete; FPGA comparison not measured.** This supplement
does not change the paper, Fig. 7, or the previously frozen handoff. It does
not contain FPGA latency, speedup, or new simulator timing.

## Inputs And Results

Reuse the byte-identical weighted Fig. 7 AU and RN graph/batch files; interpret
each positive edge weight as capacity instead of cost. The graph is directed,
the source is fixed, and both arms receive the same eight insertion records.
The input hashes and retained paths are in [inputs.sha256](inputs.sha256).
The shared G+R edge format admits positive capacities up to 4095. Unreachable
vertices have width zero; the source is fixed at the largest 32-bit unsigned
value. An edge from `u` to `v` contributes `min(width[u], capacity)` to
`v`; destination reduction is max.

| Dataset | Allocated vertices | Old arcs | Source | Changed widths | CPU propagation waves | Board pair |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| AU | 515,281 | 390,847 | 11 | 1 | 1 | Not run |
| RN | 1,971,281 | 5,533,214 | 0 | 12,328 | 348 | Not run |

The max-heap oracle recomputes the exact old and updated solution independently.
A second algorithm starts from that old solution, seeds the insertions, and
propagates improvements in frontier waves. They agree on **every** vertex in
both graphs and the directed [fixture](fixture.graph). AU's single improved
vertex has no outgoing arcs; use AU as a smoke, not as evidence for propagation
performance. RN exercises propagation. Wave and edge-visit counts in
[cpu_reference.csv](cpu_reference.csv) describe this CPU traversal, not either
accelerator's round or memory-traffic counters. CPU time is not reported as an
accelerator result.

## FPGA Readiness And Boundary

- Spine already has a generalized `positive-bottleneck` binding, not merely
  an SSSP build with different input weights. The retained software-emulation
  pass lists ten cases, and there are three synthesized `.hw.xo` objects.
  Neither is a routed board image. See [prior_artifacts.sha256](prior_artifacts.sha256)
  for the available evidence.
- The Fig. 7 G+R weighted image implements saturating addition and min
  reduction. It cannot do widest path by changing the workload file. The
  G+R implementation needs a matching bottleneck policy and checkpoint/result
  handling; keep the existing sharded PMA/streaming topology and validate any
  changed interfaces. No runnable G+R widest-path image was identified.
- Both U55C devices reported ready in XRT; no widest-path image was loaded.
  Local available memory was 17--35 GiB during the checks, with no swap;
  no routing job was started.

For a paired board run, preload each image's own representation of the same
old graph and the oracle's exact old widths. Start the host timer before any
batch-dependent preparation; include batch transfer, maintenance, all
propagation to convergence, orchestration, waits, and final result readback.
Exclude old-graph preload/bootstrap and the CPU correctness comparison from
both timers. Keep actual clocks, rounds, host/device breakdown (if
available), and compare every decoded final width against the CPU reference.
Run AU once as the paired pilot, then RN. Do not report a speedup if either
arm fails correctness or convergence.

## Reproduce The CPU Reference

From this directory on the input host, run `bash verify.sh` (C++17 compiler
and Bash). It verifies both input hashes, rebuilds the oracle, compares all
three rows, and checks every fixture width against explicit expected values.
The optional third argument of the compiled `cpu_reference` executable
writes a TSV of old/new widths, indexed by vertex, for host checkpoint
preparation and readback comparison. Large graph and state arrays are not
duplicated in Git. The state fingerprints hash little-endian 32-bit widths
using FNV-1a; full-state equality, not the fingerprints, determines PASS.
