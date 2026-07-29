"""Auditable, resumable process scheduler for long simulator campaigns."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any, Mapping, Sequence


JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TERMINAL_STATUSES = {"pass", "fail", "stopped", "blocked"}


@dataclass(frozen=True)
class CampaignJob:
    job_id: str
    command: tuple[str, ...]
    cwd: Path
    dataset_id: str
    algorithm: str
    system: str
    tier: str
    resource_class: str
    estimated_rss_bytes: int
    priority: int
    dependencies: tuple[str, ...]
    environment: Mapping[str, str]


@dataclass
class RunningProcess:
    process: subprocess.Popen[bytes]
    log_stream: Any
    cpu_id: int | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    os.replace(temporary, path)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="ascii") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()


def load_campaign_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="ascii"))
    validate_campaign_manifest(manifest)
    return manifest


def validate_campaign_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("campaign manifest schema_version must be 1")
    if not isinstance(manifest.get("campaign_id"), str) or not manifest["campaign_id"]:
        raise ValueError("campaign manifest lacks campaign_id")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("campaign manifest jobs must be a non-empty list")
    ids: list[str] = []
    for raw in jobs:
        if not isinstance(raw, Mapping):
            raise ValueError("campaign job must be an object")
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or not JOB_ID_PATTERN.fullmatch(job_id):
            raise ValueError(f"invalid campaign job_id: {job_id!r}")
        ids.append(job_id)
        command = raw.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) and argument for argument in command)
        ):
            raise ValueError(f"{job_id} command must be a non-empty string list")
        if raw.get("resource_class", "small") not in {"small", "large"}:
            raise ValueError(f"{job_id} has invalid resource_class")
        estimated_rss_gib = raw.get("estimated_rss_gib", 1.0)
        if not isinstance(estimated_rss_gib, (int, float)) or estimated_rss_gib <= 0:
            raise ValueError(f"{job_id} has invalid estimated_rss_gib")
        dependencies = raw.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(dependency, str) for dependency in dependencies
        ):
            raise ValueError(f"{job_id} dependencies must be a string list")
        environment = raw.get("environment", {})
        if not isinstance(environment, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError(f"{job_id} environment must contain strings")
    if len(ids) != len(set(ids)):
        raise ValueError("campaign job IDs are not unique")
    known = set(ids)
    for raw in jobs:
        job_id = str(raw["job_id"])
        dependencies = set(raw.get("dependencies", []))
        if job_id in dependencies:
            raise ValueError(f"{job_id} depends on itself")
        unknown = dependencies - known
        if unknown:
            raise ValueError(f"{job_id} has unknown dependencies: {sorted(unknown)}")
    dependencies_by_id = {
        str(raw["job_id"]): set(raw.get("dependencies", [])) for raw in jobs
    }
    resolved: set[str] = set()
    while len(resolved) < len(known):
        ready = {
            job_id
            for job_id, dependencies in dependencies_by_id.items()
            if job_id not in resolved and dependencies <= resolved
        }
        if not ready:
            unresolved = sorted(known - resolved)
            raise ValueError(f"campaign dependencies contain a cycle: {unresolved}")
        resolved.update(ready)


def campaign_jobs(manifest: Mapping[str, Any], manifest_path: Path) -> list[CampaignJob]:
    validate_campaign_manifest(manifest)
    default_cwd = Path(str(manifest.get("default_cwd", manifest_path.parent))).resolve()
    jobs: list[CampaignJob] = []
    for raw in manifest["jobs"]:
        jobs.append(
            CampaignJob(
                job_id=str(raw["job_id"]),
                command=tuple(str(argument) for argument in raw["command"]),
                cwd=Path(str(raw.get("cwd", default_cwd))).resolve(),
                dataset_id=str(raw.get("dataset_id", "-")),
                algorithm=str(raw.get("algorithm", "-")),
                system=str(raw.get("system", "-")),
                tier=str(raw.get("tier", "-")),
                resource_class=str(raw.get("resource_class", "small")),
                estimated_rss_bytes=int(float(raw.get("estimated_rss_gib", 1.0)) * 2**30),
                priority=int(raw.get("priority", 100)),
                dependencies=tuple(str(value) for value in raw.get("dependencies", [])),
                environment={str(key): str(value) for key, value in raw.get("environment", {}).items()},
            )
        )
    return jobs


def available_memory_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("/proc/meminfo lacks MemAvailable")


def physical_cpu_ids() -> list[int]:
    selected: dict[tuple[str, str], int] = {}
    cpu_root = Path("/sys/devices/system/cpu")
    for entry in cpu_root.glob("cpu[0-9]*"):
        cpu_text = entry.name[3:]
        if not cpu_text.isdigit():
            continue
        cpu = int(cpu_text)
        topology = entry / "topology"
        try:
            package = (topology / "physical_package_id").read_text(encoding="ascii").strip()
            core = (topology / "core_id").read_text(encoding="ascii").strip()
        except OSError:
            continue
        selected.setdefault((package, core), cpu)
    return sorted(selected.values()) or list(range(os.cpu_count() or 1))


def process_group_stats(process_group: int) -> tuple[int, float]:
    rss_bytes = 0
    cpu_seconds = 0.0
    ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii")
            closing = stat.rfind(")")
            fields = stat[closing + 2 :].split()
            process_pgrp = int(fields[2])
            if process_pgrp != process_group:
                continue
            rss_pages = int(fields[21])
            cpu_ticks = int(fields[11]) + int(fields[12])
        except (OSError, ValueError, IndexError):
            continue
        rss_bytes += rss_pages * os.sysconf("SC_PAGE_SIZE")
        cpu_seconds += cpu_ticks / ticks
    return rss_bytes, cpu_seconds


def read_progress(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class CampaignRunner:
    def __init__(
        self,
        manifest_path: Path,
        run_dir: Path,
        *,
        jobs: int,
        large_jobs: int,
        memory_reserve_bytes: int,
        sample_seconds: float,
        pin_cpus: bool,
        resume: bool,
        no_progress_warn_seconds: float = 1200.0,
        memory_emergency_bytes: int | None = None,
        memory_recovery_bytes: int | None = None,
        max_starts_per_sample: int = 4,
    ) -> None:
        if jobs <= 0 or large_jobs <= 0 or large_jobs > jobs:
            raise ValueError("jobs and large_jobs must satisfy 0 < large_jobs <= jobs")
        emergency = (
            memory_reserve_bytes
            if memory_emergency_bytes is None
            else memory_emergency_bytes
        )
        recovery = (
            max(memory_reserve_bytes, emergency)
            if memory_recovery_bytes is None
            else memory_recovery_bytes
        )
        if (
            memory_reserve_bytes < 0
            or emergency < 0
            or recovery < emergency
            or sample_seconds <= 0
            or no_progress_warn_seconds <= 0
            or max_starts_per_sample <= 0
        ):
            raise ValueError("memory reserve and sample interval are invalid")
        self.manifest_path = manifest_path.resolve()
        self.manifest = load_campaign_manifest(self.manifest_path)
        self.manifest_sha256 = sha256_file(self.manifest_path)
        self.specs = campaign_jobs(self.manifest, self.manifest_path)
        self.spec_by_id = {spec.job_id: spec for spec in self.specs}
        self.run_dir = run_dir.resolve()
        self.jobs_limit = jobs
        self.large_jobs_limit = large_jobs
        self.memory_reserve_bytes = memory_reserve_bytes
        self.memory_emergency_bytes = emergency
        self.memory_recovery_bytes = recovery
        self.max_starts_per_sample = max_starts_per_sample
        self.sample_seconds = sample_seconds
        self.pin_cpus = pin_cpus
        self.resume = resume
        self.no_progress_warn_seconds = no_progress_warn_seconds
        self.state_path = self.run_dir / "campaign_state.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.running: dict[str, RunningProcess] = {}
        self.stop_requested = False
        self.memory_pressure_active = False
        self.started_at = time.time()
        self.cpu_pool = physical_cpu_ids() if pin_cpus else []
        self.state = self._initial_state()

    def _initial_state(self) -> dict[str, Any]:
        previous: dict[str, Any] | None = None
        if self.resume and self.state_path.is_file():
            loaded = json.loads(self.state_path.read_text(encoding="ascii"))
            if loaded.get("manifest_sha256") != self.manifest_sha256:
                raise ValueError("resume manifest hash differs from campaign state")
            previous = loaded
        previous_jobs = {
            str(job["job_id"]): job for job in (previous or {}).get("jobs", [])
        }
        jobs: list[dict[str, Any]] = []
        for spec in self.specs:
            old = previous_jobs.get(spec.job_id, {})
            keep_pass = old.get("status") == "pass"
            jobs.append(
                {
                    "job_id": spec.job_id,
                    "dataset_id": spec.dataset_id,
                    "algorithm": spec.algorithm,
                    "system": spec.system,
                    "tier": spec.tier,
                    "resource_class": spec.resource_class,
                    "estimated_rss_bytes": spec.estimated_rss_bytes,
                    "dependencies": list(spec.dependencies),
                    "status": "pass" if keep_pass else "queued",
                    "attempt": int(old.get("attempt", 0)) if keep_pass else 0,
                    "elapsed_seconds": float(old.get("elapsed_seconds", 0.0)) if keep_pass else 0.0,
                    "rss_bytes": 0,
                    "peak_rss_bytes": int(old.get("peak_rss_bytes", 0)) if keep_pass else 0,
                    "cpu_seconds": 0.0,
                    "progress": old.get("progress") if keep_pass else None,
                    "exit_code": old.get("exit_code") if keep_pass else None,
                    "reason": old.get("reason") if keep_pass else None,
                }
            )
        return {
            "schema_version": 1,
            "campaign_id": self.manifest["campaign_id"],
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "launcher_pid": os.getpid(),
            "status": "running",
            "started_at": self.started_at,
            "updated_at": self.started_at,
            "configuration": {
                "jobs": self.jobs_limit,
                "large_jobs": self.large_jobs_limit,
                "memory_reserve_bytes": self.memory_reserve_bytes,
                "memory_emergency_bytes": self.memory_emergency_bytes,
                "memory_recovery_bytes": self.memory_recovery_bytes,
                "max_starts_per_sample": self.max_starts_per_sample,
                "sample_seconds": self.sample_seconds,
                "pin_cpus": self.pin_cpus,
                "automatic_timeout_seconds": None,
                "no_progress_warn_seconds": self.no_progress_warn_seconds,
            },
            "host": {},
            "summary": {},
            "jobs": jobs,
        }

    def _job_state(self, job_id: str) -> dict[str, Any]:
        return next(job for job in self.state["jobs"] if job["job_id"] == job_id)

    def _event(self, event: str, **fields: Any) -> None:
        append_jsonl(
            self.events_path,
            {"timestamp": time.time(), "event": event, **fields},
        )

    def _free_cpu(self) -> int | None:
        if not self.pin_cpus:
            return None
        used = {running.cpu_id for running in self.running.values()}
        return next((cpu for cpu in self.cpu_pool if cpu not in used), None)

    def _start(self, spec: CampaignJob) -> None:
        state = self._job_state(spec.job_id)
        job_dir = self.run_dir / "jobs" / spec.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "stdout.log"
        progress_path = job_dir / "progress.json"
        environment = os.environ.copy()
        environment.update(spec.environment)
        environment["SPINE_CAMPAIGN_JOB_ID"] = spec.job_id
        environment["SPINE_CAMPAIGN_PROGRESS_PATH"] = str(progress_path)
        environment["SPINE_CAMPAIGN_JOB_DIR"] = str(job_dir)
        log_stream = log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        cpu_id = self._free_cpu()
        if cpu_id is not None:
            try:
                os.sched_setaffinity(process.pid, {cpu_id})
            except OSError:
                cpu_id = None
        now = time.time()
        state.update(
            {
                "status": "running",
                "attempt": int(state["attempt"]) + 1,
                "pid": process.pid,
                "process_group": process.pid,
                "cpu_id": cpu_id,
                "started_at": now,
                "updated_at": now,
                "elapsed_seconds": 0.0,
                "rss_bytes": 0,
                "peak_rss_bytes": 0,
                "cpu_seconds": 0.0,
                "progress": None,
                "progress_path": str(progress_path),
                "log_path": str(log_path),
                "reason": None,
                "exit_code": None,
                "last_progress_at": now,
                "no_progress_seconds": 0.0,
                "no_progress_warning": False,
            }
        )
        atomic_write_json(
            job_dir / "command.json",
            {
                "job_id": spec.job_id,
                "command": list(spec.command),
                "cwd": str(spec.cwd),
                "environment": dict(spec.environment),
                "manifest_sha256": self.manifest_sha256,
                "started_at": now,
            },
        )
        self.running[spec.job_id] = RunningProcess(process, log_stream, cpu_id)
        self._event("job_started", job_id=spec.job_id, pid=process.pid, cpu_id=cpu_id)

    def _request_stop(self, job_id: str, reason: str) -> None:
        state = self._job_state(job_id)
        if state["status"] == "queued":
            state.update(status="stopped", reason=reason, updated_at=time.time())
            self._event("job_stopped_before_start", job_id=job_id, reason=reason)
            return
        running = self.running.get(job_id)
        if running is None or state["status"] not in {"running", "stopping"}:
            return
        if state["status"] != "stopping":
            try:
                os.killpg(running.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            state.update(
                status="stopping",
                reason=reason,
                stop_requested_at=time.time(),
                updated_at=time.time(),
            )
            self._event("job_stop_requested", job_id=job_id, reason=reason)

    def _read_controls(self) -> None:
        control_dir = self.run_dir / "control"
        if not control_dir.is_dir():
            return
        for path in sorted(control_dir.glob("*.json")):
            try:
                request = json.loads(path.read_text(encoding="ascii"))
            except (OSError, json.JSONDecodeError):
                continue
            action = request.get("action")
            reason = str(request.get("reason", "manual soft-stop"))
            if action == "stop_all":
                self.stop_requested = True
                for spec in self.specs:
                    self._request_stop(spec.job_id, reason)
            elif action == "stop_job" and request.get("job_id") in self.spec_by_id:
                self._request_stop(str(request["job_id"]), reason)
            else:
                self._event("invalid_control", path=str(path))
            path.unlink(missing_ok=True)

    def _poll_running(self) -> None:
        now = time.time()
        for job_id, running in list(self.running.items()):
            state = self._job_state(job_id)
            rss_bytes, cpu_seconds = process_group_stats(running.process.pid)
            state["rss_bytes"] = rss_bytes
            state["peak_rss_bytes"] = max(
                int(state.get("peak_rss_bytes", 0)), rss_bytes
            )
            state["cpu_seconds"] = cpu_seconds
            state["elapsed_seconds"] = now - float(state["started_at"])
            state["updated_at"] = now
            progress = read_progress(Path(state["progress_path"]))
            if progress is not None:
                previous = state.get("progress")
                state["progress"] = progress
                if progress != previous:
                    state["last_progress_at"] = now
            last_progress_at = float(state.get("last_progress_at", state["started_at"]))
            state["no_progress_seconds"] = max(0.0, now - last_progress_at)
            state["no_progress_warning"] = (
                state["no_progress_seconds"] >= self.no_progress_warn_seconds
            )
            if state["status"] == "stopping":
                requested = float(state.get("stop_requested_at", now))
                if now - requested >= 10.0 and running.process.poll() is None:
                    try:
                        os.killpg(running.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            return_code = running.process.poll()
            if return_code is None:
                continue
            running.log_stream.close()
            self.running.pop(job_id)
            was_stopping = state["status"] == "stopping"
            status = "stopped" if was_stopping else ("pass" if return_code == 0 else "fail")
            state.update(
                status=status,
                exit_code=return_code,
                finished_at=now,
                updated_at=now,
                reason=state.get("reason") if was_stopping else (
                    None if return_code == 0 else f"process exited with code {return_code}"
                ),
            )
            self._event(
                "job_finished",
                job_id=job_id,
                status=status,
                exit_code=return_code,
                elapsed_seconds=state["elapsed_seconds"],
                peak_rss_bytes=state["peak_rss_bytes"],
            )

    def _protect_memory(self) -> None:
        """Soft-stop the fewest useful victims before host OOM is possible."""

        available = available_memory_bytes()
        if self.memory_pressure_active:
            if available >= self.memory_recovery_bytes:
                self.memory_pressure_active = False
                self._event(
                    "memory_pressure_cleared",
                    available_memory_bytes=available,
                    recovery_bytes=self.memory_recovery_bytes,
                )
            elif available >= self.memory_emergency_bytes:
                return
        if available >= self.memory_emergency_bytes:
            return

        self.memory_pressure_active = True
        candidates = [
            self._job_state(job_id)
            for job_id in self.running
            if self._job_state(job_id)["status"] == "running"
        ]
        candidates.sort(
            key=lambda state: (
                int(state.get("rss_bytes", 0)),
                float(state.get("started_at", 0.0)),
            ),
            reverse=True,
        )
        projected_available = available
        victims: list[str] = []
        for state in candidates:
            job_id = str(state["job_id"])
            victims.append(job_id)
            projected_available += int(state.get("rss_bytes", 0))
            self._request_stop(
                job_id,
                "automatic low-memory circuit breaker: "
                f"MemAvailable={available} below emergency="
                f"{self.memory_emergency_bytes}",
            )
            if projected_available >= self.memory_recovery_bytes:
                break
        self._event(
            "memory_pressure_triggered",
            available_memory_bytes=available,
            emergency_bytes=self.memory_emergency_bytes,
            recovery_bytes=self.memory_recovery_bytes,
            projected_available_bytes=projected_available,
            victims=victims,
        )

    def _mark_blocked(self) -> None:
        by_id = {job["job_id"]: job for job in self.state["jobs"]}
        for state in self.state["jobs"]:
            if state["status"] != "queued":
                continue
            dependencies = [by_id[dependency] for dependency in state["dependencies"]]
            failed = [
                dependency["job_id"]
                for dependency in dependencies
                if dependency["status"] in {"fail", "stopped", "blocked"}
            ]
            if failed:
                state.update(
                    status="blocked",
                    reason=f"dependency did not pass: {', '.join(failed)}",
                    updated_at=time.time(),
                )
                self._event("job_blocked", job_id=state["job_id"], dependencies=failed)

    def _launch_ready(self) -> None:
        if self.stop_requested or self.memory_pressure_active:
            return
        by_id = {job["job_id"]: job for job in self.state["jobs"]}
        running_large = sum(
            self.spec_by_id[job_id].resource_class == "large"
            for job_id in self.running
        )
        candidates = sorted(
            (
                spec
                for spec in self.specs
                if by_id[spec.job_id]["status"] == "queued"
                and all(by_id[dependency]["status"] == "pass" for dependency in spec.dependencies)
            ),
            key=lambda spec: (spec.priority, spec.estimated_rss_bytes, spec.job_id),
        )
        startup_commitment = sum(
            max(
                0,
                self.spec_by_id[job_id].estimated_rss_bytes
                - int(self._job_state(job_id).get("rss_bytes", 0)),
            )
            for job_id in self.running
        )
        starts = 0
        for spec in candidates:
            if len(self.running) >= self.jobs_limit:
                break
            if starts >= self.max_starts_per_sample:
                break
            if self.pin_cpus and self._free_cpu() is None:
                break
            if spec.resource_class == "large" and running_large >= self.large_jobs_limit:
                continue
            available = available_memory_bytes()
            if (
                available
                - startup_commitment
                - spec.estimated_rss_bytes
                < self.memory_reserve_bytes
            ):
                state = by_id[spec.job_id]
                state["waiting_reason"] = (
                    "memory_reserve: available="
                    f"{available} startup_commitment={startup_commitment} "
                    f"estimated={spec.estimated_rss_bytes} "
                    f"reserve={self.memory_reserve_bytes}"
                )
                continue
            by_id[spec.job_id].pop("waiting_reason", None)
            self._start(spec)
            startup_commitment += spec.estimated_rss_bytes
            starts += 1
            if spec.resource_class == "large":
                running_large += 1

    def _write_state(self) -> None:
        now = time.time()
        statuses: dict[str, int] = {}
        total_rss = 0
        for job in self.state["jobs"]:
            statuses[job["status"]] = statuses.get(job["status"], 0) + 1
            total_rss += int(job.get("rss_bytes", 0))
        self.state["updated_at"] = now
        self.state["host"] = {
            "available_memory_bytes": available_memory_bytes(),
            "campaign_rss_bytes": total_rss,
            "physical_cpus": len(physical_cpu_ids()),
            "memory_pressure_active": self.memory_pressure_active,
            "memory_emergency_bytes": self.memory_emergency_bytes,
            "memory_recovery_bytes": self.memory_recovery_bytes,
        }
        self.state["summary"] = {
            "total": len(self.state["jobs"]),
            "by_status": statuses,
            "running_large": sum(
                self.spec_by_id[job_id].resource_class == "large"
                for job_id in self.running
            ),
        }
        atomic_write_json(self.state_path, self.state)

    def run(self) -> bool:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._event(
            "campaign_started",
            campaign_id=self.manifest["campaign_id"],
            manifest_sha256=self.manifest_sha256,
            launcher_pid=os.getpid(),
        )
        self._write_state()
        try:
            while True:
                self._read_controls()
                self._poll_running()
                self._protect_memory()
                self._mark_blocked()
                self._launch_ready()
                self._write_state()
                if not self.running and all(
                    job["status"] in TERMINAL_STATUSES for job in self.state["jobs"]
                ):
                    break
                time.sleep(self.sample_seconds)
        except KeyboardInterrupt:
            self.stop_requested = True
            for job_id in list(self.running):
                self._request_stop(job_id, "launcher interrupted")
            while self.running:
                self._poll_running()
                self._write_state()
                time.sleep(min(self.sample_seconds, 0.2))
        statuses = {job["status"] for job in self.state["jobs"]}
        success = statuses <= {"pass"}
        self.state["status"] = "pass" if success else "incomplete"
        self.state["finished_at"] = time.time()
        self._write_state()
        self._event("campaign_finished", status=self.state["status"])
        return success


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(amount) < 1024.0 or unit == "TiB":
            return f"{amount:.1f}{unit}"
        amount /= 1024.0
    return "-"


def progress_bar(completed: float, total: float, width: int = 18) -> str:
    if total <= 0:
        return "[" + "?" * width + "]"
    fraction = min(1.0, max(0.0, completed / total))
    filled = int(round(fraction * width))
    return "[" + "#" * filled + "." * (width - filled) + f"] {fraction:6.1%}"


def render_campaign_state(state: Mapping[str, Any], *, max_rows: int = 24) -> str:
    jobs = list(state.get("jobs", []))
    summary = state.get("summary", {})
    by_status = summary.get("by_status", {})
    terminal = sum(int(by_status.get(status, 0)) for status in TERMINAL_STATUSES)
    total = int(summary.get("total", len(jobs)))
    lines = [
        f"Campaign: {state.get('campaign_id', '-')}  status={state.get('status', '-')}",
        f"Overall  {progress_bar(terminal, total)}  "
        f"pass={by_status.get('pass', 0)} run={by_status.get('running', 0)} "
        f"queue={by_status.get('queued', 0)} fail={by_status.get('fail', 0)} "
        f"stop={by_status.get('stopped', 0)} block={by_status.get('blocked', 0)}",
        "Memory   available="
        + format_bytes(state.get("host", {}).get("available_memory_bytes"))
        + " campaign_rss="
        + format_bytes(state.get("host", {}).get("campaign_rss_bytes")),
        "",
        "STATUS    DATASET        ALGORITHM                    SYSTEM               ELAPSED     RSS  PROGRESS",
    ]
    order = {"running": 0, "stopping": 1, "fail": 2, "stopped": 3, "queued": 4, "blocked": 5, "pass": 6}
    jobs.sort(key=lambda job: (order.get(str(job.get("status")), 9), str(job.get("job_id"))))
    visible = jobs[:max_rows]
    for job in visible:
        progress = job.get("progress") or {}
        completed = progress.get("completed")
        total_work = progress.get("total")
        if isinstance(completed, (int, float)) and isinstance(total_work, (int, float)):
            progress_text = progress_bar(float(completed), float(total_work), width=10)
        else:
            progress_text = str(progress.get("phase", "-"))
        iteration = progress.get("iteration")
        if iteration is not None:
            progress_text += f" it={iteration}"
        eta = progress.get("eta_seconds")
        if isinstance(eta, (int, float)):
            progress_text += f" eta={format_duration(eta)}"
        simulated_cycles = progress.get("simulated_cycles")
        if isinstance(simulated_cycles, (int, float)):
            progress_text += f" cyc={int(simulated_cycles):,}"
        backend_requests = progress.get("backend_requests")
        if isinstance(backend_requests, (int, float)):
            progress_text += f" mem={int(backend_requests):,}"
        if job.get("no_progress_warning"):
            progress_text += (
                " NO-PROGRESS=" + format_duration(job.get("no_progress_seconds"))
            )
        elif job.get("waiting_reason"):
            progress_text = "waiting for memory reserve"
        lines.append(
            f"{str(job.get('status', '-'))[:8]:8}  "
            f"{str(job.get('dataset_id', '-'))[:14]:14} "
            f"{str(job.get('algorithm', '-'))[:28]:28} "
            f"{str(job.get('system', '-'))[:20]:20} "
            f"{format_duration(job.get('elapsed_seconds')):>8} "
            f"{format_bytes(job.get('rss_bytes')):>8}  {progress_text}"
        )
    if len(jobs) > len(visible):
        lines.append(f"... {len(jobs) - len(visible)} additional jobs hidden")
    lines.extend(
        [
            "",
            "Stop one: python3 scripts/control_large_graph_campaign.py --run-dir <DIR> stop <JOB_ID> --reason '<TEXT>'",
            "Stop all: python3 scripts/control_large_graph_campaign.py --run-dir <DIR> stop-all --reason '<TEXT>'",
        ]
    )
    return "\n".join(lines)


def write_control_request(
    run_dir: Path,
    *,
    action: str,
    job_id: str | None,
    reason: str,
) -> Path:
    if action not in {"stop_job", "stop_all"}:
        raise ValueError("unsupported campaign control action")
    if action == "stop_job" and (
        job_id is None or not JOB_ID_PATTERN.fullmatch(job_id)
    ):
        raise ValueError("stop_job requires a valid job ID")
    control_dir = run_dir.resolve() / "control"
    control_dir.mkdir(parents=True, exist_ok=True)
    suffix = job_id if job_id is not None else "all"
    path = control_dir / f"{int(time.time() * 1_000_000)}_{suffix}.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "action": action,
            "job_id": job_id,
            "reason": reason,
            "requested_at": time.time(),
            "requester_pid": os.getpid(),
        },
    )
    return path
