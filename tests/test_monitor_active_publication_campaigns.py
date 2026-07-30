from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "scripts" / "monitor_active_publication_campaigns.sh"


class ActivePublicationMonitorTests(unittest.TestCase):
    def test_resolves_reused_cross_campaign_and_capacity_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = root / "formal_v3_r19_k4_priority"
            state_dir = campaign / "run"
            state_dir.mkdir(parents=True)
            jobs = [
                {
                    "job_id": (
                        "run.fixture.weighted.insert.u8.spine."
                        f"{execution_id}"
                    ),
                    "status": "fail",
                }
                for execution_id in (
                    "reused-id",
                    "recovered-id",
                    "capacity-id",
                    "unresolved-id",
                )
            ]
            (state_dir / "campaign_state.json").write_text(
                json.dumps(
                    {
                        "status": "incomplete",
                        "summary": {"by_status": {"fail": 4}},
                        "jobs": jobs,
                        "host": {},
                    }
                )
            )

            reused = campaign / "runs" / "reused-id"
            reused.mkdir(parents=True)
            (reused / "case_result.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "admission": {"reused_child": True},
                    }
                )
            )

            recovered = (
                root / "formal_v3_r19_cc_guard" / "runs" / "recovered-id"
            )
            recovered.mkdir(parents=True)
            (recovered / "case_result.json").write_text(
                json.dumps({"status": "pass"})
            )

            admission = root / "capacity_admission" / "campaign_manifest.json"
            admission.parent.mkdir(parents=True)
            admission.write_text(
                json.dumps(
                    {"capacity_exclusions": [{"execution_id": "capacity-id"}]}
                )
            )

            env = dict(os.environ)
            env["SPINE_CAMPAIGN_ROOT"] = str(root)
            completed = subprocess.run(
                [str(MONITOR), "--once"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            line = next(
                row
                for row in completed.stdout.splitlines()
                if row.startswith("formal_v3_r19_k4_priority")
            )
            self.assertIn("reused=1", line)
            self.assertIn("recovered=1", line)
            self.assertIn("capacity=1", line)
            self.assertIn("unresolved_fail=1", line)


if __name__ == "__main__":
    unittest.main()
