# Spine resident-level bootstrap for large dynamic graphs

## Problem and scope

The HLS input sort buffer accepts at most 131072 update records. Earlier real
comparison runners incorrectly reused that online batch interface to build the
entire initial graph. A 540000-edge graph therefore failed before timing even
though the fixed levels have enough persistent capacity.

For dynamic experiments, the initial graph now represents an already-resident
snapshot. Each cold/hot family is sorted and placed in the smallest fixed level
whose configured edge capacity can hold it. The AskUbuntu 540000-edge snapshot
occupies cold family 0, level 7. The timed insertion remains an ordinary
8-record maintenance batch and targets L0.

Weighted SSSP needs a correct pre-update distance state. The simulator
therefore performs an untimed-window cold convergence check from source 0 over
the resident levels, using the normal reader, FIFO, AXI, HBM, and compute
pipeline. Its first source is supplied through the existing HOST_ACTIVE
metadata interface. The bootstrap round does not emit a dirty ACK because no
update batch exists yet. All later rounds use the original dirty/ACK protocol.

Graphs at or below `MAX_SORT_EDGES` retain the old full-maintenance bootstrap,
which preserves the existing formal matrix behavior.

## Evidence

The 540000-edge AskUbuntu run converged in 13 cold rounds. The 8-edge insertion
then converged in 2 rounds and took 235121 cycles, including 6863 maintenance
cycles. Architecture, mathematical Dijkstra, cold-state, and frontier checks
all report zero mismatches. The request ledger closes at 7196117 requests,
split into 7105839 cold and 90278 update-window requests.

Machine-readable values and hashes are stored in
`docs/evidence/spine_resident_level_bootstrap_20260728.json`.

## Reproduction

```bash
cd /home/chuxiao/spine-cycle-sim-publication
make -C cpp/sst -j2

export SPINE_IDLE_DRAMSIM3_SRC=/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3
export SPINE_IDLE_SST_INSTALL_PREFIX=/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install

python3 scripts/run_sst_spine_vertical.py \
  --no-build --scenario dynamic_sssp --validation-mode generic \
  --profile configs/architectures/spine_candidate10_opt_v2_reader_working_set.json \
  --workload tests/data/candidate10_askubuntu_paper_scale/sx_askubuntu_base_e540000.slice \
  --update-workload tests/data/candidate10_askubuntu_paper_scale/sx_askubuntu_insert_u8.slice \
  --source 0 --max-rounds 256 --max-cycles 1000000000 \
  --sst scripts/run_sst_exact_idle_dramsim3.sh --lib-dir build/sst \
  --out-dir /data/tmp/chuxiao/spine-resident-level-reproduction
```

