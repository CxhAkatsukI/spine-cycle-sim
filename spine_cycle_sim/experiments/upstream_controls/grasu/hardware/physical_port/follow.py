"""Use the shared bounded return/board driver with an explicit external-port profile."""

from dataclasses import dataclass
import re

from .. import follow
from ..board import execution as board
from . import admission


@dataclass(frozen=True)
class ExternalPortRemote(follow.Remote):
    def seal(self):
        result = self.command(["systemd-run", "--user", "--wait", "--pipe", "--quiet", "--collect",
            "--property=MemoryMax=4G", "--property=MemoryHigh=3G", "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill", "--property=RuntimeMaxSec=1800", "env",
            "PYTHONPATH=" + str(self.runner), "python3", "-m", admission.delivery.__name__,
            "--packet", self.capsule, "--continuation", self.attempt, "--output", self.returned,
            "--unit", self.unit, "--invocation", self.invocation], timeout=1860).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", result):
            raise ValueError("external-port sealer did not return one receipt digest")
        return result


if __name__ == "__main__":
    follow.main(remote_class=ExternalPortRemote, reviewer=admission, board_pass=board.EXTERNAL_PASS)
