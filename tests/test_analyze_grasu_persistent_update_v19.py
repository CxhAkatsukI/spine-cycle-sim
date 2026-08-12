import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_grasu_persistent_update_v19 import (
    load_models,
    parse_repeat_rows,
    validate_contract,
)


class AnalyzeGrasuPersistentUpdateV19Tests(unittest.TestCase):
    def test_repeat_parser_keeps_cold_and_warm_rows_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run.log"
            path.write_text(
                "GRASU_SHARDED_UPDATE_REPEAT repeat=0 final=0 update_ms=9.0 barrier_ms=8.0\n"
                "GRASU_SHARDED_UPDATE_REPEAT repeat=1 final=1 update_ms=0.5 barrier_ms=0.4\n",
                encoding="ascii",
            )
            rows = parse_repeat_rows(path)
            self.assertEqual([row["repeat"] for row in rows], [0, 1])
            self.assertEqual(rows[0]["update_ms"], 9.0)
            self.assertEqual(rows[1]["update_ms"], 0.5)

    def test_repeat_parser_accepts_pagerank_without_barrier_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run.log"
            path.write_text(
                "GRASU_SHARDED_UPDATE_REPEAT repeat=0 final=0 update_ms=1.25\n",
                encoding="ascii",
            )
            rows = parse_repeat_rows(path)
            self.assertEqual(rows[0]["update_ms"], 1.25)
            self.assertIsNone(rows[0]["barrier_ms"])

    def test_frozen_model_loader_rejects_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            path.write_text(json.dumps({"status": "DRAFT"}), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "not frozen"):
                load_models(path)

    def test_contract_excludes_transfer_from_fit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "configs/contracts/current_fpga_grasu_persistent_update_v19.json"
        contract = json.loads(path.read_text(encoding="ascii"))
        validate_contract(contract)
        self.assertFalse(contract["model"]["transfer_may_fit"])
        self.assertEqual(contract["roles"]["transfer"], ["lj", "lj08"])
        self.assertEqual(contract["integration"]["warm_repeats"], [1, 2, 3, 4])
        self.assertEqual(contract["integration"]["cold_repeat"], 0)


if __name__ == "__main__":
    unittest.main()
