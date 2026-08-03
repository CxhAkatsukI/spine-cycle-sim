# Spine Architecture and Evidence Crosswalk

**Owning repository:** `spine-cycle-sim`
**Audit date:** 2026-07-31; superseding alignment update: 2026-08-03
**Purpose:** provide a paper-editing authority for distinguishing the architecture
described by the Delta.hls manuscript from the native Candidate10 HLS prototype,
the opt-v2 HLS optimization, and the architecture actually used by the formal-v7
cycle-level performance experiments.

The manuscript audited here is `/home/chuxiao/texpage-deltahls`; unqualified
`sections/...` paths below are relative to that repository.

## 0. Superseding 2026-08-03 alignment authority

The detailed formal-v7 audit below remains useful historical evidence, but its
paper paths and several active-set statements predate the device-timed
correction. New alignment work is governed by the machine-readable contract:

```text
configs/contracts/spine_paper_architecture_alignment_v1.json
contract SHA-256: 6358e13196d7c65007eb0c49b198ecae5e9935b7feacaa6d0faa78ed41ecc8b2
paper revision: dc34c54574b645273106eb974a3fa5b78f380c03
```

That paper revision now describes the evaluated 16-cold plus 16-hot family
organization, endpoint-keyed records, device-generated active membership, and
host re-binning/relaunch outside the device-cycle interval. The contract is the
fail-closed authority when the historical prose below disagrees with it.

Progress since the original audit is explicit:

- the simulator now times device-generated SSSP/CC active frontiers and
  Residual PageRank correction, seed, and active publication;
- the routed refactor31 HLS artifact implements a device dirty frontier, HBM
  active bitmap, bounded split streams, and segmented exact fallback at
  160 MHz;
- the exact refactor31 source was reconstructed on
  `codex/paper-architecture-alignment` from base revision `cc7e3f95` and the
  frozen source diff;
- the alignment branches now host-test the per-key `queued/in_flight/dirty`
  owner scheduler, lossless reactivation protocol, and work-credit quiescence
  in both simulator and HLS source; synthesis and route remain pending;
- dormant-ID vertex activation and validity-bitmap deactivation are now
  host-tested in both alignment branches but are not part of the routed
  refactor31 artifact;
- Full PageRank now generates its source domain on device, while all four
  policies share the bounded HBM16 family-directory and HBM18 source-spool
  reader protocol; all four reader variants compile as U55C `sw_emu` XOs; and
- payload-distinct parallel weighted edges remain a separately versioned
  extension because refactor31 groups records by `(src,dst)`.

The refactor31 profile is a preliminary FPGA calibration baseline. It must not
be used as the final paper-aligned architecture or silently mixed with the
150-MHz target profile.

This document is intentionally conservative. It does not say that the current
results are invalid. It says exactly which artifact supports each claim, where
the artifacts agree, and where the manuscript currently describes a broader
system than the one used for performance evaluation.

## 1. Executive decision

The performance simulator is **HLS-derived and mechanism-aligned**, but it is not
a cycle-for-cycle model of one complete, single HLS/xclbin artifact. The formal-v7
Spine results combine:

1. the native Candidate10 maintenance, reader, memory layout, stream, and
   compute lineage;
2. two bounded reader optimizations implemented in HLS (opt-v1 and opt-v2);
3. a later hot-promotion behavior correction with an HLS reference;
4. execution-driven models of finite FIFOs, AXI requests, HBM service,
   backpressure, and algorithm execution; and
5. host/simulator orchestration for parts of active-set construction, repeated
   frontier rounds, PageRank input preparation, and recovery from device-dirty
   limits.

The manuscript, by contrast, specifies a larger target design: generic
full-record identity, 16 modulo-owned destination families, a complete signed
cross-level latest-view resolver, shadow descriptors and atomic topology-bank
publication, a fully device-resident active-key scheduler, work credits, and
three generated algorithm policies.

The recommended paper narrative is therefore a **two-layer narrative**:

- **Target architecture:** the complete compiler/architecture design specified
  in Sections 3--5. Mechanisms not present in the evaluated artifact must be
  labeled as target, proposed, or not yet evaluated.
- **Evaluated architecture:** the frozen formal-v7 opt-v2 Spine model. This is a
  bounded, execution-driven, HLS-backed proposed accelerator configuration,
  not an FPGA timing measurement and not a complete implementation of every
  target mechanism.

The main end-to-end figure must be attributed to the evaluated architecture.
Native Candidate10 should be used as implementation lineage and hardware
validation evidence, not as the identity of the plotted opt-v2 data.

## 2. The four artifacts that must not be conflated

