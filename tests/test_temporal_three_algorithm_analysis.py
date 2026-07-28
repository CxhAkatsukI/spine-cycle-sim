from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.temporal_three_algorithm_analysis import (
    ALGORITHM_LABELS,
    EXPANDED_BATCHES,
    PAPER_SCALE_BATCHES,
    _expanded_paper_tables,
    _paper_tables,
    _paper_scale_tables,
    _validate_grasu_physical_manifest,
    _write_csv,
)
from spine_cycle_sim.experiments.grasu_addressing import (
    FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
)


class TemporalThreeAlgorithmAnalysisTest(unittest.TestCase):
    def _physical_manifest(self, root: Path) -> Path:
        profile_id = "grasu_regraph_candidate10_k1_multipart_weighted_v4"
        profile_path = root / "profile.json"
        profile = {
            "profile_id": profile_id,
            "memory": {"channels": 32, "channel_capacity_bytes": 512 << 20},
            "parameters": {
                **FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
                "physical_address_map_id": "candidate10_hbm_pc_nonalias_v1",
            },
        }
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        digest = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        bases = {
            "update": "grasu_update_base_bytes",
            "binary": "grasu_binary_base_bytes",
            "row": "grasu_row_offset_base_bytes",
            "pma": "grasu_pma_base_bytes",
            "source_state": "grasu_source_state_base_bytes",
            "vertex_state": "grasu_vertex_state_base_bytes",
            "degree": "grasu_degree_base_bytes",
        }
        manifest = {
            "profile": str(profile_path),
            "profile_sha256": digest,
            "physical_hbm_address_regions": {
                name: {
                    "base_bytes": profile["parameters"][parameter],
                    "size_bytes": 64,
                    "end_bytes": profile["parameters"][parameter] + 64,
                    "channels": [30] if name in {"vertex_state", "degree"} else [0],
                }
                for name, parameter in bases.items()
            },
        }
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run_dir

    def test_physical_hbm_manifest_accepts_frozen_nonalias_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._physical_manifest(Path(temporary))
            result = _validate_grasu_physical_manifest(
                run_dir, "grasu_regraph_candidate10_k1_multipart_weighted_v4"
            )
            self.assertEqual(result["regions"], 7)

    def test_physical_hbm_manifest_rejects_shared_channel_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._physical_manifest(Path(temporary))
            manifest_path = run_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            update = manifest["physical_hbm_address_regions"]["update"]
            update["size_bytes"] = (64 << 20) + 64
            update["end_bytes"] = (64 << 20) + 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overlap on a shared channel"):
                _validate_grasu_physical_manifest(
                    run_dir, "grasu_regraph_candidate10_k1_multipart_weighted_v4"
                )

    def test_physical_hbm_manifest_rejects_profile_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self._physical_manifest(Path(temporary))
            manifest = json.loads((run_dir / "manifest.json").read_text())
            Path(manifest["profile"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "profile hash mismatch"):
                _validate_grasu_physical_manifest(
                    run_dir, "grasu_regraph_candidate10_k1_multipart_weighted_v4"
                )

    def test_paper_scale_tables_require_three_algorithms_and_batches(self) -> None:
        pairs = [
            {
                "algorithm": algorithm,
                "batch_size": batch,
                "dataset_id": "sx_askubuntu",
                "spine_e2e_ms": float(batch),
                "grasu_e2e_ms": float(2 * batch),
                "cross_system_correct": True,
            }
            for algorithm in ALGORITHM_LABELS
            for batch in PAPER_SCALE_BATCHES
        ]
        correctness, batches = _paper_scale_tables(pairs)
        self.assertEqual([row["real_pairs"] for row in correctness], [3, 3, 3])
        self.assertEqual(len(batches), 9)
        self.assertTrue(all(row["spine_speedup"] == 2.0 for row in batches))

        pairs[-1]["cross_system_correct"] = False
        with self.assertRaisesRegex(ValueError, "correctness is incomplete"):
            _paper_scale_tables(pairs)

    def test_csv_writer_uses_union_of_heterogeneous_row_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "rows.csv"
            _write_csv(
                output,
                [
                    {"run_id": "legacy", "cycles": 10},
                    {"run_id": "physical", "cycles": 20, "dram_reads": 3},
                ],
            )
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(list(rows[0]), ["run_id", "cycles", "dram_reads"])
            self.assertEqual(rows[0]["dram_reads"], "")
            self.assertEqual(rows[1]["dram_reads"], "3")

    def test_expanded_tables_require_three_by_three_by_five(self) -> None:
        pairs = [
            {
                "algorithm": algorithm,
                "batch_size": batch,
                "spine_e2e_ms": 4.0,
                "grasu_e2e_ms": 2.0,
                "cross_system_correct": True,
            }
            for algorithm in ALGORITHM_LABELS
            for batch in EXPANDED_BATCHES
            for _ in range(5)
        ]
        correctness, batches = _expanded_paper_tables(pairs)
        self.assertEqual([row["real_pairs"] for row in correctness], [15, 15, 15])
        self.assertEqual(len(batches), 9)
        self.assertEqual(
            [row["algorithm_index"] for row in batches],
            [0, 0, 0, 1, 1, 1, 2, 2, 2],
        )
        self.assertTrue(all(row["spine_speedup"] == 0.5 for row in batches))

        pairs[-1]["cross_system_correct"] = False
        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _expanded_paper_tables(pairs)

    def test_paper_tables_require_complete_cross_product(self) -> None:
        abbreviations = {f"d{index}": f"D{index}" for index in range(5)}
        pairs = [
            {
                "dataset_id": dataset,
                "algorithm": algorithm,
                "spine_e2e_ms": 2.0,
                "grasu_e2e_ms": 4.0,
                "spine_speedup": 2.0,
                "cross_system_correct": True,
            }
            for dataset in abbreviations
            for algorithm in ALGORITHM_LABELS
        ]
        correctness, algorithms, datasets = _paper_tables(pairs, abbreviations)
        self.assertEqual([row["real_pairs"] for row in correctness], [5, 5, 5])
        self.assertEqual([row["spine_speedup"] for row in algorithms], [2.0] * 3)
        self.assertEqual(len(datasets), 5)

        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _paper_tables(pairs[:-1], abbreviations)

    def test_paper_tables_fail_on_incorrect_pair(self) -> None:
        abbreviations = {f"d{index}": f"D{index}" for index in range(5)}
        pairs = [
            {
                "dataset_id": dataset,
                "algorithm": algorithm,
                "spine_e2e_ms": 2.0,
                "grasu_e2e_ms": 4.0,
                "spine_speedup": 2.0,
                "cross_system_correct": not (
                    dataset == "d0" and algorithm == "weighted_sssp"
                ),
            }
            for dataset in abbreviations
            for algorithm in ALGORITHM_LABELS
        ]
        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _paper_tables(pairs, abbreviations)
