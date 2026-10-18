# Algorithm-Specific Production Compilation

## Scope

The owning `hardware.algorithm_build` package prepares a portable source closure
and compiles the **eleven CC or twelve PageRank kernel types** afresh. Each
algorithm has a separate output directory, manifest, service and acceptance
decision. SSSP continues in its independently frozen
[remote route](../remote/README.md); this package does not modify its inputs.

This is synthesis preparation, **not routing, RTL admission, device correctness,
published-performance reproduction or a new Figure 7 result**. Existing SSSP
resource/timing checks must not be reused as CC/PageRank evidence. The next gate
must examine the actual exported resources and AXI/stream ABI before a separate
link experiment. Algorithm-specific finite RTL, routed timing and board
correctness remain independent admission gates. An experimental link may run
in parallel with RTL work, but cannot admit that missing evidence.

## Fixed Contract

- Hardware target, 150 MHz, sharded K4 with four frontends/shared downstream.
- Production `complete-search-cache`, 131072 cache segments per cache half.
- Explicit `bank-stream` adapter policy: 1024-row tiles, 256-line bank FIFOs,
  cross-row/packet pipelining and 512-bit row reads. Device hosts must use
  `GRASU_REGRAPH_ROW_LINE_READ=1`; scalar-row hosts are not interchangeable.
- CC uses destination-only edges and completion-token cache/DDR kernels.
  Residual/full PR use destination-only edges, their distinct PR mode, degree
  dispatch/update and source preparation, **without the CC completion-token ABI**.
- Exact source bytes, generated configs/commands, imported runner modules,
  explicit 2024.1 tool/environment/platform and completed XOs are hashed.
  Archived sources honestly report unavailable local Git metadata; the portable
  `sources.json` separately records the actual integration commit and original
  paths/hashes. Missing Git metadata must not be replaced by invented revisions.
- Generated shell preambles are not executed. Only the exact validated v++
  compile argument lists run; missing/duplicate kernels, wrong clock, changed
  source selection or adapter ABI cause rejection.

Source ownership is separated into `inputs.py` (portable closure), `commands.py`
(algorithm/ABI admission), `study.py` (bounded execution), and a thin module CLI.
`inspection.py` reads canonical XO exports/connections and fresh per-kernel HLS
resources; `review.py` checks a terminal compile's identity and the separately
verified portable capacity queries. `routing.py` owns the one-CU placement
change and fresh export/resource review; `route_study.py` owns bounded linking.
No simulator timing coefficient changes here.
`adapter_rtl.py` separately tests the actual exported adapter's AXI/AXIS
behavior; it does not admit the complete algorithm or replace board timing.
`artifacts.py` seals completed remote links, `topology.py` compares routed
connections with the fresh algorithm exports, and `admission.py` checks the
returned artifact against the requested local source closure and timing report.
`follow.py` owns waiting for one exact remote invocation, bounded remote sealing,
transport and local admission. It never requests or programs a board.
`compile_follow.py` waits for one exact compilation invocation and delegates
fresh XO/resource/ABI review and finite-budget linking to the existing route
owner. It does not replace return admission or authorize FPGA programming.
`local_follow.py` waits for that exact local link service, seals its child output
and independently reviews source, clock, topology and routed timing. It never
programs an FPGA or treats link success as timing, RTL or board approval.

## Latest Source And Compile Continuation

The [current candidate guide](../comparison_candidate/README.md) records fresh
adapter RTL and local-return board requests. The timestamped records below
remain historical; a completed compile is not routed or board acceptance.

The latest portable closure is `production-algorithm-sources-v4`, integration
`87a0a2cdb8c647247bb4d61dbd06ca4e98028f0b`. Its source-index SHA-256 is
`f92aa72f426f8c2177608fdb205af7aca0e14ef8dbe78e200fd69e4a1b70ea02`.
All 180 transported source files are retained locally and on the remote builder.
It includes the PageRank Apply packing fix and the fresh registered cache
comparison stage. The latter has passing host functional, segment-oracle and
HLS checks, and all eighteen search plus six transactions per cache binding
now pass fresh component Verilog/interface checks. Independent component
re-admission also passes. None of these admits integrated RTL, physical timing
or board correctness; see the [production route guide](../README.md).

The prior v3 closure is integration `1a5650c79ae0c29418b93184a1590f256e33f0b6`,
index SHA-256 `8b41653890d1e48e32c5f3531d79ba8fe227d0eccc883b8a08845e04f136f00f`.
Its source bytes match v2; its host device-lease change is outside the compile
closure. V2/v3 include the Apply fix but not the latest cache stage. V1 includes
neither fix. Never relabel those separately frozen routes as v4 results.

### Latest Local Compilations

