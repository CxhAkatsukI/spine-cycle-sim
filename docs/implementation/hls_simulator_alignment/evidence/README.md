# Evidence Index

Read [the handoff](../README.md) and [validation scope](../VALIDATION.md) before
using these files. Raw logs are copied unchanged from
`/data/chuxiao/validation/hls_simulator_alignment_20261024/` on `trifoliate`.
Local build binaries and bulky temporary directories are not committed.

| File or directory | Meaning |
| --- | --- |
| `adapter.log` | Three-format independent adapter compile/run summary |
| `framed_alias_fix.log` | Successful manual/connected ReGraph and aliased Apply rerun |
| `apply_alias_initial_failure.log` | Genuine vendor burst-model overlap assertion before the Apply ordering fix |
| `host_prefetch.log`, `host_legacy.log` | Four host builds and six-partition CPU preparation/oracle results |
| `host_prefetch_manifest.env`, `host_legacy_manifest.env` | Explicit no-hardware scope and selected profile |
| `adapter_selection_final.log` | Candidate/legacy generation and refusal regression |
| `adapter_selection_initial_failure.log` | Earlier test-fixture error, preserved |
| `build_regression_final.log` | Master-audit and build-script regressions |
| `build_regression_initial_failure.log` | Earlier missing-environment invocation, preserved |
| `spine_sparse.build.log`, `spine_sparse.run.log` | Fresh macro-enabled Spine focused test |
| `build_packets/{sssp,cc,fullpr,respr}/` | Clean-commit source hashes, manifests, flags, connectivity and generated commands; inspection only |

Generated packets contain absolute paths from their generation machine. They
were not executed as FPGA builds. Regenerate with the pinned HLS generators
for a new machine; do not manually patch paths and describe the result as the
same frozen packet. The top-level documentation makes the 32-master admission
failure explicit despite the generators' generic "run later" messages.
