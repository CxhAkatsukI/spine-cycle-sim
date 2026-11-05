"""Bridge the board ARC policy to the existing process-tree watchdog."""

import time

from . import memory_policy, prelaunch_memory


class Observer:
    """Observe headroom; the tree watchdog still owns process cleanup and RSS."""

    def __init__(self, timeout):
        if memory_policy.selected() == memory_policy.DEFAULT:
            raise ValueError("tree memory observation requires an explicit ARC board profile")
        self.timeout = timeout
        self.receipt = dict(profile=memory_policy.selected(), status="NOT_STARTED", checks=0)
        self.pressure = memory_policy.PressureWindow()

    def remember(self, observation):
        row = self.receipt
        row.update(last_observation=observation, checks=row["checks"] + 1)
        row["minimum_effective_available_bytes"] = min(
            row.get("minimum_effective_available_bytes", float("inf")),
            observation["effective_available_bytes"])
        row["maximum_pressure_avg10"] = {
            key: max(row.get("maximum_pressure_avg10", {}).get(key, 0), value)
            for key, value in observation["pressure_avg10"].items()}

    def __call__(self, *, initial):
        try:
            if initial:
                if self.receipt["checks"]:
                    raise ValueError("a board memory observer cannot be reused")
                observation, prelaunch = prelaunch_memory.admit(self.timeout)
                self.receipt.update(admission=observation, prelaunch=prelaunch, status="MONITORING")
            else:
                settle = memory_policy.settling()
                observation = memory_policy.live(allow_transient_pressure=True) if settle else memory_policy.live()
            self.remember(observation)
            if not initial and memory_policy.settling():
                self.pressure.check(observation, time.monotonic())
            return observation["effective_available_bytes"]
        except BaseException as error:
            observation = getattr(error, "observation", None)
            if observation is not None and observation is not self.receipt.get("last_observation"):
                self.remember(observation)
            self.receipt.update(status="ABORTED", error=repr(error))
            if hasattr(error, "memory_guard"):
                self.receipt["prelaunch_failure"] = error.memory_guard
            raise
        finally:
            if memory_policy.settling():
                self.receipt.update(pressure_grace_seconds=memory_policy.PRESSURE_GRACE_SECONDS,
                                    maximum_consecutive_pressure_seconds=self.pressure.maximum_seconds,
                                    pressured_checks=self.pressure.pressured_checks)