Local tool preflight passes with the explicit 2024.1 installation, U55C platform
and campaign-owned compatibility libraries. CC, ResPR and FullPR have completed
compilation. All use v4 sources and immutable
simulator runner `algorithm-return-runner-2b9cf3c`, archive SHA-256
`a1517443ce25b60df47aa219116dd84d994ba3344944ca1fffc49a4f6e2dace4`.
The local root is
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.

| Algorithm | Local output | Service / invocation |
| --- | --- | --- |
| CC | `production-cc-compile-local-v2` | `spine-production-cc-compile-local-20261018-v2.service` / `c43a6ab156e341e683de58b99d05df85` |
| ResPR | `production-respr-compile-local-v2` | `spine-production-respr-compile-local-20261018-v2.service` / `cea9d8238407459f90a6f581b0161fc4` |
| FullPR | `production-fullpr-compile-local-v1` | `spine-production-fullpr-compile-local-20261018-v1.service` / `bf324b00d0864f66a2fb215c079be3f1` |

Each has 16/14-GiB max/high, zero swap, group OOM kill, 400% CPU, a distinct
CPU affinity and a 133200-second lifetime. Shared admission retains the full
peer budgets and 32+8-GiB reserve. Compatibility must name the actual nested
`local-tool-compat-v1/compat-2024.1` directory. The earlier CC/ResPR local v1
attempts retain their missing-library-directory failures before compilation;
v2 uses a fresh output, not rewritten failure evidence.

Each local compile now has an independent `follow-compile` service using the
same immutable runner and v4 source index. It waits for exactly the compilation
invocation above; a terminal successful compile is followed by fresh resource,
ABI and environment checks, then the existing finite-memory route owner with
`aggressive-route-v1`. CC and ResPR have passed compilation and entered fresh
review; their links still wait for finite memory admission. FullPR waits for
compilation. Each has 40/36-GiB max/high, zero swap, group OOM kill, 800%
CPU and a 270000-second lifetime. Its child output is `OUTPUT/route`.

| Algorithm | Local follower output | Service / invocation |
| --- | --- | --- |
| CC | `production-cc-compile-route-local-v1` | `spine-production-cc-compile-route-local-20261018-v1.service` / `8866c7c03edc446a9dd2d14bdc39d876` |
| ResPR | `production-respr-compile-route-local-v1` | `spine-production-respr-compile-route-local-20261018-v1.service` / `37e683aed86d4459932d9ad4c88935aa` |
| FullPR | `production-fullpr-compile-route-local-v1` | `spine-production-fullpr-compile-route-local-20261018-v1.service` / `0bba11cc2a3e4d7d9ec7d6e88536616a` |

These followers do not seal, admit or program an FPGA. Completed links still
need independent timing/source/clock admission and the algorithm RTL and board
gates. A queued follower is not evidence that routing has begun or will pass.

### Independent Local Return

The `follow-local-route` command closes the local return gap without remote
transport. Use an immutable runner and the exact **parent** compile/link service
identity above; `--route` names that parent's `route` child. The compile manifest
and full source index must match the requested algorithm and 150-MHz clock.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build follow-local-route \
  --compilation /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-cc-compile-local-v2 \
  --route /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-cc-compile-route-local-v1/route \
  --sources /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-algorithm-sources-v4 \
  --output /path/to/fresh/local-return \
  --unit spine-production-cc-compile-route-local-20261018-v1.service \
  --invocation 8866c7c03edc446a9dd2d14bdc39d876 \
  --algorithm connected_components --maximum-wait 270000 --poll-seconds 30
```

Contain this command with 4/3-GiB max/high, zero swap, group OOM kill and a
274000-second lifetime. It rejects missing, restarted, failed or timed-out
services, changed source bytes, wrong algorithms/receipts and unsuccessful
timing admission. Failed admission retains the sealed receipt for diagnosis.
Success is `ALGORITHM_LOCAL_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION`, with
all RTL, board and publication flags still false. A later board experiment
must explicitly consume this new admission; old queued board requests do not
automatically switch sources. All 68 algorithm-build tests pass, including
nine focused local-return tests. No simulator numerical model changed.

### Prior Remote Continuation

The prior v3-source FullPR compilation is `production-fullpr-compile-v2`, service
`spine-production-fullpr-compile-20261018-v2.service`, invocation
`2d8f7afce8a74532a7cebca981af85a5`, with unchanged compile runner `92ab3cd`
and the v3 source closure. At the 17:08 UTC checkpoint it is waiting for a
finite budget on an unrelated Vivado process; about 422 GiB is available and
both already-admitted CC/FullPR routes continue. This is not an all-tools-idle
policy and is not a completed compilation.

The reusable `follow-compile` command can supervise this exact invocation:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build follow-compile \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-fullpr-compile-v2 \
  --sources /data/chuxiao/baseline_hardware_validation_20261017/production-algorithm-sources-v3 \
  --storage /path/to/frozen/resource_evidence \
  --output /path/to/new/fullpr-compile-route-follow \
  --compile-unit spine-production-fullpr-compile-20261018-v2.service \
  --compile-invocation 2d8f7afce8a74532a7cebca981af85a5 \
  --algorithm full_pagerank --timing-profile aggressive-route-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1 \
  --shim /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1
```

