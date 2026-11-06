import csv
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction import work


class WorkTests(unittest.TestCase):
    def test_only_in_window_records(self):
        text = ("CC_BOOTSTRAP_PASS physical_edges=900\n"
                "CC_UPDATE_PASS physical_edges=25 rounds=4 vertex_visits=9\n"
                "KERNEL_PAIR_RESULT iteration=0 processed_edges=12 source_requests=2\n")
        rows = work.records(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fields"]["physical_edges"], "25")
        self.assertNotIn("source_requests", rows[0]["fields"])

    def test_duplicate_fields_rejected(self):
        with self.assertRaises(ValueError):
            work.records("KERNEL_PAIR_RESULT processed_edges=1 processed_edges=2")

    def test_portable_archive_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            study = dict(campaign=0, dataset="AU", algorithm="connected_components")
            (data / "summary.json").write_text(json.dumps(dict(studies=[study])))
            sample = dict(sample_index=0, warmup=True, status="PASS", arms=dict(spine={}))
            campaign = dict(cases=[dict(name="target", samples=[sample])])
            (data / "campaign-0.json").write_text(json.dumps(campaign))
            with tarfile.open(data / "host-logs.tar.gz", "w:gz") as archive:
                payload = b"CC_UPDATE_PASS physical_edges=25 rounds=4\n"
                member = tarfile.TarInfo("campaign-0/target/sample-0/spine.stdout.txt")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            result = work.export(root, root / "work")
            self.assertEqual(result["records"], 1)
            with (root / "work/records.csv").open() as stream:
                row, = csv.DictReader(stream)
            self.assertEqual(row["log_physical_edges"], "25")
            self.assertEqual(row["warmup"], "True")
            self.assertNotIn("log_source_requests", row)


if __name__ == "__main__":
    unittest.main()
