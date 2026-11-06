# ARC-Aware Board Admission

The explicit `zfs-arc-clean-half-v1` profile is limited to the single-pass
resident-pair, Spine host-retime, and CC qualification board runners. It does not change FPGA
build admission, simulator memory policies, HLS, inputs, or timing boundaries.
The default remains `memavailable-v1`; frozen campaigns are not modified.

OpenZFS ARC is reclaimable under memory pressure. Linux `MemAvailable` alone
can undercount it. No global cache setting, ARC maximum, or administrator
cache purge is needed for this profile. The observed estimate is:

```text
clean = min(mru_evictable_data + mfu_evictable_data, max(size - c_min, 0))
effective_available = max(MemAvailable, min(MemTotal, MemFree + clean / 2))
```

Only half of clean evictable data receives credit. Metadata is excluded.
Adding ARC credit to `MemAvailable` would risk double counting, so the second
term starts with `MemFree`. Missing or malformed ARC/PSI counters fail closed.
This is a conservative admission estimate, not a guarantee of immediate
reclaim; ARC reclaim can cause host stalls.

## Containment And Records

- Atomic admission still reserves the task's full 8/16/24/32/40/48-GiB cgroup
  limit, all bounded peer reservations, and a 32-GiB safety reserve.
  A peer reservation is validated against its own full finite max/high,
  zero swap and group-OOM settings, not against the board runner's smaller
  limits. For example, a 104/100-GiB peer still reserves all 104 GiB.
- `MemoryHigh`, zero swap, exclusive PCI-board leases, and timeouts remain.
- Admission and running children require memory PSI `some avg10 < 10%`
  and `full avg10 < 1%`; running children also retain a 32-GiB effective
  physical reserve. The live check runs every second.
- On pressure, timeout, or interruption, terminate only the owned child
  process group or the smoke watchdog's pidfd-tracked workers; never adjust
  or terminate another user's work.
- Receipts retain raw memory/ARC/PSI admission observations, the minimum
  effective headroom, maximum observed PSI, named profile, and source pins.
  Memory events and peak cgroup usage remain in the final result.

Failed supervised executions also retain `<arm>.memory-failure.json` with
hashed stdout/stderr, the admission and last memory observation, minimum
headroom, peak PSI, observation counts and the original exception. The
settling profile retains its pressure duration/count even when it aborts.
Before/after cgroup snapshots include `memory.current`, `memory.peak`,
`memory.events` and `memory.pressure`; an unavailable diagnostic is recorded
as an error rather than invented. The dual-clock resident-pair report pins this sidecar.
These are diagnostics, not an extra sample or a relaxation of any gate.

The direct CC runner additionally accepts `--memory-gib 40` or `48` for large
raw-graph audits. Use max/high of 40/36 GiB or 48/46 GiB, and zero swap; the
full hard limit is reserved atomically before admission, with the same 32-GiB
live reserve. The default remains 32 GiB. The 48/46-GiB verification is an
explicit board lease setting; compiler defaults remain 40/36 GiB. This changes CPU preparation/audit
capacity, not the FPGA image or measured batch boundary. An already-running
attempt's recorded limit extension must retain its before/after limits,
full lease update, physical-memory observation, and reason in the raw archive.

Global PSI alone cannot attribute a stall to a particular board task. In
particular, high global PSI while no owned board task runs is not a board
OOM. Per-cgroup pressure is useful context, but neither a low cgroup value
nor a lack of OOM events proves that an aborted pair would have completed.
Earlier failures without these diagnostics remain unchanged.

Select with `--memory-profile zfs-arc-clean-half-v1` on
`source_retention.dual_clock_matrix`, `dual_clock_resident`,
`correction_matrix`, or `correction_retime`. A matrix may explicitly select
remaining datasets with `--datasets LJ LJ08 R19`; its receipt marks that it
is not a complete eight-dataset matrix. Earlier accepted samples are kept
separately, not silently rerun or rewritten.

The same option is accepted by `source_retention.cc_au_collect`,
`spine_smoke`, `cc_warm_matrix`, and `active_min_resident`. The collector
uses it only for local board execution after validating the exact remote
build; it does not change remote build supervision. The warm CC matrix
forwards the chosen profile to its per-dataset board child. The AU smoke
retains a 24-GiB cgroup limit; warm CC pairs retain 32 GiB. The smoke's
existing RSS/watchdog checks and the pair's exclusive board lease remain in
force. Receipts identify the profile separately from the FPGA measurement.

