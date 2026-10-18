# Routed Checkpoint Diagnostic

## Scope

The ResPR v2 link completed on the high-memory host, but its final report has
WNS -0.107 ns, TNS -18.575 ns and 443 failing setup endpoints. It is not
timing-admitted and cannot supply a formal board comparison. Its worst setup
path runs from a GraSU cache URAM output into update logic; reported data-path
delay is 6.569 ns, of which 4.796 ns (73%) is routing. This motivates a
physical-only diagnostic, not a claim that physical optimization will succeed.

The owning package is
`spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.postroute`.
`inputs.py` admits one exact terminal successful link, including its environment
probes, source/XO closure, zero OOM record, binary identity and unique final
routed checkpoint. The default `--producer-kind algorithm` uses the experimental
CC/ResPR/FullPR producer contract. The distinct SSSP relocation contract requires
`--producer-kind remote-sssp`; `sssp_inputs.py` replays that producer's capsule,
parent identity, full command, raw link and all six raw environment checks.
It supplies an in-memory algorithm label without modifying the frozen parent.
There is no schema guessing or fallback after failed validation. A running,
failed or substituted producer is rejected before opening its checkpoint.
`refine.tcl` opens the admitted checkpoint
in a new non-project session, preserves its 150/500/450-MHz clock constraints,
and records four reports: baseline, clock optimization, aggressive fanout
optimization, then alternate replication. All passes, including regressions,
are retained; the final checkpoint is not selected by best observed WNS.
`analysis.py` preserves setup, hold and pulse results separately. `probe.py`
owns containment, atomic admission, execution and failure retention.

**No bitstream is generated, no FPGA is programmed, and neither a positive
WNS nor diagnostic completion admits the old xclbin.** Route-status and DRC
reports remain raw diagnostics, not independently validated signoff gates.
A useful physical strategy must subsequently enter a separately frozen
artifact-generation and full timing/clock/topology/RTL/board admission flow.
No HLS arithmetic, ABI, capacity, clock constraint or simulator factor changes.

## Deployed Attempt

The frozen runner is simulator `4472627`, directory
`physical-diagnostics-runner-4472627` under the remote campaign root below.
The minimal runner archive SHA-256 is
`dd7d1c5d64d7d2f41c4a7532c036e9312ef96730b74f7911514e564a6a77dc8c`.
Service `spine-respr-postroute-20261018-v1.service`, invocation
`6ce4cd7327e84d7ea534168580fff71d`, owns output
`production-respr-postroute-diagnostic-v1`. Read-only inspection at
2026-10-18 15:24 UTC found it complete with all four reports retained:

| Pass | WNS (ns) | TNS (ns) | Failing setup endpoints | Strict timing |
| --- | ---: | ---: | ---: | --- |
| Baseline | -0.107 | -18.575 | 443 | Fail |
| Clock optimization | -0.107 | -18.575 | 443 | Fail |
| Aggressive fanout | -0.080 | -13.795 | 405 | Fail |
| Alternate replication | -0.080 | -13.795 | 405 | Fail |

All four reports have zero hold and pulse failures. The final result is
`POSTROUTE_DIAGNOSTIC_COMPLETE_NOT_BITSTREAM_OR_BOARD_ADMISSION`, not timing
closure. Physical refinement improved setup slack but did not close timing.
The child took 6,135.98 seconds, sampled peak tree RSS was 26,205,280 KiB,
and every cgroup memory event counter was zero. Its verified containment was
40/36 GiB max/high, zero swap and group OOM kill. The result SHA-256 is
`34076f87ebbc104c16039d87e78356df9d5726aa6a5feaf356ef97ae79e5f9e5`;
the final diagnostic checkpoint SHA-256 is
`f1ee02df6124f56c92fd8cd20242fdfd3e075af1a8135265759e602165664d83`.
The original reports and refined checkpoint remain in the remote attempt
directory; no bitstream was generated or programmed.

Read-only replay of the parent's actual final report, SHA-256
`760e74b83067645d4e5b00fdc6f9eae23b6d58fb3ac498b81c5e731419650bac`,
confirms 443 setup failures, zero hold/pulse failures and strict rejection.
The parent's returned binary also has actual DATA/HBM clocks 147/434 MHz.
Neither the parent binary nor a later diagnostic report is board admission.

## SSSP Diagnostic Queue

SSSP producer `spine-g-production-remote-20261018-v2.service`, invocation
`1ae4ec61720648c6a043398f3796e11b`, completed its link in 24,207.44 seconds.
Its final report still has WNS -0.013 ns, TNS -0.039 ns and four failing
setup endpoints, with zero hold/pulse failures. Its return/board continuation
rejected the artifact; generating an xclbin did not admit its clock or timing.

The independent diagnostic is service
`spine-sssp-postroute-20261018-v1.service`, invocation
`270a495592bc4f1ca8196e67298da334`, output
`production-sssp-postroute-diagnostic-v1` under the remote campaign root.
It uses `--producer-kind remote-sssp` and the read-only
`original-g-port-runner-bd60e37` source archive, SHA-256
`107c26731bad72bd760f17443fb9bb6d67a6abef7c0b29bb08234691e5a1affd`.
Its 40/36-GiB, zero-swap/group-OOM containment and full-peer admission policy
are unchanged. At 2026-10-18 15:28 UTC it is queued; there is no SSSP
refinement result or new board-admitted artifact.

## Run

Run a fixed source archive on the builder, in a fresh directory and separate
40-GiB `MemoryMax`, 36-GiB `MemoryHigh`, zero-swap/group-OOM cgroup. Atomic
admission reserves all peer budgets plus 32 GiB system reserve and 8 GiB
background allowance. Admission has a one-day deadline and the Vivado child
has a four-hour deadline. At least 80 GiB free disk is required. The parent
and all captured inputs must remain unchanged throughout.

```bash
python3 -m spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.postroute.probe \
  --route /data/chuxiao/baseline_hardware_validation_20261017/production-respr-route-v2 \
  --unit spine-production-respr-route-20261018-v2.service \
  --invocation 0b6cd3bdd41040b59ff3a890c7a218a2 \
  --output /data/chuxiao/baseline_hardware_validation_20261017/fresh-respr-postroute-diagnostic \
  --environment-root /data/chuxiao/baseline_hardware_validation_20261017/production-inputs-v1 \
  --xilinx /data/feiyang/xilinx \
  --platform /absolute/reviewed-u55c-platform/platform.xpfm \
  --compatibility /data/feiyang/xilinx/compat-2024.1
```

`results.json` separates diagnostic execution from timing-report outcomes;
`manifest.json` pins the parent checkpoint/report, script and tool closure.
`refine.*.txt` and resource records preserve the actual child execution.
All hardware/figure/publication admission flags remain false. Synthetic
parser/Tcl/guard tests do not replace a real Vivado run:

```bash
python3 -m unittest discover -s tests -p test_production_postroute.py -v
python3 -m unittest discover -s tests -p test_production_postroute_sssp.py -v
```

The SSSP tests cover explicit producer selection, unchanged raw records and
rejection of changed status, OOM, clock, host, capsule, parent, command, memory
policy, timeout or source closure. They are synthetic contract tests, not
physical timing calibration. Adding this producer does not start a diagnostic;
an SSSP attempt must first finish and retain its exact service invocation.