Use a new fixed runner and output, with 40/36-GiB max/high, zero swap, group
OOM kill, 800% CPU, 8192 tasks, 65536 open files and a finite service lifetime
covering compile wait plus the separate route queue/link limits. The follower
freezes source, compile-manifest and runner identities while waiting. A failed,
missing, restarted or timed-out compile service stops before linking. A terminal
success must also have the requested complete compile report. The existing
route owner then independently reviews every XO and admits its full memory
budget; it does not inherit an earlier compile's resource approval.

The child link is always in `OUTPUT/route`. Its independent `execution.json`
and binary identity must match the returned result. Parent success is only
`COMPILE_AND_LINK_PASS_AWAITING_TIMING_RTL_AND_BOARD`, with all timing, RTL,
board and publication claims false. Return/seal that child using the exact
parent service invocation only after terminal success; strict local admission
still decides whether its clock/timing/connectivity qualify. Failed child
execution identities remain in the parent report. Nine focused follower tests
and the existing algorithm tests cover these failure and identity boundaries.

The continuation is now deployed as
`spine-production-fullpr-compile-route-20261018-v1.service`, invocation
`6bc5f930f57f47dc994bdcf21cea3635`, output
`production-fullpr-compile-route-follow-v1` under the remote experiment root
below. Its fixed runner `algorithm-compile-follow-runner-4d44dc8` was transferred
in `algorithm-compile-follow-runner-4d44dc8.tar.gz`, SHA-256
`ac6ea55d8cab9bd8c45f0afa2eaf12531fa3ae8f20d3ab21cf241ce00f31bfa2`.
The service has a 270000-second lifetime. At 17:25 UTC it is still
`WAITING_FOR_EXACT_COMPILATION`, without errors or a completed link. The exact
compile invocation above, not the ongoing older FullPR link, is its prerequisite.

Local return following retains its 133200-second default. An explicit
`--maximum-wait 270000` is supported for this combined compile/link service;
its containing service must additionally cover sealing, transfer and admission.
This extends only finite waiting, not clock tolerance or any evidence gate.
The return still seals the child `OUTPUT/route`, checks the exact parent
invocation and independently enforces source, ABI, connectivity and timing.
Fifty-nine focused algorithm-build tests pass, including the longer bounded
wait and rejection of changed or unsuccessfully terminated services.

The deployed local return follower is
`spine-production-fullpr-return-20261018-v3.service`, invocation
`44fd04bb4ce643a1afd54a55d444206b`, output `production-fullpr-return-follow-v3`
under the local experiment root. It uses runner `2b9cf3c`, the explicit
270000-second wait and a 274000-second containing service, with 4/3-GiB
max/high and zero swap. It waits for parent invocation `6bc5f930f57f47dc994bdcf21cea3635`
and seals that parent's `route` child using the remote runner above. It still
targets the **v3** closure, not the newly compiling local v4 outputs.

## Deployed Checkpoint

The three v1 compilations on `seele`
(`ssh -p 23333 chuxiao@10.129.161.241`) completed successfully. All canonical
XO macro/stream/master checks passed, with no implicitly mapped memory masters.
They are **not completed routes**. Fresh resource estimates are:

| Algorithm | LUT | FF | BRAM18 | URAM | DSP |
| --- | ---: | ---: | ---: | ---: | ---: |
| CC | 898247 | 600666 | 1102 | 768 | 0 |
| ResPR | 999427 | 6770535 | 1241 | 768 | 532 |
| FullPR | 967573 | 821535 | 1211 | 768 | 436 |

All three original placements require 384/64/320 URAM across SLR0/1/2,
exceeding SLR0's independently queried 320 sites. Moving only
`lksg_stream_4` from SLR0 to SLR1 gives 320/128/320. This leaves all cache,
graph and CU capacities unchanged; it is not a routing-fit guarantee.

ResPR has an additional hard conflict: its 6,770,535 estimated FF exceed the
whole U55C's 2,607,360 FF. Apply alone accounts for 6,019,300, including
5,919,616 pipeline phi FF. Do not submit this v1 estimate as a fitting design.
Integration `8f5928e` changes lane packing without changing arithmetic/ABI;
old/new source checks pass bitwise against the same reference, but only a
**fresh synthesis** can establish whether the resource problem is removed.
Its separate v2 ResPR compile and link have finished, but the final route
fails strict setup timing and is not board-admitted.

All paths below are relative to
`/data/chuxiao/baseline_hardware_validation_20261017/` on that host:

