from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.publication_workloads import (
    PublicationSourceSpec,
    canonical_edge_weight,
    edge_hash_bucket,
    materialize_publication_workload,
    read_slice_metadata_streaming,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice


class PublicationWorkloadTests(unittest.TestCase):
    def _materialize(
        self,
        spec: PublicationSourceSpec,
        output: Path,
        *,
        batches: tuple[int, ...] = (1, 2),
    ) -> dict[str, object]:
        return materialize_publication_workload(
            spec,
            output,
            sort_parallel=1,
            sort_memory="8M",
            batch_sizes=batches,
            pagerank_scales=(1, 2, 4),
            progress_path=output / "progress.json",
        )

    def test_r19_swap_dedup_projection_and_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "r19.txt"
            source.write_text(
                "2 1\n3 1\n3 1\n2 2\n1 3\n", encoding="ascii"
            )
            spec = PublicationSourceSpec(
                dataset_id="rmat_test",
                source_path=source,
                source_encoding="plain_rmat_dst_src",
                declared_vertices=6,
                index_base=1,
                swap_endpoints=True,
                expected_unique_edges=3,
            )
            output = root / "out"
            manifest = self._materialize(spec, output)

            self.assertEqual(manifest["graphs"]["directed"]["records"], 3)
            self.assertEqual(manifest["graphs"]["reciprocal"]["records"], 4)
            self.assertFalse(manifest["graphs"]["same_artifact"])
            graph = load_slice(Path(manifest["graphs"]["directed"]["path"]))
            self.assertEqual(
                Path(manifest["graphs"]["directed"]["path"])
                .read_text(encoding="ascii")
                .splitlines()[0],
                "# spine_real_slice_version=1",
            )
            self.assertEqual(
                [(edge.src, edge.dst) for edge in graph.records],
                [(0, 1), (0, 2), (2, 0)],
            )
            self.assertEqual(
                graph.records[0].weight, canonical_edge_weight(0, 1)
            )
            self.assertEqual(len(manifest["updates"]), 14)
            self.assertFalse((output / ".work").exists())
            progress = json.loads((output / "progress.json").read_text())
            self.assertEqual(progress["status"], "pass")

    def test_temporal_base_boundary_preserves_external_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "temporal.txt.gz"
            with gzip.open(source, "wt", encoding="ascii") as stream:
                stream.write(
                    "0 1 10\n"
                    "0 1 11\n"
                    "1 2 12\n"
                    "2 2 13\n"
                    "2 3 14\n"
                    "3 4 15\n"
                    "4 2 16\n"
                )
            spec = PublicationSourceSpec(
                dataset_id="temporal_test",
                source_path=source,
                source_encoding="gzip_temporal_src_dst_timestamp",
                paper_base_events=4,
            )
            manifest = self._materialize(spec, root / "out")

            self.assertEqual(manifest["normalization"]["raw_records"], 7)
            self.assertEqual(manifest["normalization"]["self_loops_removed"], 1)
            self.assertEqual(manifest["graphs"]["directed"]["records"], 2)
            self.assertEqual(manifest["graphs"]["directed"]["vertices"], 5)
            insert = next(
                row
                for row in manifest["updates"]
                if row["projection"] == "directed"
                and row["scenario"] == "insert"
                and row["user_mutations"] == 2
            )
            update = load_slice(Path(insert["path"]))
            self.assertEqual(len(update.records), 2)
            self.assertTrue(
                all((edge.src, edge.dst) not in {(0, 1), (1, 2)} for edge in update.records)
            )

    def test_matrix_market_archive_reciprocal_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "graph.tar.gz"
            payload = (
                "%%MatrixMarket matrix coordinate pattern general\n"
                "% tiny fixture\n"
                "6 6 3\n"
                "2 1\n"
                "3 1\n"
                "4 4\n"
            ).encode("ascii")
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("tiny/tiny.mtx")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            spec = PublicationSourceSpec(
                dataset_id="matrix_test",
                source_path=archive_path,
                source_encoding="tar_matrix_market",
                archive_member="tiny/tiny.mtx",
                semantic_projection="reciprocal_to_paper_edge_count",
                index_base=1,
            )
            manifest = self._materialize(spec, root / "out", batches=(1,))

            self.assertEqual(manifest["normalization"]["matrix_dimensions"], [6, 6, 3])
            self.assertEqual(manifest["graphs"]["directed"]["records"], 4)
            self.assertTrue(manifest["graphs"]["same_artifact"])
            metadata = read_slice_metadata_streaming(
                Path(manifest["graphs"]["directed"]["path"])
            )
            self.assertEqual(metadata.vertices, 6)
            self.assertEqual(metadata.records, 4)

    def test_pagerank_scales_are_exact_nested_min_hash_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "r19.txt"
            input_edges = [(source_id, source_id + 1) for source_id in range(20)]
            source.write_text(
                "".join(
                    f"{destination + 1} {source_id + 1}\n"
                    for source_id, destination in input_edges
                ),
                encoding="ascii",
            )
            spec = PublicationSourceSpec(
                dataset_id="hash_test",
                source_path=source,
                source_encoding="plain_rmat_dst_src",
                declared_vertices=21,
                index_base=1,
                swap_endpoints=True,
            )
            manifest = self._materialize(spec, root / "out")
            expected_rank = sorted(
                input_edges,
                key=lambda edge: (edge_hash_bucket(*edge, seed=20_260_729 + 401), edge),
            )
            observed: list[set[tuple[int, int]]] = []
            for size, artifact in zip((1, 2, 4), manifest["full_pagerank_slices"]):
                graph = load_slice(Path(artifact["path"]))
                edges = {(edge.src, edge.dst) for edge in graph.records}
                self.assertEqual(edges, set(expected_rank[:size]))
                self.assertEqual(
                    artifact["selection_policy"],
                    "exact_min_edge_hash_preserving_original_vertex_ids_v2",
                )
                observed.append(edges)
            self.assertLessEqual(observed[0], observed[1])
            self.assertLessEqual(observed[1], observed[2])


if __name__ == "__main__":
    unittest.main()
