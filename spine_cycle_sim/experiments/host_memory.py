"""Host-memory lifecycle and conservative Linux/ZFS admission estimates."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
import gc
import json
from pathlib import Path


POLICY = "linux_memavailable_plus_bounded_zfs_evictable_data_v1"


def release_process_heap() -> bool:
    """Collect Python objects and return free glibc arenas to the operating system."""

    gc.collect()
    try:
        trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return False
    trim.argtypes = (ctypes.c_size_t,)
    trim.restype = ctypes.c_int
    return bool(trim(0))


@dataclass(frozen=True)
class HostMemory:
    mem_total_bytes: int
    mem_available_bytes: int
    arc_size_bytes: int = 0
    arc_min_bytes: int = 0
    arc_evictable_data_bytes: int = 0
    arc_allowance_bytes: int = 0
    arc_status: str = "absent"
    accounting_policy: str = POLICY

    @property
    def available_bytes(self) -> int:
        return min(self.mem_total_bytes,
                   self.mem_available_bytes + self.arc_allowance_bytes)

    def record(self) -> dict:
        return {**asdict(self), "available_bytes": self.available_bytes}


def _meminfo(text: str) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in {"MemTotal:", "MemAvailable:"}:
            continue
        key = fields[0][:-1]
        if key in values or len(fields) != 3 or fields[2] != "kB":
            raise ValueError("invalid or duplicate host memory statistic")
        values[key] = int(fields[1]) * 1024
    if set(values) != {"MemTotal", "MemAvailable"} or not (
            0 <= values["MemAvailable"] <= values["MemTotal"] and values["MemTotal"] > 0):
        raise ValueError("missing or inconsistent MemTotal/MemAvailable")
    return values


def _arcstats(text: str) -> dict[str, int]:
    required = {"size", "c_min", "mru_evictable_data", "mfu_evictable_data"}
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in required:
            continue
        if fields[0] in values or len(fields) != 3 or fields[1] != "4":
            raise ValueError("invalid or duplicate ARC statistic")
        values[fields[0]] = int(fields[2])
    if set(values) != required or any(value < 0 for value in values.values()):
        raise ValueError("missing or negative ARC statistic")
    return values


def sample_host_memory(*, meminfo: Path = Path("/proc/meminfo"),
                       arcstats: Path = Path("/proc/spl/kstat/zfs/arcstats")) -> HostMemory:
    memory = _meminfo(meminfo.read_text(encoding="ascii"))
    base = {"mem_total_bytes": memory["MemTotal"],
            "mem_available_bytes": memory["MemAvailable"]}
    try:
        arc = _arcstats(arcstats.read_text(encoding="ascii"))
    except FileNotFoundError:
        return HostMemory(**base)
    except (OSError, UnicodeError, ValueError):
        return HostMemory(**base, arc_status="unreadable_or_invalid")
    if arc["size"] > memory["MemTotal"] or arc["c_min"] > memory["MemTotal"]:
        return HostMemory(**base, arc_status="unreadable_or_invalid")
    evictable = arc["mru_evictable_data"] + arc["mfu_evictable_data"]
    # Exclude metadata and anonymous ARC; keep c_min even if all data is evictable.
    allowance = min(evictable, max(0, arc["size"] - arc["c_min"]),
                    memory["MemTotal"] - memory["MemAvailable"])
    return HostMemory(**base, arc_size_bytes=arc["size"], arc_min_bytes=arc["c_min"],
                      arc_evictable_data_bytes=evictable, arc_allowance_bytes=allowance,
                      arc_status="bounded_evictable_data")


def available_memory_bytes() -> int:
    return sample_host_memory().available_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bytes", action="store_true", help="print only the admission estimate")
    args = parser.parse_args()
    snapshot = sample_host_memory()
    print(snapshot.available_bytes if args.bytes else json.dumps(snapshot.record(), sort_keys=True))


if __name__ == "__main__":
    main()
