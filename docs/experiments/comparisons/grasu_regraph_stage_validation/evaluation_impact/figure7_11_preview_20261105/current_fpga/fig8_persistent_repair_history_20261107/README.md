# Figure 8 Repair History

This is the diagnostic record, not the final performance selection. The
[repaired V9 FPGA delivery](../fig8_persistent_repaired_20261107/README.md)
uses one fixed pair of executables across all eight cases. It never selects
the faster sample from these earlier candidates. The
[original V1 delivery](../fig8_persistent_once_20261107/README.md) is unchanged.

## What Was Wrong

The persistent wrapper serialized a compact initial graph, while the retained
hardware's carry writer used fixed physical addresses. Later carries could
write beyond the host allocation or overlap still-live compact data. Some
logical batches also exceeded a fixed per-family carry capacity. Merely raising
the initial bootstrap level did not fix either problem.

V9 uses the existing kernel-compatible fixed addresses, bounds device arenas
by the old graph, vertex domain and physical-launch budget, and uploads the
initial live regions directly there. A logical batch is split chronologically
into physical calls of at most 8,192 updates before sorting. This bounds L0 by
8,192 and its first two-way L1 merge by 16,384. Every physical call is timed.
The complete final initial-plus-insert graph oracle must pass.

The static graph is placed at L10, leaving L0--L9 for updates. This is a
declared change from V1's L2 and the earlier simulator's L4, not evidence that
all policies have identical performance. The current matrix has at most 1,000
physical calls; reaching static L10 requires 1,024 nonempty commits in a family.
This is finite headroom, not an unlimited-update guarantee. G still uses the
future trace union for PMA reservation, with its original setup costs charged.

## Host Optimization

After correctness was repaired, some AU batch-sweep points still lost. The
host was allocating/zeroing full maximum-domain scratch shadows and moving
unused data. V9 keeps full device capacities but uses compact CPU staging for
input and the required scratch prefixes. Aligned raw backing outlives its
OpenCL buffers. `CONTENT_UNDEFINED` residency does not transfer uninitialized
host memory; all subsequently consumed device state is initialized first.

- Dirty bitmap: zero `ceil(V/128)` 128-bit words for the fixed vertex domain.
- Family directory: upload `ceil(V/4)` words, including zero entries for
  initially absent sources. Masks come only from the old graph.
- Owner state: initialize through the existing lifecycle kernel.
- Graph: upload all live payload regions at fixed addresses; zero page epochs
  prevent consumers reading empty graph pages. Cold-bank carry page-base words
  are initialized even in initially empty banks.
- Metadata: retain the full initialized image, patch descriptors and migrate
  once. The lifecycle kernel has no metadata argument.
- Update inputs: upload each physical invocation normally. Dirty-list and
  bucket valid lanes are device-written before consumption.

The frozen kernel source is under
`/data/feiyang/spine-hls-repair-builds/baseline-20261008-clean345f3df-v1/source/src/`.
`spine_partitioned.hpp:7038` reads directory words; lines 7129--7158 implement
dirty bitmap read/modify/write; the carry path at line 5128 uses fixed graph
addresses; `spine_owner_state.hpp:602` initializes the vertex domain. These
locations refer to that frozen source, not a mutable development checkout.
Source hashes, compiler commands and exact host code are in each archive.
This reduced initialization is maintenance-only: it does not authorize later
domain expansion or propagation against uninitialized scratch.

Both sides still count initial layout/allocation/residency plus per-batch
preparation, DMA, launch and completion. No setup cost moved outside the timer.
Graph parsing, image programming, validation and logging remain excluded,
with the documented initial lifecycle status-check exception. No FPGA kernel,
clock or G implementation changed in these repairs.

## Earlier Attempts

[diagnostics.tar.gz](diagnostics.tar.gz) retains original journals, CSVs, raw
logs, clock receipts and frozen source archives from V2--V8, including losses
and failed attempts. Entries retain their original `fig8-fpga-persistent-*`
names. V2's `pilot` and `pilot-bounded` journals remained `PREPARING`, so they
are not completed measurements. V4's merged source journals identify its two
disjoint campaigns. Inputs and large binaries remain externally hash-indexed.

Archive SHA-256:
`e6b5efc1409e21d30c203c9644d1f4c34a74ccff351beddbc0ea895148e36684`.

| Candidate | Completed scope | G / Spine on AU 131K, 10 batches | Main change |
| --- | --- | ---: | --- |
| V2 | PK failed; two AU pairs measured | 0.386x | Initial fixed-layout repair |
| V3 | PK failed; one AU pair measured | 0.416x | Bounded arena refinement |
| V4 | Eight valid pairs | 0.850x | L10, safe physical calls, minimal unused active buffer |
| V5 | Eight valid pairs | 0.935x | Direct fixed-arena graph upload |
| V6 | Two AU pairs | 0.908x | Initialize only required scratch prefixes |
| V7 | Two AU pairs | 0.889x | Unbound scratch and single metadata upload |
| V8 | Two AU pairs | 0.920x | Compact CPU staging with unbound device buffers |

These are distinct code candidates, not repeated samples of one candidate.
Their times cannot be pooled or used for error bars. V9 replaces the unbound
buffer allocation path with explicit aligned backing while retaining compact
staging and complete required initialization. Its source-pinned full matrix
is the separate delivery linked above. A narrow single-sample win is not a
statistical guarantee of a win on every rerun.

## Figure 7 Impact

The repair is restricted to the Fig. 8 persistent maintenance wrapper and an
explicitly opted-in production-host maintenance constructor path. Default
resident-compute behavior is unchanged. Fig. 7 used separate host executables
and a propagation/convergence boundary; these wrapper repairs alone do not
invalidate its frozen measurements or require a Fig. 7 rerun. They also do
not convert this update-only experiment into convergence evidence.
