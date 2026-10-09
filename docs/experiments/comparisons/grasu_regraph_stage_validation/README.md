# Isolated G / R Validation

Start with the [execution and acceptance plan](PLAN.md), then the preceding
[source/comparability audit](../grasu_regraph_publication_match/README.md).
This folder owns the new study's results and conclusions, rather than
scattering them among figure-refresh and daily investigation directories.

Status: the SST/Spine extraction passed exact regression and was pushed in
`51565fc`. Four independent author-source functional controls now pass; read
[their results and limitations](SOURCE_CONTROLS.md). Original G/R cycle models,
publication-speed matching, and the matched A4/B overhead study remain in
progress. No new FPGA timing is claimed.

The [original-kernel scheduling checkpoint](HLS_SCHEDULES.md) now covers
four GraSU kernels and the original ReGraph Little/Big, merger, wrapper and
apply components. R scheduling uses explicitly labeled U55C controls because
U280 support is absent locally; PR apply has a separately declared control
interface compatibility directive. These HLS estimates are neither complete
cycle-model validation nor publication performance reproduction.

The [finite Little Gather/merge checkpoint](LITTLE_FINITE_MODEL.md) now adds
an independent cycle-component family with private destination arrays,
forwarding, full drain/clear, registered FIFOs and finite in-flight work.
It matches all 786,432 original-source output words over the admitted 4-Little
and 11-Little component fixtures. Its boundary excludes edge/source memory
service and Apply; whole-R timing and A4/B overhead remain unfinished.

The [Little memory/frontend checkpoint](LITTLE_FRONTEND_MODEL.md) extends this
family through finite edge/source AXI service and Scatter, matching five
request-dependent original-source controls, including sparse source windows.
All frozen Gather/capture results remain identical. The ten positive frontend
rows, allocation rejection, repeats and instrumentation pass. Apply/writeback,
Big/mixed scheduling and complete stage timing remain unfinished.

The [Little PR state checkpoint](LITTLE_STATE_MODEL.md) extends the independent
path through degree reads, Apply and acknowledged broadcast writes. It also
checks three connected resident A4 rounds with shared source/write channels.
The old frontend/Gather analyses remain identical. Publication matching and
matched adapter overhead are still not established.

The [original-host input checkpoint](ORIGINAL_HOST_INPUTS.md) now passes full
DBG, partition/scheduling and PR-initialization checks for complete Amazon
and two neighboring fixtures, for both A4 and the artifact's 11+3 example.
All six cases repeat exactly under normal and UBSan builds. This admits input
preparation, not whole-R device timing or the publication's best topology.

The [A4 whole-graph checkpoint](A4_GRAPH_EXECUTION.md) now executes every
original scheduled partition through acknowledged PR writeback on full Amazon
and two neighboring inputs. Complete pre-Apply values, four replicas, work and
memory ledgers, repetitions, reverse registration and instrumentation pass.
It explicitly audits parent versus burst credits while preserving all old
component/source-comparison outputs. Its mock-memory cycles are predicted,
not a publication-speed match or a completed A4/B overhead experiment.

The [Big routing/Gather checkpoint](BIG_ROUTING_GATHER.md) now passes a
separate finite omega/bank/three-way-merger model against 2,097,152 original
source words. Eight functional/pressure/reuse rows, malformed captures,
repetitions and two UBSan executables pass. All four existing component and
eight complete-A4 execution outputs remain exact. Big source-memory service,
connected mixed execution and publication timing admission remain open.

The [Big memory/frontend checkpoint](BIG_MEMORY_FRONTEND.md) now checks the
original request generator, last-cacheline wrapper, response routing and
Scatter, comparing every request/response/update field over six source
fixtures. Twelve finite-resource rows, source/model instrumentation and all
old component/A4/Big-Gather outputs pass. That checkpoint stops before the
mixed connection below; publication memory/topology/window admission remains open.

The [mixed whole-graph checkpoint](MIXED_GRAPH_EXECUTION.md) now connects
the 11+3 artifact example through complete indexed PR state and 14 replicas.
It exposes and rejects an original host/publication-tail allocation mismatch,
then runs an explicitly zero-extended compatibility control. Complete graph,
pressure/repetition/UBSan and exact old A4/Big checks pass. This closes connected
functional mixed execution, not original-best-topology or timing admission.

