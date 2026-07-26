# Candidate10 Shared Pseudo-channel Arbitration

Date: 2026-07-26

## Scope

This milestone removes fixed C++ component-registration priority when multiple
AXI masters target the same HBM pseudo-channel. It does not change the frozen
Candidate10 channel map, AXI widths, outstanding limits, or DRAMSim3 timing.

The SST backend now uses registered per-pseudo-channel round-robin arbitration:

1. AXI masters submit intents during `evaluate`.
2. The backend selects at most the configured channel acceptance rate during
   `commit`.
3. Winners consume their grants and stage requests on the next core cycle.
4. A full channel outstanding window preserves the intent and records a
   capacity-blocked cycle.

The one-cycle grant boundary is intentional. It prevents a component evaluated
earlier in a cycle from sending a request before later components have exposed
their intents.

## Fail-closed ledger

Every successful formal comparison row must report `backend_arbitration` and
satisfy:

```text
unique_intents == grants == consumed_grants == backend_requests
pending_intents == pending_grants == 0
ledger_closed == true
```

The shared matrix parent gate rejects a row that violates this ledger. It also
exports request waits, contended cycles, contention losers, capacity-blocked
cycles, and maximum contenders to `results.csv`.

`backend_submit_stalls` remains the broad backend-facing stall counter. The new
fields separate actual multi-master contention and outstanding-window pressure
from the mandatory registered request/grant delay.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j 4
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst
python3 scripts/run_shared_comparison_matrix.py \
  --claim-scope structural_exploratory \
  --run-id syn_weighted_diamond_v8__weighted_sssp \
  --out-dir /data/tmp/chuxiao/candidate10_registered_arbiter_smoke_v6_20260726 \
  --jobs 1 --no-build
```

## Evidence

Both systems pass the architecture and independent mathematical oracles, the
DRAM request ledger, the locality ledger, and the new arbitration ledger.

| System | Old cycles | Registered cycles | Change | Requests | Contended cycles | Losers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Spine | 58,618 | 62,210 | +6.13% | 3,982 | 0 | 0 |
| GraSU+ReGraph | 200,002 | 201,826 | +0.91% | 84,555 | 639 | 639 |

The cycle change is not itself a calibrated performance claim. It demonstrates
that the old backend allowed same-cycle pass-through based on component order.
In this tiny workload, GraSU+ReGraph also exercises real shared-channel
contention while Spine does not. Broader holdout and sensitivity matrices are
required before interpreting architecture-level speedups.

Machine-readable evidence is in
`docs/evidence/candidate10_registered_arbiter_smoke_20260726.json`.