| Layer | Frozen identity | What it establishes | What it does not establish |
|---|---|---|---|
| Manuscript target | `sections/03NN_compiler_lowering.tex`, `04NN_latest_view_hierarchy.tex`, and `05NN_transactional_execution.tex` | The intended compiler contract and complete architecture semantics | That all modules are implemented, routed, or represented in the formal-v7 timing results |
| Native Candidate10 | profile `spine_candidate10_one_pass_1e61fc0`; `reduce-levels-for-routing`; revision `1e61fc0822608f8776399cc10a851f6fe5806f92`; frozen dirty-source hash is authoritative | Routed U55C weighted-SSSP prototype; 16 cold partitions plus 16 hot shards; 11 ratio-2 levels; split reader/maintenance and compute; 23 HBM pseudo-channels; selected hardware behavior and timing evidence | Generic full-record semantics, complete target transaction controller, all three algorithm HLS shells, or opt-v2 performance |
| opt-v2 HLS | `codex/source-page-working-set-cache`; revision `c338b323d95707b7b5a84f622795439004a7f013` | Bounded fallback metadata reuse, finite source-page cache, 32,768-record exact-path gate, HLS RTL/resource evidence, and a later routed weighted-SSSP core at 150 MHz | A routed complete three-algorithm Delta.hls system or exact identity with every formal-v7 behavior |
| Formal-v7 performance simulator | contract `large_graph_publication_campaign_fullgraph_v7_20260730`; opt-v2 profile plus skip-fit behavior; simulator source commit `c22a59a3369a128faa116896d4d801f9698ffe52` | Execution-driven cycle estimates, correctness-gated algorithm results, finite queue/AXI/HBM behavior, traffic, and component activity for the frozen normalized comparison | FPGA-measured E2E latency, host-inclusive wall time, or a proof that every target-only mechanism has been implemented in HLS |

Two provenance qualifications matter:

- The native profile points to a dirty source snapshot. The frozen HLS source
  hash and xclbin hash are stronger identities than the Git revision alone.
- The opt-v2 architecture profile still says `synthesis_only`, but the later
  PPA-v4 evidence records a routed weighted-SSSP opt-v2 xclbin at 150 MHz with
  `WNS = +0.003 ns`. The profile metadata is stale; the later route supersedes
  only the feasibility status, not the remaining functional gaps.

## 3. Terminology that the paper must use consistently

### 3.1 Native

`native` means behavior and parameters inherited from the routed Candidate10
prototype. It does not mean the complete architecture described by the paper.

### 3.2 Normalized

`normalized` means a comparison configuration that places Spine and
GraSU+ReGraph under a shared platform contract: the same nominal clock, HBM
backend and geometry, finite AXI/FIFO rules, algorithm semantics, and explicit
resource parameters. Normalization is for a scientifically controlled
architecture comparison. It is not evidence that either side is an unchanged
copy of its original HLS implementation.

### 3.3 opt-v2

`opt-v2` is not merely a fair-parameter normalization. It is a bounded Spine
microarchitecture optimization on top of Candidate10:

- opt-v1 reuses the finite launch-level directory cache in the fallback path;
- opt-v2 adds an 11-entry source-page cache for the current fixed family,
  cleared on every fixed-family invocation or fallback tile pass; and
- opt-v2 enlarges the exact-path active-record gate from 16,384 to 32,768
  records, adding 393,216 logical bytes of on-chip working storage.

These changes have HLS semantic and synthesis evidence. The source-page cache
and larger gate are not ideal or unbounded simulator shortcuts.

### 3.4 Formal-v7 evaluated Spine

The plotted Spine system is more precisely:

> Candidate10 opt-v2 with the formal-v7 skip-fit hot-promotion correction,
> evaluated by the execution-driven cycle-level simulator under the frozen
> normalized platform contract.

It should not be shortened to `native HLS` in the Evaluation section.

### 3.5 Measured, simulated, and projected

Use these terms as follows:

- **simulated execution:** a completed cycle-simulator run;
- **projected result:** a total extrapolated from a stopped prefix or validated
  preflight under the documented stability rule;
- **strict lower bound / timeout:** completed prefix proves only that execution
  exceeds the stated bound;
- **FPGA measurement:** a result observed by running an xclbin on the board.

Calling a completed simulator run merely `measured` is ambiguous. Figure text
should say `completed simulated execution` unless it is explicitly contrasting
that result with a projection inside the same simulator.

## 4. Summary crosswalk

The classification column uses:

- **A -- aligned:** the evaluated simulator and HLS lineage implement the same
  essential bounded mechanism;
- **B -- HLS-backed optimization:** implemented and costed in HLS, but not part
  of the native Candidate10 baseline;
- **C -- partial or hybrid:** simulator/HLS share part of the behavior, but host
  orchestration or an unmatched implementation boundary remains; and
- **D -- target-only:** specified by the manuscript but not established by the
  evaluated artifact.