| Algorithm | Output | Service / invocation |
| --- | --- | --- |
| CC | `production-cc-compile-v1` | `spine-production-cc-compile-20261018-v1.service` / `936a8b164c5d45e99a976fff2fb37fa0` |
| ResPR | `production-respr-compile-v1` | `spine-production-respr-compile-20261018-v1.service` / `e14684e208574d41982176c56ffb0a40` |
| FullPR | `production-fullpr-compile-v1` | `spine-production-fullpr-compile-20261018-v1.service` / `f56396f235e143f69d68256dbbb76edd` |

The fixed compile runner is simulator `92ab3cd`, directory
`algorithm-runner-92ab3cd`, with archive `production-algorithm-runner-v1.tar.gz`
SHA-256 `bdf34026a2e1a60b637659709df141d25c1a578a4a06f66f2d850b18eeb9f50e`.
The 180-file source closure is `production-algorithm-sources-v1`, owned by
integration `8e9ea1b`; its `sources.json` SHA-256 is
`6db652360011da5bdd2cb230f7ad39fa6eaa98095b186d010155ca1fb6e345dc`.
The same closure is retained under the local experiment root
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/`.
Do not replace these active runners, sources or outputs in place.

The v1 export reviews are retained in `production-{cc,respr,fullpr}-export-review-v1`
using simulator `25526fb` in `algorithm-review-runner-v1`, archive SHA-256
`f006a42f9f57268d6e52560ab24d7bd4fb182db5708b70cfc8c342bd942d0a6f`.
These historical reviews screened only URAM; the new inspector additionally
rejects whole-device LUT/FF/BRAM/URAM/DSP overflow. The old reviews are not
silently rewritten to claim that additional check.

The new closure `production-algorithm-sources-v2` records integration `8f5928e`.
`production-respr-compile-v2` uses the unchanged `algorithm-runner-92ab3cd`,
service `spine-production-respr-compile-20261018-v2.service`, invocation
`317f14ce51554b3f81759b9440d93a2c`, with the same 16-GiB containment and
unchanged algorithm/cache/workload scope. CC/FullPR v1 XOs remain independent.
The v2 source index SHA-256 is
`fe0e1ff3a52491f50dee61203ffa11156c09d567254a8c1a3de11482000d62d8`.
The fresh v2 Apply report estimates 269408 FF (versus 6019300 before),
65487 LUT, 90 BRAM18, zero URAM and 272 DSP. The complete v2 compilation passed.
Its complete fresh ledger is 997852 LUT, 1020643 FF, 1241 BRAM18, 768 URAM
and 532 DSP. These remain HLS estimates, not routed utilization or timing.
A separate link rechecks the complete resource/ABI ledger and applies the
same one-CU placement change before v++. It uses output
`production-respr-route-v2`, service
`spine-production-respr-route-20261018-v2.service`, invocation
`0b6cd3bdd41040b59ff3a890c7a218a2`, and unchanged runner `417a8bd`.

The initial CC and FullPR experimental links used simulator `417a8bd`,
directory `algorithm-route-runner-417a8bd`. The minimal runner archive is
`production-algorithm-route-runner-v2.tar.gz`, SHA-256
`958042f8e0ab8036eac8de42ab18c36d7587d395a463acddf86021ec88ed2c62`.
Both pass fresh whole-device/URAM screens after the one-CU move, canonical
ABI/stream checks, and all six environment probes. Both have since completed
linking but failed strict timing/clock admission; they are not FPGA evidence:

| Algorithm | Output | Service / invocation |
| --- | --- | --- |
| CC | `production-cc-route-v1` | `spine-production-cc-route-20261018-v1.service` / `134e9b3bde86475d877333406235a149` |
| FullPR | `production-fullpr-route-v1` | `spine-production-fullpr-route-20261018-v1.service` / `0b93dc35db4f48bcb64866adf28ff699` |

Each has a separate 40-GiB max / 36-GiB high cgroup with no swap. After ResPR
compilation, four 40-GiB links plus 32+8-GiB reserves require
200 GiB under atomic admission; about 469 GiB was available at the recorded
checkpoint. This is a budget/admission observation, not a peak-RSS prediction.

The separately contained `production-algorithm-bank-smoke-v1` source test
passes weighted, destination-only and unit edge formats (11.78 s elapsed,
287.9 MiB peak). It is functional C++ evidence only, not RTL/backpressure or
timing evidence. SSSP's independent remote route and board continuation are
documented in the [remote package](../remote/README.md).

## Reproduction

Run from a fixed simulator checkout. All output paths must be new.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build prepare \
  --integration /home/chuxiao/grasu-regraph-complete-g \
  --grasu /home/chuxiao/GraSU \
  --regraph /data/tmp/chuxiao/ReGraph_sssp_hw_coldinit_250mhz_scratch \
  --output /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-algorithm-sources-v1
```

