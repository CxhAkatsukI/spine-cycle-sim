from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import (
    CampaignRunner,
    physical_cpu_ids,
    render_campaign_state,
    validate_campaign_manifest,
    write_control_request,
)


class CampaignRuntimeTest(unittest.TestCase):
    def test_physical_cpu_ids_choose_the_lowest_sibling_per_core(self) -> None:
        cpus = physical_cpu_ids()
        self.assertEqual(cpus, sorted(cpus))
        self.assertEqual(len(cpus), len(set(cpus)))
        if Path("/sys/devices/system/cpu/cpu0").exists():
            self.assertEqual(cpus[0], 0)

    def test_runner_rejects_cpu_offset_outside_pool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "cpu_offset_test",
                        "jobs": [{"job_id": "only", "command": ["true"]}],
                    }
                ),
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "cpu_offset"):
                CampaignRunner(
                    manifest_path,
                    root / "run",
                    jobs=1,
                    large_jobs=1,
                    memory_reserve_bytes=0,
                    sample_seconds=1.0,
                    pin_cpus=True,
                    resume=False,
                    cpu_offset=len(physical_cpu_ids()),
                )

    def test_manifest_rejects_dependency_cycle(self) -> None:
        manifest = {
            "schema_version": 1,
            "campaign_id": "cycle",
            "jobs": [
                {"job_id": "a", "command": ["true"], "dependencies": ["b"]},
                {"job_id": "b", "command": ["true"], "dependencies": ["a"]},
            ],
        }
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_campaign_manifest(manifest)

    def test_runner_records_progress_dependencies_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            run_dir = root / "run"
            progress_program = (
                "import json,os,pathlib; "
                "path=pathlib.Path(os.environ['SPINE_CAMPAIGN_PROGRESS_PATH']); "
                "path.write_text(json.dumps({'phase':'simulate','completed':4,"
                "'total':4,'iteration':2,'eta_seconds':0,"
                "'simulated_cycles':123456,'backend_requests':789}), "
                "encoding='ascii')"
            )
            manifest = {
                "schema_version": 1,
                "campaign_id": "runtime_test",
                "default_cwd": str(root),
                "jobs": [
                    {
                        "job_id": "prepare",
                        "command": [sys.executable, "-c", progress_program],
                        "dataset_id": "tiny",
                        "algorithm": "prepare",
                        "system": "host",
                        "tier": "prepare",
                        "estimated_rss_gib": 0.01,
                    },
                    {
                        "job_id": "simulate",
                        "command": [sys.executable, "-c", progress_program],
                        "dataset_id": "tiny",
                        "algorithm": "weighted_sssp",
                        "system": "spine",
                        "tier": "main",
                        "resource_class": "large",
                        "estimated_rss_gib": 0.01,
                        "dependencies": ["prepare"],
                    },
                ],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="ascii")
            runner = CampaignRunner(
                manifest_path,
                run_dir,
                jobs=2,
                large_jobs=1,
                memory_reserve_bytes=0,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=False,
                no_progress_warn_seconds=10.0,
            )
            self.assertTrue(runner.run())

            state = json.loads((run_dir / "campaign_state.json").read_text())
            self.assertEqual(state["status"], "pass")
            self.assertEqual(state["summary"]["by_status"], {"pass": 2})
            self.assertEqual(state["jobs"][1]["progress"]["completed"], 4)
            rendered = render_campaign_state(state)
            self.assertIn("100.0%", rendered)
            self.assertIn("ETA", rendered)
            self.assertIn("00:00", rendered)
            self.assertIn("cyc=123,456", rendered)
            self.assertIn("mem=789", rendered)
            events = (run_dir / "events.jsonl").read_text()
            self.assertLess(events.index('"job_id": "prepare"'), events.index('"job_id": "simulate"'))

            resumed = CampaignRunner(
                manifest_path,
                run_dir,
                jobs=1,
                large_jobs=1,
                memory_reserve_bytes=0,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=True,
            )
            self.assertTrue(resumed.run())
            resumed_state = json.loads((run_dir / "campaign_state.json").read_text())
            self.assertEqual([job["attempt"] for job in resumed_state["jobs"]], [1, 1])

    def test_monitor_derives_eta_only_for_bounded_progress(self) -> None:
        state = {
            "campaign_id": "eta",
            "status": "running",
            "summary": {"total": 1, "by_status": {"running": 1}},
            "host": {},
            "jobs": [
                {
                    "job_id": "bounded",
                    "status": "running",
                    "dataset_id": "tiny",
                    "algorithm": "full_pagerank",
                    "system": "spine",
                    "elapsed_seconds": 90,
                    "rss_bytes": 0,
                    "progress": {"phase": "compute", "completed": 1, "total": 4},
                }
            ],
        }
        rendered = render_campaign_state(state)
        self.assertIn("04:30", rendered)

    def test_monitor_distinguishes_stale_heartbeat_from_idle_process(self) -> None:
        state = {
            "campaign_id": "heartbeat",
            "status": "running",
            "summary": {"total": 1, "by_status": {"running": 1}},
            "host": {},
            "jobs": [
                {
                    "job_id": "long_round",
                    "status": "running",
                    "dataset_id": "large",
                    "algorithm": "weighted_sssp",
                    "system": "spine",
                    "elapsed_seconds": 3600,
                    "cpu_seconds": 3590,
                    "rss_bytes": 1024,
                    "no_progress_warning": True,
                    "no_progress_seconds": 1800,
                    "progress": {"phase": "compute", "simulated_cycles": 10},
                }
            ],
        }
        active = render_campaign_state(state)
        self.assertIn("HEARTBEAT-STALE=30:00 CPU=100%", active)
        self.assertNotIn("NO-PROGRESS", active)

        state["jobs"][0]["cpu_seconds"] = 10
        idle = render_campaign_state(state)
        self.assertIn("NO-PROGRESS=30:00 CPU=0%", idle)
        self.assertNotIn("HEARTBEAT-STALE", idle)

    def test_control_request_is_atomic_and_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            path = write_control_request(
                run_dir,
                action="stop_job",
                job_id="dataset.algorithm.system",
                reason="manual progress review",
            )
            payload = json.loads(path.read_text())
            self.assertEqual(payload["action"], "stop_job")
            self.assertEqual(payload["job_id"], "dataset.algorithm.system")
            self.assertEqual(payload["reason"], "manual progress review")

    def test_memory_pressure_soft_stops_largest_process_and_is_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "memory_pressure_test",
                        "default_cwd": str(root),
                        "jobs": [
                            {
                                "job_id": "sleeper",
                                "command": [sys.executable, "-c", "import time; time.sleep(60)"],
                                "estimated_rss_gib": 0.01,
                            }
                        ],
                    }
                ),
                encoding="ascii",
            )
            runner = CampaignRunner(
                manifest_path,
                root / "run",
                jobs=1,
                large_jobs=1,
                memory_reserve_bytes=100,
                memory_emergency_bytes=100,
                memory_recovery_bytes=100,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=False,
            )
            runner._start(runner.specs[0])
            with patch(
                "spine_cycle_sim.experiments.campaign_runtime.available_memory_bytes",
                return_value=0,
            ):
                runner._poll_running()
                runner._protect_memory()
            state = runner._job_state("sleeper")
            self.assertEqual(state["status"], "stopping")
            self.assertTrue(runner.memory_pressure_active)
            self.assertIn("automatic low-memory", state["reason"])
            while runner.running:
                runner._poll_running()
                time.sleep(0.01)
            self.assertEqual(state["status"], "stopped")
            self.assertEqual(state["rss_bytes"], 0)

    def test_start_removes_stale_progress_from_prior_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "stale_progress_test",
                        "jobs": [
                            {
                                "job_id": "sleeper",
                                "command": [
                                    sys.executable,
                                    "-c",
                                    "import time; time.sleep(60)",
                                ],
                            }
                        ],
                    }
                ),
                encoding="ascii",
            )
            stale = run_dir / "jobs" / "sleeper" / "progress.json"
            stale.parent.mkdir(parents=True)
            stale.write_text('{"simulated_cycles":999999}\n', encoding="ascii")
            runner = CampaignRunner(
                manifest_path,
                run_dir,
                jobs=1,
                large_jobs=1,
                memory_reserve_bytes=0,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=False,
            )
            runner._start(runner.specs[0])
            self.assertFalse(stale.exists())
            runner._request_stop("sleeper", "test cleanup")
            while runner.running:
                runner._poll_running()
                time.sleep(0.01)

    def test_launch_reservation_counts_not_yet_resident_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            jobs = [
                {
                    "job_id": f"job{index}",
                    "command": [sys.executable, "-c", "import time; time.sleep(60)"],
                    "estimated_rss_gib": 1.0,
                }
                for index in range(3)
            ]
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "launch_reservation_test",
                        "default_cwd": str(root),
                        "jobs": jobs,
                    }
                ),
                encoding="ascii",
            )
            runner = CampaignRunner(
                manifest_path,
                root / "run",
                jobs=3,
                large_jobs=1,
                memory_reserve_bytes=1 << 30,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=False,
                max_starts_per_sample=3,
            )
            with patch(
                "spine_cycle_sim.experiments.campaign_runtime.available_memory_bytes",
                return_value=3 << 30,
            ):
                runner._launch_ready()
            self.assertEqual(len(runner.running), 2)
            for job_id in list(runner.running):
                runner._request_stop(job_id, "test cleanup")
            while runner.running:
                runner._poll_running()
                time.sleep(0.01)

    def test_host_reservation_blocks_a_second_campaign_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reservation_path = root / "host-reservations.json"

            def make_runner(name: str) -> CampaignRunner:
                manifest_path = root / f"{name}.json"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "campaign_id": name,
                            "jobs": [
                                {
                                    "job_id": name,
                                    "command": [
                                        sys.executable,
                                        "-c",
                                        "import time; time.sleep(60)",
                                    ],
                                    "estimated_rss_gib": 1.0,
                                }
                            ],
                        }
                    ),
                    encoding="ascii",
                )
                return CampaignRunner(
                    manifest_path,
                    root / f"run-{name}",
                    jobs=1,
                    large_jobs=1,
                    memory_reserve_bytes=1 << 30,
                    sample_seconds=0.01,
                    pin_cpus=False,
                    resume=False,
                    host_reservation_path=reservation_path,
                )

            first = make_runner("first")
            second = make_runner("second")
            available = int(2.5 * 2**30)
            with patch(
                "spine_cycle_sim.experiments.campaign_runtime.available_memory_bytes",
                return_value=available,
            ):
                first._launch_ready()
                second._launch_ready()
            self.assertEqual(set(first.running), {"first"})
            self.assertFalse(second.running)
            self.assertIn(
                "host_startup_commitment",
                second._job_state("second")["waiting_reason"],
            )

            first._request_stop("first", "test cleanup")
            while first.running:
                first._poll_running()
                time.sleep(0.01)
            with patch(
                "spine_cycle_sim.experiments.campaign_runtime.available_memory_bytes",
                return_value=available,
            ):
                second._launch_ready()
            self.assertEqual(set(second.running), {"second"})
            second._request_stop("second", "test cleanup")
            while second.running:
                second._poll_running()
                time.sleep(0.01)

    def test_host_reservation_ledger_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            reservation_path = root / "host-reservations.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "corrupt_reservation_test",
                        "jobs": [{"job_id": "only", "command": ["true"]}],
                    }
                ),
                encoding="ascii",
            )
            reservation_path.write_text("{", encoding="ascii")
            runner = CampaignRunner(
                manifest_path,
                root / "run",
                jobs=1,
                large_jobs=1,
                memory_reserve_bytes=0,
                sample_seconds=0.01,
                pin_cpus=False,
                resume=False,
                host_reservation_path=reservation_path,
            )
            with self.assertRaisesRegex(RuntimeError, "invalid host reservation ledger"):
                runner._launch_ready()
            self.assertFalse(runner.running)

    def test_host_reservation_lock_serializes_independent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reservation_path = root / "host-reservations.json"
            marker_path = root / "holder-ready"
            observed_path = root / "observed"
            holder_program = "\n".join(
                (
                    "import os, pathlib, time",
                    "from spine_cycle_sim.experiments.campaign_runtime import "
                    "locked_host_reservations, process_identity",
                    f"path = pathlib.Path({str(reservation_path)!r})",
                    f"marker = pathlib.Path({str(marker_path)!r})",
                    "with locked_host_reservations(path) as reservations:",
                    "    process_group, start_ticks = process_identity(os.getpid())",
                    "    reservations.append({",
                    "        'run_dir': 'holder', 'job_id': 'holder',",
                    "        'process': os.getpid(), 'process_group': process_group,",
                    "        'start_ticks': start_ticks, 'estimated_rss_bytes': 1,",
                    "    })",
                    "    marker.write_text('ready', encoding='ascii')",
                    "    time.sleep(0.5)",
                    "time.sleep(0.5)",
                )
            )
            observer_program = "\n".join(
                (
                    "import pathlib",
                    "from spine_cycle_sim.experiments.campaign_runtime import "
                    "locked_host_reservations",
                    f"path = pathlib.Path({str(reservation_path)!r})",
                    f"observed = pathlib.Path({str(observed_path)!r})",
                    "with locked_host_reservations(path) as reservations:",
                    "    observed.write_text(str(len(reservations)), encoding='ascii')",
                )
            )
            holder = subprocess.Popen([sys.executable, "-c", holder_program])
            try:
                deadline = time.monotonic() + 5.0
                while not marker_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker_path.exists())
                observer = subprocess.run(
                    [sys.executable, "-c", observer_program],
                    check=False,
                    timeout=5.0,
                )
                self.assertEqual(observer.returncode, 0)
                self.assertEqual(observed_path.read_text(encoding="ascii"), "1")
            finally:
                holder.terminate()
                holder.wait(timeout=5.0)


if __name__ == "__main__":
    unittest.main()
