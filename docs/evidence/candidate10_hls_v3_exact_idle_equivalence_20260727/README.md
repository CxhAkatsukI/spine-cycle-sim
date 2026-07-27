# Candidate10 exact-idle formal equivalence

This bundle validates the exact DRAMSim3 idle-advance backend against the
frozen always-clocked Candidate10 formal matrix. It covers 73 workload pairs,
both architectures, weighted SSSP, dynamic weighted SSSP, Full PageRank, and
thresholded residual PageRank.

## Result

The fail-closed audit passes:

- 146/146 system runs and 73/73 pairs completed correctly;
- 27,629 pre-existing result fields are identical;
- 1,578 final/epoch DRAMSim3 JSON files are byte-identical;
- 123 result files are byte-identical;
- the other 23 files are the Spine Full PageRank runs, each with exactly the
  frozen 48 new reader/compute diagnostic fields and no changed old field;
- host runtime improves by 3.871x geometric mean across the 146 observations.

Host speedup is not accelerator performance. Simulated cycles, requests,
stalls, correctness state, DRAM commands, refresh, and HBM energy are
unchanged. This result establishes observable equivalence for the formal
matrix; the orthogonal HBM sensitivity sweep remains a separate gate.

## Contents

- `equivalence_manifest.json`: aggregate fail-closed verdict and hashes;
- `equivalence_rows.csv`: one row per system/workload result;
- `candidate_comparison_manifest.json`, `candidate_results.csv`, and
  `candidate_pairs.csv`: exact-idle parent evidence;
- `candidate_raw_json.tar.gz`: all candidate result, run, manifest, and DRAM
  JSON needed to repeat the comparison;
- `SHA256SUMS`: integrity hashes for every file in this bundle.

The always-clocked raw reference is the sibling bundle
`../candidate10_hls_v3_formal_matrix_20260727/raw_json.tar.gz`.

## Reproduction

Build the isolated backend as documented in
`../../dramsim3_exact_idle_advance_20260727.md`, then run:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-repro/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-repro-install

python3 scripts/run_shared_comparison_matrix.py \
  --manifest configs/experiments/shared_comparison_candidate10_hls_v3_20260726.json \
  --out-dir /data/tmp/chuxiao/candidate10-exact-idle-formal-reproduction \
  --jobs 2 --timeout-seconds 7200 \
  --max-cycles-run syn_gather_bank_fanin_e1024__residual_pagerank/spine=450000000 \
  --claim-scope structural_exploratory --no-build \
  --sst scripts/run_sst_exact_idle_dramsim3.sh
```

Repeat the audit entirely from the committed archives:

```bash
mkdir -p /data/tmp/chuxiao/candidate10-exact-idle-audit
cd /data/tmp/chuxiao/candidate10-exact-idle-audit
tar -xzf /home/chuxiao/spine-cycle-sim-publication/docs/evidence/candidate10_hls_v3_formal_matrix_20260727/raw_json.tar.gz
tar -xzf /home/chuxiao/spine-cycle-sim-publication/docs/evidence/candidate10_hls_v3_exact_idle_equivalence_20260727/candidate_raw_json.tar.gz

cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/analyze_exact_idle_equivalence.py \
  --baseline-dir /data/tmp/chuxiao/candidate10-exact-idle-audit/candidate10_hls_v3_formal_matrix_20260727 \
  --candidate-dir /data/tmp/chuxiao/candidate10-exact-idle-audit/candidate10_hls_v3_exact_idle_formal_matrix_v1_20260727 \
  --out-dir /data/tmp/chuxiao/candidate10-exact-idle-audit/result
```