Transfer the closed source directory and a separately hashed fixed runner to
the build host. Execute each algorithm under its **own cgroup v2 service**:
16 GiB `MemoryMax`, 14 GiB `MemoryHigh`, zero swap, group OOM kill, 400% CPU,
8192 tasks and 65536 open files. Compiles are sequential within each algorithm;
separate algorithms can run concurrently when full finite budgets fit.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build execute \
  --algorithm connected_components \
  --sources /data/chuxiao/baseline_hardware_validation_20261017/production-algorithm-sources-v1 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1 \
  --shim /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1
```

Use `residual_pagerank` or `full_pagerank` and a distinct output for PR. The
atomic compiler lease reserves each build's **full** limit, all known peer
limits, 32 GiB system reserve and 8 GiB background allowance. It does not wait
for all tools to exit. Unknown/unbounded peers prevent admission. A live RSS
and available-memory watchdog remains active. Each kernel has a one-hour
deadline; queue admission has a one-day deadline; at least 80 GiB free disk is
required before generation. These are safety limits, not runtime predictions.

## Reading Results

`execution.json` is the live status and retained error record. `sources.json`
owns the transported source identity, `manifest.json` the generated commands
and compile-time pins, `environment.json` the explicit tool environment,
`preflight/results.json` the six environment probes, and `compile/` per-kernel
logs/progress/resource samples. Outputs stay outside Git.

`COMPILATION_PASS_AWAITING_RESOURCE_RTL_AND_ROUTE` means all declared XOs exist
and their hashes/source pins passed. It **does not** mean a bitstream exists or
the design fits the board. Failures remain `FAILED_RETAINED` in their original
directory. Run the command/source-admission tests with:

```bash
python3 -m unittest discover -s tests -p test_g_algorithm_build.py -v
```

## Post-Synthesis Review

The read-only review requires a **terminal successful** compilation, unchanged
source/runner/tool/config/XO pins, all declared kernels completed without OOM,
and the independent, hash-verified
[portable storage-query package](../../resource_evidence/README.md).
It never rewrites a running compilation or changes placement automatically.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build review \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --storage /data/chuxiao/baseline_hardware_validation_20261017/algorithm-review-runner-v1/docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/hardware_validation/complete_pipeline/resource_evidence \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-cc-export-review-v1
```

Use the actual separately frozen review runner's path. The command compares
exported `GRASU_*`/`CACHE_BANK_*` macros to the declared compile command, requires
the 512-bit aliased PMA/row master, checks every stream endpoint/direction/data
width and repeated memory binding, and counts **all CUs** from fresh top-level
reports at the exact U55C part and rounded 150-MHz target. Internal Vivado
scratch copies of `kernel.xml` are not canonical XO interfaces.

The result includes LUT/FF/BRAM/URAM/DSP totals per SLR, an independent **URAM
placement** check, and a **whole-device resource-estimate** check. The latter
requires each exact-part HLS report to agree on U55C capacities and rejects
any total estimate above them. It does not subtract shell resources or
establish per-SLR LUT/FF placement fit.
`EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION`
is not full resource fit, AXIS sideband/protocol verification, finite RTL
backpressure, a routed clock, board correctness or published-performance match.
Any automatically assigned memory masters are explicitly listed for manual
review. A storage conflict remains a failure requiring a separately reviewed
placement/config; no shrinkage of graph/cache capacity is allowed as a workaround.

```bash
python3 -m unittest discover -s tests -p test_g_algorithm_inspection.py -v
python3 -m unittest discover -s tests -p test_g_algorithm_review.py -v
```

## Experimental Link

Use a separately frozen runner with the whole-device check. `route-experiment`
revalidates the terminal compilation and portable capacity capsule, retains
the original review, changes only `lksg_stream_4:SLR0` to `SLR1`, relocates
output directories/platform, and independently reinspects the candidate.
Remaining resource conflicts or implicit memory masters stop before v++.
Every original algorithm XO remains; no kernel is substituted or removed.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build route-experiment \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --storage /path/to/frozen/resource_evidence \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-cc-route-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1 \
  --shim /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1
