"""Identity, exclusive PCI-addressed leasing, and bounded subprocess execution."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess

from ..board_execution import memory_policy


def identity(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def save(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def check_memory(memory_gib=8, *, require_live_reserve=True):
    if require_live_reserve:
        memory_policy.live()
    group = next(line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                 if line.startswith("0::"))
    root = Path("/sys/fs/cgroup") / group.lstrip("/")
    maximum = (root / "memory.max").read_text().strip()
    if maximum == "max" or not 0 < int(maximum) <= memory_gib * 2**30:
        raise MemoryError(f"run the campaign in a cgroup with MemoryMax at most {memory_gib} GiB")
    if (root / "memory.swap.max").read_text().strip() != "0":
        raise MemoryError("zero cgroup swap required")
    return root


@contextmanager
def lease(index, bdf):
    nodes = [p for p in Path("/sys/class/drm").glob("renderD*") if (p / "device").resolve().name == bdf]
    if len(nodes) != 1:
        raise ValueError("exactly one render node must match PCI address")
    fd = os.open(f"/tmp/chuxiao-sharded-k4-board-{index}.lock",
                 os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield Path("/dev/dri") / nodes[0].name, fd
    finally:
        os.close(fd)


def execute(command, output, name, fd, node, bdf, *, memory_gib=8, timeout=240):
    check_memory(memory_gib)
    if subprocess.run(["fuser", str(node)], capture_output=True).returncode != 1:
        raise RuntimeError("board is not demonstrably idle")
    env = dict(os.environ, ORIGINAL_G_LEASE_FD=str(fd), ORIGINAL_G_EXPECT_BDF=bdf,
               ORIGINAL_R_LEASE_FD=str(fd), ORIGINAL_R_EXPECT_BDF=bdf,
               XILINX_XRT="/opt/xilinx/xrt", MALLOC_ARENA_MAX="2")
    command = ["/usr/bin/taskset", "-c", "124,125", *map(str, command)]
    log, error = output / f"{name}.stdout.txt", output / f"{name}.stderr.txt"
    with log.open("x") as stdout, error.open("x") as stderr:
        options = dict(env=env, pass_fds=(fd,), cwd=output, stdout=stdout, stderr=stderr)
        if memory_policy.selected() != memory_policy.DEFAULT:
            from ..board_execution import guarded_process
            code, memory = guarded_process.run(command, timeout=timeout, **options)
        else:
            code = subprocess.run(command, timeout=timeout, **options).returncode
            memory = dict(profile=memory_policy.DEFAULT)
    if code:
        raise RuntimeError(f"{name} failed ({code}): {error}")
    return {"command": command, "stdout": identity(log), "stderr": identity(error),
            "memory_guard": memory,
            "maximum_child_rss_kib_so_far": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