| Mechanism | Manuscript target | Native Candidate10 | opt-v2/formal-v7 evaluated Spine | Class | Required paper action |
|---|---|---|---|---|---|
| Destination organization | `P=16`, `h(v)=v mod P`, one destination-owned family per record | 16 range-based cold partitions plus 16 hash-based hot shards | Same 32-family hot/cold organization, including skip-fit promotion correction | C | Rewrite the evaluated-architecture description or label modulo-16 ownership as target-only |
| Record identity | Generic `(src,dst,payload,delta)` full-record multigraph | Primary key `(src,dst)` with weight and signed diff fields | Coalesces endpoint groups, sums diff, and retains minimum weight | D | Do not claim generic parallel full-record support from current E2E data |
| Vertex lifecycle | Fixed `MAX_N`, dormant-ID activation, validity-gated deletion after incident-edge retirement | Fixed vertex arrays; no matched routed lifecycle controller | Opt-in SSSP path times validity-bitmap RMW on shared PC22, rejects invalid endpoints, and correctness-tests activate/use/retire/deactivate | B/D | Extend the same gate to all policies and HLS before claiming complete generated support |
| Batch sorting/reduction | Four-wide full-record bitonic/FLiMS sorter up to `Q=2^17` | Endpoint-keyed sorter and differential coalescing | Execution-driven Candidate10 update path; tested batches use supported HLS record format | C | Separate generic target sorter from evaluated endpoint sorter |
| Ratio-2 levels/carry | 11 levels, ratio 2, realized carry work | 11 levels, ratio 2, fixed family capacities and carry | Same level/carry organization and capacity rules | A | Safe as shared architectural lineage; state exact evaluated capacities |
| Hot/cold classification | Not present in the current target text | Hot bitmap plus cold partition and hot-shard capacities | Same, with formal-v7 skip-fit correction | C | Add hot/cold layout to evaluated architecture or remove claims that results use only modulo families |
| HBM mapping | Parameterized HBM-backed family storage | 23 U55C pseudo-channels, 512-bit ports, 16 graph banks plus control/state channels | Same 23-PC budget; online DRAMSim3 backend under shared profile | A | State that performance is simulated under this mapping; route evidence is feasibility support |
| Page CSR and epochs | Per-slice page epochs, source bitmap, page base, row offsets | Bounded page metadata and epoch-gated row lookup | Execution-driven page/index requests and finite source-page cache | A/B | Keep, but do not equate current family directory with the complete target presence directory without qualification |
| Family directory | Exact `P x L` physical-row presence gathered per source | 32-bit cold/hot family directory and level metadata | Directory skip and request accounting modeled | C | Describe the evaluated directory format separately from the target `16 x 11` logical directory |
| L0 publication | Private target image plus complete atomic topology publication | Grouped dirty-frontier and page metadata publication | Detailed L0 writer/publication timing modeled from HLS | C | Claim the evidenced L0/page publication mechanism, not the complete shadow-descriptor transaction |
| Cross-level latest view | Family-local signed `k`-way resolver emits each full record exactly once | Endpoint-keyed carry coalescing; complete generic resolver is not evidenced | Supported endpoint semantics are correctness-gated; complete generic full-record resolver is absent | D | Preserve an explicit limitation; do not attribute generic latest-view correctness to the current E2E figure |
| Exact tile path | Bounded row-service datapath implied by target | Exact range-task path with active gate | Gate is 32,768 in opt-v2; finite FIFO/AXI/HBM path modeled | A/B | Describe as an evaluated microarchitecture detail and disclose gate capacity |
| Fallback tile path | Target fallback semantics at policy level | Full-tile load/replay/store and host handoff at finite limits | Fallback metadata reuse and source-page cache modeled | A/B/C | Separate device fallback work from untimed host fallback preparation |
| Active discovery | Device-resident policy/scheduler derives work | Persistent dirty frontier exists, but later rounds may use `HOST_ACTIVE` | Existing evaluated rows retain their documented boundaries; the alignment branch now has an opt-in SSSP owner path in which compute generates and handshakes every later active ID | C/B | Do not retroactively relabel old rows; use the new profile only after separate calibration |
| Per-key scheduler | Owner FIFO, `queued/in_flight/dirty`, no lost reactivation | Dirty bitmap/list and bounded reader/compute paths, not the complete target owner state machine | Opt-in SSSP path now models finite per-partition ingress/reactivation FIFOs, HBM-backed ready/deferred lists, lossless dirty requeue, and credits; HLS is pending | B/D | Calibrate the new simulator profile and implement the same protocol in HLS before an implementation claim |
| Atomic state transition | Destination-owned atomic update for generated map/reduce | Weighted-SSSP compute datapath and finite stream path | Algorithm policy models execute SSSP, CC, Full PR, and Residual PR | C | Claim simulator correctness for algorithms; claim HLS feasibility only for the available shells |
| PageRank degree/correction | Old/new row replay, private degree image, bounded seed buffer | Not a complete routed target PageRank transaction | Simulator host preparation builds active bins/out-degrees; algorithm execution is modeled | C/D | Do not say target PageRank seed/publication pipeline is implemented by the current Spine xclbin |
| Atomic topology bank switch | Shadow descriptor banks, precommit fence, one selector write | No complete matching transaction controller | Not represented as one matched complete HLS module graph | D | Keep as proposed target mechanism or implement and cost it; exclude it from supported measured claims |
| Global quiescence | Device work credits, FIFO/dirty/in-flight drain | Kernel/round completion plus host control | Opt-in SSSP runs require the owner credit ledger plus all modeled AXI/FIFO paths to close; host re-bin/relaunch remains outside device cycles as the paper now states | B/D | Keep host-inclusive and device-cycle boundaries separate; HLS evidence remains required |
| Algorithms | Generated SSSP, CC, residual PageRank policies | Routed Spine evidence is primarily weighted SSSP | Four algorithm policies are cycle-simulated and dual-oracle checked | C | Separate algorithm-level simulator support from algorithm-specific HLS generation support |
| Timing identity | Complete generated accelerator | Routed native SSSP Candidate10 | Routed opt-v2 SSSP core exists, but formal-v7 also includes later behavior and simulator orchestration | C | Call route evidence an implementation/feasibility anchor, not cycle calibration of the complete plotted system |

