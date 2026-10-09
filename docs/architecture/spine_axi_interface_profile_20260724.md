# Spine per-interface AXI profile

Date: 2026-07-24

## Why this correction was required

The cycle core previously instantiated every `FixedAxiPort` as a 64-byte
(512-bit) interface. That number belongs to the board-memory profile and does
not describe every kernel master. The accepted split-kernel RTL reports the
following `CH0_USER_DW` values:

| Interface | Kernel width | Model beat |
| --- | ---: | ---: |
| graph0..15 | 64 bits | 8 bytes |
| sorted edges / persistent dirty state | 128 bits | 16 bytes |
| active bins | 256 bits | 32 bytes |
| metadata | 64 bits | 8 bytes |
| maintenance result | 32 bits | 4 bytes |
| vertex state | 32 bits | 4 bytes |
| active output | 64 bits | 8 bytes |
| active bitmap | 64 bits | 8 bytes |
| compute result | 32 bits | 4 bytes |

The reports also instantiate a 16-beat maximum burst and 16 outstanding
transactions for active read/write interfaces. `USER_MAXREQS` is seven for
read/write data interfaces and four for write-only result interfaces. The
cycle model now records these separately instead of deriving all ports from a
single physical-HBM width.

## Implementation

`FixedAxiPortConfig` now passes all AXI geometry and service-rate fields into
`AxiMaster`. `SpineAxiInterfaceProfile` owns the per-interface widths and
constructs a port config for each named Spine interface. The default profile
is `hls_split_9c08763`; the former behavior is retained only as the explicit
`legacy_uniform64` profile.

Every SST Spine result records the profile ID and relevant widths. The runner
rejects a result whose recorded profile differs from the requested profile.

## Structural A/B evidence

Both profiles use the same graph payload, algorithms, SST DRAMSim3 backend,
HBM channel mapping and correctness checks. Only AXI interface shape changes.

| Workload | HLS-profile cycles | Legacy cycles | Cycle ratio | HLS requests | Legacy requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amazon exact L0 slice | 6,517 | 5,699 | 1.144x | 1,368 | 584 |
| Amazon full-tile compute | 496,386 | 355,100 | 1.398x | 175,315 | 35,548 |

Both runs have zero value and frontier mismatches. The old uniform-64 model
therefore preserved functionality but materially undercounted narrow-interface
transfers, especially the 32-bit vertex-state path.

These are structural execution-driven results, not absolute hardware
calibration. A platform interconnect can widen, pack or otherwise transform
kernel AXI traffic before HBM. That conversion is not yet an explicit
component. Also, `AxiMaster` models individual backend beats but returns data
to its producer only when the complete parent request has retired. The next
maintenance milestone must expose sorted-edge data progressively enough to
overlap HBM delivery with an `II=1` scan.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim

cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j2

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --axi-profile hls_split_9c08763 \
  --out-dir results/sst_spine_axi_hls_amazon_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_l0 --no-build \
  --axi-profile legacy_uniform64 \
  --out-dir results/sst_spine_axi_legacy64_amazon_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_full_compute --no-build \
  --axi-profile hls_split_9c08763 \
  --out-dir results/sst_spine_axi_hls_full_compute_20260724

python3 scripts/run_sst_spine_vertical.py \
  --scenario amazon_full_compute --no-build \
  --axi-profile legacy_uniform64 \
  --out-dir results/sst_spine_axi_legacy64_full_compute_20260724
```

Machine-readable evidence is in
`docs/evidence/spine_axi_interface_profile_20260724_summary.json`.
