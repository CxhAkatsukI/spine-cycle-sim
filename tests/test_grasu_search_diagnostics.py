import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from tests import test_grasu_search_concurrency as concurrency
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.study import metadata
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_diagnostics.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_diagnostics.preparation import ARMS, matrix
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_diagnostics.delivery import package
from spine_cycle_sim.experiments.campaign_runtime import sha256_file


class SearchDiagnosticsTests(unittest.TestCase):
    def fixture(self):
        previous, _ = concurrency.SearchConcurrencyTests().fixture()
        previous.update(status="G_SEARCH_CONCURRENCY_VALIDATED_REFERENCE_TIMING_OPEN",
                        forwarded_reference_within_ten_percent_both_directions=False)
        rows = copy.deepcopy([r for r in previous["rows"] if r["arm"] in ARMS])
        for row in rows:
            original = row["arm"] == "original_forwarded"
            nports = 8 if original else 1
            names = [f"search{i}.table{j}" if original else f"grasu-row{i}"
                     for i in range(4) for j in range(nports)]
            names += [f"other{i}" for i in range((46 if original else 18) - len(names))]
            ports = [{"name": name, "parent_limit": 16, "requests": 1, "responses": 1,
                      "beats_issued": 1, "beats_completed": 1, "read_bytes": 0, "write_bytes": 0,
                      "backend_stalls": 0, "parent_stalls": 0} for name in names]
            for field in ("read_bytes", "write_bytes"):
                ports[-1][field] = row["observation"][field]
            count = row["observation"]["cache_updates"]
            row["diagnostics"] = {"ports": ports, "search_done": [50] * 4,
                "dispatch_done": 51, "cache_loaded": [10] * 2, "write_started": [91] * 2,
                "hot_completed": [count, 0], "first_hot_update": [11 if count else 0, 0],
                "last_hot_update": [90 if count else 0, 0], "metadata_port_cycles": [100 * nports] * 4,
                "metadata_full_cycles": [50 * nports] * 4, "metadata_peak_parents": [16] * 4}
        return {**metadata(), "rows": rows, "matrix": matrix(), "errors": []}, previous

    def test_all_114_rows_exact_without_promoting_failed_gate(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(result["exact_replayed_rows"], 114)
        self.assertFalse(result["complete_previous_performance_gate"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertEqual(result["stage_observations"][0]["metadata"][0]["full_fraction"], .5)

    def test_scope_identity_resource_and_admission_rejections(self):
        for fault in ("missing", "duplicate", "matrix", "previous", "cycle", "state", "failed", "clock", "admission"):
            with self.subTest(fault=fault):
                report, previous = self.fixture()
                if fault == "missing": report["rows"].pop()
                if fault == "duplicate": report["rows"].append(report["rows"][0])
                if fault == "matrix": report["matrix"].pop()
                if fault == "previous": previous["rows"].pop()
                if fault == "cycle": report["rows"][-1]["observation"]["cycles"] += 1
                if fault == "state": report["rows"][-1]["state_sha256"] = "b" * 64
                if fault == "failed": report["errors"].append({"error": "retained"})
                if fault == "clock": report["clock_mhz"] = 250
                if fault == "admission": report["hardware_timing_admitted"] = True
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_missing_markers_drain_traffic_and_pressure_rejected(self):
        for fault in ("marker", "order", "count", "port", "traffic", "requests", "beats", "denominator", "pressure", "peak"):
            with self.subTest(fault=fault):
                report, previous = self.fixture()
                detail = report["rows"][-1]["diagnostics"]
                if fault == "marker": detail["search_done"][0] = 0
                if fault == "order": detail["write_started"][0] = 1
                if fault == "count": detail["hot_completed"][0] += 1
                if fault == "port": detail["ports"][0]["name"] = detail["ports"][1]["name"]
                if fault == "traffic": detail["ports"][-1]["read_bytes"] += 1
                if fault == "requests": detail["ports"][0]["responses"] += 1
                if fault == "beats": detail["ports"][0]["beats_completed"] += 1
                if fault == "denominator": detail["metadata_port_cycles"][0] += 1
                if fault == "pressure": detail["metadata_full_cycles"][0] = 100000
                if fault == "peak": detail["metadata_peak_parents"][0] = 18
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_delivery_archives_exact_sidecars_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / "pin"
            pin.write_bytes(b"complete state")
            report, previous = self.fixture()
            for value in (report, previous):
                for row in value["rows"]:
                    row["state_sha256"] = sha256_file(pin)
            for row in report["rows"]:
                name = f'lat{row["latency"]}_{row["case"]}_{row["arm"]}'
                (root / (name + ".u32le")).write_bytes(pin.read_bytes())
                path = root / (name + ".diagnostics.json")
                path.write_text(json.dumps(row["diagnostics"]))
                row["diagnostics_sha256"] = sha256_file(path)
            report.update(analyze(report, previous), steps=[],
                pins=[{"path": str(pin), "sha256": sha256_file(pin)}],
                status="G_READ_ONLY_DIAGNOSTICS_EXACT_REPLAY")
            source, old = root / "matrix.json", root / "previous.json"
            source.write_text(json.dumps(report))
            old.write_text(json.dumps(previous))
            result = package(root / "evidence", source, old)
            self.assertEqual(result["exact_replayed_rows"], 114)
            with tarfile.open(root / "evidence/raw_runs.tar.gz") as archive:
                self.assertEqual(len(archive.getnames()), 114)
            path.write_text('{"tampered":true}')
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                package(root / "rejected-hash", source, old)
            report["rows"][-1]["diagnostics_sha256"] = sha256_file(path)
            source.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                package(root / "rejected-content", source, old)


if __name__ == "__main__":
    unittest.main()
