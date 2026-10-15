"""Reserve finite compiler cgroup budgets, without serializing independent builds."""

from pathlib import Path

from .containment import GIB


def budget(pid: int, *, proc: Path = Path("/proc"),
           root: Path = Path("/sys/fs/cgroup")) -> tuple[Path, int]:
    rows = (proc / str(pid) / "cgroup").read_text().splitlines()
    groups = [line[3:] for line in rows if line.startswith("0::/")]
    if len(groups) != 1 or ".." in Path(groups[0]).parts:
        raise ValueError("one safe unified compiler cgroup required")
    directory = root / groups[0].lstrip("/")
    selected = None
    while directory != root:
        limit = (directory / "memory.max").read_text().strip()
        if limit != "max":
            amount = int(limit)
            if amount <= 0 or (directory / "memory.swap.max").read_text().strip() != "0":
                raise ValueError("positive finite compiler limit and zero swap required")
            # Shared bounded ancestors cover their descendants only once.
            selected = directory, amount
        directory = directory.parent
    if selected is None:
        raise ValueError("competing compiler has no finite cgroup memory limit")
    return selected


def reservations(builds: list, own: Path, *, proc: Path = Path("/proc"),
                 root: Path = Path("/sys/fs/cgroup")) -> list:
    groups = {}
    rejected = []
    for row in builds:
        pid = int(row.split()[0])
        try:
            directory, amount = budget(pid, proc=proc, root=root)
            if directory == own or directory.is_relative_to(own):
                continue
            key = str(directory)
            record = groups.setdefault(key, {"cgroup": key, "memory_max_bytes": amount,
                                             "bounded": True, "pids": []})
            if record["memory_max_bytes"] != amount:
                raise ValueError("competing compiler limit changed during admission")
            record["pids"].append(pid)
        except FileNotFoundError:
            if (proc / str(pid)).exists():
                rejected.append({"pid": pid, "bounded": False, "reason": "missing cgroup limit"})
        except (OSError, ValueError) as error:
            rejected.append({"pid": pid, "bounded": False, "reason": str(error)})
    return [*groups.values(), *rejected]


def required_bytes(manifest: dict, builds: list) -> int:
    background = manifest.get("background_memory_gib", 0)
    if type(background) is not int or not 0 <= background <= 40:
        raise ValueError("background workload reserve must be between zero and 40 GiB")
    total = (manifest["tree_memory_gib"] + manifest["reserve_gib"] + background) * GIB
    if manifest.get("allow_bounded_builds", False):
        total += sum(row.get("memory_max_bytes", 0) for row in builds)
    return total


def eligible(available: int, builds: list, manifest: dict) -> bool:
    if not manifest.get("allow_bounded_builds", False):
        return not builds and available >= required_bytes(manifest, builds)
    return (all(row.get("bounded") is True and row.get("memory_max_bytes", 0) > 0
                for row in builds) and available >= required_bytes(manifest, builds))
