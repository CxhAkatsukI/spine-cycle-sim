"""Supervise the large CC resume with one explicit, shared memory policy."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import time

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import admission
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import (
    Lease, merge, start_time,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import (
    GIB, current, other_builds,
)
from .runtime import identity, save


POLICY = dict(tree_memory_gib=104, high_memory_gib=100, reserve_gib=128,
              background_memory_gib=8, allow_bounded_builds=True)
MEMORY_PROFILES = {"104g-v1": POLICY, "192g-v1": dict(
    POLICY, tree_memory_gib=192, high_memory_gib=184), "320g-v1": dict(
    POLICY, tree_memory_gib=320, high_memory_gib=304)}


def properties(policy=POLICY):
    return [f"MemoryMax={policy['tree_memory_gib']}G",
            f"MemoryHigh={policy['high_memory_gib']}G", "MemorySwapMax=0",
            "OOMPolicy=kill", "KillMode=control-group", "RuntimeMaxSec=25h"]


def verify(group, policy=POLICY):
    expected = dict(zip(("memory.max", "memory.high", "memory.swap.max", "memory.oom.group"),
                        map(str, (policy['tree_memory_gib'] * GIB,
                                  policy['high_memory_gib'] * GIB, 0, 1))))
    actual = {name: (group / name).read_text().strip() for name in expected}
    if actual != expected:
        raise MemoryError(f"CC resume containment differs: {actual!r}")
    return actual


def available():
    fields = dict(line.split(":", 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(fields['MemTotal'].split()[0]) * 1024 < 480 * GIB:
        raise MemoryError('large CC resume requires the >=480-GiB host')
    return int(fields['MemAvailable'].split()[0]) * 1024


def stop(child):
    if child is None or child.poll() is not None:
        return
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=30)


def reserve(group, policy, lease, report, output, wait_seconds):
    started = time.monotonic()
    while True:
        with lease.locked():
            verify(group, policy)
            peers = merge(admission.reservations(other_builds(), group), lease.peers())
            amount = available()
            report['admission'] = dict(available_bytes=amount, reservations=peers,
                                      required_bytes=admission.required_bytes(policy, peers))
            report['admission_waited_seconds'] = time.monotonic() - started
            if admission.eligible(amount, peers, policy):
                save(lease.path, dict(cgroup=str(group), memory_max_bytes=policy['tree_memory_gib'] * GIB,
                                     bounded=True, pid=os.getpid(), start_time=start_time(os.getpid())))
                lease.held = True
                return
        if not wait_seconds:
            raise MemoryError('full compiler budgets plus 128-GiB reserve do not fit')
        remaining = wait_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('compiler admission deadline expired without starting tools')
        report['status'] = 'WAITING_FOR_ADMISSION'
        save(output / 'execution.json', report)
        time.sleep(min(5, remaining))


def run(args):
    if not 1 <= args.timeout_seconds <= 86400:
        raise ValueError('resume deadline must be between one second and 24 hours')
    wait_seconds = getattr(args, 'admission_wait_seconds', 0)
    if not 0 <= wait_seconds <= min(7200, args.timeout_seconds):
        raise ValueError('admission wait must be at most two hours within the resume deadline')
    profile = getattr(args, 'memory_profile', '104g-v1')
    policy = MEMORY_PROFILES[profile]
    group = current()
    verify(group, policy)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status='ADMITTING', policy=policy, memory_profile=profile,
                  admission_wait_seconds=wait_seconds,
                  script=identity(args.script), supervisor=identity(__file__),
                  cgroup=str(group), properties=properties(policy))
    lease = Lease(Path.home() / '.cache/spine-cycle-sim/compiler-reservations', group)
    child = None

    def interrupted(signum, frame):
        raise InterruptedError(f'resume interrupted by signal {signum}')

    old_signals = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    started = time.monotonic()
    try:
        # Reserve the full tree before any compiler can be spawned.
        reserve(group, policy, lease, report, args.output, wait_seconds)
        with (args.output / 'build.log').open('x') as log:
            child = subprocess.Popen(['/bin/bash', str(args.script.resolve())],
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            report.update(status='BUILDING', child_pid=child.pid)
            while child.poll() is None:
                verify(group, policy)
                amount = available()
                report.update(available_bytes=amount, elapsed_seconds=time.monotonic() - started,
                              memory_current_bytes=int((group / 'memory.current').read_text()))
                save(args.output / 'execution.json', report)
                if amount < policy['reserve_gib'] * GIB:
                    raise MemoryError('128-GiB live reserve breached')
                if report['elapsed_seconds'] >= args.timeout_seconds:
                    raise TimeoutError('CC resume deadline expired')
                time.sleep(5)
            report['returncode'] = child.returncode
            if child.returncode:
                raise RuntimeError(f'compiler exited {child.returncode}; raw logs retained')
        report['status'] = 'BUILD_COMPLETED_NOT_BOARD_ADMITTED'
    except BaseException as error:
        report.update(status='FAILED_RETAINED', error=repr(error))
        raise
    finally:
        stop(child)
        lease.release()
        report['elapsed_seconds'] = time.monotonic() - started
        report['memory_events'] = dict(line.split() for line in (group / 'memory.events').read_text().splitlines())
        report['build_log'] = identity(args.output / 'build.log') if (args.output / 'build.log').exists() else None
        save(args.output / 'execution.json', report)
        for sig, previous in old_signals.items():
            signal.signal(sig, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--print-properties', action='store_true')
    parser.add_argument('--script', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=86400)
    parser.add_argument('--admission-wait-seconds', type=int, default=0)
    parser.add_argument('--memory-profile', choices=MEMORY_PROFILES, default='104g-v1')
    args = parser.parse_args()
    if args.print_properties:
        print('\n'.join(properties(MEMORY_PROFILES[args.memory_profile])))
    elif args.script is None or args.output is None:
        parser.error('--script and --output are required for execution')
    else:
        run(args)


if __name__ == '__main__':
    main()
