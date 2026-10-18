# Remote Production Routing

## Scope

Use the high-memory `seele` host for compilation/routing, not FPGA measurement.
It has no Xilinx FPGA device. Board admission and measurement remain on
`trifoliate`. The production source, eleven XOs, 22 CUs, connections, SLR
placement, 150-MHz target and two-job settings are unchanged. This is a new
attempt with an explicitly recorded remote toolchain/platform, not a retry
written over the earlier attempt or a new algorithm-performance result.

The owning code is
`spine_cycle_sim/experiments/evaluation_impact/common_g/complete_pipeline/hardware/remote/`:
`capsule.py` exports/verifies immutable inputs and relocates only tool/output
paths; `environment.py` captures the explicit vendor/platform closure;
`study.py` owns admission, preflight and the bounded link. `delivery.py` seals
terminal remote evidence without rewriting paths; `admission.py` checks its
local parent, exact command/configuration, topology and strict final timing.
`qualification.py` reuses the three production board validators;
`transport.py` owns bounded SSH/rsync and `continuation.py` the unattended
wait/return/qualification sequence. `__main__.py` is the CLI. A successful
remote link is never itself board or baseline admission.

## Live Attempt

The production SSSP link is running on `seele`, under service
`spine-g-production-remote-20261017-v1.service`, invocation
`25c17cb9dbea43bb8d4184d281ba147b`. It passed all six environment checks and
entered block synthesis at 2026-10-18 03:24:43 UTC (11:24:43 CST). At 03:29 UTC its memory
peak was approximately 11.4 GiB, with 478 GiB available on the host and no
OOM events. These are build observations, not final routed timing.

The frozen link runner is simulator commit `7e0ed3a`; its archive hash is
`7cd42d9a81d63f4dc4bd0294b5639faa71c1b89c8d105ca80d09341608618f20`.
The capsule hash is
`1077ef1456e8626a2306f26c4f4a4be8f1e41976e89925763731030e708331b2`.
The output is `production-sssp-route-v1` under the remote root below. Keep
that runner untouched; return sealing uses a separately frozen runner.

## Inputs And Environment

The parent is the [reviewed production packet](../README.md), raw directory
`/data/chuxiao/experiments/baseline_hardware_validation_20261015/g-production-route-v1`.
Its manifest SHA-256 is
`f75ec64b70c5e65d2d7c79658b59097387eb9af3a5ac6b11e28b4cab6a663ae0`.
All 2485 parent pins were checked while exporting the fresh relocation capsule.
The original manifest is copied byte-for-byte. Every copied XO, source member,
connectivity file and compiler shim has an indexed hash tied to that parent.
Paths in legacy include flags remain unchanged: this run links frozen XOs,
not source files. An include path is not evidence of fresh source compilation.

Remote roots:

- Tools: `/data/feiyang/xilinx`, Vitis/Vivado/Vitis_HLS 2024.1.
- Compatibility libraries: `/data/feiyang/xilinx/compat-2024.1`.
- Platform: `/data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm`.
- Owned outputs: `/data/chuxiao/baseline_hardware_validation_20261017/`.

Freeze the runner with `git archive` at the tested commit, transfer that
archive and the capsule, and extract them in new directories. The environment
capture pins settings/loaders, launchers, host compilers, platform files and
compatibility libraries. It does not claim to hash every vendor executable.
Six checks must pass before routing: Vitis/Vivado/GCC/G++ versions, host-thread
compilation with the reviewed shim, and execution of that test binary.

## Resource Contract

The inspection found 499 GiB total and approximately 488 GiB available RAM,
128 logical CPUs and 1.2 TiB free under `/data`. These are observations, not
permission for unbounded concurrency. Each route retains a 40-GiB hard limit,
36-GiB high watermark, zero swap and group OOM kill. Admission reserves 32 GiB
for the system, 8 GiB for background activity, and each peer build's full
finite limit. Unknown/unbounded FPGA compiler peers block admission. Concurrent
bounded builds are allowed when the budgets fit; no all-tools-idle rule exists.

At least 160 GiB free build disk is required before environment preparation.
The link deadline is twelve hours, admission queue is at most one day, and the
service lifetime must cover both. The live tree-RSS/available-memory watchdog
remains active after admission. Use `OOMPolicy=kill` with systemd; the kernel
`memory.oom.group` value is independently checked by the runner.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote prepare \
  --parent /path/to/frozen-production-route \
  --output /path/to/fresh-capsule

# Run from the frozen runner inside its bounded user service on seele.
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote execute \
  --capsule /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/production-sssp-route-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /data/feiyang/runtime/frontier-xrt-20261015/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

## Acceptance And Figures

`execution.json` records live/terminal status, and `manifest.json` freezes
the relocated command and inputs. `LINK_PASS_AWAITING_TIMING_AND_BOARD` means
only that linking returned successfully and produced the indexed binary.
Strict routed timing/topology, production G state/metadata, resident physical
PMA handoff and board performance remain separate gates.