## 5. Detailed differences and their consequences

### 5.1 Family ownership is the largest visible architecture mismatch

The manuscript currently states:

```text
P = 16
h(v) = v mod P
```

and uses this mapping for payload, metadata, and analytic-state ownership.

Candidate10 and opt-v2 instead define:

```text
cold_partition(dst) = floor(dst / vertex_partition_size), clipped to 16
hot_family(dst)      = 16 + hash(dst) mod 16, when hot_bitmap[dst] is set
families             = 16 cold + 16 hot = 32
```

The hot bitmap is generated from destination indegree and capacity pressure.
Formal-v7 additionally freezes a correction that does not promote vertices
from cold partitions that already satisfy their capacity target. This avoids
wasting finite hot-shard capacity without relieving an overflowing cold
partition.

**Why it matters:** family count and routing affect HBM placement, skew,
capacity rejection, directory masks, parallelism, and traffic. A performance
result from the 32-family hot/cold design cannot directly validate a paper
claim about a 16-family modulo design.

**Recommended edit:** describe the evaluated physical organization as 16 cold
destination ranges plus 16 hot shards. If modulo-16 ownership is retained as a
clean target design, state explicitly that it is not the configuration used by
the formal-v7 E2E results.

### 5.2 Current edge identity is endpoint-keyed, not generic full-record

The target paper defines a record as `(src,dst,payload,delta)` and includes all
payload fields in the sort and equality identity. This allows multiple records
with the same endpoints but different payloads to coexist.

The native and simulated Candidate10 format stores `src`, `dst`, a 16-bit
weight, and a signed 16-bit differential, but grouping is by `(src,dst)`.
When one group is reduced, differentials are summed and the minimum encountered
weight is retained. Therefore, two parallel weighted records with the same
endpoints do not have independent full-record identities.

**Why it matters:** current correctness evidence is valid for the supported
endpoint-keyed graph semantics, including the tested weighted SSSP updates. It
does not prove the target compiler's generic full-record multigraph semantics.

**Recommended edit:** keep full-record lowering as a target contribution only
if clearly labeled. In Evaluation, state that the current evaluated record key
is `(src,dst)` and that generic payload-distinct parallel records are outside
the evaluated claim boundary.

### 5.3 Ratio-2 maintenance is the strongest aligned mechanism

All relevant artifacts use 11 provisioned levels with ratio 2 and bounded
family storage. Candidate10 maintenance performs sorting/classification,
family dispatch, differential coalescing, target-level selection, carry input
reads, and target writes. The cycle simulator issues the associated metadata
and payload operations through finite memory ports and tracks the realized
carry volume.

**Why it matters:** claims that maintenance cost follows realized sorting,
classification, carry reads, and writes have direct implementation lineage.
The exact cost still belongs to the evaluated Candidate10 organization, not to
an arbitrary target implementation.

**Recommended edit:** retain the realized-work framing, but bind all numerical
results to the evaluated level capacities, family mapping, and memory profile.

### 5.4 The evaluated reader contains real bounded optimizations

opt-v1 reuses an already loaded family/level descriptor cache in fallback.
opt-v2 adds a finite source-page index cache and doubles the exact active gate.
The source-page cache has one entry per level for the currently executing fixed
family and is cleared at every fixed-family invocation or fallback tile pass.
The active-gate increase costs 393,216 logical on-chip bytes.

The opt-v2 weighted-SSSP core has a routed U55C result at 150 MHz. The complete
formal-v7 behavior is nevertheless not represented by one xclbin because the
formal model also incorporates the later skip-fit hot-promotion correction and
algorithm/runtime behavior beyond that routed SSSP core.

**Why it matters:** opt-v2 is a legitimate proposed architecture optimization,
not a free simulator shortcut. It must, however, be disclosed as an
optimization rather than presented as native Candidate10.

