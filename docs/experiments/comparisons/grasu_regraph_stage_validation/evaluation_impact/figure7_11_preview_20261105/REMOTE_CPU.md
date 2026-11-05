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
