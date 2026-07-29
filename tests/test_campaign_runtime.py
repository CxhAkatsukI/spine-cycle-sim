from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import (
    CampaignRunner,
    render_campaign_state,
    validate_campaign_manifest,
    write_control_request,
)


class CampaignRuntimeTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
