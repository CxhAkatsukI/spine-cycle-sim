# Route Environment And Memory Admission

## Decision

The fresh `route-v2` attempt passes six bounded environment smoke checks.
**The route still did not start:** 51.73 GiB was available at admission,
below the unchanged 40-GiB process-tree budget plus 16-GiB host reserve.
There is no new xclbin, routed clock or FPGA timing from this checkpoint.
The preceding [production XO](../README.md), first admission refusal and
[model sensitivity](../../sensitivity/README.md) remain separate evidence.

| Check | Result |
| --- | --- |
| Original shell prefix | Exact reviewed settings/exports; the shell's link command is never sourced/executed |
| Vitis / Vivado launcher versions | Both report 2024.1 |
| Host GCC / G++ | Both report Debian 15.2.0-14 |
| Host compatibility | C++ thread/condition-variable compile and execution pass; include trace contains the frozen `gcc_compat/bits/gthr-default.h` |
| Environment dependencies | Settings loader, its five sourced scripts, shim and resolved launcher/host-compiler identities pinned |
| Link inputs | Same eleven XOs, only production-v2 adapter substituted; same connectivity and 150-MHz request; synth/impl jobs two each |
| Environment probe budgets | Six sequential commands, each at most 4 GiB and 90 seconds; 16-GiB live reserve |
| Largest sampled probe tree | 131,828 KiB; minimum available memory 51.71 GiB |
| Route admission | `ADMISSION_REJECTED_NOT_STARTED`; requested execution returns exit code 2 |
| Numerical models, default plugin, HLS | Unchanged |

## What This Closes

The older execution wrapper inherited its caller's environment. Extracting
the `v++` command did not reproduce the original shell's Vitis settings,
header paths, library paths or GCC compatibility include. The new cohesive
owner, `empty_segment/route_environment/`, explicitly reconstructs these
reviewed exports before preflight and admission. It does not edit frozen
route owners or production dependency snapshots.

The base environment has a fixed `/usr/bin:/bin` PATH, locale and explicitly
selected identity/license variables. Vendor settings then prepend their
paths; original include/library/compiler prefixes are applied; temporary
directories point into the fresh run. Arbitrary inherited Python/compiler
search paths are not propagated. License values are passed only in memory;
the report records hashes, not credentials. Every actual probe receives
this explicit environment, as would a memory-admitted link.

This reproduces the **reviewed export contract**, not the unknown complete
environment of the historical August build. The host-thread smoke does not
test every vendor-internal compiler or prove Vivado linking will succeed.
Launcher/settings/shim/compiler pins are not an exhaustive hash closure of
the vendor installation and system libraries. These limits are explicit in
the manifest and verification report.

## Evidence And Owners

[evidence/verification.json](evidence/verification.json) indexes
[evidence/raw_environment_admission.tar.gz](evidence/raw_environment_admission.tar.gz).
The archive contains the environment report, exact command/config, admission
and exit records, all six command logs/watchdogs, the small thread executable,
and selected pinned owner/settings/header snapshots. Original XOs and vendor
executables are hash-indexed rather than bundled.

| Module | Responsibility |
| --- | --- |
| `contract.py` | Reject unreviewed shell prefixes; source only the reviewed settings; reconstruct and pin explicit environment |
| `probe.py` | Bounded launcher/version and host-thread compatibility checks |
| `__main__.py` | Fresh preparation, binding, preflight, unchanged memory admission, explicit-environment route, honest exit status |
| `delivery.py` | Recheck and seal this specific non-start evidence; not a generic successful-route delivery |

The recorded raw attempt is
`/data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/route-v2`.
The sixteen focused tests cover changed exports/settings/environment/license,
secret redaction, explicit environment dispatch, preserved failures and
non-launch on refusal. All **375 selected Python regression tests pass**;
the watchdog records 62.43 seconds, 2,055,884 KiB peak sampled tree RSS and
49.76 GiB minimum available memory. [checks/verification.json](checks/verification.json)
indexes their raw logs and post-execution owner/test snapshots. Those snapshots
are not a predeclared numerical-build dependency closure.

The subsequent [evidence recheck](checks/evidence_recheck.json) passes the
production XO's current-input/ABI gate, all twelve sensitivity full-state and
traffic checks with exact legacy replay, and this environment non-start gate.
It rechecks retained results rather than rerunning the numerical experiments;
its watchdog records 17.93 seconds and 969,380 KiB peak sampled tree RSS.
This Python-only change does not require rebuilding a frozen numerical
binary or SST plugin; the earlier 28-case C++ replay remains historical.

## Reproduction And Remaining Work

Run from the simulator repository with fresh paths. The existing refusal is
immutable; do not retry into `route-v1` or `route-v2` and do not reduce the
memory budget to obtain admission.

```bash
python3 -m spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment \
  --build /data/tmp/chuxiao/grasu_regraph_sharded_k4_sssp_hw_b8d2ba3_20260806 \
  --production /data/chuxiao/experiments/sharded_k4_skip_empty_segment_20261011/production-v2 \
  --output results/empty-helper-route-fresh --execute
```

Without `--execute`, preflight/admission still run but link does not. An
execution refusal returns 2, a preparation/link failure returns 1, and a
successful link only admits `LINK_PASS_AWAITING_TIMING_AND_BOARD`.
The live route watchdog retains the four-hour bound, 40-GiB sampled tree
limit and 16-GiB reserve. Pidfd tracking is not cgroup containment.

Once resources permit, use a fresh attempt, inspect final timing and
connectivity, and run paired resident old/new board cases. Only then can the
new candidate's hardware timing be assessed. The full A4-versus-actual-K4
comparison and production-model timing alignment are still open; this
environment checkpoint does not complete the overall study.