The same-platform original A4 control now passes its fresh 18-row FPGA matrix
in `a4-board-supervisor-v3` (invocation
`e0c7225785574947aa931e5646025dea`): three graphs, two argument bindings,
three repetitions. Its boundary is one resident signed fixed-point PR
superstep, not convergence or host-inclusive dynamic update. It is not a
published-throughput reproduction. The original publication topology and
this resource-matched control must not be substituted for one another.

Final Figures 7--11 still require the latest integrated baseline and fixed
Spine comparisons. Keep FPGA latency, host-inclusive throughput, conserved
traffic/modeled HBM energy, predicted normalized stages, and realized-work
model validation distinct. No historical figure or paper is changed by the
remote route launch.

The older diagnostic `g-gr-board-supervisor-v5` also passes all declared
18 G and 27 resident G+SSSP executions (54 and 81 batch rows, respectively),
with zero OOM events. Its older search/cache exports do not qualify this
production-source build. The fresh metadata-host v2 passes its CPU positive
and stale-generation controls; same-address device consumption still needs
the returned production artifact.

## Return And Board Qualification

`seal` requires a successful terminal service with the exact invocation,
zero OOM events, all six successful raw preflight resource records, unchanged
remote input pins, the binary and exactly one final routed timing report.
It copies the original manifests byte-for-byte into a new portable return
directory. The receipt indexes source identities and copied hashes; obtain
its digest over SSH, not from an untrusted replacement file.

`admit` verifies that receipt, rechecks the original local production parent,
reconstructs the relocated command/configuration and required input coverage,
and independently inspects both xclbins. Clock, all 22 CUs and connectivity
must match. Final WNS/WHS/WPWS, TNS and failing endpoints must pass the existing
strict routed-timing parser. A missing or failed check prevents programming.

`qualify` reuses the existing numerical validators without accepting an old
diagnostic route in place of the returned candidate. With three repetitions,
it runs 3 native five-shard G executions, 3 same-BO metadata executions and
27 resident G+SSSP executions. The metadata case checks two generations of
single-segment row consumption, **not** general binary-search refresh.
Finite-stream integrated RTL and a publication-performance match are separate.

The local supervisor requires an 8-GiB hard cap, 7-GiB high watermark, zero
swap and group OOM kill. It admits full bounded peer budgets and the existing
104-GiB board-watchdog reserve, waiting at most one hour for safe memory.
It does not wait for every other compiler to exit. The board remains leased,
idle-checked and PCIe-BDF checked before programming; failures are retained
without automatic board resets or numerical retries.

Preserve the route's terminal systemd identity while returning it. A transient
unit may otherwise be garbage-collected after a successful exit. The live
attempt has the bounded, ordering-only reference
`spine-g-production-return-reference-20261017-v1.service` (invocation
`3f5bf99ff7934f87bb770f747ab3a838`): `After=exact-route.service`, a 32-MiB
cap and a 40-hour lifetime. `After=` neither starts nor restarts the route;
do not replace it with a dependency that can restart a finished build. A local
short-lived service check verified retention of the exact terminal invocation.
Keep the reference until qualification finishes, then stop it. A missing or
changed route invocation still fails closed; the receipt does not synthesize
terminal service evidence from the presence of an xclbin.

```bash
# Explicit manual stages; use fresh output directories.
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote seal \
  --capsule /remote/capsule --attempt /remote/route --output /remote/returned \
  --unit exact-route.service --invocation EXACT_32_HEX_INVOCATION

python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote admit \
  --returned /local/returned --parent /local/frozen-production-route \
  --original /local/original.xclbin --output /local/fresh-admission \
  --receipt-sha256 EXACT_RECEIPT_SHA256

# Inside the local bounded service: wait, seal via a bounded remote service,
# transport, verify, admit and run the unchanged board matrices.
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote follow \
  --target chuxiao@10.129.161.241 --port 23333 \
  --remote-runner /remote/separate-return-runner \
  --remote-capsule /remote/capsule --remote-attempt /remote/route \
  --remote-returned /remote/fresh-return \
  --route-unit exact-route.service --route-invocation EXACT_32_HEX_INVOCATION \
  --native-preflight /local/native-host --metadata-preflight /local/metadata-host \
  --gr-preflight /local/gr-host --parent /local/frozen-production-route \
  --original /local/original.xclbin --output /local/fresh-continuation \
  --device 0 --repeats 3 --execute
```

`results.json` reports waiting, transport and board states; a failed child
retains its own raw records. Successful completion remains
`PRODUCTION_G_GR_BOARD_QUALIFICATION_PASS_NOT_BASELINE_ADMISSION`, not final
Figures 7--11 or published-G/R reproduction. Regressions cover moved evidence,
changed pins/configuration, failed/restarted services, OOM/preflight rejection,
strict timing/CU rejection, memory admission and partial/failed board matrices.
