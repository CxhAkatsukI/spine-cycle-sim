"""PID-bound cleanup of observed workers, including nested process sessions.

Sampling is not cgroup containment: a child that forks and reparents between
snapshots can escape observation. pidfds prevent cleanup from killing a later
unrelated process that reuses an observed PID.
"""

import os
import select
import signal


class ObservedProcesses:
    def __init__(self):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise RuntimeError("process-tree watchdog requires Linux pidfds")
        self.handles = {}
        self.observed_pids = set()

    def observe(self, pids):
        self.live_pids()
        for pid in pids:
            if pid not in self.handles:
                try:
                    self.handles[pid] = os.pidfd_open(pid)
                    self.observed_pids.add(pid)
                except ProcessLookupError:
                    pass
        self.live_pids()

    def live_pids(self):
        live = []
        for pid, handle in list(self.handles.items()):
            poller = select.poll()
            poller.register(handle, select.POLLIN)
            if poller.poll(0):
                # Retain history without keeping a descriptor for every compiler job.
                os.close(handle)
                del self.handles[pid]
            else:
                live.append(pid)
        return live

    def kill(self, root):
        signaled = []
        # Kill observed workers before their launcher, retaining pidfd identities.
        for pid in sorted(self.handles, key=lambda value: value == root):
            try:
                signal.pidfd_send_signal(self.handles[pid], signal.SIGKILL)
                signaled.append(pid)
            except ProcessLookupError:
                pass
        return signaled

    def close(self):
        for handle in self.handles.values():
            os.close(handle)
        self.handles.clear()
