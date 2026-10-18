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
`inputs.py` admits one exact terminal successful experimental algorithm link,
including its environment probes, source/XO closure, zero OOM record, binary
identity and unique final routed checkpoint. `refine.tcl` opens that checkpoint
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
```