| Path | Current evidence | Still required |
| --- | --- | --- |
| G | Original cache dispatch, all 16 URAM banks, preload/update/writeback agree with an independent oracle over three batches | Original search/DDR/host path, temporal workload admission and finite-resource timing |
| A | Original Little/Big captures pass; complete 11+3 graph execution, indexed state and finite ledgers pass under declared tail padding | Original-host allocation compatibility, graph-selected topology, publication memory/clock/window/denominator admission and timing match |
| A4 | Full multi-partition execution on complete Amazon and two fixtures; every pre-Apply sum/four state replicas and finite ledgers pass; instantiated AXI capacities audited | Realistic memory/topology timing admission, original-publication comparison and fixed-resource adapter control B |
| B | Not executed | PMA input adapter feeding the same admitted original A4 downstream; state/work/cycle comparison |
| C | Not executed | Separate validated G and B windows, measured host orchestration and overlap accounting |

[Independent upstream source pins](source_pins.json) record fresh clean
checkouts and inspected file hashes. They are distinct from the modified local
HLS ports. Reproduce them under ignored build output:

```bash
git clone https://github.com/Xtra-Computing/ReGraph.git build/publication_sources/regraph
git -C build/publication_sources/regraph checkout --detach 365456826cef495285383d939907f847e05ad74b
git clone https://github.com/qgwang-hust/GraSU.git build/publication_sources/grasu
git -C build/publication_sources/grasu checkout --detach e95da256be9e7f2361449323b6fe0abf98c1b152
```

The GraSU geometry question recorded in the source-pin snapshot is now
resolved: Section 6.1 explicitly specifies eight 4-byte entries, a 32-byte
PE buffer. Current upstream instead packs sixteen 32-bit entries, a 64-byte
segment. Host-side 64-bit edge records are converted into 32-bit destination
slots before device upload; they do not explain away this difference. See
[the source-control findings](SOURCE_CONTROLS.md). The passing control uses
the unmodified source's 16-slot geometry. A separate, explicitly named
paper-8-slot control is required before a paper-configuration timing claim;
the source configuration is not assumed to have equal performance.

The upstream ReGraph repository includes an AM candidate at
`dataset/amazon-2008.mtx`: 5,158,388 two-column edge rows, SHA-256
`60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815`.
Despite the extension, it is not a Matrix Market file with a header. The
upstream loader keeps the integer IDs and uses maximum ID plus one. This
candidate now passes original-host DBG/partition/task and initial-state
admission. Device-iteration and publication-event admission remain open;
its availability does not make Table IV's graph-selected topology known.

## Reproduce Source Controls

Use a fresh output path; the runner refuses to overwrite previous runs:

```bash
python3 scripts/run_upstream_stage_controls.py \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_source_functional
python3 -m unittest discover -s tests -p test_upstream_stage_controls.py
```

The source generator uses Python 3.11, pinned in the contract. The study
runner itself also runs on Python 3.13. HLS headers and GMP are needed only
for these optional author-source controls; the ordinary C++ core still builds
without Vitis. Processes run sequentially with a 2-GiB address-space limit,
128-MiB stack allowance, 16-GiB memory reserve, and bounded compile/run times.

The [v2 contract](../../../../configs/experiments/grasu_regraph_upstream_controls_v2.json)
adds the Big source control to the preserved first Little/cache matrix. Code
ownership is in
[upstream_controls](../../../../spine_cycle_sim/experiments/upstream_controls/)
and [source probes](../../../../cpp/tests/publication_sources/). Source
preparation, bounded execution, result validation and orchestration are
separate modules, with one thin CLI. Production HLS, simulator numerical
components, frozen plugins and figure packages are unchanged.

The [SST/Spine extraction checkpoint](../../../repository/sst_spine_refactor/README.md)
passed exact regression before this new control work. Existing
rejected fixtures are preserved there and cannot be admitted as study samples.
