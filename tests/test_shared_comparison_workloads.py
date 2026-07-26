from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.shared_workloads import (
    SliceGraph,
    SliceRecord,
    _materialize_update,
    extract_compact_real_slice,
    load_slice,
    synthetic_fixtures,
    validate_shared_comparison_manifest,
    write_slice,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT
    / "configs"
    / "experiments"
    / "shared_comparison_candidate10_v2_20260726.json"
)


class SharedComparisonWorkloadTests(unittest.TestCase):
    def test_frozen_manifest_meets_count_disjointness_and_algorithm_gates(self) -> None:
        manifest = validate_shared_comparison_manifest(ROOT, MANIFEST)
        self.assertEqual(manifest["counts"]["synthetic_fixtures"], 20)
        self.assertEqual(manifest["counts"]["real_datasets"], 3)
        self.assertEqual(manifest["counts"]["run_cases"], 73)
        self.assertEqual(
            {source["dataset_id"] for source in manifest["real_sources"]},
            {"amazon_2008", "web_google", "soc_flickr_und"},
        )

    def test_synthetic_generation_is_deterministic_and_unique(self) -> None:
        first = synthetic_fixtures()
        second = synthetic_fixtures()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        payloads = {
            hashlib.sha256(
                repr((item.graph.vertices, item.graph.records)).encode("ascii")
            ).hexdigest()
            for item in first
        }
        self.assertEqual(len(payloads), 20)

    def test_slice_round_trip_preserves_empty_and_weighted_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case.slice"
            graph = SliceGraph(
                "round_trip",
                7,
                (SliceRecord(0, 1, 9, 1), SliceRecord(2, 4, 3, -1)),
            )
            write_slice(path, graph)
            loaded = load_slice(path)
        self.assertEqual(loaded, graph)

    def test_dynamic_updates_are_legal_and_cover_required_paths(self) -> None:
        dynamic = [item for item in synthetic_fixtures() if item.dynamic_update]
        self.assertEqual(
            {item.dynamic_path for item in dynamic},
            {
                "incremental_insert",
                "full_rebuild_delete",
                "full_rebuild_increase",
                "full_rebuild_mixed",
            },
        )
        for item in dynamic:
            assert item.dynamic_update is not None
            self.assertEqual(
                [(edge.src, edge.dst) for edge in item.dynamic_update.records],
                sorted((edge.src, edge.dst) for edge in item.dynamic_update.records),
            )
            final = _materialize_update(item.graph, item.dynamic_update)
            self.assertTrue(any(count > 0 for count in final.values()))

    def test_real_extraction_is_order_stable_and_compacts_ids(self) -> None:
        content = "\n".join(
            [
                "%%MatrixMarket matrix coordinate pattern general",
                "10 10 9",
                "9 5",
                "2 4",
                "9 3",
                "2 8",
                "7 1",
                "9 2",
                "2 3",
                "7 6",
                "9 8",
            ]
        ) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "graph.mtx"
            source.write_text(content, encoding="ascii")
            graph, mapping, provenance = extract_compact_real_slice(
                "unit", source, source_count=2, edge_limit=5
            )
        self.assertEqual(graph.case_id, "real_unit_compact")
        self.assertEqual(provenance["sssp_source_original_id"], 9)
        self.assertEqual(provenance["sssp_source_local_id"], 0)
        self.assertEqual(len(graph.records), 5)
        self.assertEqual(mapping[0][1], 9)
        self.assertTrue(all(edge.src < graph.vertices for edge in graph.records))
        self.assertTrue(all(edge.dst < graph.vertices for edge in graph.records))

    def test_real_extraction_rejects_malformed_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.mtx"
            source.write_text("1 2\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "dimensions"):
                extract_compact_real_slice("bad", source)

    def test_manifest_hash_tampering_is_fatal(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="ascii"))
        payload["fixtures"][0]["graph"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_shared_comparison_manifest(ROOT, path)

    def test_candidate10_manifest_rejects_profile_lineage_tampering(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="ascii"))
        payload["profiles"][1]["path"] = (
            "configs/architectures/spine_latest_afb8199.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "profile lineage"):
                validate_shared_comparison_manifest(ROOT, path)

    def test_real_extraction_is_byte_deterministic(self) -> None:
        edges = ((1, 2), (1, 3), (2, 3), (3, 4), (3, 5), (5, 1))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "graph.mtx"
            text = "%%MatrixMarket matrix coordinate pattern general\n"
            text += f"8 8 {len(edges)}\n"
            text += "".join(f"{src} {dst}\n" for src, dst in edges)
            source.write_text(text, encoding="ascii")
            first = extract_compact_real_slice(
                "unit", source, source_count=3, edge_limit=5
            )
            second = extract_compact_real_slice(
                "unit", source, source_count=3, edge_limit=5
            )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
