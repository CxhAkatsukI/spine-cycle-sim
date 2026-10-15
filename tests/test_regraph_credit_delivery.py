import copy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_credits.delivery import validate, verify


EVIDENCE = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/"
    "evaluation_impact/r_credits/evidence")


class CreditDeliveryTests(unittest.TestCase):
    def test_complete_portable_matrix_retains_negative_resource_result(self):
        index = verify(EVIDENCE)
        self.assertEqual(index["rows"], 28)
        self.assertEqual(index["analysis"]["legacy_rows_replayed_exactly"], 12)
        self.assertEqual(len([name for name in index["blobs"] if name.startswith("states/")]), 92)
        for row in index["analysis"]["comparisons"]:
            self.assertLess(row["over_legacy_a4"]["candidate"], 1.1)
            self.assertGreater(row["over_a4_io16"]["candidate"], 2.9)

    def changed_index(self, change):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            index = json.loads((EVIDENCE / "index.json").read_text())
            change(index)
            (output / "index.json").write_text(json.dumps(index))
            shutil.copyfile(EVIDENCE / index["archive"], output / index["archive"])
            with self.assertRaises(ValueError):
                verify(output)

    def test_source_prediction_cannot_be_promoted_to_hardware(self):
        self.changed_index(lambda index: index.update(hardware_timing_admitted=True))

    def test_input_and_state_blob_identity_cannot_be_replaced(self):
        self.changed_index(lambda index: next(iter(index["blobs"].values())).update(sha256="changed"))

    def test_unindexed_archive_member_is_rejected(self):
        self.changed_index(lambda index: index["members"].pop())

    def test_report_and_raw_numerical_outputs_must_agree(self):
        index = json.loads((EVIDENCE / "index.json").read_text())
        with tarfile.open(EVIDENCE / index["archive"]) as archive:
            def read(name):
                return archive.extractfile(name).read()
            report = json.loads(read("results.json"))
            reference = json.loads(read("pre_edit/reference.json"))
            raw = read("raw/r_lat64_reverse0_a4.stdout.txt")
            altered = raw.replace(b'"cycles":668278', b'"cycles":668279', 1)
            self.assertNotEqual(altered, raw)
            def changed(name):
                return altered if name == "raw/r_lat64_reverse0_a4.stdout.txt" else read(name)
            with self.assertRaises(ValueError):
                validate(copy.deepcopy(report), reference, changed, index["blobs"])


if __name__ == "__main__":
    unittest.main()
