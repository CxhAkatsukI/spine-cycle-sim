import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_grasu_persistent_update_v20 import load_models, validate_contract


class AnalyzeGrasuPersistentUpdateV20Tests(unittest.TestCase):
    def test_contract_freezes_so_pk_as_holdout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/contracts/current_fpga_grasu_persistent_update_v20.json").read_text())
        validate_contract(contract)
        self.assertEqual(contract["roles"]["holdout"], ["so", "pk"])
        self.assertFalse(contract["model"]["holdout_may_fit"])

    def test_model_loader_rejects_unfrozen_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            path.write_text('{"status":"DRAFT"}\n', encoding="ascii")
            with self.assertRaisesRegex(ValueError, "not frozen"):
                load_models(path)


if __name__ == "__main__":
    unittest.main()
