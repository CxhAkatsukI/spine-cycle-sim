# Host Memory Admission

The shared Python admission probe lives in
`spine_cycle_sim/experiments/host_memory.py`. It affects process admission and
watchdogs, not simulated HBM capacity, timing, or FPGA performance numbers.

```bash
python3 spine_cycle_sim/experiments/host_memory.py
python3 spine_cycle_sim/experiments/host_memory.py --bytes
```

## Linux And ZFS

On this Debian/OpenZFS host, `/proc/meminfo` does not include the reclaimable
ARC data in `MemAvailable`. The old probe used only that field. btop 1.3.0
with `zfs_arc_cached=True` adds `max(0, ARC.size - ARC.c_min)`; see its
[Linux collector](https://github.com/aristocratos/btop/blob/v1.3.0/src/linux/btop_collect.cpp).
Thus about 20 GiB from Linux plus 117 GiB from ARC explains a displayed
137 GiB. The old probe prematurely stopped several compiler trees. Those
watchdog stops are retained failures, not evidence of a synthesis defect.

The new admission estimate is deliberately lower than btop's full-ARC estimate:

```
allowance = min(mru_evictable_data + mfu_evictable_data,
                max(0, size - c_min), MemTotal - MemAvailable)
available = MemAvailable + allowance
```

Only evictable ARC data is credited, not metadata or anonymous ARC. The
[OpenZFS minimum](https://openzfs.github.io/openzfs-docs/Performance%20and%20Tuning/Module%20Parameters.html#zfs-arc-min)
is retained. Absent, unreadable, malformed, or inconsistent ARC statistics
fall back to Linux's estimate. Missing or inconsistent Linux memory fields
refuse admission. The JSON output records each term and the policy identity.
This is a reclaim-based host estimate, not a guarantee of immediate allocation
or an assertion that every Linux/ZFS version accounts memory identically.

## Limits Still Apply

Compiler admission reserves complete finite peer budgets plus the new job's
budget and a 24-GiB host margin. Each current build retains its 56-GiB
`memory.max`, 52-GiB high watermark, zero swap, process-tree watchdog, timeout,
and whole-group OOM policy. Reclaiming ARC can involve latency and I/O.
Unrelated workloads can still reduce headroom; a corrected estimate does not
remove safety checks. No ARC limit or other system-wide setting is changed.

Fresh runs record the accounting policy. Historical `available_bytes` fields
used Linux `MemAvailable` only and must not be silently reinterpreted. The
Spine shell can explicitly select this standalone probe; it otherwise retains
its Linux-only preflight. Frozen failed directories are never resumed in place.

## Checks

`tests/test_host_memory.py` covers non-ZFS hosts, conservative ARC bounds,
malformed statistics, missing Linux fields, and the standalone probe. Existing
campaign and route-watchdog tests retain their bounded-launch/stop checks.
