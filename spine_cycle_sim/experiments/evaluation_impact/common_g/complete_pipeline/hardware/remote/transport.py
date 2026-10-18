"""Bounded SSH state queries, return sealing and hash-checked directory transport."""

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess

from ....continuous_board.execution.supervisor import FIELDS

MODULE = "spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote"


@dataclass(frozen=True)
class Remote:
    target: str
    port: int
    runner: Path
    capsule: Path
    attempt: Path
    returned: Path
    unit: str
    invocation: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", self.target) or \
                type(self.port) is not int or not 1 <= self.port <= 65535 or \
                any(not path.is_absolute() or ".." in path.parts for path in (
                    self.runner, self.capsule, self.attempt, self.returned)) or \
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", self.unit) or \
                not re.fullmatch(r"[0-9a-f]{32}", self.invocation):
            raise ValueError("explicit safe remote endpoint, paths and invocation required")

    @property
    def ssh(self):
        return ["ssh", "-p", str(self.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]

    def command(self, argv, *, timeout):
        result = subprocess.run([*self.ssh, self.target, shlex.join(map(str, argv))],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"remote command failed ({result.returncode}): {result.stderr[-4000:]}")
        return result.stdout

    def state(self):
        result = self.command(["systemctl", "--user", "show", self.unit, "--no-pager",
                               "--property=" + ",".join(FIELDS)], timeout=30)
        rows = [line.split("=", 1) for line in result.splitlines()]
        if len(rows) != len(FIELDS) or any(len(row) != 2 for row in rows) or \
                {row[0] for row in rows} != set(FIELDS):
            raise ValueError("incomplete remote service identity")
        return dict(rows)

    def seal(self):
        # This is a separate bounded sealer, never an edit of the live route runner.
        result = self.command(["systemd-run", "--user", "--wait", "--pipe", "--quiet", "--collect",
            "--property=MemoryMax=4G", "--property=MemoryHigh=3G", "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill", "--property=RuntimeMaxSec=1800", "env",
            "PYTHONPATH=" + str(self.runner), "python3", "-m", MODULE, "seal",
            "--capsule", self.capsule, "--attempt", self.attempt, "--output", self.returned,
            "--unit", self.unit, "--invocation", self.invocation], timeout=1860).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", result):
            raise ValueError("remote sealer did not return one receipt digest")
        return result

    def transfer(self, output):
        output.mkdir(parents=True, exist_ok=False)
        result = subprocess.run(["rsync", "-a", "--protect-args", "--timeout=120", "-e", shlex.join(self.ssh),
            self.target + ":" + str(self.returned) + "/", str(output) + "/"],
            capture_output=True, text=True, timeout=1800)
        if result.returncode:
            raise RuntimeError(f"remote return transfer failed ({result.returncode}): {result.stderr[-4000:]}")
