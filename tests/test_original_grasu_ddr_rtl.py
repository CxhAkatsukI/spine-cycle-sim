import json
import copy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.grasu_ddr_rtl import fixtures, analysis
from spine_cycle_sim.experiments.grasu_ddr_rtl.delivery import check_manifest
from spine_cycle_sim.experiments.grasu_ddr_rtl.study import step_order


class GrasuDdrRtlTests(unittest.TestCase):
    def test_all_declared_sequences_are_valid_and_preserve_padding(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/experiments/original_grasu_ddr_rtl_v1.json").read_text())
        self.assertEqual(len(contract["cases"]), 12)
        for case in contract["cases"]:
            with self.subTest(case=case["id"]):
                initial, expected = fixtures.state(case["sequence"])
                self.assertEqual(len(initial), 32)
                for row in expected:
                    self.assertEqual(row, sorted(row))
                    self.assertEqual(len(row), 16)

    def test_packet_routes_cover_both_subpaths_and_all_lanes(self):
        packets = [fixtures.encode(item) for item in fixtures.updates("unique_both")]
        routes = {(value >> 5) & 1 for value in packets}
        lanes = {(value >> 6) & 15 for value in packets}
        self.assertEqual(routes, {0, 1})
        self.assertEqual(lanes, set(range(16)))

    def test_fixture_binary_and_hex_are_identical_complete_states(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "fixture"
            facts = fixtures.prepare(directory, {"sequence": "repeat_both"})
            self.assertEqual(facts["updates"], 6)
            for name in ("initial", "expected"):
                self.assertEqual(fixtures.read_hex(directory / (name + ".hex")), (directory / (name + ".u32le")).read_bytes())

    def test_reject_unknown_or_partial_RTL_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.hex"
            for value in ("0\n" * 32, "x" * 128 + "\n", "0" * 128 + "\n"):
                path.write_text(value)
                with self.assertRaises(ValueError): fixtures.read_hex(path)

    def test_reject_unknown_sequence_and_invalid_update(self):
        with self.assertRaises(ValueError): fixtures.updates("unknown")
        for item in ((32, 20, False), (0, 1000, False), (0, 20, 1)):
            with self.assertRaises(ValueError): fixtures.encode(item)

    def test_source_requires_complete_oracle_state_and_exact_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "fixture"
            case = {"sequence": "single"}
            fixtures.prepare(directory, case)
            (directory / "source.u32le").write_bytes((directory / "expected.u32le").read_bytes())
            stdout = 'G_DDR_SOURCE {"passed":true,"updates":1,"all_prefix_and_end_guards_unchanged":true}\n'
            result = analysis.source(stdout, analysis.WIDTH_WARNING, directory, case)
            self.assertEqual(result["bytes"], 2048)
            with self.assertRaises(ValueError): analysis.source(stdout, "", directory, case)
            (directory / "source.u32le").write_bytes(b"\0" * 2048)
            with self.assertRaises(ValueError): analysis.source(stdout, analysis.WIDTH_WARNING, directory, case)

    def rtl_fixture(self, directory):
        case = {"sequence": "single", "latency": 64, "input_gap": 0}
        fixtures.prepare(directory, case)
        result = {"protocol_passed": True, "updates": 1, "start_cycle": 1, "done_cycle": 160,
            "drained_cycle": 163, "reads": 1, "writes": 1, "read_acks": 1, "write_acks": 1}
        lines = [f"DDR_INPUT cycle=2 data={fixtures.encode((0, 20, False)):024x}",
            "DDR_INPUT cycle=4 data=00000000ffffffffffffffff", "DDR_AR cycle=10 port=0 line=0",
            "DDR_READ cycle=74 port=0 line=0", "DDR_RACK cycle=75 port=0 line=0",
            "DDR_AW cycle=80 port=2 line=0", "DDR_W cycle=81 port=2",
            "DDR_WRITE cycle=145 port=2 line=0", "DDR_BACK cycle=146 port=2 line=0",
            "DDR_RTL_RESULT " + json.dumps(result)]
        capture = directory / "rtl.hex"
        capture.write_text((directory / "expected.hex").read_text())
        contract = {"max_cycles": 20000, "memory_lines": 32, "queue_depth_per_port": 16, "capture_settle_cycles": 3}
        return "\n".join(lines), capture, case, contract

    def test_complete_rtl_trace_and_oracle_are_admitted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "fixture"
            stdout, capture, case, contract = self.rtl_fixture(directory)
            row = analysis.rtl(stdout, "", capture, directory, case, contract)
            self.assertEqual(row["status"], analysis.STATUS)
            self.assertEqual(row["cycles"], 162)
            self.assertEqual(row["kernel_cycles"], 159)
            self.assertEqual(len(row["events"]), 7)

    def test_rtl_rejects_latency_port_order_ack_and_counter_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "fixture"
            stdout, capture, case, contract = self.rtl_fixture(directory)
            changes = [("READ cycle=74", "READ cycle=73"), ("WRITE cycle=145", "WRITE cycle=144"),
                ("RACK cycle=75", "RACK cycle=74"), ("BACK cycle=146", "BACK cycle=145"),
                ("AR cycle=10 port=0", "AR cycle=10 port=1"), ("line=0", "line=32"),
                ('"protocol_passed": true', '"protocol_passed": 1'), ('"updates": 1', '"updates": true'),
                ("DDR_W cycle=81 port=2", "DDR_W cycle=81 port=2 line=0"),
                ("DDR_RACK cycle=75 port=0 line=0", ""), ("DDR_RTL_RESULT", "MISSING")]
            for before, after in changes:
                with self.subTest(before=before):
                    with self.assertRaises(ValueError): analysis.rtl(stdout.replace(before, after), "", capture, directory, case, contract)
            with self.assertRaises(ValueError): analysis.rtl(stdout + "\n" + stdout, "", capture, directory, case, contract)
            with self.assertRaises(ValueError): analysis.rtl(stdout, "unexpected diagnostic", capture, directory, case, contract)

    def test_rtl_state_mismatch_is_explicitly_not_admitted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "fixture"
            stdout, capture, case, contract = self.rtl_fixture(directory)
            capture.write_text((directory / "initial.hex").read_text())
            row = analysis.rtl(stdout, "", capture, directory, case, contract)
            self.assertEqual(row["status"], analysis.MISMATCH)
            self.assertTrue(row["mismatched_words"])

    def test_bus_negative_gate_requires_exact_reason_and_fatal(self):
        control = {"rejection": "invalid read port/burst/capacity"}
        self.assertEqual(analysis.bus("Fatal: invalid read port/burst/capacity\n", "", control)["status"], "EXPECTED_BUS_REJECTION")
        for stdout in ("invalid read port/burst/capacity", "Fatal: unrelated failure", "", "Fatal: invalid read port/burst/capacity\nAbnormal program termination (11)"):
            with self.assertRaises(ValueError): analysis.bus(stdout, "", control)

    def test_manifest_rejects_omission_false_match_and_changed_identity(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/experiments/original_grasu_ddr_rtl_v1.json").read_text())
        report = {"status": analysis.STATUS, "FPGA_measured_cycles": None, "publication_rate_error_pct": None,
            "source_identities": ["identity"], "evidence_class": contract["evidence_class"],
            "steps": [{"id": name} for name in step_order(contract)], "bus_controls": contract["bus_controls"],
            "cases": [{"id": row["id"], "status": analysis.STATUS, "source": ["same"] * 3,
                "rtl": [{"status": analysis.STATUS}] * 2} for row in contract["cases"]]}
        check_manifest(report, contract, ["identity"])
        variants = []
        for field, value in (("FPGA_measured_cycles", 162), ("publication_rate_error_pct", 1.0),
                ("status", "PUBLICATION_MATCH"), ("source_identities", []), ("cases", report["cases"][:-1]),
                ("steps", report["steps"][:-1]), ("bus_controls", [])):
            variants.append({**report, field: value})
        variant = copy.deepcopy(report); variant["cases"][0]["rtl"] = variant["cases"][0]["rtl"][:1]; variants.append(variant)
        for variant in variants:
            with self.assertRaises(ValueError): check_manifest(variant, contract, ["identity"])


if __name__ == "__main__":
    unittest.main()
