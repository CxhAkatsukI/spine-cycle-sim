# Candidate10 mixed fast/full path attribution (2026-07-26)

## Scope

This milestone closes the phase-boundary ambiguity for the 8,193-edge
`tiny_mixed_fallback` diagnostic.  The historical case name is misleading:
both hardware and the execution-driven simulator report one fast tile, one
full tile, two range tasks, and fallback reason zero.  The path is therefore
classified as `mixed_fast_full_no_fallback`.

The workload has one active source.  Its first destination tile contains
4,096 edges and takes the fast path; its second tile contains 4,097 edges and
takes the full path.  Both sides construct and replay exactly 8,193 payloads.

## Execution-driven timing ledger

The SST result now exports raw start/end cycles for each logical round and for
the reader and compute units.  It also exports the round span after maintenance
so that the first `round_cycles` value is not incorrectly treated as D-stage
time when it includes B-stage execution.

For the normalized Candidate10 profile:

| Component | Cycles |
| --- | ---: |
| B-stage maintenance | 296,193 |
| B launch to first memory issue | 1 |
| B active memory/control interval | 296,191 |
| B post-memory drain | 1 |
| First D-stage core span after B | 112,494 |
| First-round reader active interval | 82,799 |
| First-round compute active interval | 112,364 |
| Dirty acknowledgement | 598 |
| Empty-frontier termination round | 8,141 |
| Scheduler boundary | 1 |
| Total | 417,427 |

Reader and compute intervals overlap; they must not be added.  The E2E ledger
closes as `sum(round_cycles) + dirty_ack_cycles + scheduler_boundary = total`.

## Hardware comparison boundary

The existing hardware row agrees exactly on the structural schedule.  At
150 MHz, its XRT event durations correspond to 480,376.5 maintenance cycles,
1,107,045 compute-event cycles, and 1,587,420 E2E-event cycles.  These event
windows are not scope-matched to simulator core intervals, so the analysis
reports numerical differences only as diagnostics and explicitly sets
`scope_matched=false` and `hardware_absolute_cycle_calibration_claim=false`.

The maintenance difference is 184,183.5 cycles.  Simulator launch plus drain
is only two cycles, and this workload observes no shared-pseudo-channel
contention.  Therefore neither wrapper launch/drain nor shared-channel
arbitration explains the residual.  The unresolved B-stage work lies inside
the active memory/control interval and remains a fine-grained modeling gap.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario weighted_sssp \
  --validation-mode generic \
  --workload /data/tmp/chuxiao/candidate10_mixed_path_attribution_b_v1_20260726/workloads/holdout_tiny_mixed_fallback_8193.slice \
  --profile configs/architectures/spine_candidate10_normalized_v1.json \
  --out-dir /data/tmp/chuxiao/candidate10_mixed_path_e2e_spine_v2_20260726 \
  --max-cycles 10000000 \
  --no-build

python3 scripts/analyze_candidate10_mixed_path.py \
  --spine-result /data/tmp/chuxiao/candidate10_mixed_path_e2e_spine_v2_20260726/result.json \
  --maintenance-result /data/tmp/chuxiao/candidate10_mixed_path_attribution_b_v1_20260726/runs/holdout_tiny_mixed_fallback_8193/summary.json \
  --hardware-csv docs/evidence/spine_candidate10_hw_20260725/correctness_cases.csv \
  --output docs/evidence/candidate10_mixed_fast_full_attribution_20260726.json
```

The analyzer fails closed on a structural mismatch, an open B request ledger,
an open arbiter ledger, or an unexplained E2E phase residual larger than one
cycle.
