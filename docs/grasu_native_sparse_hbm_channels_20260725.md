# Native SST sparse HBM controller binding

Date: 2026-07-25

## Claim boundary

This milestone reduces simulator host execution cost only. The pinned native
GraSU + compactor + ReGraph architecture still exposes 32 physical U55C HBM
pseudo-channels. The existing HLS topology can issue requests only to channels
`0`, `1`, `2`, `3`, and `30`:

- GraSU update and the PMA compactor use PMA channels `0..3`;
- the compactor row array and ReGraph edge array use channel `0`;
- ReGraph source-state primary and mirror use channels `1` and `3`;
- ReGraph apply state uses channel `30`.

The SST configuration now instantiates DRAMSim3 controllers only for those
reachable physical channel numbers. The C++ model retains a 32-entry channel
namespace, and a request to an unbound channel is a fatal configuration error.
Consequently, this optimization cannot silently remap a request or merge
contention from distinct active channels.

This does not remove the native PMA-to-edge-array conversion. The native
pipeline remains `update -> barrier -> compactor -> compute`, with conversion
time included.

## Exact equivalence evidence

The two-controller configurations below use the same code and workload. The
full configuration instantiates all 32 DRAMSim3 controllers; the sparse
configuration instantiates `0,1,2,3,30`.

| Case | Full controllers | Sparse controllers | Speedup | Result identity |
| --- | ---: | ---: | ---: | --- |
| native unit, 2 supersteps | 3.934 s | 1.026 s | 3.834x | byte-identical |
| `small_chain_v64`, 64 supersteps | 84.655 s | 18.185 s | 4.655x | byte-identical |

For the native unit case, all ten DRAMSim3 files (`json` and `txt` for each of
the five reachable channels) are also byte-identical between full and sparse
runs. This proves that removing the 27 idle simulator components did not alter
active-channel request ordering, timing, contention, or statistics for that
case.

Result identities:

```text
native unit      e955ebc225f43a3c03a04ae3838aa956e2d4ca5f782fdc2bc534171ba5b9fb57
small_chain_v64  7265d22fdb3edcc05ca8c55c0c66feac19d3db02e0f4c7929d709a7ec2ec56f0
```

These are single-run engineering measurements on an AMD EPYC 7C13 host. They
must not be reported as accelerator speedups.

## Runtime gate

Linear extrapolation from the measured sparse 64-superstep case places the
4096-superstep chain at approximately 19.4 minutes. The subsequent complete
stress run finished in 19.16 minutes, 1.24% below that projection, without
fast-forwarding an architecture cycle or HBM transaction. The measured gate
and raw evidence are documented in
`docs/grasu_native_stress_runtime_20260725.md`.

## Reproduction

Build and test:

```bash
cd /home/chuxiao/spine-cycle-sim
cmake --build build/cycle-core -j2
ctest --test-dir build/cycle-core --output-on-failure
make -C cpp/sst -j2
python3 -m unittest discover -s tests
```

Run full and sparse unit configurations:

```bash
python3 scripts/run_sst_grasu_regraph_native.py \
  --no-build \
  --instantiate-all-hbm-channels \
  --out-dir results/grasu_native_full_channels_unit

python3 scripts/run_sst_grasu_regraph_native.py \
  --no-build \
  --out-dir results/grasu_native_sparse_channels_unit

cmp \
  results/grasu_native_full_channels_unit/result.json \
  results/grasu_native_sparse_channels_unit/result.json
```

Run the frozen 64-superstep holdout:

```bash
python3 scripts/run_grasu_native_hw_matrix.py \
  --no-build \
  --roles holdout \
  --case small_chain_v64 \
  --out-dir results/grasu_native_sparse_small_chain

cmp \
  docs/evidence/grasu_native_hw_matrix/simulation/small_chain_v64.result.json \
  results/grasu_native_sparse_small_chain/small_chain_v64/sst/result.json
```

Machine-readable evidence is
`docs/evidence/grasu_native_sparse_hbm_channels_20260725.json`.
