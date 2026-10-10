import csv
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.grasu_finite import analysis
from spine_cycle_sim.experiments.grasu_finite.analysis import equivalent
from spine_cycle_sim.experiments.grasu_finite.delivery import check_manifest
from spine_cycle_sim.experiments.upstream_controls.grasu.fixtures import batches, request_rows


class OriginalGrasuFiniteTests(unittest.TestCase):
    def test_repeated_comparison_does_not_ignore_stalls_or_windows(self):
        equivalent({"cycles": 1, "stalls": 2}, {"cycles": 1, "stalls": 2})
        with self.assertRaises(ValueError):
            equivalent({"cycles": 1, "stalls": 2}, {"cycles": 1, "stalls": 3})
        with self.assertRaises(ValueError):
            equivalent({"windows": [1, 2]}, {"windows": [2, 1]})

    def test_lane_257_fixture_reuses_search_lanes(self):
        rows = request_rows(batches(4)[0])
        self.assertGreater(sum(row[:3] == (0, 0, 0) for row in rows), 1)

    def manifest(self):
        contract = json.loads((Path(__file__).resolve().parents[1] / "configs/experiments/original_grasu_finite_v1.json").read_text())
        names = []
        for case in range(8):
            names.extend((f"source_{case}", f"source_ubsan_{case}"))
        for row in contract["matrix"]:
            names.extend(f'{row["id"]}_{repeat}' for repeat in range(contract["repetitions"]))
            if row["id"] in contract["ubsan_rows"]:
                names.append(row["id"] + "_ubsan")
        return contract, {"status": "G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING", "contract": contract,
            "rows": [{"id": row["id"], "repetition": repeat} for row in contract["matrix"] for repeat in range(contract["repetitions"])],
            "source_rows": [{"case": case} for case in range(8)], "source_ubsan_rows": [{"case": case} for case in range(8)],
            "ubsan_rows": [{"id": name} for name in contract["ubsan_rows"]],
            "steps": [{"stdout": "/output/" + name + ".stdout.txt"} for name in names]}

    def test_complete_execution_manifest(self):
        contract, report = self.manifest()
        check_manifest(report, contract)

    def test_omitted_or_relabelled_matrix_evidence_rejected(self):
        contract, report = self.manifest()
        for field in ("rows", "source_rows", "source_ubsan_rows", "ubsan_rows", "steps"):
            changed = copy.deepcopy(report)
            changed[field].pop()
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_manifest(changed, contract)
        changed = copy.deepcopy(report)
        changed["status"] = "SMOKE_PASS_NOT_ADMITTED"
        with self.assertRaises(ValueError):
            check_manifest(changed, contract)


class FiniteEvidenceGates(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.stdout = self.root / "stdout"
        self.stderr = self.root / "stderr"
        self.stderr.write_text("")
        self.original = bytes(256)
        self.patch = patch.multiple(analysis, HALF=2, HOT=1)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.oracle = patch.object(analysis, "final_state", return_value=self.original)
        self.oracle.start()
        self.addCleanup(self.oracle.stop)
        for bank in range(4):
            (self.capture / f"bank{bank}.bin").write_bytes(bytes(128) + b"\xa5" * 64)
        (self.capture / "merged.u32le").write_bytes(self.original)
        (self.capture / "search.tsv").write_text("batch\tkernel\tlane\tkind\taddress\tvalue\n")
        self.fields = ["initiator", "bank", "width", "parents", "completed", "beats", "finished_beats", "reads", "writes", "backend_stalls"]
        self.ports = []
        for index in range(46):
            hot = index in (36, 41)
            bank = index // 9 if index < 36 else (index - 36) // 5 * 2 + int((index - 36) % 5 != 0)
            self.ports.append(dict(zip(self.fields, (index + 1, bank, 8 if index < 36 else 64,
                2 if hot else 0, 2 if hot else 0, 2 if hot else 0, 2 if hot else 0,
                64 if hot else 0, 64 if hot else 0, 0))))
        self.result = {"status": "SOURCE16_STATE_AND_FINITE_LEDGER_PASS", "timing_kind": "declared_prediction",
            "batches": 1, "updates": 0, "cache_updates": 0, "ddr_updates": 0, "search_reads": 0,
            "read_bytes": 128, "write_bytes": 128, "parents": 4, "completed": 4, "beats": 4,
            "finished_beats": 4, "backend_stalls": 0, "predicted_cycles": [1],
            "component_done_windows": [[1] * 10], "fpga_timing_match": None, "publication_timing_match": None}
        self.write()

    def write(self):
        self.stdout.write_text("G_FINITE_RESULT " + json.dumps(self.result) + "\n")
        with (self.capture / "ports.tsv").open("w") as stream:
            writer = csv.DictWriter(stream, self.fields, delimiter="\t")
            writer.writeheader()
            writer.writerows(self.ports)

    def check(self):
        return analysis.analyze(self.capture, 0, self.stdout, self.stderr)

    def test_complete_fixture_passes(self):
        self.assertEqual(self.check()["checked_buffer_slots"], 128)

    def test_changed_stale_physical_copy_rejected(self):
        path = self.capture / "bank1.bin"
        data = bytearray(path.read_bytes())
        data[0] = 1
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "physical buffer"):
            self.check()

    def test_guard_corruption_rejected(self):
        path = self.capture / "bank0.bin"
        path.write_bytes(path.read_bytes()[:-1] + b"\0")
        with self.assertRaisesRegex(ValueError, "guard"):
            self.check()

    def test_merged_state_corruption_rejected(self):
        (self.capture / "merged.u32le").write_bytes(b"x" + self.original[1:])
        with self.assertRaisesRegex(ValueError, "merged"):
            self.check()

    def test_fake_search_request_rejected(self):
        with (self.capture / "search.tsv").open("a") as stream:
            stream.write("0\t0\t0\t0\t0\t0\n")
        with self.assertRaisesRegex(ValueError, "request sequence"):
            self.check()

    def test_port_width_and_bank_must_match(self):
        self.ports[0]["width"] = 64
        self.write()
        with self.assertRaisesRegex(ValueError, "mapping"):
            self.check()

    def test_port_beat_loss_rejected(self):
        self.ports[36]["finished_beats"] -= 1
        self.write()
        with self.assertRaisesRegex(ValueError, "conservation"):
            self.check()

    def test_aggregate_cannot_hide_port_stalls(self):
        self.ports[36]["backend_stalls"] = 1
        self.write()
        with self.assertRaisesRegex(ValueError, "aggregate"):
            self.check()

    def test_bool_counter_rejected(self):
        self.result["updates"] = False
        self.write()
        with self.assertRaisesRegex(ValueError, "ledger"):
            self.check()

    def test_missing_window_rejected(self):
        self.result["component_done_windows"][0].pop()
        self.write()
        with self.assertRaisesRegex(ValueError, "windows"):
            self.check()

    def test_hardware_claim_rejected(self):
        self.result["fpga_timing_match"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "hardware"):
            self.check()

    def test_unexpected_diagnostic_rejected(self):
        self.stderr.write_text("runtime error\n")
        with self.assertRaisesRegex(ValueError, "diagnostics"):
            self.check()

    def test_duplicate_json_field_rejected(self):
        self.stdout.write_text(self.stdout.read_text().replace('"updates": 0', '"updates": 0, "updates": 0'))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.check()


if __name__ == "__main__":
    unittest.main()
