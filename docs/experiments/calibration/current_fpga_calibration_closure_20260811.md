# Current FPGA calibration closure

Date: 2026-08-11

## Scope

This checkpoint freezes the evidence boundary used to refresh Figures 8--10.
It does not claim that calibration is complete.  The required gates are total
cycles, observable component intervals, execution-driven memory/FIFO ledgers,
and structural work equivalence.  Calibration and holdout datasets remain
disjoint under:

- `configs/contracts/evaluation_refresh_fpga_cases_v2.json`;
- `configs/contracts/evaluation_refresh_fpga_calibration_v3.json`.

The current routed Spine profiles now declare
`resident_preload_policy=hls_compacted_l2_l10_v1`.  This policy mirrors the
routed host bootstrap: L0/L1 remain available for dynamic updates, a resident
family is placed in the smallest fitting level at or above L2, and a family
larger than every single level is packed from L10 downward.  Automatic hot
classification uses the aggregate L2--L10 family capacity and the routed
fixed hash; a hot-shard overflow is a hardware capacity rejection rather than
a simulator-only balancing fallback.

This supersedes the native-alignment statements in
`docs/spine_capacity_safe_hierarchy_20260729.md` and
`docs/rq3_stage_ledger_and_resident_fallback_20260731.md` that describe a
single-L10 bootstrap or a simulator-only balanced/multilevel admission policy.
Those files remain historical implementation records.

## Structural mismatch found and repaired

The previous R19-32 CC simulation used 55,405 hot vertices and produced range
tasks `[315, 2]`.  The routed hardware used 4,674 hot vertices and reported
`KERNEL_PAIR_RESULT` task counts `[258, 2]` with processed edges `[807, 2]`.
This was a mechanism mismatch, so fitting a cycle scale would have been
invalid.

With the compacted HLS preload policy, the correctness-gated R19-32 simulation
reports:

| Quantity | Simulator | Routed FPGA |
|---|---:|---:|
| hot vertices | 4,674 | 4,674 |
| hot edges | 12,988,252 | 12,988,252 |
| iterations | 2 | 2 |
| range tasks | `[258, 2]` | `[258, 2]` |
| processed edges | `[807, 2]` | `[807, 2]` |
| simulator cycles | 91,800 | not used in this structural check |

The admitted simulator evidence is under:

```text
/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811/
  runs_current_v1/r19/spine/connected_components_compacted_hls
```

The immutable compacted plugin is built at:

```text
cpp/sst/build/sst-owner-compacted-v1/libspine_cycle.so
```

Its SHA-256 for this checkpoint is
`6739bd1056b75d86fe825c2208640e64c9a940c4814f59f105eda703285cdb35`.
The v3 contract requires this same execution image for Spine and G+R.  A row
from any earlier plugin is rejected even if its correctness status is `PASS`.

## Audit behavior

`scripts/audit_evaluation_refresh_alignment.py` now reads all four manifests
required by the v3 contract.  In particular, absence or failure of
`structural_work_validation.json` blocks Figures 8--10 from becoming `READY`.
Spine must match routed iteration, range-task, and processed-edge counters.
The routed G+R hosts do not expose equivalent counters, so their scope is
recorded as `not_observable`; this limitation cannot be converted into a
hardware-counter match.

`scripts/analyze_current_fpga_components.py` emits contract-compatible
coverage and threshold records for component timing, memory/FIFO conservation,
and structural work.  Request, byte, and FIFO conservation remain simulator
ledgers because routed HBM byte counters are unavailable.

## Reproduction

```bash
python3 scripts/generate_spine_owner_fifo_hls_profiles_v1.py --check

make -C cpp/sst -j4 \
  BUILD_DIR=build/sst-owner-compacted-v1

ctest --test-dir build/owner-wiring --output-on-failure
python3 -m unittest discover -s tests

python3 scripts/analyze_current_fpga_components.py \
  --cases configs/contracts/evaluation_refresh_fpga_cases_v2.json \
  --contract configs/contracts/evaluation_refresh_fpga_calibration_v3.json \
  --simulation-root \
    /data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811 \
  --out-dir docs/evaluation_refresh_20260810/calibration
```

The final analyzer command is expected to fail closed until all 24 simulator
rows exist and every calibration/holdout threshold passes.

Run the two bounded-memory matrices with:

```bash
python3 scripts/run_current_fpga_spine_compacted_matrix.py \
  --jobs 3 --memory-reserve-gib 64

python3 scripts/run_current_fpga_grasu_frozen_matrix.py \
  --jobs 3 --memory-reserve-gib 64 \
  --lib-dir cpp/sst/build/sst-owner-compacted-v1
```

The runners execute AU/SU/WK with bounded parallelism and R19 sequentially.
They publish atomically replaced status files at:

```text
/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811/
  spine_compacted_matrix_status.json
/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811/
  grasu_unified_plugin_matrix_status.json
```
