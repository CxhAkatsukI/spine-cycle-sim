# Native GraSU/ReGraph multi-workload FPGA alignment

Date: 2026-07-25

## Claim boundary

This matrix validates the existing-HLS native path, including host vertex
reorder and the serial PMA-to-edge-array conversion:

```text
external graph/update IDs
  -> host update-density vertex reorder
  -> GraSU PMA update
  -> completion barrier + capacity-wide compactor
  -> fixed-superstep ReGraph SSSP
```

All timing rows are an **unfitted, trend-only baseline**. No constant or scale
factor was fitted from these results. Structural equality and SSSP correctness
are required gates; an absolute-time gate is deliberately not applied until a
mechanism-based AXI/controller model has been calibrated on the frozen
calibration split.

## Frozen artifacts and split

`configs/experiments/grasu_native_hw_matrix_20260725.json` pins every workload
and raw hardware log by SHA-256. All eleven logs use:

- target: U55C `hw`;
- xclbin SHA-256: `5a730a2da85ddf522f577ca7d7024f7aa401bb07802f3bf9b4326dfd312e917e`;
- host SHA-256: `0189b94f16af5ea4e9a5803f963db6558229be76447187862737aadf5a9ad9cb`;
- workload-manifest SHA-256: `094dbe66fa58b6fa14d22fc74edcc564978c7c8c3e5ea9ff7407cc78077a098a`.

The split was frozen before any native timing fit:

| Role | Cases | Use |
| --- | ---: | --- |
| calibration | 5 | future mechanism-based fit only |
| holdout | 5 | parameter selection and fitting forbidden |
| stress | 1 | `large_chain_v4096`, excluded from default runtime/timing gates |

Both calibration and holdout contain chain, hot-source, spread, and hot-dest
behavior across 16 to 65,536 vertices. The existing cases are not an
independent-factor microbenchmark design, so they can validate transfer and
expose gaps but cannot uniquely identify each missing latency mechanism.

## Structural and correctness result

The default ten-case matrix passed:

```text
structure matches       10 / 10
SSSP mismatches          0 in every case
native HLS contract      safe in every case
wall-clock runtime       1004.52 s (16.74 min)
largest single runtime   371.18 s (medium_spread_v65536_u16384)
```

Exact checks include vertex/edge/update counts, external and reordered source
IDs, reserved PMA slots, compact slots, slots scanned per superstep, fixed
supersteps, and SSSP output. Observed source mappings include `0 -> 33`,
`0 -> 62`, `0 -> 352`, `0 -> 4088`, and `0 -> 5472`, so this is not merely a
set of identity-map cases.

The first matrix attempt also exposed a real input-contract gap: a zero-update
graph produces a metadata-only update slice. The loader now accepts it only
when the update caller explicitly requests `allow_empty` and the file contains
valid vertex metadata. Generic graph inputs still reject empty edge sets.

## Unfitted timing result

Median absolute errors at the pinned 200 MHz kernel clock are:

| Role | Update | Conversion | Compute span | Event E2E |
| --- | ---: | ---: | ---: | ---: |
| calibration | 94.46% | 35.41% | 36.54% | 47.99% |
| holdout | 99.71% | 82.51% | 37.42% | 50.60% |
| all | 97.08% | 58.96% | 36.58% | 50.10% |

Every signed component and E2E error is negative: the simulator is optimistic,
not noisy around the hardware time. Per-case E2E error ranges from `-38.58%`
to `-67.99%`.

The components expose different missing behavior:

1. **Update:** zero/tiny batches take one to hundreds of simulated cycles but
   0.4-0.7 ms in FPGA event windows. Kernel/control startup and empty-pipeline
   behavior are not represented. The error falls to about 85-94% on larger
   updates, so one global multiplier is not defensible.
2. **Conversion:** tiny cases miss a large fixed cost (82-95% error), while
   million-slot cases are still 33% optimistic. This indicates both fixed
   controller/event-window cost and a per-row/per-slot AXI-platform gap.
3. **Compute:** error is more stable (26-49%) across 2-64 supersteps and 32 to
   81,920 compact slots. The execution-driven fixed sweep and edge traffic are
   present, but the SST DRAM-device model does not yet reproduce the complete
   platform AXI/interconnect/controller path.

These observations reject a single fitted E2E offset or scale. The next timing
work must isolate startup, row/segment scan, compact edge traffic, and
supersteps independently, then fit only calibration cases and evaluate the
frozen holdout once.

That follow-up is now complete as a separate measured-envelope layer. It uses
component-specific predictors, adds six-sample evidence for the four tiny
cases, and reaches 0.40% median / 2.38% maximum E2E error on the untouched
holdout. It does not rewrite this unfitted baseline or claim kernel-internal
cycle accuracy. See `docs/grasu_native_timing_envelope_20260725.md`.

## Evidence

Committed evidence is under `docs/evidence/grasu_native_hw_matrix/`:

- eleven raw FPGA logs, including the stress-only case;
- ten raw simulator result JSON files and ten generated alignment reports;
- `predictions.csv`, `group_summary.csv`, and `manifest.json`;
- the exact graph inputs are under `tests/data/grasu_native_hw_matrix/`.

The simulator results retain the complete component, traffic, stall,
outstanding, correctness, and distance ledgers. DRAMSim epoch files remain
generated run artifacts under `results/`; a later memory-energy milestone will
extract and preserve a compact per-channel activity ledger rather than commit
32 mostly idle epoch files per case.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

python3 scripts/run_grasu_native_hw_matrix.py \
  --out-dir results/grasu_native_hw_matrix_20260725

python3 -m unittest \
  tests.test_grasu_native_hw_matrix \
  tests.test_grasu_native_runner \
  tests.test_grasu_native_hw_alignment
```

The default command runs calibration plus holdout. Run the stress case
separately; it has a 300-million-cycle guard and is intentionally not part of
the ordinary runtime gate:

```bash
python3 scripts/run_grasu_native_hw_matrix.py --no-build \
  --roles stress \
  --out-dir results/grasu_native_hw_matrix_stress_20260725
```
