"""Fail closed unless Linux cgroup v2 bounds every compiler descendant."""

from pathlib import Path
import subprocess

GIB = 1024**3


def verify(directory: Path, memory_gib: int = 40) -> dict:
    fields = {key: (directory / key).read_text().strip() for key in (
        "memory.max", "memory.high", "memory.swap.max", "memory.oom.group")}
    if (fields["memory.max"] == "max" or not 0 < int(fields["memory.max"]) <= memory_gib * GIB
            or fields["memory.high"] == "max" or not 0 < int(fields["memory.high"]) <= 36 * GIB
            or int(fields["memory.high"]) > int(fields["memory.max"])
            or fields["memory.swap.max"] != "0" or fields["memory.oom.group"] != "1"):
        raise ValueError("bounded memory.high/max, zero swap and group OOM kill required")
    return {"path": str(directory), "limits": fields}


def current() -> Path:
    rows = Path("/proc/self/cgroup").read_text().splitlines()
    unified = [line[3:] for line in rows if line.startswith("0::/")]
    if len(unified) != 1 or "/../" in unified[0] + "/":
        raise ValueError("one unified cgroup v2 membership required")
    return Path("/sys/fs/cgroup") / unified[0].lstrip("/")


def other_builds() -> list:
    result = subprocess.run(["ps", "-C", "vivado,vitis_hls,v++,vpl", "-o", "pid=,comm="],
                            text=True, capture_output=True, timeout=10)
    if result.returncode not in (0, 1) or result.stderr:
        raise RuntimeError("cannot inspect other hardware builds")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
