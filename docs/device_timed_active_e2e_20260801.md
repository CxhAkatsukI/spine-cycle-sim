# Device-timed active-set E2E correction evidence

## Purpose

This change closes two timing-boundary gaps in the publication Spine model:

1. Dynamic SSSP and CC consume the active list produced by the simulated
   device rather than a host-constructed active-bin shortcut.
2. Thresholded Residual PageRank performs old/new-rank correction, physical
   edge scans, seed writes, and active-list publication inside the timed device
   boundary.

The dynamic measurement window is therefore resident sorted updates through
device maintenance, correction when applicable, active publication,
propagation, and convergence. Bootstrap of the old graph remains separately
verified and untimed. Host DMA and the external FLiMS sorter remain outside the
declared device boundary.

## Frozen transition contract

The formal transition contract is:

```text
configs/contracts/large_graph_publication_campaign_fullgraph_v8.json
```

It defines an ordered supersedence chain:

- historical host-active plugins -> device-active plugin
  `84626d7f2de2904df2557c9e08299495b28e7cd5389e075dc094550f75965216`;
- historical/device-active Residual PageRank plugins -> device-correction
  plugin
  `7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6`.

An old result is replaced only when the successor has the same execution ID,
identical case metadata, and identical final-state SHA-256. A missing successor
invalidates the historical result instead of silently retaining it.

## Formal campaigns

The final device-correction Residual PageRank rows are under:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v14_device_residual_spine
```

The device-active R19 row is under:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v12_device_active_r19
```

The PK, LJ, and LJ08 SSSP completion campaign is under:

```text
/data/tmp/chuxiao/large_graph_campaign_v1/formal_v15_device_active_sssp_completion
```

It is launched with one large process at a time and explicit memory protection:

```bash
cd /home/chuxiao/spine-cycle-sim-publication

python3 scripts/run_large_graph_campaign.py \
  --manifest /data/tmp/chuxiao/large_graph_campaign_v1/formal_v15_device_active_sssp_completion/campaign_manifest.json \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/formal_v15_device_active_sssp_completion \
  --jobs 3 --large-jobs 1 \
  --memory-reserve-gib 16 \
  --memory-emergency-gib 10 \
  --memory-recovery-gib 20 \
  --max-starts-per-sample 1 \
  --sample-seconds 5 \
  --no-progress-warn-minutes 20 \
  --host-reservation-path /data/tmp/chuxiao/large_graph_campaign_v1/host_reservations.json
```

Monitor it with:

```bash
python3 scripts/monitor_large_graph_campaign.py \
  --run-dir /data/tmp/chuxiao/large_graph_campaign_v1/formal_v15_device_active_sssp_completion
```

## Measured timing impact

All rows below pass both the architecture-precision and independent
mathematical oracle. Percent change compares against the latest matching
historical result.

| Dataset | Algorithm | Historical cycles | Corrected cycles | Change |
| --- | --- | ---: | ---: | ---: |
| AU | SSSP | 62,331 | 61,817 | -0.82% |
| SU | SSSP | 61,256 | 60,699 | -0.91% |
| WK | SSSP | 43,227 | 43,227 | 0.00% |
| R19 | SSSP | 64,058 | 63,722 | -0.52% |
| PK | SSSP | 123,762 | 124,377 | +0.50% |
| LJ | SSSP | 294,699 | 298,578 | +1.32% |
| LJ08 | SSSP | 91,575 | 92,507 | +1.02% |
| AU | CC | 2,183,489 | 2,183,292 | -0.01% |
| SU | CC | 2,397,752 | 2,397,167 | -0.02% |
| WK | CC | 9,587,612 | 9,587,027 | -0.01% |
| SO | CC | 25,547,188 | 25,424,995 | -0.48% |
| AU | Residual PR | 2,172,364 | 2,175,289 | +0.13% |
| SU | Residual PR | 2,390,535 | 2,392,695 | +0.09% |
| WK | Residual PR | 4,789,895 | 4,796,702 | +0.14% |
| SO | Residual PR | 25,254,357 | 25,281,265 | +0.11% |

The correction changes cycles by at most 1.32% on every completed row.
It does not reverse the measured comparison: the paired AU/SU/WK speedups over
G+R K4-shared remain 1499.9--4809.1x for SSSP, 6.17--14.12x for CC, and
6.77--14.68x for Residual PageRank. SO stopped-prefix bounds remain greater
than 22.1x for CC and 20.7x for Residual PageRank.

## RQ3 attribution

Residual correction is exported as a separate `residual_correction` component.
The formal RQ3 ledger attributes its serial device interval to `T_seed`, so:

```text
maintenance + residual correction + resolve/app/drain/sync = E2E cycles
```

The current RQ3 analysis has 95 correctness-admitted rows and 47 direct
ten-stage ledgers; all direct ledgers close. The real-trace holdout has
R2=0.9326 and median absolute percentage error 26.46%. These values support
trend and bottleneck claims, not cycle-for-cycle FPGA calibration.

## Reproduction and verification

```bash
cd /home/chuxiao/spine-cycle-sim-publication

bash scripts/analyze_formal_v7_primary.sh
SPINE_RQ3_OUTPUT_DIR=/data/tmp/chuxiao/large_graph_campaign_v1/rq3_live \
  bash scripts/analyze_active_rq3.sh

python3 -m unittest discover -s tests -q
cmake --build build -j8
ctest --test-dir build --output-on-failure
```

The final paper package is regenerated with:

```bash
bash scripts/refresh_formal_v7_report.sh
```
