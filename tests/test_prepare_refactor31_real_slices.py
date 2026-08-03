from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_refactor31_real_slice_matrix.py"
SPEC = importlib.util.spec_from_file_location("prepare_refactor31", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareRefactor31RealSlicesTests(unittest.TestCase):
    def test_matrix_market_is_remapped_and_weighted_deterministically(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "graph.mtx"
            source.write_text(
                "%%MatrixMarket matrix coordinate pattern general\n"
                "5 5 6\n"
                "5 2\n5 3\n5 4\n5 1\n2 1\n3 1\n",
                encoding="ascii",
            )
            rows = MODULE.prepare_dataset(
                dataset_id="MM",
                source_path=source,
                targets=[4, 6],
                out_dir=root / "out",
                vertex_limit=8,
                expected_reject_targets=set(),
            )
            self.assertEqual([row["status"] for row in rows], ["generated"] * 2)
            self.assertEqual(rows[0]["source"], 0)
            text = Path(rows[0]["path"]).read_text(encoding="ascii")
            self.assertIn("# vertices=5", text)
            self.assertIn(
                f"0 1 {MODULE.endpoint_weight(0, 1)} 1", text
            )

    def test_plain_zero_based_input_and_duplicate_endpoint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "graph.txt"
            source.write_text("# graph\n10 20\n10 20\n20 30\n", encoding="ascii")
            rows = MODULE.prepare_dataset(
                dataset_id="TXT",
                source_path=source,
                targets=[2],
                out_dir=root / "out",
                vertex_limit=3,
                expected_reject_targets=set(),
            )
            self.assertEqual(rows[0]["vertices"], 3)
            records = [
                line for line in Path(rows[0]["path"]).read_text().splitlines()
                if not line.startswith("#")
            ]
            self.assertEqual(len(records), 2)

    def test_expected_capacity_rejection_is_manifested(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "graph.txt"
            source.write_text("0 1\n1 2\n2 3\n", encoding="ascii")
            rows = MODULE.prepare_dataset(
                dataset_id="CAP",
                source_path=source,
                targets=[3],
                out_dir=root / "out",
                vertex_limit=3,
                expected_reject_targets={3},
            )
            self.assertEqual(rows[0]["status"], "vertex_domain_exceeded")
            self.assertFalse((root / "out" / "cap_e3.slice").exists())

    def test_v2_matrix_keeps_or8m_as_capacity_probe(self) -> None:
        matrix = json.loads(
            (Path(__file__).resolve().parents[1]
             / "configs/experiments/spine_refactor31_fpga_calibration_matrix_v2.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(matrix["holdout"]["datasets"][1]["edge_scale"], 4_000_000)
        self.assertEqual(matrix["capacity_probes"][0]["edge_scale"], 8_000_000)


if __name__ == "__main__":
    unittest.main()
