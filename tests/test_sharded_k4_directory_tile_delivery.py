"""Recompute the sealed finite-bank matrix and reject changed raw evidence."""

import io
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_archive import extracted
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.delivery import ARCHIVE, verify
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.archive_parts import assembled
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.recheck import hls, model

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
              "adapter_optimization/row_line/directory_tile/evidence")


class DirectoryTileDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        record = json.loads((DOC / "verification.json").read_text())
        cls.context = ExitStack()
        cls.addClassCleanup(cls.context.close)
        archive = cls.context.enter_context(assembled(DOC, record, archive_name=ARCHIVE))
        cls.evidence = cls.context.enter_context(extracted(archive, record, max_bytes=1024**3))

    def reject(self, relative, mutation, validate, message):
        path = self.evidence / relative
        original = path.read_bytes()
        try:
            changed = mutation(original)
            self.assertNotEqual(changed, original)
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, message):
                validate(self.evidence)
        finally:
            path.write_bytes(original)

    def test_prediction_scope_and_complete_replay(self):
        result = verify(DOC)
        self.assertEqual(result["status"], "PREDICTION_TARGET_MET_NOT_FPGA")
        self.assertTrue(result["target_met"])
        self.assertEqual((result["model_runs"], result["RTL_cases"], result["legacy_SST_cases"]), (18, 23, 5))
        self.assertEqual([row["cycles"] for row in result["warm_results"]], [699141, 1251794])
        for key in ("hardware_timing_admitted", "strict_resource_match_admitted",
                    "publication_match_admitted", "production_promotion", "paper_modified"):
            self.assertIs(result[key], False)

    def test_physical_traffic_mutation_rejected(self):
        def mutation(data):
            lines = data.decode().splitlines()
            for index, line in enumerate(lines):
                if line.startswith("REAL_ROUND "):
                    row = json.loads(line.removeprefix("REAL_ROUND "))
                    row["read_bytes"] -= 64
                    lines[index] = "REAL_ROUND " + json.dumps(row)
            return ("\n".join(lines) + "\n").encode()
        self.reject("model/raw/warm_update_lat64_reverse0_tile.stdout.txt", mutation,
                    model, "conserved physical work")

    def test_complete_replica_mutation_rejected(self):
        self.reject("model/states/warm_update_lat64_reverse0_tile/k4_source1.u32le",
                    lambda data: bytes([data[0] ^ 1]) + data[1:], model, "source replica differs")

    def test_original_control_mutation_rejected(self):
        self.reject("model/raw/warm_update_lat64_reverse0_original.stdout.txt",
                    lambda data: data.replace(b'"cycles":668278', b'"cycles":668279')
                        if b'"cycles":668278' in data else
                        data.replace(b'"cycles": 668278', b'"cycles": 668279'),
                    model, "original A4 exact numerical replay")

    def test_hls_source_archive_mutation_rejected(self):
        def mutation(data):
            output = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as source, \
                    tarfile.open(fileobj=output, mode="w:gz") as target:
                for index, member in enumerate(source.getmembers()):
                    content = source.extractfile(member).read() + (b"\n" if index == 0 else b"")
                    member.size = len(content)
                    target.addfile(member, io.BytesIO(content))
            return output.getvalue()
        self.reject("hls/sources.tar.gz", mutation, hls, "HLS source bytes differ")

    def test_executed_rtl_mutation_rejected(self):
        candidate = self.evidence / "hls/candidate"
        path = next(path for path in sorted(candidate.glob("*.v"))
                    if path.name != "bank_stream_axi_tb.sv")
        self.reject(str(path.relative_to(self.evidence)), lambda data: data + b"\n",
                    hls, "executed RTL differs from XO")

    def test_sealed_conclusion_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "verification.json").write_bytes((DOC / "verification.json").read_bytes())
            (destination / "results.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "sealed conclusion differs"):
                verify(destination)


if __name__ == "__main__":
    unittest.main()