**Recommended edit:** name the cache, capacity, clearing scope, added storage,
and route evidence in the evaluated-architecture setup. Use an ablation to
separate its effect if the paper attributes speedup to the base architecture.

### 5.5 Page CSR aligns; the complete target presence directory does not

Candidate10 and the formal simulator perform page-epoch checks, source-bitmap
reads, rank/base lookup, row-offset reads, and edge-payload requests. These are
execution-driven memory operations, and opt-v2's page cache only removes the
explicitly cached subset.

The paper's target directory is conceptually a `P x L` exact presence vector
per source. The evaluated implementation uses a 32-bit cold/hot family
directory together with level metadata and page-level structures. These are
related mechanisms but not the same physical format.

**Why it matters:** the paper may claim that exact metadata avoids blind row
probes, but request counts, directory capacity, and the number of parallel
segments must use the evaluated format when interpreting formal-v7 results.

### 5.6 The complete signed latest-view resolver remains target-only

The paper specifies a family-local bounded `k`-way merge across visible levels,
summing signs for each complete `(dst,payload)` identity and emitting only
membership-one records.

Candidate10 coalesces endpoint-keyed records when constructing a carried target
level. The current paper's own Evaluation boundary states that the endpoint
artifact does not establish the complete signed cross-level resolver. The
formal simulator correctness gates materialize/check the supported endpoint
semantics, but this is not evidence that the generic target full-record resolver
exists as the described HLS datapath.

**Why it matters:** without this distinction, the paper would use endpoint
correctness to support a strictly stronger multigraph/latest-view claim.

**Recommended edit:** preserve a direct statement that complete full-record
cross-level resolution is not part of the current implementation evidence.
Do not describe the new E2E figure as validating this target-only mechanism.

### 5.7 Active execution is partly device-driven and partly host-orchestrated

The HLS lineage contains a persistent dirty list/bitmap, device-dirty mode,
source-value request protocol, exact range tasks, finite fallback limits, and a
dirty acknowledgement path. This is meaningful device-side functionality.

However, the formal simulator system also:

- constructs `HOST_ACTIVE` bins in `build_spine_host_active_bins()`;
- calls `restart_read_compute()` for later frontier rounds;
- records host fallback control as `host_control_cycles = 0` and
  `host_control_timed = false`;
- builds PageRank host input and out-degree data in
  `build_pagerank_host_input()`; and
- excludes host construction and transfer/launch accounting in documented
  paths, even though HBM reads of the published active records are timed.

The target paper instead specifies owner FIFOs, `queued/in_flight/dirty` state,
fair arbitration, reactivation, work credits, and device global drain. The
paper-alignment branch now implements these mechanisms as an opt-in SSSP
simulator profile. It does not alter the historical result rows and has not yet
been mirrored into HLS or the PageRank/CC systems.

**Why it matters:** the historical simulator rows time modeled accelerator
work, not a complete CPU-plus-device deployment. The new profile closes the
SSSP per-key credit ledger while retaining the paper's explicit host
re-bin/relaunch boundary; it still needs calibration before replacing those
rows.

**Recommended edit:** replace unqualified claims such as `the target keeps all
feedback rounds on device` with one of the following:

1. a target-design statement explicitly separated from evaluated behavior; or
2. an evaluated-prototype statement that discloses host-built active bins and
   untimed relaunch/control work.

### 5.8 The target transaction controller is not the evaluated publication path

The manuscript specifies two descriptor banks, inactive-image copy/update,
degree/seed roots, a precommit fence, one atomic topology selector, deferred
reclamation, and result release after work-credit drain.

Candidate10 provides grouped dirty-frontier publication, page epochs, metadata
status, result records, and dirty ACK. These mechanisms support coherent local
state transitions, but they are not the complete descriptor-bank transaction
controller described in Section 5. The formal simulator does not turn the
missing target controller into a matched HLS implementation.

**Why it matters:** target atomic-publication correctness and its descriptor,
fence, switch, and synchronization latency cannot be claimed as measured by the
current E2E data.

**Recommended edit:** mark descriptor-bank publication and work-credit drain as
target mechanisms. In RQ3, report only timing components that are actually
emitted by the simulator. A modeled zero or an inferred remainder must not be
presented as a directly observed target-controller latency.

### 5.9 Algorithm support has different meanings in the simulator and HLS

The formal cycle simulator supports and correctness-checks weighted SSSP,
Connected Components, Full PageRank, and thresholded Residual PageRank. Full
PageRank is an additional evaluation baseline; the manuscript's three dynamic
target policies are weighted SSSP, Connected Components, and thresholded
Residual PageRank. This is valid algorithm-level simulator evidence.

The available routed Spine opt-v2 artifact is a weighted-SSSP core baseline.
The PPA ledger explicitly warns that this does not make the other
simulator-supported Spine algorithms iso-functional HLS builds. GraSU+ReGraph has separate routed
algorithm-specific shells, but those are not a substitute for missing Spine
shells.