```

Launch under its own 40-GiB max / 36-GiB high cgroup, zero swap, group OOM kill,
800% CPU, 8192 tasks and 65536 open files. Full finite-budget leases retain the
32+8-GiB reserve and live watchdog; no global tool-idle requirement is imposed.
Each link has a 12-hour deadline, a one-day memory-admission deadline, and a
160-GiB free-disk prerequisite. Vivado synthesis and implementation each use
two jobs. Runtime limits are not estimated completion times.

`LINK_PASS_UNVERIFIED_RTL_AWAITING_TIMING_AND_BOARD` is deliberately distinct
from hardware admission. Finite algorithm RTL/backpressure evidence, actual
clock/timing, connectivity and device correctness still need separate checks.
Neither a passing compile nor a bitstream's existence supplies new Figure 7
performance or an original-publication match. All outputs and failures stay
in their fresh directories; the paper and existing figures remain unchanged.

### Physical Timing Retry

CC v1 completed the link but **failed strict admission**. Its final routed
summary reports WNS -0.084 ns, TNS -5.751 ns and 163 failing setup endpoints.
The returned clock metadata also fails the required 150-MHz data-clock check.
The binary SHA-256 is
`a8e6209e8a84ad4c1e6e675d2be83d890b45303bab9b26a68cfb1a950903b8b1`;
the retained `production-cc-return-follow-v1` report is `FAILED_RETAINED`.
It has not been programmed or admitted to a performance comparison.

CC v2's physical-only retry also completes linking but fails strict setup
timing: WNS -0.070 ns, TNS -1.986 ns and 68 failing setup endpoints. Hold WNS
is +0.009 ns with no hold or pulse-width violations. The local
`production-cc-return-follow-v3` retains `FAILED_RETAINED`; no board was
requested. This retry still uses the v1 source closure, not the fresh cache
comparison stage in v4. Its failure is not evidence about v4 routed timing.

`route-experiment --timing-profile aggressive-route-v1` supports a separate
physical-only retry, using the same five Vivado placement/physical-opt/route
properties as the independent SSSP retry. It keeps every XO, connectivity,
capacity and target clock unchanged. The selected profile is frozen in the
route manifest; returned admission requires exactly its declared properties,
with no additional Vivado overrides. The default requires no Vivado section.
Use a new output/service and receipt, never rewrite the failed v1 evidence.
Final clock/timing requirements remain unchanged; this option is not a waiver
or a prediction of successful timing closure.

FullPR v1 also completed v++ but failed strict admission: WNS -0.269 ns,
TNS -161.233 ns, 1520 failing setup endpoints and actual DATA clock 144 MHz
instead of 150 MHz. Its original return and dependent board continuation
both retain their failures; no card was programmed by that continuation.

Its independent physical-only retry is `production-fullpr-route-v2`, service
`spine-production-fullpr-route-20261018-v2.service`, invocation
`c0e275f36b064ee598681cfbaadc5f48`, using frozen runner `8fff331` and profile
`aggressive-route-v1`. The route manifest SHA-256 is
`34d7ac3655317d78b04023ca7f1be2e75b93c7332747b2bc62e6d79d72694572`.
At the 12:17 UTC checkpoint it is executing block synthesis (61/322 jobs),
not waiting for admission. Approximately 446 GiB is available. SSSP and CC
already-admitted finite builds also continue concurrently.
The FullPR retry retains its own 40/36-GiB max/high limits and zero swap;
neither the clock requirement nor cache capacity is relaxed.

ResPR v2 has now completed linking but fails strict setup timing: WNS
-0.107 ns, TNS -18.575 ns, 443 failing endpoints, with zero OOM events.
Its independently returned xclbin reports DATA 147 MHz and HBM 434 MHz;
the required 150/450-MHz clocks are not met. The retained local
`production-respr-return-follow-v1` fails before requesting a board. The
trusted return receipt SHA-256 is
`10aafc0978b5304be550905754f173fcef4c73fc6f666608ef6bcef6e814647b`.
Its final report is
`production-respr-route-v2/reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt`.
The independent [checkpoint diagnostic](postroute/README.md) explores physical
refinement without changing that failed artifact or generating a bitstream.
Diagnostic completion is not routed signoff or authorization to use the old
binary in a performance comparison.

## Return And Timing Admission

Use `seal-route` on the builder only after the **exact service invocation**
has terminated successfully. It requires unchanged compilation/source/XO pins,
six passing environment probes, clean link exit, zero OOM events, the candidate
binary and exactly one final routed timing report. No remote absolute paths
are rewritten. The new return directory contains a hash-indexed `receipt.json`,
the binary, route logs/reports and compile/source identity records.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build seal-route \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --route /data/chuxiao/baseline_hardware_validation_20261017/production-cc-route-v1 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-cc-return-v1 \
  --unit spine-production-cc-route-20261018-v1.service \
  --invocation 134e9b3bde86475d877333406235a149
```

Run the sealer in a separate bounded 4-GiB/no-swap service using a fixed runner,
not by editing the live compilation runner. Its only stdout is the receipt
SHA-256. Obtain that digest over the trusted SSH connection and copy the whole
return directory with rsync; then run the local, read-only admission:

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build admit-route \
  --returned /path/to/local/production-cc-return-v1 \
  --sources /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-algorithm-sources-v1 \
  --output /path/to/new/production-cc-route-admission-v1 \
  --receipt-sha256 "$RECEIPT_SHA256"
