#!/usr/bin/env python3
"""Assign running jobs from multiple campaign launchers to distinct physical CPUs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import (  # noqa: E402
    physical_cpu_ids,
)


def process_group_tasks(process_group: int) -> list[int]:
    tasks: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2 :].split()
            if int(fields[2]) != process_group:
                continue
            tasks.update(
                int(task.name)
                for task in (entry / "task").iterdir()
                if task.name.isdigit()
            )
        except (OSError, ValueError, IndexError):
            continue
    return sorted(tasks)


def running_jobs(run_dirs: list[Path]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        state_path = run_dir.resolve() / "campaign_state.json"
        state = json.loads(state_path.read_text(encoding="ascii"))
        for job in state["jobs"]:
            if job.get("status") != "running":
                continue
            jobs.append(
                {
                    "run_dir": str(run_dir.resolve()),
                    "campaign_id": state["campaign_id"],
                    "job_id": str(job["job_id"]),
                    "process_group": int(job["process_group"]),
                    "recorded_cpu_id": job.get("cpu_id"),
                    "started_at": float(job["started_at"]),
                }
            )
    return sorted(jobs, key=lambda row: (row["started_at"], row["job_id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--cpu-offset", type=int, default=0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    cpus = physical_cpu_ids()
    jobs = running_jobs(args.run_dir)
    if args.cpu_offset < 0 or args.cpu_offset + len(jobs) > len(cpus):
        raise ValueError("running jobs do not fit in the requested physical CPU pool")

    assignments = []
    for index, job in enumerate(jobs):
        cpu = cpus[args.cpu_offset + index]
        tasks = process_group_tasks(job["process_group"])
        if not tasks:
            raise RuntimeError(f"process group vanished: {job['job_id']}")
        previous = {task: sorted(os.sched_getaffinity(task)) for task in tasks}
        for task in tasks:
            os.sched_setaffinity(task, {cpu})
        verified = {task: sorted(os.sched_getaffinity(task)) for task in tasks}
        if any(affinity != [cpu] for affinity in verified.values()):
            raise RuntimeError(f"failed to pin every task for {job['job_id']}")
        assignments.append(
            {
                **job,
                "effective_cpu_id": cpu,
                "tasks": tasks,
                "previous_affinity": previous,
                "verified_affinity": verified,
            }
        )

    report = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu_offset": args.cpu_offset,
        "physical_cpu_pool": cpus,
        "assignment_count": len(assignments),
        "assignments": assignments,
        "host_wall_time_note": (
            "Wall time before this timestamp may include cross-campaign CPU-pin "
            "contention; simulated cycles are unaffected."
        ),
        "status": "pass",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                "assignments": len(assignments),
                "report": str(args.report.resolve()),
                "status": "pass",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
