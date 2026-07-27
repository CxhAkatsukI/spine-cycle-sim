# Candidate10 exact-idle HBM sensitivity equivalence

This bundle closes the exact-idle backend's orthogonal memory-profile gate.
The frozen sweep contains five DRAMSim3 profiles, 12 workloads per profile,
and both Candidate10 architectures: 120 system results in total.

## Result

The fail-closed audit passes:

- 120/120 system runs are correct and memory ledgers close;
- 23,530 pre-existing result fields are identical;
- 1,300 final/epoch DRAMSim3 JSON files are byte-identical;
- 105 result files are byte-identical;
- the other 15 files are Spine Full PageRank runs with exactly 48 frozen new
  diagnostic fields each and no changed old field;
- `sensitivity_details.csv` and `sensitivity_summary.csv` are byte-identical;
- all four overlays retain zero strict Spine/GraSU+ReGraph rank inversions;
- host runtime improves by 3.861x geometric mean across 120 observations.

The unchanged sensitivity table reports 1.435x, 1.385x, 1.413x, and 1.413x
Spine speedup geometric means for low latency, high latency, high bandwidth,
and low bandwidth, respectively. The two winner changes originate from a
baseline tie; neither is a strict architecture reversal.

Host speedup is not accelerator performance. This bundle proves that omitting
provably idle DRAM ticks changes neither simulated hardware time nor the
memory-profile conclusions.

## Contents

- `equivalence_manifest.json` and `equivalence_rows.csv`: fail-closed verdict;
- `candidate_sensitivity_*`: exact-idle aggregate output;
- `baseline_raw_json.tar.gz`: always-clocked child matrices and DRAM JSON;
- `candidate_raw_json.tar.gz`: exact-idle child matrices and DRAM JSON;
- `SHA256SUMS`: integrity hashes for every committed file.

## Reproduction

Run the exact-idle sweep after building the isolated backend documented in
`../../dramsim3_exact_idle_advance_20260727.md`:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-repro/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-repro-install

python3 scripts/run_shared_hbm_sensitivity.py \
  --out-dir /data/tmp/chuxiao/candidate10-exact-idle-hbm-reproduction \
  --jobs 2 --timeout-seconds 7200 --no-build \
  --sst scripts/run_sst_exact_idle_dramsim3.sh
```

Repeat the audit entirely from this bundle:

```bash
mkdir -p /data/tmp/chuxiao/candidate10-exact-idle-hbm-audit
cd /data/tmp/chuxiao/candidate10-exact-idle-hbm-audit
tar -xzf /home/chuxiao/spine-cycle-sim-publication/docs/evidence/candidate10_exact_idle_hbm_sensitivity_equivalence_20260727/baseline_raw_json.tar.gz
tar -xzf /home/chuxiao/spine-cycle-sim-publication/docs/evidence/candidate10_exact_idle_hbm_sensitivity_equivalence_20260727/candidate_raw_json.tar.gz

cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_exact_idle_sensitivity_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/candidate10-exact-idle-hbm-audit/candidate10_hbm_sensitivity_v1_20260727 \
  --candidate-dir /data/tmp/chuxiao/candidate10-exact-idle-hbm-audit/candidate10_exact_idle_hbm_sensitivity_v1_20260727 \
  --out-dir /data/tmp/chuxiao/candidate10-exact-idle-hbm-audit/result
```