`dual_clock_matrix` and `dual_clock_resident` may separately opt into
`--qualification /path/to/qualification.json` with the exact qualified
`--spine-host`. This replays the existing CPU correction tests and measures
one fresh sample of **each** arm directly, rather than first measuring the
old host and then retiming Spine. It does not change memory admission or
relax any kernel, clock, input, threshold, oracle or timing-boundary gate.
The old-graph-only cache preparation remains excluded and explicitly reported;
CPU qualification alone is not a board correctness result. The default
unqualified-host identity and the existing host-only retime runner are unchanged.

## Ownership And Checks

`hardware/board_execution/memory_policy.py` owns observation and policy;
`guarded_process.py` owns live child supervision. `pair_resources.py` owns
atomic memory and board admission. `source_retention/runtime.py` retains
cgroup checks and execution receipts. `tree_memory.py` supplies ARC
observations to the existing smoke process-tree watchdog; it does not own
or signal processes.

Run `python3 -m unittest discover -s tests -p 'test_board*memory*.py'` and
the existing source-retention clock/matrix/host-retime tests before use.

The reclaim rationale comes from the
[OpenZFS module parameters](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Module%20Parameters.html)
and [Linux ARC shrinker](https://github.com/openzfs/zfs/blob/master/module/os/linux/zfs/arc_os.c).
The [kernel PSI guide](https://docs.kernel.org/accounting/psi.html) defines
stall percentages; they are not an OOM prediction or a memory capacity value.
The half-credit and PSI limits above are our safety policy, not OpenZFS
performance guarantees.

## Bounded Reclaim Settling

`zfs-arc-clean-half-settle10-v1` is a separate opt-in profile for the same
board runners. It preserves the estimate, strict low-PSI admission, full peer
reservations, cgroup max/high, zero swap and immediate 32-GiB live-reserve
check. During an owned child only, high PSI must persist for ten seconds
before aborting; a low-PSI observation resets that timer. Missing/malformed
observations, timeout or a reserve breach still stop immediately. The
one-second monitor records peak PSI, number of pressured observations and
maximum consecutive pressure duration in every successful receipt.

This addresses a specific operational failure: LJ08's preceding strict
attempts stopped while loading old state, with about 20 GiB peak cgroup use,
no OOM/high/max events, over 32 GiB effective reserve and transient full PSI
around 1.1%. It does not establish that those attempts would have completed,
nor change their failed status. Ten seconds is a bounded settling policy,
not a measured ZFS reclaim guarantee. Original strict-profile runs, defaults,
and numerical/FPGA settings remain unchanged; new runs require fresh paths
and source pins.

Clock programming and source-pin verification can outlast a passing queue
observation. Under the settling profile only, each child therefore permits
at most 60 seconds of strict prelaunch re-admission when PSI rises in that
interval. No child exists during this wait; it consumes the existing command
timeout. Launch still requires the original low-PSI observation and physical
reserve. A reserve breach or malformed counters fails immediately. Exhausted
waits retain `child_started=false` and `NOT_STARTED` diagnostics. The running
child's ten-second pressure limit, finite cgroup and all timing boundaries
are unchanged. The strict profile and default do not retry prelaunch checks.

## Background Pressure Profile

`zfs-arc-clean-half-background5-v1` is a separate board-only opt-in, declared
before its first board measurement. It reuses the half-clean-ARC estimate,
full task and peer reservations, 32-GiB physical reserve, zero swap, finite
cgroup max/high, exclusive board lease, and bounded command timeouts. The
only pressure threshold change is `full avg10 < 5%` instead of `< 1%`;
`some avg10 < 10%` is unchanged. Above-threshold observations still queue
before launch, and stop an owned running child after ten consecutive
seconds. Missing counters and physical-reserve breaches fail immediately.
The existing profiles and their receipts retain their original meanings.

The motivating November 6 observation was about 37 GiB `MemAvailable`,
123 GiB ARC, 106 GiB clean evictable data, and 82 GiB discounted effective
headroom, while global full PSI stayed near 2% with no owned board child.
The earlier 1% threshold was an operational caution, not an OOM limit.
Five percent caps admitted global full-stall time at one twentieth of the
averaging window; it is not proof of OOM safety or an estimate of runtime
error. Containment, headroom, and live checks remain essential.

Every observation identifies the named profile and its explicit pressure
limits. New executions use fresh outputs and pinned runner source. Both
arms of a new pair use the same profile. Host-inclusive measurements may
still be affected by background reclaim, which must remain visible in the
receipts; no correction factor is applied. Old strict-profile samples are
not relabeled, and this change does not turn a correctness-only smoke or an
incomplete FPGA route record into an admitted performance result.
