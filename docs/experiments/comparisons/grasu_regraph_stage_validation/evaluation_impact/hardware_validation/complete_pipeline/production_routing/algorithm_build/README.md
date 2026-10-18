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
must examine the actual exported resources, AXI/stream ABI and algorithm-specific
finite transactions before starting a separate link attempt.

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
verified portable capacity queries. No simulator timing coefficient changes here.

## Deployed Checkpoint

At **2026-10-18 04:16 UTC**, all three fresh services on `seele`
(`ssh -p 23333 chuxiao@10.129.161.241`) are active with no reported errors.
CC has reached its frontend mux; both PR modes have reached their distinct
apply kernel. These are running compilations, not completed routes.

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

The result includes LUT/FF/BRAM/URAM/DSP totals per SLR, but the capacity decision
is **URAM storage only**. `EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION`
is not full resource fit, AXIS sideband/protocol verification, finite RTL
backpressure, a routed clock, board correctness or published-performance match.
Any automatically assigned memory masters are explicitly listed for manual
review. A storage conflict remains a failure requiring a separately reviewed
placement/config; no shrinkage of graph/cache capacity is allowed as a workaround.

```bash
python3 -m unittest discover -s tests -p test_g_algorithm_inspection.py -v
python3 -m unittest discover -s tests -p test_g_algorithm_review.py -v
```
