# Little Memory/Scatter Checkpoint

This extends the [finite Gather/merge checkpoint](LITTLE_FINITE_MODEL.md)
with separately owned edge reader, source-memory service and Scatter modules.
It is a partial original-ReGraph control, **not a whole-R timing match**.
See the [implementation contract](../../../implementation/grasu_regraph/original_regraph_little_frontend.md)
for all finite resources and memory/timing assumptions.

## Scope And Acceptance

The fixed boundary starts with resident padded edges and source properties
and ends at the global merged-property FIFO, before Apply. No CPU setup, DMA,
launch/relaunch, degree reads, state writeback, Big/mixed scheduling or graph
preprocessing is measured. The model is intentionally separate from the
production SST G+R implementation.

The predeclared matrix requires ten positive model rows plus one allocation
rejection. Five request-dependent original-source controls must agree on
320 emitted tuple words and 4,096 returned source lines. These are functional
comparisons, not author-kernel device-cycle measurements.

The original-source control also verifies the signed 33-bit type of the
Scatter request-guard subtraction. Source-window gaps are supported; the
earlier unsigned-wrap deadlock hypothesis was rejected, not attributed to
the original ReGraph algorithm. The original wrapper validates every generated
response in a separate functional replay.

## Predicted Results

The table below records model cycles under the explicit mock-memory contract,
not FPGA latency or published ReGraph performance:

| Model row | Cycles | Source requests | Source bytes | Edge bytes |
| --- | ---: | ---: | ---: | ---: |
| Round 0 | 1,170 | 2 | 32,768 | 512 |
| Round 1 | 1,753 | 3 | 49,152 | 512 |
| Rounds 0/1/2 | 2,336 | 4 | 65,536 | 768 |
| Reverse registration | 2,336 | 4 | 65,536 | 768 |
| Depth-1 queues, slow sink | 7,163 | 4 | 65,536 | 768 |
| One outstanding burst | 6,236 | 4 | 65,536 | 768 |
| Memory latency 128 | 2,592 | 4 | 65,536 | 768 |
| Four Little, through Gather/merge | 34,618 | 16 | 262,144 | 3,072 |
| Initial round 2 | 1,753 | 3 | 49,152 | 256 |
| Round 0 then 3 | 2,336 | 4 | 65,536 | 512 |

The four-Little row checks 65,536 output words. The other rows check every
Scatter tuple. Dummy edges are included in physical reads but excluded from
the graph-sum oracle. Source lookahead and discarded responses remain in the
traffic ledger. Queue pressure increases time without changing memory work.
All completion tests require components, queues, AXI parents/beats and the
backend to drain, rather than stopping at the last arithmetic result.

The final isolated Release build passes all eight C++ executables, 19 focused
frontend/Gather Python tests, the three existing corrupted-reference controls
and a separately compiled undefined-behavior-instrumented frontend. Repeated
frontend stdout and all counters are identical; instrumentation produces the
same output with no diagnostics. The prior 786,432-word Gather comparison,
all seven invariant cycle/counter rows and original capture hashes remain
exactly equal to the frozen checkpoint.

Final acceptance is recorded in [frontend_results.json](frontend_results.json).
The sequential build takes 121.31 seconds with peak process RSS 690,108 KiB;
the frontend itself takes about 0.10 seconds and 18,332 KiB. The separately
instrumented build takes 19.75 seconds with 343,340 KiB peak process RSS.
These are host resource measurements, not modeled device cycles.

An additional 80-test focused Python suite passes across original-R admission,
upstream functional/HLS controls, repository organization, extraction equivalence
and publication gates. Its logs are included in the raw package. All 2,437
protected evidence/user files retain their baseline hashes, and the frozen
SST plugin remains SHA-256
`9a26e1fb51ecf7b99ccf0784c9e5bbc459cf857d293add557b9c52770b2c9d79`.
Existing production numerical bodies and the SST source list are unchanged.
The earlier 14-case SST extraction matrix is retained, not rerun for this
separate-library checkpoint; no full Python suite or new FPGA run is claimed.

## Raw Attempts

All early source-control attempts are retained in the raw archive:

| Attempt | Outcome and cause |
| --- | --- |
| `scatter_protocol_v1` | Probe compile failure: datatype header include order |
| `scatter_protocol_v2` | 120-second watchdog timeout: the functional delegate's `size()` incorrectly hid available responses from the original empty-check API |
| `scatter_protocol_v3` | The unsigned-wrap hypothesis disagreed with actual HLS signed subtraction; expected-outcome check failed |
| `scatter_protocol_v4_signed_guard` | Five source cases passed after correcting signedness; superseded by the explicit per-case trace capture below |
| `scatter_protocol_final_v5` | Five request/response and scalar-output checks passed, including sparse source-round traces |

The first frontend admission invocation also rejected bytewise comparison of
a normalized JSON contract copy with its original formatting. Before any
model run, that check was corrected to typed structural comparison while
retaining the original contract's SHA-256 identity. Its regression test uses
the normalized serialization. No input or numerical evidence was altered.

## Reproduce

Use fresh output paths; the runners and delivery refuse overwrites. First
prepare the [pinned original sources](README.md), then run:

```bash
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/regraph_upstream_scatter_protocol_v2.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_scatter_protocol
python3 scripts/run_upstream_stage_controls.py \
  --contract configs/experiments/grasu_regraph_upstream_captures_v1.json \
  --hls-include /data/yxx/tools/xilinx/Vitis_HLS/2024.1/include \
  --out results/upstream_stage_controls/reproduce_frontend_captures
python3 scripts/run_original_regraph_frontend_validation.py \
  --captures results/upstream_stage_controls/reproduce_frontend_captures \
  --protocol results/upstream_stage_controls/reproduce_scatter_protocol \
  --out results/upstream_stage_controls/reproduce_frontend_model
```

The final runner builds Release in an isolated directory, repeats all frontend
and source-comparison outputs, runs the C++ and focused Python regression
suites, retains corruption controls, and runs an independently compiled
undefined-behavior-instrumented frontend. Build/run timeouts, a 4-GiB address
limit, single build job and at least 16-GiB available-memory reserve are recorded
per step. Peak RSS is the maximum reported for a process, not a simultaneous
aggregate of the process tree.

Packaging is owned by `original_regraph_validation.frontend_delivery`:

```python
from pathlib import Path
from spine_cycle_sim.experiments.original_regraph_validation.frontend_delivery import deliver_frontend

root = Path.cwd()
base = root / "results/upstream_stage_controls"
deliver_frontend(
    root,
    base / "reproduce_frontend_captures",
    base / "reproduce_scatter_protocol",
    base / "reproduce_frontend_model",
    base / "reproduce_frontend_delivery",
    attempts=[],
)
```

## Deliverables And Remaining Work

- `frontend_results.json`: fixed contract/source/compiler identities, all
  executed steps and structured model/source results.
- `frontend_verification.json`: raw archive contents and per-file hashes.
- `raw_little_frontend_model.tar.gz`: source captures, protocol runs, early
  attempts, build flags and validation logs; no binaries or author source trees.

The old Gather evidence and production/frozen plugin are preserved. This
checkpoint does not validate whole-R speed. Next are Apply/degree/state
writeback with the real shared property-channel budget, full partition/round
orchestration, Big/mixed scheduling and workload admission. Original G timing,
publication A, matched A4/B adapter overhead and host composition must still
be measured separately. Similar complete-system totals cannot replace them.
