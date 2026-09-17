# Figure correction and six evaluation questions

This note accompanies the corrected simulator-repository handoff. It does not
edit the paper. Statements below apply to the sources and evidence identified
here; they are not a claim that every target feature is implemented or every
simulator stage is FPGA-calibrated.

## Figure 10 version correction

The August 12 renderer/package was created after the alignment campaign, but
it selected an earlier `7563b028...` CSV. Figure 10's single-plugin check did
not enforce equality with Figures 8/9/11. This was a data-selection error.

The replacement contains eleven v12 executions, SHA-256
`f1fca617de22877ca675c72c6877444c029af8b83d4c30a25754d85f7e324b70`.
Ten executions reuse existing immutable raw results; one SSSP zero-net run is
new. The plugin and timing parameters were not rebuilt or changed. The only
analysis change admits verified zero-round PR correction, based on explicit
zero work counters, convergence, empty round arrays, and closed owner and
correction ledgers. Missing instrumentation on a nonempty path is still
rejected. Gzip copies preserve every byte of the original raw JSON; both
compressed and original hashes are verified during regeneration.

The new zero-net example uses the original reciprocal delete/reinsert trace
on eight vertices. An independent multiset check establishes that the final
weighted graph equals the initial graph. The v12 SSSP implementation takes
its full-rebuild fallback: 28,343 dynamic cycles after a separately recorded
21,968-cycle cold prefix. It does not establish the target no-repair fast
path. Both graph oracles and the runner's request/protocol checks pass.

The attempted v12 CC zero-net run is retained and rejected. Its final labels
match both oracles, but the active-edge oracle expects zero edges while the
device dirty publication triggers work on two edges. The raw result reports
`success=false` and `active_edge_execution_ledger_match=false`. Those flags
have not been overwritten. This remains a CC zero-net validation mismatch,
outside the admitted SSSP example; it must not be described as a passed CC
zero-net experiment.

Reproduce the accepted ZN run from the simulator repository (a new output
directory is recommended):

```bash
ulimit -v 12582912
timeout 180 /data/tmp/chuxiao/spine-cycle-sim-eval-venv/bin/python \
  scripts/run_sst_spine_vertical.py \
  --scenario dynamic_sssp_delete \
  --workload tests/data/connected_components_formal/cc_zero_net_base.slice \
  --update-workload tests/data/connected_components_formal/cc_zero_net_delete_then_reinsert_u2.slice \
  --out-dir /data/tmp/chuxiao/fig10_v12_repair_20260917/zero_net_sssp_reproduction \
  --profile configs/architectures/spine_owner_fifo_sssp_hls_v1.json \
  --sst /data/feiyang/sst/bin/sst \
  --lib-dir cpp/sst/build/sst-current-fpga-v12 \
  --validation-mode generic --max-cycles 10000000 --no-build
```

## 1. Setup versus dynamic-latency boundary

The delivered hardware Figure 7 reads `setup_speedup_median` from the
three-repeat full-graph tables. The aggregator obtains this ratio from
G+R `setup_inclusive_ms` and Spine `dynamic_setup_inclusive_ms`. Therefore,
relabeling the values as setup-excluding device cycles would be incorrect.

Spine's recorded quantity is the sum of maintenance wrapper wall time,
iterative wrapper wall time, and separately recorded dynamic host
preparation. The wrappers include their buffer work, transfers, launch/wait,
and readback. They do not encompass all surrounding host work: construction
of an argument such as the next frontier, and processing returned arrays,
can occur outside the wrapper. G+R's sharded host timer begins after initial
resident-state/update-buffer preparation and ends after final readback.
Neither quantity is cold graph-loading time. The two implementation timers
also should not be advertised as one identical, fully instrumented
application wall-clock interval.

Recommended wording:

> Figure 7 reports dynamic latency using the recorded setup-inclusive host
> intervals, starting from a resident, converged old graph. The reported
> intervals include timed maintenance and iterative execution wrappers and
> recorded host preparation; static graph setup and host work outside these
> intervals are excluded. Simulator device-cycle attribution uses a separate
> update-to-convergence boundary.

The setup section must define both Figure 7's hardware boundary and Figure
8's host-plus-modeled-device update-only boundary; they are not interchangeable.
**No new run is needed to accurately describe the existing measurements.**
A claim of complete batch-arrival-to-result wall-clock latency would require
additional host instrumentation and measurement, not a wording change.

Sources: `grasu-regraph-integration/scripts/summarize_matched_fpga_matrix.py`,
`scripts/aggregate_matched_fpga_repeats.py`, its
`tools/sharded_k4_native_host.cpp`, and
`spine-dynamic-graph-paper-owner-fifos/tests/test_integration/host_partitioned_algorithms_smoke.cpp`.
The immutable hardware table identities are in `provenance/fig7.json`.

## 2. 176 versus 352 bits

For a hypothetical dense presence matrix covering every family and level,
32 families times 11 levels is 352 bits per source. The 176-bit number matches
16 times 11, the earlier partition/cold-family scope; it cannot describe the
full 32-family matrix without explicitly restricting that scope.