```

Use the distinct compilation, source closure, invocation and output for each
algorithm (ResPR uses v2). The local check dumps the returned xclbin's actual
XRT metadata and requires the exported CU identities/control protocols, one
150-MHz data clock, exact argument-to-HBM mappings including pointer aliases,
512-MiB pseudochannels, and every declared stream endpoint pair. Incidental
`dc_N` stream names are not an ABI. Unused pointer-shaped control arguments
are not invented memory masters. The final timing report must meet setup,
hold and pulse-width constraints; old SSSP connectivity is not a substitute.

`ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD` admits only this source,
clock, connectivity and timing evidence. It does **not** admit whole-algorithm
RTL, FPGA arithmetic/convergence, stage performance, a new Figure 7 row or a
publication-performance match. Failures are retained; no FPGA is programmed
by these commands. Until links finish, these are reproduction instructions,
not a claim that any algorithm has passed routed admission.

```bash
python3 -m unittest discover -s tests -p 'test_g_algorithm_*.py' -v
```

## Fresh Adapter RTL

`adapter-rtl` first revalidates the terminal compilation and exact exported
destination-only/sharded bank-stream ABI. It extracts the **full adapter top
and its generated RTL from that XO**, not a helper model or an old reference
XO. It freezes the benches, generated RTL, source/compile review, tools and
runner before executing xvlog/xelab/xsim. A placement-screen conflict may be
recorded here without blocking an isolated adapter functional test; it is
not waived for a full-device link or board claim.

The existing 23-case bank-stream bench covers empty/single sources, packed-row
and tile boundaries up to 1025 vertices, sparse early/late/interleaved sources,
multi-segment rows, injected 1/64/128-cycle ordered memory delays, and a
1000-cycle output stall. It checks output payload/KEEP/STRB/LAST, stability
under backpressure, no writes, legal aligned AXI bursts within 4-KiB bounds,
padded directory capacity, and request/response conservation. The independent
destination-only wrapper expects `partition_offset + local_dst19`, plus the
dummy marker. The weighted wrapper instead preserves weight/destination bits.
The fixed partition offset is 65536 and local capacity 32, so confusing local,
global and weighted formats cannot silently pass. This packet test is **not**
graph-level CC/PR arithmetic/convergence evidence.

The first CC/FullPR trials remain `FAILED_RETAINED` in
`production-{cc,fullpr}-adapter-rtl-v1`, using simulator `eb31c55`:
services `spine-production-{cc,fullpr}-adapter-rtl-20261018-v1.service`,
invocations `9b4f611563d9478dac08a0871d03e217` and
`f5422ff57f674eb6a7c7403e49a0c1d7`, respectively. The reused weighted bench
expected opaque raw destination words, which contradicts the destination-only
HLS contract above. xsim returned zero despite its `$fatal`; the strict
complete-transcript gate correctly rejected both runs. The new wrapper changes
only the expected packet format and adds detailed mismatch diagnostics. It
does not change HLS, memory responses, sideband checks or trial coverage.
The separate v2 runs now each pass all 23 trials, with terminal status
`FRESH_ADAPTER_AXI_RTL_PASS_NOT_ALGORITHM_RTL_OR_BOARD`, no reported errors,
and zero OOM events:

| Algorithm | Output | Service / invocation |
| --- | --- | --- |
| CC | `production-cc-adapter-rtl-v2` | `spine-production-cc-adapter-rtl-20261018-v2.service` / `a97e483050a24c6fa90dc826bba3c0ff` |
| FullPR | `production-fullpr-adapter-rtl-v2` | `spine-production-fullpr-adapter-rtl-20261018-v2.service` / `856d494088cb4d8aa85533d3c1c7af0e` |
| ResPR | `production-respr-adapter-rtl-v2` | `spine-production-respr-adapter-rtl-20261018-v2.service` / `01cb32d95ab64440b30c1a2552deab5c` |

The fixed runner is simulator `10a385b`, directory
`algorithm-rtl-runner-10a385b`, archive
`production-algorithm-rtl-runner-v2.tar.gz`, SHA-256
`90b74e531f2767436643e9140113114fa112eeab9678234ef8aeb88372b1e44e`.
CC and FullPR consume their v1 compilation; ResPR consumes its independent
v2 compilation. The v1 failures remain intact. These passes verify the actual
adapter interfaces, not whole-algorithm RTL, routed timing or board convergence.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build adapter-rtl \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --storage /path/to/frozen/resource_evidence \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-cc-adapter-rtl-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1 \
  --shim /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1
```

