# ARC-Aware Board Admission

The explicit `zfs-arc-clean-half-v1` profile is limited to the single-pass
resident-pair and Spine host-retime board runners. It does not change FPGA
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

- Atomic admission still reserves the task's full 8/16/24/32-GiB cgroup
  limit, all bounded peer reservations, and a 32-GiB safety reserve.
  A peer reservation is validated against its own full finite max/high,
  zero swap and group-OOM settings, not against the board runner's smaller
  limits. For example, a 104/100-GiB peer still reserves all 104 GiB.
- `MemoryHigh`, zero swap, exclusive PCI-board leases, and timeouts remain.
- Admission and running children require memory PSI `some avg10 < 10%`
  and `full avg10 < 1%`; running children also retain a 32-GiB effective
  physical reserve. The live check runs every second.
- On pressure, timeout, or interruption, terminate only the owned child
  process group; never adjust or terminate another user's work.
- Receipts retain raw memory/ARC/PSI admission observations, the minimum
  effective headroom, maximum observed PSI, named profile, and source pins.
  Memory events and peak cgroup usage remain in the final result.

Select with `--memory-profile zfs-arc-clean-half-v1` on
`source_retention.dual_clock_matrix`, `dual_clock_resident`,
`correction_matrix`, or `correction_retime`. A matrix may explicitly select
remaining datasets with `--datasets LJ LJ08 R19`; its receipt marks that it
is not a complete eight-dataset matrix. Earlier accepted samples are kept
separately, not silently rerun or rewritten.

## Ownership And Checks

`hardware/board_execution/memory_policy.py` owns observation and policy;
`guarded_process.py` owns live child supervision. `pair_resources.py` owns
atomic memory and board admission. `source_retention/runtime.py` retains
cgroup checks and execution receipts.

Run `python3 -m unittest discover -s tests -p test_board_arc_memory.py` and
the existing source-retention clock/matrix/host-retime tests before use.

The reclaim rationale comes from the
[OpenZFS module parameters](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Module%20Parameters.html)
and [Linux ARC shrinker](https://github.com/openzfs/zfs/blob/master/module/os/linux/zfs/arc_os.c).
The half-credit and PSI limits above are our safety policy, not OpenZFS
performance guarantees.
