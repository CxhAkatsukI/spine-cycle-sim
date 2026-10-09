# Current-FPGA owner round evidence v8

Date: 2026-08-12

## Scope

This checkpoint closes the observability gap between the device-owner core and
the SST result JSON. It does not freeze timing calibration parameters. Every
recorded Spine compute round now exports reader and compute source-completion
markers, owner begin/dispatch/complete/activation/finalize counters, and owner
HBM read/write request and byte counters.

For an owner-enabled round, the exact protocol request count is:

```text
2 + 7 * source_dispatches + 6 * source_completions
  + 8 * activation_words + 9
```

The SST element checks that formula when writing the result. The current-FPGA
analyzer independently recomputes it from the exported arrays and rejects a
row if any round, request, byte, or source-completion ledger is open. It also
requires the current Spine profiles to report an enabled owner scheduler.

## Immutable build candidate

```text
cpp/sst/build/sst-current-fpga-v8/libspine_cycle.so
SHA-256 65c37be3390e6192ce3af17a5d45f49f0a5f0cbc5d561807729390d749440e8e
```

This SHA is a candidate execution image. It becomes frozen only after the
architecture/profile contract and transition audit are regenerated.

## Correctness-admitted AU smokes

The following rows use the current owner-FIFO profiles and the AU workloads
under `/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811`.

| Algorithm | Device rounds | Owner dispatches per round | Owner HBM requests per round | Result | Analyzer ledger |
| --- | ---: | --- | --- | --- | --- |
| weighted SSSP | 2 | `[2, 1]` | `[45, 24]` | PASS | PASS |
| connected components | 1 | `[10]` | `[141]` | PASS | PASS |
| residual PageRank | 0 | `[]` | `[]` | PASS correction-only | PASS |

Result hashes are:

```text
SSSP  5fa758cbceb26aac7342ad3152e8ccc014ecc55cec683cf9e96f7d83887f0452
CC    c616ac901117c0fddc2836a5d7c35c9c01c12c2c475a10dd792db5ab3e2e746c
ResPR cbee27ac2feb06b537df432d78c21be0b663ef78443438dc3d2532b5bfa5faf5
```

The correction-only ResPR row correctly contains no propagation round. A
separate eight-vertex diagnostic exercised 256 non-empty PageRank rounds and
closed all 256 per-round request/byte ledgers, but did not converge under that
synthetic update and is therefore diagnostic-only, not admissible performance
or correctness evidence. Its result hash is
`d9ef215cee3718160a956b05ff505ff818c4fdb216bc33e99980e9f99f7a5110`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-sharded-k4-v3

make -C cpp/sst BUILD_DIR=build/sst-current-fpga-v8 -j8
ctest --test-dir build/owner-protocol-v7 --output-on-failure
python3 -m unittest tests.test_current_fpga_component_evidence
```

The smoke result root is:

```text
/data/tmp/chuxiao/current_fpga_v8_owner_evidence_smoke_20260812
```

## Remaining gate

This checkpoint proves owner protocol observability and conservation. It does
not prove current-FPGA cycle agreement. The next gate freezes this plugin and
the AU/SU calibration versus WK/R19 holdout split, runs the current matrix,
and applies timing scales fitted only on AU/SU.