**Why it matters:** the paper can report cycle-simulator performance for all
correctness-admitted algorithms, but it cannot say that the compiler currently
generates and routes all those complete Spine accelerators.

**Recommended edit:** use `the simulator implements the evaluated algorithm
policies` for
evaluation and `the routed weighted-SSSP opt-v2 core demonstrates feasibility`
for implementation evidence. Reserve `the compiler generates all policies`
until code-generation and algorithm-specific HLS evidence exist.

### 5.10 The formal-v7 model has no single exact xclbin identity

formal-v7 selects the opt-v2 profile and additionally freezes
`automatic_hot_promotion_skips_already_fit_cold_partitions`, referenced to HLS
branch `codex/skip-fit-hot-promotion` at revision
`867bee49e483950a82d69d3f3d8b0661ccbef544`. The simulator plugin is separately
hashed by the contract.

This is acceptable for a simulator-first architecture paper if each extension
is bounded, correctness-gated, and backed by implementation/cost evidence. It
is not acceptable to describe formal-v7 as a replay of one board binary.

## 6. Measurement boundary required for the E2E figure

The formal-v7 contract defines the dynamic-update window as beginning when the
first update is accepted and ending after update processing, active detection,
compute response, and modeled FIFO drain. Bootstrap is reported separately and
excluded. Positive weighted SSSP first establishes a verified old-graph state
outside the dynamic-update window.

At least some host operations are not timed:

- construction of `HOST_ACTIVE` records;
- host fallback preparation;
- command launch and event wait;
- host-to-device publication/migration of active metadata in documented paths;
- repeated-round host control; and
- PageRank host preprocessing used to prepare active bins/out-degrees.

Therefore, `setup-inclusive` is unsafe unless the caption defines `setup` to
mean only the modeled device-side update setup. The recommended label is:

> **Dynamic-update device-model cycles**, from first accepted update through
> modeled update processing, active execution, response, and FIFO drain;
> bootstrap and untimed host orchestration are excluded.

If the paper wants a true host-plus-device setup-inclusive result, those host
operations must be measured or conservatively modeled and added.

## 7. What the current evidence can and cannot support

### 7.1 Claims that are supportable with careful wording

- A frozen execution-driven cycle simulator compares an opt-v2 Spine design
  with a normalized conversion-free GraSU+ReGraph design under a shared memory
  and algorithm contract.
- Every admitted performance row passes the specified architecture-precision
  and independent mathematical correctness gates; failed rows are excluded.
- Candidate10-derived maintenance, finite row lookup, FIFO/AXI/HBM traffic,
  and backpressure generate requests from execution rather than from a single
  edge-count-to-time formula.
- Ratio-2 maintenance latency and traffic respond to realized update/carry
  work in the evaluated architecture.
- opt-v1/opt-v2 are bounded hardware mechanisms with HLS evidence; the opt-v2
  weighted-SSSP core has routed 150-MHz U55C feasibility evidence.
- The simulator supports comparative bottleneck, traffic, sensitivity, and
  architecture what-if analysis within its frozen evidence boundary.

### 7.2 Claims that are not currently supportable

- `The plotted bars are FPGA measurements.`
- `The plotted Spine is the unmodified native Candidate10 xclbin.`
- `The complete full-record Delta.hls architecture has been implemented and
  routed.`
- `All feedback rounds, active discovery, and quiescence execute on device in
  the evaluated system.`
- `The current artifact supports arbitrary payload-distinct parallel edges.`
- `The shadow descriptor bank, atomic selector, full seed transaction, and
  work-credit drain were timed in the E2E figure.`
- `All simulator-supported Spine algorithm datapaths have matching routed HLS
  builds.`
- `Completed simulator runs include all host setup, transfer, launch, and wait
  overhead.`
- `Projected or timeout values are measured performance` or inclusion of those
  values in aggregate speedup statistics.
- `Spine and GraSU+ReGraph routed resource ratios are iso-functional.` The PPA
  ledger explicitly disables that comparison.

## 8. Required manuscript edits

### 8.1 Abstract (`sections/00NN_abstract.tex`)

Current risk: `We present a compiler--architecture design` is acceptable, but
phrasing around device-resident iteration may be read as an implemented
complete system.

Recommended action:

- call Delta.hls a compiler--architecture **design and evaluated
  microarchitecture model**;
- state that performance comes from an execution-driven cycle simulator; and
- state that routed HLS evidence covers key mechanisms / the weighted-SSSP
  core, not every generated policy.

### 8.2 Introduction (`sections/01NN_introduction.tex`)

Statements requiring revision or explicit target qualification include:

- `the target keeps all feedback rounds on device`;
- `We define ... a backend that lowers ... into the complete ordered dynamic
  path`; and
- `full-record multigraph` when used as if it were evaluated.

Recommended action: use `target design` for these statements, then add one
sentence saying that the evaluated artifact is endpoint-keyed and uses
host-orchestrated active rounds in the paths identified in Evaluation.

