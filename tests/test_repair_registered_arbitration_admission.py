from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.repair_registered_arbitration_admission import (
    EXPECTED_ERROR,
    find_repair_candidates,
)


class RegisteredArbitrationAdmissionRepairTests(unittest.TestCase):
    def _campaign(self, *, error: str = EXPECTED_ERROR, progress: str = "pass") -> Path:
        root = Path(self._temporary.name)
        job_id = "run.graph.weighted_sssp.insert.u8.grasu_regraph_k1.deadbeef"
        job_dir = root / "jobs" / job_id
        job_dir.mkdir(parents=True)
        log_path = job_dir / "stdout.log"
        log_path.write_text(f"Traceback\n{error}\n", encoding="utf-8")
        (root / "campaign_manifest.json").write_text(
            json.dumps(
                {
                    "default_cwd": "/tmp",
                    "jobs": [
                        {
                            "job_id": job_id,
                            "command": ["python3", "/repo/scripts/run_publication_case.py"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "campaign_state.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "job_id": job_id,
                            "status": "fail",
                            "progress": {"status": progress},
                            "log_path": str(log_path),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return root

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_exact_completed_parent_failure_is_selected(self) -> None:
        candidates = find_repair_candidates(self._campaign())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].execution_id, "deadbeef")

    def test_child_failure_or_different_parent_failure_is_not_selected(self) -> None:
        self.assertEqual(
            find_repair_candidates(self._campaign(progress="fail")), ()
        )
        self._temporary.cleanup()
        self._temporary = tempfile.TemporaryDirectory()
        self.assertEqual(
            find_repair_candidates(
                self._campaign(
                    error=(
                        "RuntimeError: publication parent admission failed: "
                        "mathematical_oracle"
                    )
                )
            ),
            (),
        )

    def test_existing_repair_is_idempotently_skipped(self) -> None:
        campaign = self._campaign()
        result = campaign / "runs" / "deadbeef" / "case_result.json"
        result.parent.mkdir(parents=True)
        result.write_text(
            json.dumps(
                {
                    "status": "pass",
                    "admission": {"reused_child": True},
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(find_repair_candidates(campaign), ())


if __name__ == "__main__":
    unittest.main()
