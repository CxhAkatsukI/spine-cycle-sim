from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_evaluation_refresh_alignment import build_audit


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class EvaluationRefreshAlignmentAuditTests(unittest.TestCase):
    def test_archived_figures_keep_audit_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            write_json(provenance / "fig7.json", {"status": "PASS"})
            write_json(
                provenance / "fig8.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            write_json(
                provenance / "fig9.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            write_json(
                provenance / "fig10.json",
                {"status": "INTERIM_ARCHIVED_SIMULATOR_DATA"},
            )
            analysis = root / "analysis"
            write_json(
                analysis / "summary.json",
                {
                    "status": "PARTIAL",
                    "observed_executions": 10,
                    "expected_executions": 18,
                    "missing_execution_ids": ["missing"],
                },
            )
            with (analysis / "pair_rows.csv").open(
                "w", encoding="utf-8", newline=""
            ) as sink:
                writer = csv.DictWriter(
                    sink, fieldnames=["dataset_id", "algorithm"]
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "dataset_id": "sx_askubuntu",
                        "algorithm": "weighted_sssp",
                    }
                )

            audit = build_audit(root, analysis)

        self.assertEqual(audit["status"], "INCOMPLETE")
        self.assertTrue(audit["figures"]["fig7"]["aligned"])
        self.assertFalse(audit["figures"]["fig8"]["aligned"])
        self.assertFalse(audit["figures"]["fig9"]["aligned"])
        self.assertEqual(audit["campaign"]["pair_rows"], 1)
        self.assertFalse(audit["campaign"]["complete_for_fig9"])

    def test_all_pass_campaign_statuses_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance = root / "provenance"
            statuses = {
                "fig7": "PASS",
                "fig8": "PASS_CURRENT_MODEL_DATA",
                "fig9": "PASS_CAMPAIGN_ANALYSIS",
                "fig10": "PASS_CURRENT_MODEL_DATA",
            }
            for figure, status in statuses.items():
                write_json(provenance / f"{figure}.json", {"status": status})
            analysis = root / "analysis"
            write_json(
                analysis / "summary.json",
                {
                    "status": "PASS",
                    "observed_executions": 18,
                    "expected_executions": 18,
                    "missing_execution_ids": [],
                },
            )
            with (analysis / "pair_rows.csv").open(
                "w", encoding="utf-8", newline=""
            ) as sink:
                writer = csv.DictWriter(
                    sink, fieldnames=["dataset_id", "algorithm"]
                )
                writer.writeheader()
                for dataset in ("sx_askubuntu", "sx_superuser", "wiki_talk_temporal"):
                    for algorithm in (
                        "weighted_sssp",
                        "connected_components",
                        "thresholded_residual_pagerank",
                    ):
                        writer.writerow(
                            {"dataset_id": dataset, "algorithm": algorithm}
                        )

            audit = build_audit(root, analysis)

        self.assertEqual(audit["status"], "READY")
        self.assertEqual(audit["campaign"]["pair_rows"], 9)
        self.assertEqual(audit["next_actions"], [])


if __name__ == "__main__":
    unittest.main()
