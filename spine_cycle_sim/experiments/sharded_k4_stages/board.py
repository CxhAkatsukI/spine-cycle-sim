"""Shared board lease and unchanged production-host command contract."""

from contextlib import contextmanager
import fcntl
from pathlib import Path
import subprocess


@contextmanager
def board_lease(device: int):
    if device not in (0, 1):
        raise ValueError("known U55C device index required")
    render = Path(("/dev/dri/renderD128", "/dev/dri/renderD131")[device])
    if not render.exists():
        raise FileNotFoundError(render)
    with Path(f"/tmp/chuxiao-sharded-k4-board-{device}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield render


def require_idle_board(render: Path) -> None:
    users = subprocess.run(["fuser", str(render)], capture_output=True, text=True)
    if users.returncode != 1:
        raise RuntimeError(f"board is occupied or occupancy check failed: {users.stdout} {users.stderr}")


def hardware_command(integration: Path, row: dict, host: Path, xclbin: Path,
                     output: Path, device: int, timeout: int, trace: str) -> list[str]:
    return ["env", f"GRASU_SHARDED_EVENT_TRACE={trace}", "GRASU_UPDATE_REPEATS=1",
            "bash", str(integration / "scripts/run_pma_native_hw.sh"),
            "--algorithm", row["algorithm"], "--host", str(host),
            "--xclbin", str(xclbin), "--graph", row["graph"],
            "--out-dir", str(output), "--source", row["source"],
            "--max-supersteps", "256", "--device-index", str(device),
            "--timeout", str(max(1, timeout - 20))]