### 8.3 Compiler lowering (`sections/03NN_compiler_lowering.tex`)

The section currently reads as an implemented code generator. Separate:

1. verified target lowering/specification;
2. algorithm-policy implementations in the simulator; and
3. algorithm-specific HLS artifacts actually synthesized/routed.

Do not use simulator support alone as evidence that the complete compiler emits
the full HLS module graph.

### 8.4 Hierarchy (`sections/04NN_latest_view_hierarchy.tex`)

Required changes:

- either replace the evaluated ownership mapping with 16 cold ranges plus 16
  hot shards or clearly mark `h(v)=v mod 16` as target-only;
- retain the endpoint-keyed limitation near the full-record description;
- distinguish the evaluated 32-bit family directory from the target `16 x 11`
  directory; and
- distinguish carry-time endpoint coalescing from the complete generic signed
  cross-level resolver.

### 8.5 Transactional execution (`sections/05NN_transactional_execution.tex`)

This section is predominantly a target design. Keep it if the paper is clear
that descriptor banking, complete atomic publication, owner scheduler, work
credits, and all-device drain are not established by the current E2E evidence.

The final paragraph already reserves several complete-path claims. Expand that
boundary to mention host-built active bins, relaunches, and PageRank host input
preparation.

### 8.6 Evaluation (`sections/06NN_evaluation.tex`)

This section needs the most immediate cleanup:

1. identify formal-v7 opt-v2, not native HLS, as the plotted Spine;
2. define normalized comparison parameters and freeze policy;
3. define `completed simulated`, `projected`, and `strict lower bound`;
4. define the dynamic-update device-model timing window and exclusions;
5. disclose 16 cold partitions, 16 hot shards, 11 levels, four compute lanes,
   23 HBM pseudo-channels, 64-byte memory lines, finite FIFO/AXI limits, and the
   opt-v2 caches/gate;
6. state that correctness admission is required before a row enters any
   performance aggregate;
7. exclude projected and lower-bound rows from aggregate speedups;
8. keep generic full-record, atomic publication, and device scheduler claims
   outside the E2E result interpretation; and
9. reconcile the older evidence-status table and prototype-only prose with the
   newly added formal-v7 E2E figure. The two evidence narratives currently
   describe different milestones.

### 8.7 Conclusion (`sections/08NN_conclusion.tex`)

The current conclusion is relatively conservative because it says that
controlled measurements validate physical premises. Preserve that discipline.
Add cycle-simulator E2E conclusions only for the evaluated architecture and do
not generalize them to the unevaluated full-record transaction path.

## 9. Suggested paper-ready wording

### 9.1 Evaluated-system identity

> We evaluate a frozen opt-v2 Spine configuration derived from the routed
> Candidate10 HLS design. It preserves Candidate10's 11-level ratio-2
> hierarchy, 16 cold destination partitions, 16 hot shards, split
> reader/maintenance and compute path, and 23-pseudo-channel U55C memory map.
> opt-v2 adds bounded fallback-directory reuse, an 11-entry per-family
> source-page cache, and a 32,768-record exact-path working set; these
> mechanisms have HLS implementation evidence. The formal-v7 model also
> includes the frozen skip-fit hot-promotion correction.

### 9.2 Simulator evidence boundary

> Performance results are completed executions of an execution-driven
> cycle-level simulator, not FPGA wall-clock measurements. Components issue
> finite AXI requests through bounded FIFOs to an online DRAMSim3 HBM model;
> request, byte, response, and algorithm-state conservation are checked before
> a row is admitted. Routed HLS artifacts establish implementation feasibility
> for the Candidate10 lineage and opt-v2 weighted-SSSP core, but no single
> xclbin implements every behavior in the evaluated multi-algorithm model.

### 9.3 Timing boundary

> Dynamic-update latency begins when the modeled accelerator accepts the first
> update and ends after update processing, active execution, response, and FIFO
> drain. Graph bootstrap and host construction/publication of later
> `HOST_ACTIVE` rounds are excluded. We therefore report device-model update
> cycles rather than host-inclusive wall time.

### 9.4 Functional boundary

> The evaluated graph format is endpoint-keyed: records carry source,
> destination, weight, and signed differential, while reduction groups by
> `(src,dst)`. The generic payload-distinct full-record multigraph resolver,
> shadow-descriptor topology transaction, and complete device work-credit
> scheduler remain target mechanisms and are not claimed as implemented by the
> current E2E artifact.

### 9.5 Algorithm boundary

> The cycle simulator implements weighted SSSP, Connected Components, Full
> PageRank, and thresholded Residual PageRank and admits performance rows only
> after architecture-precision and independent mathematical checks. Current
> routed Spine opt-v2 evidence covers the weighted-SSSP core; algorithm-level
> simulator support should not be read as routed HLS evidence for every policy.

## 10. Minimal disclosure table recommended for Evaluation

