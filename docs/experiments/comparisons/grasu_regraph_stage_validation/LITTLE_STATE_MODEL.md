# Little PR Apply And State Checkpoint

This adds index/terminator, original PR Apply, explicit degree reads and
acknowledged broadcast writeback to the independent original-R components.
The [implementation contract](../../../implementation/grasu_regraph/original_regraph_little_state.md)
defines arithmetic limits, finite resources and timing assumptions. This is
not a measured FPGA or original-publication performance match.

## Fixed Gates

The [state contract](../../../../configs/experiments/original_regraph_state_validation_v1.json)
requires:

- Six state rows: baseline, drained reuse, reverse registration, one Apply
  credit, one writer credit and doubled memory latency.
- Five protocol rejections: early Apply/writer end, degree/write allocation
  overflow and an unknown write acknowledgement. Signed arithmetic overflow
  is rejected separately inside the C++ test.
- Six original-source comparisons: three 65,536-word fixtures with four and
  fourteen property replicas, totaling 393,216 logical output words. Every
  model replica is also checked against an independent scalar oracle.
- Three resident A4 iterations, then the entire fixture with reversed
  registration order; all states, cycles, traffic and contention must agree.
- Byte-identical repeated output/counters, damaged/truncated/excess source
  rejection, independent UBSan runs, and exact old frontend/Gather analyses.

The fourteen-replica case validates the generated writer and Apply component;
it is **not** an execution of eleven Little plus three Big pipelines.

## Results

The authoritative final status and executed resource logs are in
[state_results.json](state_results.json); package hashes and file index are in
[state_verification.json](state_verification.json). Model cycles below are
predictions under the declared mock-memory contract:

| State row | Cycles | Relevant observed pressure |
| --- | ---: | --- |
| Baseline, 128 lines | 4,525 | Writer acknowledgements extend beyond Apply completion |
| Drained reuse / reverse registration | 4,525 each | All counters identical to baseline |
| One Apply and writer credit | 12,620 | 12,192 Apply credit-stall cycles |
| One writer credit, ordinary Apply credits | 9,318 | 8,890 writer credit stalls; 8,880 Apply output stalls |
| Memory latency 128 instead of 64 | 8,685 | Same values and traffic, longer memory service |

Each original-source comparison completes in 141,421 modeled cycles with
65,536 checked logical words, 262,144 degree-read bytes and either 1,048,576
or 3,670,016 acknowledged write bytes. Replica count does not increase cycles
in this isolated fixture because the writes use distinct physical channels;
the payload and traffic checks still cover every copy.

The connected four-Little fixture processes 384 physical / 368 logical
edges per iteration over a padded 65,536-destination extent. It completes
three rounds at 143,281 modeled cycles each, reading 1,582,080 bytes and
writing 3,145,728 bytes in total. Source reads and property writes share odd
HBM channels; the fixture records 60 contended channel-cycles. Reversing
component registration preserves all these quantities and final properties.
These tiny functional fixtures do not establish a large-graph edge rate.

All ten CTest executables and an 89-test focused Python suite pass. Separate
UBSan executables for frontend, state, source comparison and connected
iterations reproduce their Release outputs without diagnostics. The isolated
single-job Release build takes 127.24 seconds with peak process RSS 689,360
KiB; the connected iteration executable takes about 0.96 seconds and 20,432
KiB. Host resource measurements are not device-cycle measurements.

The 163-file raw archive is 216,764 bytes, SHA-256
`07bd1894afe8647618bbef252dd8942e383fef9fc74fe31640374d96c685cdcb`.
[state_preservation.json](state_preservation.json) records that all 2,437
protected files and the frozen SST plugin retain their previous hashes.
No new FPGA timing run, full Python suite or new SST matrix is claimed.

## Reproduce

Prepare the [pinned author sources](README.md), then use fresh output paths:

```bash
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/grasu_regraph_upstream_captures_v1.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_state_gather
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/regraph_upstream_scatter_protocol_v2.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_state_scatter
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/regraph_upstream_apply_v1.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_state_apply
python3 scripts/run_original_regraph_state_validation.py \
  --captures results/upstream_stage_controls/reproduce_state_gather \
  --protocol results/upstream_stage_controls/reproduce_state_scatter \
  --apply-captures results/upstream_stage_controls/reproduce_state_apply \
  --out results/upstream_stage_controls/reproduce_state_model
```

The state runner reuses the complete frontend validation/build rather than
duplicating its lifecycle, then admits state and iteration gates. Python
ownership separates source admission, numerical result validation, execution,
instrumentation and packaging. One thin CLI selects the fixed contract.
Source hashes, compile commands, CMake cache, bounded resource logs and repeats
are retained. Build parallelism is one; model limits are 4 GiB with a 16-GiB
reserve. Source-control compilation has a separate 2-GiB limit.

Package with `original_regraph_validation.state_delivery.deliver_state`;
it rechecks source/capture/binary and raw-result identities and refuses to
overwrite evidence:

```python
from pathlib import Path
from spine_cycle_sim.experiments.original_regraph_validation.state_delivery import deliver_state

root = Path.cwd()
base = root / "results/upstream_stage_controls"
deliver_state(root, base / "reproduce_state_gather", base / "reproduce_state_scatter",
              base / "reproduce_state_apply", base / "reproduce_state_model",
              base / "reproduce_state_delivery", attempts=[])
```

## Attempts And Remaining Work

`state_preflight_v2` retains the failed pressure assertion: restricting both
Apply and writer to one credit throttled the upstream producer, so the writer
had no credit stall. The test incorrectly required both to stall. The corrected
matrix checks Apply pressure and writer pressure independently; no model
timing or source values were changed to satisfy that assertion.
`state_preflight_v1` and `state_preflight_v3` retain earlier extraction/smoke
checks. The raw archive also preserves the final source captures, full old
regression, state repetitions, negative controls and instrumentation logs.

The common memory-fixture extraction preserves the entire frozen frontend
analysis, all seven Gather invariant results and the 786,432 original-source
Gather comparison words. Production numerical bodies and the SST source
list are unchanged. The existing fourteen-case SST extraction result is
retained, not rerun for this separate CMake-library checkpoint.

Remaining work is full original-R partition/Big/mixed scheduling, exact
workload/DBG/iteration admission and memory timing, original G timing and
paper/source geometry controls, then matched A4/B adapter overhead and host
composition. Similar full-system totals cannot substitute for these gates.
