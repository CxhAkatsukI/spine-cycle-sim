# Spine HOST_ACTIVE linearization and plugin equivalence

## Scope

Commit `f0cb2c6bf547c3728afb4abcb6d17a4de489b1f5` changes only the
untimed host construction of Spine `HOST_ACTIVE` bins. It does not alter a
simulated clock, component, FIFO, AXI transaction, HBM request, algorithm
operation, architecture profile, or hardware parameter.

The old implementation scanned every resident cold and hot level edge once
for every active source. Its host complexity was `O(A * E)`, where `A` is the
active-frontier size and `E` is the resident edge count. A live StackOverflow
Weighted SSSP execution reached 308M simulated cycles and then spent more than
three hours at 100% host CPU in `build_host_active_bins`, without advancing the
simulated cycle counter.

The replacement creates one route summary per unique active source, scans all
resident edges once, and emits records in the original input-source order. Its
complexity is `O(A + E)`. Duplicate sources, edgeless sources, cold level
masks, hot family masks, destination partition routing, and source values are
preserved.

## Build

The baseline and candidate plugins are:

```text
baseline  eee35f39c118538da5565e497d29b989e5bb492c1368839d424a984c32e2aae9
candidate c2a60d5250f5594dae98114bd32a96910fe08d11a299eadc6d0b2d1fa56161c6
```

Rebuild the candidate without overwriting an active campaign plugin:

```bash
make -C cpp/sst \
  BUILD_DIR=/data/tmp/chuxiao/host-active-linear-native-build-20260730 \
  native -j8
sha256sum \
  /data/tmp/chuxiao/host-active-linear-native-build-20260730/libspine_cycle.so
```

## Validation

The C++ unit oracle retains the old scan implementation and compares every
emitted record against the new builder. It covers multiple levels and
families, hot and cold edges, duplicate active sources, an edgeless source,
inactive edges, ordering, masks, values, and invalid-source rejection.

```bash
cmake --build build -j8
./build/cpp/spine_cycle_core_tests spine_host_active_bin_builder
./build/cpp/spine_cycle_core_tests
python3 -m unittest discover -s tests
```

Observed results were 111/111 C++ tests and 681 Python tests passing, with five
documented Python skips, before the plugin-equivalence additions. The complete
suite is rerun after those additions as a separate gate.

Two old/new SST comparisons remove only these top-level provenance fields:

```text
sst_host_wall_seconds
sst_library_binding
sst_plugin_sha256
```

Every other JSON field must match exactly. The reports are:

- `docs/evidence/spine_host_active_linear_tiny_equivalence_20260730.json`
- `docs/evidence/spine_host_active_linear_askubuntu_equivalence_20260730.json`

The tiny multiround Weighted SSSP comparison matched at 61,149 cycles and 3,946
backend requests. The full AskUbuntu incremental Weighted SSSP comparison
matched at 24,919,004 cycles and 6,011,567 backend requests, with identical
final-state digest and zero architecture/mathematical oracle mismatches.

On the same AskUbuntu case, SST host wall time fell from 590.321 seconds to
320.634 seconds, a 1.84x speedup. This wall-time ratio is supporting simulator
throughput evidence; it is not an accelerator performance result.

Regenerate either report with:

```bash
python3 scripts/verify_plugin_host_runtime_equivalence.py \
  --baseline-summary BASELINE/summary.json \
  --candidate-summary CANDIDATE/summary.json \
  --label LABEL \
  --output REPORT.json
```

## Formal admission

`configs/contracts/large_graph_publication_campaign_fullgraph_v4.json` keeps
the old plugin as the common frozen baseline and admits the candidate only for
Spine through a fail-closed equivalence entry. The entry pins both report
hashes, both plugin hashes, the implementation commit, the exact allowed
difference fields, and the required report labels. GraSU+ReGraph cannot use
this exception.

The publication runners include the verified proof in
`admission.plugin_admission`. Missing, changed, incomplete, duplicated, or
semantically mismatching reports reject the candidate before SST starts.

The host wall optimization therefore may be used to finish large Spine runs,
while simulated cycles from old and new plugin cohorts remain comparable. No
claim is made that arbitrary future plugin binaries belong to this equivalence
class.