| Item | Value / disclosure |
|---|---|
| Spine result identity | formal-v7 Candidate10 opt-v2 plus skip-fit correction |
| Result type | completed cycle-simulator execution unless marked projected or lower bound |
| Graph ownership | 16 cold range partitions + 16 hash-based hot shards |
| Hierarchy | 11 ratio-2 levels |
| Compute width | 4 lanes |
| HBM | U55C-style 32-PC backend; 23 PCs allocated by Spine profile |
| Memory line | 64 bytes in the formal-v7 shared DRAMSim3 contract |
| opt-v2 state | finite per-family 11-entry page cache; 32,768-record exact gate; +393,216 logical bytes |
| Algorithms | SSSP, CC, Full PR, thresholded Residual PR in simulator |
| Correctness | architecture-precision and independent mathematical oracles; failed rows excluded |
| Timed start/end | first accepted update through modeled response and FIFO drain |
| Exclusions | bootstrap; untimed host active-bin construction, relaunch/control, and documented host transfers |
| Projection policy | projections and strict lower bounds shown separately and excluded from aggregate speedup |
| HLS evidence | native Candidate10 routed; opt-v2 weighted-SSSP core routed at 150 MHz; no complete three-algorithm Spine xclbin identity |
| Record limitation | endpoint-keyed; generic payload-distinct parallel records not evaluated |
| Target-only mechanisms | complete signed full-record resolver, shadow-descriptor transaction, all-device scheduler/work-credit drain |

## 11. Evidence map for reviewers and authors

### Manuscript sources

- `sections/03NN_compiler_lowering.tex`
- `sections/04NN_latest_view_hierarchy.tex`
- `sections/05NN_transactional_execution.tex`
- `sections/06NN_evaluation.tex`

### Simulator profiles and contracts

- `/home/chuxiao/spine-cycle-sim-publication/configs/architectures/spine_candidate10_one_pass_1e61fc0.json`
- `/home/chuxiao/spine-cycle-sim-publication/configs/architectures/spine_candidate10_opt_v1_fallback_level_cache.json`
- `/home/chuxiao/spine-cycle-sim-publication/configs/architectures/spine_candidate10_opt_v2_reader_working_set.json`
- `/home/chuxiao/spine-cycle-sim-publication/configs/contracts/large_graph_publication_campaign_fullgraph_v7.json`
- `/home/chuxiao/spine-cycle-sim-publication/configs/evidence/candidate10_publication_ppa_v4.json`

### Simulator implementation and limitations

- `/home/chuxiao/spine-cycle-sim-publication/cpp/src/spine_l0.cpp`
  - endpoint coalescing and Candidate10 maintenance
- `/home/chuxiao/spine-cycle-sim-publication/cpp/src/spine_split.cpp`
  - finite exact/fallback row reader, streams, page cache, and compute path
- `/home/chuxiao/spine-cycle-sim-publication/cpp/src/spine_system.cpp`
  - host-active bins, round relaunch, PageRank host preparation, and untimed
    host handoff accounting
- `/home/chuxiao/spine-cycle-sim-publication/docs/spine_opt_v1_fallback_level_cache_20260728.md`
- `/home/chuxiao/spine-cycle-sim-publication/docs/spine_opt_v2_reader_working_set_20260728.md`
- `/home/chuxiao/spine-cycle-sim-publication/docs/spine_metadata_active_payload_path_20260724.md`
- `/home/chuxiao/spine-cycle-sim-publication/docs/spine_dirty_ownership_20260724.md`
- `/home/chuxiao/spine-cycle-sim-publication/docs/spine_skip_fit_hot_promotion_v7_20260730.md`

### HLS implementation

- `/home/chuxiao/spine-dynamic-graph-opt-v2/src/spine_partitioned.hpp`
- `/home/chuxiao/spine-dynamic-graph-opt-v2/tests/test_integration/host_split.hpp`
- `/home/chuxiao/spine-dynamic-graph-opt-v2/tests/test_integration/system_partitioned_split_e2e.cfg`

## 12. Final author checklist

Before submission, every architecture or performance sentence should answer:

1. Is this a **target-design**, **simulator-implemented**, **HLS-synthesized**,
   **HLS-routed**, or **FPGA-measured** statement?
2. Does it refer to native Candidate10, opt-v2, or formal-v7 opt-v2 plus the
   skip-fit correction?
3. Does `family` mean 16 modulo owners, 16 cold ranges, or all 32 cold/hot
   families?
4. Does the graph model mean generic full records or endpoint-keyed records?
5. Does latency include host active-bin construction, migration, launch, wait,
   bootstrap, and repeated-round control?
6. Is the value a completed simulator execution, a projection, a strict lower
   bound, an HLS estimate, or a board measurement?
7. Does the corresponding algorithm have simulator evidence, HLS evidence, or
   both?
8. Is the mechanism actually represented in the timing breakdown, or only in
   the target architecture description?

If any sentence cannot answer these questions unambiguously, it should be
revised before it enters the abstract, contributions, figure caption, or
headline conclusion.