The evaluated implementation's coarse 32-bit family directory plus level/page
metadata must not be confused with either hypothetical full presence matrix.
Recommended replacement: "avoids a dense per-source family-by-level presence
matrix (352 bits for 32 families and 11 levels)." Alternatively omit the
numeric aside and describe the evaluated directory format directly.

This is a definition/arithmetic correction, not a request to allocate 352 bits
in the implementation. See `docs/spine_architecture_evidence_crosswalk.md`,
section 5.5, and the `families`/`levels` entries in the frozen profiles.

## 3. Internal opt-v2 name

Use "the placed-and-routed weighted-SSSP implementation" when referring to
that specific historical artifact. For current results, state the algorithms
and artifact scope supported by the actual manifests: routed full-graph
SSSP/CC/ResPR, with a separate compact FullPR comparison. Do not rename a
historical opt-v2 result as the newer owner-scheduler result without changing
its evidence reference. The internal nickname itself needs no new experiment.

## 4. Eleven executions and normalized bars

The corrected figure contains 1 ZN + 3 shallow-insertion + 3 carry + 3 PR
correction + 1 deletion-fallback executions, totaling 11. L1/L3/L5 are the
three selected carry levels, not five bars L1 through L5. AU/SU/WK are
AskUbuntu/Superuser/WikiTalk, FL is Flickr, and Syn denotes a synthetic
fixture. The new ZN fixture uses weighted SSSP, not CC.

Suggested caption:

> Simulator-predicted cycle attribution for eleven executions using one
> frozen simulator version. Each bar is independently normalized to 100% of
> its measured device-cycle window. The ten-stage ledger is grouped into
> maintenance, seed/publication, resolve, application, and completion/drain.
> L1/L3/L5 denote forced carry levels, FL denotes Flickr, and Syn denotes a
> synthetic fixture. Zero-net follows the implementation's rebuild fallback;
> SU/WK PR correction converges without a propagation round.

This corrects labels and interpretation; the separate version-selection
problem required replacing the data, as performed in this handoff.

## 5. High R-squared alongside high percentage error

The diagnostic uses `R^2 = 1 - SSE/SST` on observed cycle counts. It is not
squared correlation, and does penalize biased predictions. Its weighting is
in absolute squared cycles, whereas APE divides each error by that row's
observed cycles.

In the seven real-trace holdout rows, the Flickr correction case is 920,110
cycles and contributes 84.94% of SST. The other observations range from
6,143 to 95,160 cycles. Flickr's APE is 9.84%; several smaller observations
have 48--90% APE. Errors have both signs, so this is not one uniform scale
offset. That distribution explains the simultaneous R-squared of 0.978,
median APE of 57.3%, and maximum APE of 90.2%.

Suggested wording:

> The large dynamic range makes R-squared primarily reflect the largest
> observation; relative errors remain substantial on several smaller cases.
> We therefore use the model as a diagnostic of realized-work trends, with
> median and maximum real-trace APE of 57.3% and 90.2%, respectively.

Keep both error metrics. Do not describe this as a precise latency predictor.
No refit is needed to report this limitation; demonstrating improved
prediction accuracy would require new model validation. Historical per-stage
R-squared values must not be attributed to a new dataset without recomputing
them. Figure 11 and its existing split/model are not changed by this fix.

## 6. Outstanding budget

The profile table mixes two layers. `memory.max_outstanding_per_port=32`
in the Spine profile is not its AXI adapter limit. The source-shaped Spine
adapter uses `SpineAxiInterfaceProfile::max_outstanding_bursts=16`. G+R's
GraSU adapter is also configured with 16. Both SST paths instantiate the same
memory backend with a per-channel capacity of 32, one admission per channel
per cycle, and a response queue capacity of 128.

Evidence: `cpp/include/spine_sim/spine_system.hpp` (interface defaults),
`cpp/sst/online_memory_probe.cpp` (`spine_axi_profile_from_id` and the
`SstMemoryBackend` constructor in `setup`), the frozen architecture profiles,
and `docs/candidate10_l0_writer_rtl_schedule_20260726.md` (adapter audit).
The backend construction also appears unchanged in the v12 freeze commit
`9342fc2`; it is not a new setting introduced by this figure repair.

Use separate rows for the modeled adapter outstanding-burst limit (16) and
shared SST backend per-channel capacity (32). Do not describe the mixed
32-versus-16 profile fields as comparable per-port hardware budgets, or claim
that they follow published defaults without source evidence. This finding
does not require changing the frozen plugin or rerunning the matrix.

## Disposition

Items 2, 3, and 4 require corrected wording/labels. Item 5 requires a narrower
prediction claim and explicit error reporting. Items 1 and 6 can be resolved
for the existing measurements by specifying the verified timing and parameter
layers; a stronger whole-application timing claim would need new measurements.
The Figure 10 version mismatch required data replacement and a new ZN run.
The failed CC ZN check remains explicitly recorded, not silently marked fixed.