Use a separate 4-GiB max / 3-GiB high, zero-swap, group-OOM-kill service with
200% CPU, 4096 tasks and 65536 open files. The same atomic lease policy keeps
32+8-GiB reserves and counts full peer limits. Each tool step has a 180-second
deadline and a live-memory watchdog. A terminal pass is explicitly
`FRESH_ADAPTER_AXI_RTL_PASS_NOT_ALGORITHM_RTL_OR_BOARD`; whole-algorithm RTL,
HBM timing, routed clock, board correctness and publication match remain false.
Synthetic 10-ns bench clocks and injected memory delays are not converted
into predicted FPGA performance. Failed runs remain in their original folder.

## Automatic Return

Freeze the current runner in a new directory on both hosts. Do not overwrite
the older route/compile runners. The follower waits for one explicit successful
service invocation, launches its sealer in a separate 4-GiB/3-GiB/no-swap
remote service, verifies the trusted receipt digest after rsync, and invokes
the same strict admission above. Source-closure, algorithm, service or invocation
drift rejects the result. The local follower also needs a separate
4-GiB/no-swap cgroup and a finite runtime; the default wait is 133200 seconds.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build.follow \
  --target chuxiao@10.129.161.241 --port 23333 \
  --algorithm connected_components \
  --runner /path/to/new/fixed/remote/runner \
  --capsule /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --compilation /data/chuxiao/baseline_hardware_validation_20261017/production-cc-compile-v1 \
  --attempt /data/chuxiao/baseline_hardware_validation_20261017/production-cc-route-v1 \
  --returned /path/to/fresh/remote/return \
  --unit spine-production-cc-route-20261018-v1.service \
  --invocation 134e9b3bde86475d877333406235a149 \
  --sources /data/chuxiao/experiments/baseline_hardware_validation_20261015/production-algorithm-sources-v1 \
  --output /path/to/fresh/local/follower
```

`ALGORITHM_REMOTE_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION` binds the exact
local admission report. It leaves board, convergence and publication claims
false. The separate [full-graph continuation](../../../fullgraph_readiness/README.md#board-continuation)
consumes CC/ResPR admission after offline preparation succeeds; FullPR is
returned and reviewed independently, not silently treated as convergence.

The original local followers use frozen simulator `237b519` and its separately
hashed `production-return-board-runner-237b519.tar.gz` archive (SHA-256
`2c06795458901aa036cf3e11b23cc13ecebfd6a6aa0914df2f74da2b77b6263c`).
Each has a separate 4-GiB max/3-GiB high/no-swap cgroup, CPU 120, and a finite
145800-second service lifetime. They initially report
`WAITING_FOR_EXACT_REMOTE_ROUTE`, with no FPGA requested:

| Algorithm | Local output | Local service / invocation |
| --- | --- | --- |
| CC | `production-cc-return-follow-v1` | `spine-production-cc-return-20261018-v1.service` / `a228795e0777452ea6e97b7f62366cd5` |
| FullPR | `production-fullpr-return-follow-v1` | `spine-production-fullpr-return-20261018-v1.service` / `93deef1f0d06489ea1975f71779f911a` |
| ResPR | `production-respr-return-follow-v1` | `spine-production-respr-return-20261018-v1.service` / `a8e06769b82c4d92a8c8066e2a41e054` |

Each consumes the exact remote route invocation already recorded above, then
creates a distinct remote `production-{cc,fullpr,respr}-return-v1` receipt.
Its local `admission/summary.json` must pass before any board continuation.
The service being active, or a partial binary appearing in the build tree,
does not satisfy this condition. FullPR uses the separate
[resident-convergence protocol](../../../fullgraph_readiness/fullpr_resident/README.md),
not the legacy fixed-round test or three-algorithm supervisor.

CC's v1 route failed strict timing admission. Its current local follower is
`spine-production-cc-return-20261018-v3.service`, invocation
`5365002cfc3a421fbb8ba3a53d8841e8`, output `production-cc-return-follow-v3`.
It waits for route-v2 invocation `ecd61444f76145a6bac7846e41898060`, returns
to `production-cc-return-v3` remotely and uses frozen runner `da7e791` on
both hosts. Its archive SHA256 is
`8f8d2cf27c6050567c9574eb2708f58af667d2ff5bd86b4f078392a4ab40af4c`.
V2 was stopped while still waiting, without requesting a board. The new
follower retains the 4/3-GiB limits, zero swap, group OOM kill and finite
lifetime; retained `active/exited` success is checked by exact invocation,
exit status and zero main PID. ResPR's selector above is unchanged.

FullPR's failed v1 follower is superseded only for the new attempt by
`spine-production-fullpr-return-20261018-v2.service`, invocation
`9f93433f962740e085a10b711c3394b4`, output
`production-fullpr-return-follow-v2`. It waits for exactly the FullPR v2
route invocation above and seals to remote `production-fullpr-return-v2`.
Both hosts use runner `da7e791` and the same hashed archive as CC's current
follower. The physical-profile-aware strict checks remain enabled. A separate
FullPR board continuation waits for this exact follower, not the rejected v1.
