# Remote CPU Prediction Runs

The portable persistent-update runner changes build/runtime paths only. It
does not change C++ sources, cycle parameters, batch semantics or the setup
formula. Default paths and compiler flags remain the local defaults. An
isolated worktree keeps the source pins of already waiting local jobs intact.

The declared remote cohort uses one sample per arm, on the same CPU host and
affinity for both arms. Do not pool its host-preparation times with the earlier
trifoliate cohort or call either cohort FPGA timing. Keep both sets of evidence.
Before accepting remote trace results, compare the smoke device cycles and
read/write ledgers exactly with the earlier local smoke. Host nanoseconds are
expected to differ across CPU hosts and must not be part of that equality test.

Use explicit `--compiler`, `--sst`, `--sst-include`, `--dram`, `--python-home`
and `--python-library` paths. The last two are paired and apply only to the
SST child, not the supervising system Python. The report indexes dependency
files, compiler version, host, affinity, source and build artifacts. Transfer
input graphs unchanged; relocated manifests must separately pin their input
identities. A remote result does not establish routed-baseline admission.

Use `python3 -m spine_cycle_sim.experiments.evaluation_impact.figure_refresh.input_relocation`
to create a new manifest with `--source`, `--output`, `--graph`, `--updates`,
`--graph-sha256` and `--updates-sha256`. It rejects a changed transferred file
or an existing output and preserves the source manifest's other fields. The
original manifest and transferred file identities remain indexed in the new one.

SST receives `--lib-path` for the fresh plugin directory, not `--add-lib-path`.
The latter still loads the compile-time install configuration even with
`--no-env-config`, which fails when that installation path does not exist on
the destination host. This isolates plugin discovery without editing SST or
creating a compatibility directory in another user's installation. A missing
runtime dependency or failed smoke remains a failed attempt, not a trace row.

On seele (at least 480 GiB RAM), use the existing named
`seele-reserve-128g-v1` policy: exact 40/36-GiB max/high cgroup, zero own swap,
128-GiB live reserve, and atomic reservation against other finite jobs. The
child address-space limit remains 32 GiB. A live watchdog terminates only the
owned tree if the reserve or containment is breached. This is not permission
to change another user's jobs or global memory settings.

The existing local SO/PK waiting runs remain separate, with their frozen
source and original memory policy. No completed point is silently replaced
by a faster host measurement. New results require a new export directory and
an explicit host-cohort label in its README.

## November 5 Completed Cohort

The [checked export](fresh_simulator/portable_fig8/README.md) contains all five
declared statuses: AU/SU/WK/SO complete, PK failed at Spine hierarchy capacity.
Both smoke arms exactly match the frozen local device cycles and ledgers.
The exporter also checks compiled numerical units/flags, DRAM identities,
relocated input hashes, raw counters and the setup formula. The numerical
model was not retuned. Source inventory differences are confined to CMake's
uncompiled test target and 155 additional uncompiled test files, documented
in the export; a source-level identity check is not FPGA calibration.

The four measured preparation samples use Xeon Platinum 8375C CPUs and GCC
15.2.0. Their combined setup-prediction ratios are 3.83/3.85/9.09/6.99.
PK has no ratio. The raw stderr and failed receipt remain in the archive.
The [portable cohort README](fresh_simulator/portable_fig8/README.md#reproduction)
includes exact exporter commands and the earlier SU reference identity.

## Explicit Headroom Follow-Up

The subsequent `headroom-source-05aff52b` execution checkout is frozen at
`05aff52b`. It exposes an explicit Spine bootstrap policy:
`--preload-minimum-level 4`. Existing edges start at L4 or above, reserving
lower levels for later chronological carries. Finite capacities, update
ordering, correctness checks and device timing parameters are unchanged.
Host layout construction and initial logical upload are still charged.
This is a configuration change from the earlier L2 cohort, not merely a
CPU-portability rerun or a timing correction. Matching HLS bootstrap behavior
has not been established. Keep the earlier PK failure and L2 results intact.

All five datasets were rerun with the same L4 policy, Xeon host, GCC 15.2,
CPU 20, numerical source and dependencies. Their completed ten-batch ratios
are AU 3.50, SU 3.58, WK 8.91, SO 6.73 and PK 1.51. A fresh PK receipt is
the frozen numerical smoke reference for this cohort; exact equality to that
reference is not a claim of old-L2 equivalence or FPGA calibration.

The matching batch sweep uses the same execution checkout, host, affinity
and policy, and the same AU graph/update bytes in all three cases:
131,072 total updates split into 10, 100 or 1,000 chronological batches.
It runs sequentially after the dataset cohort, under the same 40/36-GiB
limits, zero swap and named seele reserve policy. Preserve every status,
including a capacity failure or a ratio below one. Do not reuse the local
EPYC sensitivity samples in this Xeon cohort.

The portable exporter accepts `freeze`, `export` and `sweep` subcommands.
`sweep --case COUNT RESULTS_JSON ... --reference REFERENCE --cohort SCOPE`
requires all three counts, identical graph/update identities and the exact
host/configuration cohort of the completed five-dataset export. The receipt
archive retains the frozen reference, cohort scope, raw logs, configurations
and compiler recipes. An export runs from a separate checkout so that the
execution source pins remain unchanged.
