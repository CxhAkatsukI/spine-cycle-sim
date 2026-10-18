"""Wait for the cooperative card lock, never reset or preempt another owner."""

from contextlib import contextmanager, ExitStack
import fcntl
from pathlib import Path
import time

from spine_cycle_sim.experiments.sharded_k4_stages.board import board_lease

MEASUREMENT_LOCK = Path.home() / ".cache/spine-cycle-sim/fullgraph-wall-measurement.lock"


@contextmanager
def measurement_lease():
    MEASUREMENT_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with MEASUREMENT_LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


@contextmanager
def _wait(factory, seconds, progress):
    deadline = None
    with ExitStack() as stack:
        while True:
            try:
                resource = stack.enter_context(factory())
                break
            except BlockingIOError:
                if deadline is None:
                    deadline = time.monotonic() + seconds
                remaining = deadline - time.monotonic()
                progress()
                if remaining <= 0:
                    raise TimeoutError("exclusive measurement/card lease wait expired; no board requested")
                time.sleep(min(10, remaining))
        # Exceptions from actual board work must not be mistaken for lock contention.
        yield resource


@contextmanager
def wait_for_card(device, seconds, progress):
    # The two cards may share the same fixed host CPUs. Serialize the measured
    # matrices, not FPGA compilation, to avoid timing their mutual CPU contention.
    with _wait(measurement_lease, seconds, progress):
        with _wait(lambda: board_lease(device), seconds, progress) as render:
            yield render
