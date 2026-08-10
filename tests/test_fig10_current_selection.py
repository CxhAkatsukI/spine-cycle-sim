from __future__ import annotations

import csv
import tempfile
from pathlib import Path
import unittest

from scripts.render_evaluation_refresh import collect_fig10_rows_from_path


class Fig10CurrentSelectionTests(unittest.TestCase):
    def test_selects_current_model_rows_without_fixed_archived_ids(self) -> None:
        rows = [
            ("zero", "synthetic_cc_zero_net", "connected_components", "zero_net"),
            ("au", "sx_askubuntu", "weighted_sssp", "shallow_insertion"),
            ("su", "sx_superuser", "weighted_sssp", "shallow_insertion"),
            ("wk", "wiki_talk_temporal", "weighted_sssp", "shallow_insertion"),
            ("rq3_trace_carry_l1_e8", "synthetic_trace_carry_l1", "weighted_sssp", "deep_carry"),
            ("rq3_trace_carry_l3_e8", "synthetic_trace_carry_l3", "weighted_sssp", "deep_carry"),
            ("rq3_trace_carry_l5_e8", "synthetic_trace_carry_l5", "weighted_sssp", "deep_carry"),
            (
                "rq3_flickr_residual_correction_u8_eps1e6",
                "soc_flickr_sinkfree_8192e",
                "thresholded_residual_pagerank",
                "pagerank_correction",
            ),
            ("pr_su", "sx_superuser", "thresholded_residual_pagerank", "pagerank_correction"),
            (
                "pr_wk",
                "wiki_talk_temporal",
                "thresholded_residual_pagerank",
                "pagerank_correction",
            ),
            ("delete", "syn_dynamic_delete_fallback", "weighted_sssp", "deletion_fallback"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rq3_latency_rows.csv"
            with path.open("w", encoding="ascii", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=("execution_id", "dataset_id", "algorithm", "case_class"),
                )
                writer.writeheader()
                writer.writerows(
                    {
                        "execution_id": execution_id,
                        "dataset_id": dataset_id,
                        "algorithm": algorithm,
                        "case_class": case_class,
                    }
                    for execution_id, dataset_id, algorithm, case_class in rows
                )

            selected = collect_fig10_rows_from_path(path)

        self.assertEqual(len(selected), 11)
        self.assertEqual(
            [(row["figure_group"], row["figure_tick"]) for row in selected],
            [
                ("ZN", "Syn"),
                ("SI", "AU"),
                ("SI", "SU"),
                ("SI", "WK"),
                ("Carry", "L1"),
                ("Carry", "L3"),
                ("Carry", "L5"),
                ("PR-corr", "FL"),
                ("PR-corr", "SU"),
                ("PR-corr", "WK"),
                ("Del", "Syn"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
