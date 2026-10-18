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
Its separate v2 ResPR compile has finished; the experimental link is running,
not yet accepted as a routed design.

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
A separate link rechecks the complete resource/ABI ledger and applies the
same one-CU placement change before v++. It uses output
`production-respr-route-v2`, service
`spine-production-respr-route-20261018-v2.service`, invocation
`0b6cd3bdd41040b59ff3a890c7a218a2`, and unchanged runner `417a8bd`.

CC and FullPR experimental links are active under simulator `417a8bd`,
directory `algorithm-route-runner-417a8bd`. The minimal runner archive is
`production-algorithm-route-runner-v2.tar.gz`, SHA-256
`958042f8e0ab8036eac8de42ab18c36d7587d395a463acddf86021ec88ed2c62`.
Both pass fresh whole-device/URAM screens after the one-CU move, canonical
ABI/stream checks, and all six environment probes. They are **running links,
not completed bitstreams or FPGA evidence**:

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
A new run must actually pass; diagnosing the bench does not admit that pass.

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
