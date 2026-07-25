from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.real_small_batches import (
    HLS_FIXED_SSSP_ROUNDS,
    REAL_BATCH_SIZE,
    apply_explicit_weighted_updates,
    build_real_small_batch_manifest,
    build_real_small_batches,
    sssp_convergence_rounds,
    validate_real_small_batch_manifest,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]
SHARED_MANIFEST = (
    ROOT / "configs" / "experiments" / "shared_comparison_workloads_20260725.json"
)
FROZEN_MANIFEST = (
    ROOT / "configs" / "experiments" / "hls_weighted_real_small_batches_20260726.json"
)


class RealSmallBatchTests(unittest.TestCase):
    def _real_graphs(self) -> list[tuple[str, Path]]:
        manifest = json.loads(SHARED_MANIFEST.read_text(encoding="utf-8"))
        return [
            (fixture["dataset_id"], ROOT / fixture["graph"]["path"])
            for fixture in manifest["fixtures"]
            if fixture["dataset_kind"] == "real_compact_slice"
        ]

    def test_each_dataset_has_three_eight_mutation_batches(self) -> None:
        for dataset_id, graph_path in self._real_graphs():
            batches = build_real_small_batches(dataset_id, load_slice(graph_path))
            self.assertEqual(
                {batch.scenario for batch in batches},
                {"insert", "delete", "weight_change"},
            )
            self.assertTrue(
                all(batch.user_mutations == REAL_BATCH_SIZE for batch in batches)
            )
            self.assertEqual(
                {batch.scenario: batch.physical_records for batch in batches},
                {"insert": 8, "delete": 8, "weight_change": 16},
            )

    def test_every_final_graph_is_exact_within_four_rounds(self) -> None:
        for dataset_id, graph_path in self._real_graphs():
            graph = load_slice(graph_path)
            for batch in build_real_small_batches(dataset_id, graph):
                with self.subTest(dataset=dataset_id, scenario=batch.scenario):
                    final_graph = apply_explicit_weighted_updates(graph, batch.update)
                    self.assertEqual(len(final_graph.records), batch.final_edges)
                    self.assertEqual(
                        sssp_convergence_rounds(final_graph),
                        batch.convergence_rounds,
                    )
                    self.assertLessEqual(
                        batch.convergence_rounds, HLS_FIXED_SSSP_ROUNDS
                    )

    def test_weight_changes_are_ordered_exact_delete_then_insert(self) -> None:
        for dataset_id, graph_path in self._real_graphs():
            batch = next(
                batch
                for batch in build_real_small_batches(dataset_id, load_slice(graph_path))
                if batch.scenario == "weight_change"
            )
            self.assertEqual(
                [(record.src, record.dst) for record in batch.update.records],
                sorted((record.src, record.dst) for record in batch.update.records),
            )
            for offset in range(0, len(batch.update.records), 2):
                deletion, insertion = batch.update.records[offset : offset + 2]
                self.assertEqual(deletion.diff, -1)
                self.assertEqual(insertion.diff, 1)
                self.assertEqual(
                    (deletion.src, deletion.dst),
                    (insertion.src, insertion.dst),
                )
                self.assertNotEqual(deletion.weight, insertion.weight)

    def test_frozen_manifest_validates(self) -> None:
        manifest = validate_real_small_batch_manifest(ROOT, FROZEN_MANIFEST)
        self.assertEqual(len(manifest["runs"]), 9)

    def test_regeneration_is_byte_identical(self) -> None:
        frozen = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            temporary_root = Path(temporary)
            output_dir = temporary_root / "workloads"
            manifest_path = temporary_root / "manifest.json"
            generated = build_real_small_batch_manifest(
                ROOT,
                shared_manifest_path=SHARED_MANIFEST,
                output_dir=output_dir,
                manifest_path=manifest_path,
            )
            self.assertEqual(
                [
                    (run["run_id"], run["user_mutations"], run["physical_records"])
                    for run in generated["runs"]
                ],
                [
                    (run["run_id"], run["user_mutations"], run["physical_records"])
                    for run in frozen["runs"]
                ],
            )
            for generated_run, frozen_run in zip(generated["runs"], frozen["runs"]):
                generated_path = ROOT / generated_run["update"]["path"]
                frozen_path = ROOT / frozen_run["update"]["path"]
                self.assertEqual(generated_path.read_bytes(), frozen_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
