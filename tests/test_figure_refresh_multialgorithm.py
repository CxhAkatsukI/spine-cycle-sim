"""The extension must preserve complete pairs, numerical gates and provenance."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import (
    delivery, matrix, tables, validation,
)


def complete_report():
    cases, rows = [], []
    for algorithm, dataset in sorted(validation.EXPECTED):
        case = dict(figure=9, algorithm=algorithm, dataset=dataset, updates=8,
            projection={"SSSP": "directed", "CC": "reciprocal", "ResPR": "residual_sink_free"}[algorithm],
            vertices=10, initial_edges=20, physical_update_records=16 if algorithm == "CC" else 8)
        if algorithm == "SSSP":
            case["root"] = {"AU": 11, "SU": 23, "WK": 0}[dataset]
        arm = dict(cycles=100, rounds=2, read_bytes=64, write_bytes=64, energy_pj=2,
            state_hashes=dict(old_state="old", expected="oracle", final="final"),
            energy_details=dict(total_energy_pj=2), evidence="raw")
        cases.append(case)
        rows.append(analysis.comparison(case, dict(spine=copy.deepcopy(arm), gr=copy.deepcopy(arm))))
    return dict(status="COMPLETE_SUPPORTED_SCOPE", pins_unchanged=True, failures=[],
                baseline_admitted=False, matrix=cases, rows=rows)


class MultialgorithmFigureTests(unittest.TestCase):
    def test_nine_cases_keep_algorithm_specific_projections_and_physical_records(self):
        manifest = dict(graphs={p: dict(path=p, vertices=10, records=20) for p in
                        ("directed", "reciprocal", "residual_sink_free")}, updates=[dict(
                        projection=p, user_mutations=8, scenario="insert", records=n, path=p)
                        for p, n in (("directed", 8), ("reciprocal", 16), ("residual_sink_free", 8))])
        with patch.object(Path, "read_text", return_value=json.dumps(manifest)):
            rows = matrix.cases()
        self.assertEqual(len(rows), 9)
        self.assertEqual({(r["algorithm"], r["physical_update_records"]) for r in rows},
                         {("SSSP", 8), ("CC", 16), ("ResPR", 8)})
        self.assertEqual({r["dataset"]: r["root"] for r in rows if r["algorithm"] == "SSSP"},
                         {"AU": 11, "SU": 23, "WK": 0})
        with self.assertRaises(ValueError):
            matrix.cases(algorithms=("FullPR",))

    def test_missing_failed_or_performance_admitted_matrices_cannot_be_selected(self):
        report = complete_report()
        self.assertEqual(len(validation.selection(report, {})), 9)
        for field, value in (("status", "PARTIAL_RETAINED"), ("pins_unchanged", False),
                             ("failures", ["failure"]), ("baseline_admitted", True)):
            changed = dict(report, **{field: value})
            with self.assertRaisesRegex(ValueError, "complete unchanged"):
                validation.selection(changed, {})
        report["rows"].pop()
        with self.assertRaisesRegex(ValueError, "nine-pair"):
            validation.selection(report, {})

    def test_initial_states_or_ratio_arithmetic_cannot_drift(self):
        report = complete_report()
        report["rows"][0]["gr"]["state_hashes"]["old_state"] = "different"
        with self.assertRaisesRegex(ValueError, "share old"):
            validation.selection(report, {})
        report = complete_report()
        report["rows"][0]["accepted_bytes_ratio"] = 999
        with self.assertRaisesRegex(ValueError, "arithmetic"):
            validation.selection(report, {})

    def test_exports_include_nine_fresh_pairs_without_retaining_old_energy(self):
        rows = validation.selection(complete_report(), dict(source_report_sha256="digest"))
        summary = dict(comparisons=rows)
        result = tables.export_rows(summary)
        self.assertNotIn(b"\r", result["fig9_memory_energy_rows.csv"])
        self.assertNotIn(b"retained_pinned_SSSP", result["fig9_memory_energy_rows.csv"])
        self.assertIn(b"fresh_same_model", result["fig9_memory_energy_rows.csv"])
        self.assertEqual(len(result["fig9_arms.csv"].splitlines()), 19)

    def test_all_channel_energy_must_be_finite_and_conserved(self):
        entry = dict(total_energy=8, act_energy=1, act_stb_energy={"0": 1}, pre_stb_energy=1,
                     read_energy=1, write_energy=1, ref_energy=1, refb_energy=1, sref_energy=1,
                     num_read_cmds=3, num_write_cmds=4)
        read = lambda name: json.dumps({"0": entry}).encode()
        self.assertEqual(validation.energy_details(read, "case")["total_energy_pj"], 256)
        entry["total_energy"] = 7
        with self.assertRaisesRegex(ValueError, "conserve"):
            validation.energy_details(read, "case")
        entry["read_energy"] = float("inf")
        with self.assertRaisesRegex(ValueError, "invalid"):
            validation.energy_details(read, "case")

    def test_less_traffic_does_not_force_an_energy_or_latency_advantage(self):
        case = dict(figure=9, algorithm="ResPR", dataset="AU", updates=8)
        spine = dict(read_bytes=64, write_bytes=64, cycles=1000, energy_pj=100)
        gr = dict(read_bytes=640, write_bytes=640, cycles=100, energy_pj=20)
        row = analysis.comparison(case, dict(spine=spine, gr=gr))
        self.assertEqual(row["accepted_bytes_ratio"], 10)
        self.assertEqual(row["hbm_energy_ratio"], 0.2)
        self.assertGreater(row["spine"]["cycles"], row["gr"]["cycles"])

    def test_source_snapshot_handles_both_cmake_lists_and_detects_tampering(self):
        blobs = {"CMakeLists.txt": b"root", "cpp/CMakeLists.txt": b"core"}
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as handle:
            for name, blob in blobs.items():
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                handle.addfile(info, io.BytesIO(blob))
        blob = archive.getvalue()
        report = dict(pins=[dict(path="/repo/" + n, sha256=hashlib.sha256(b).hexdigest())
                            for n, b in blobs.items()] + [dict(path="/out/run/sources.tar.gz",
                            sha256=hashlib.sha256(blob).hexdigest())])
        validation.source_snapshot(report, lambda _: blob, "run/")
        report["pins"][0]["sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "frozen pin"):
            validation.source_snapshot(report, lambda _: blob, "run/")

    def test_archives_reject_duplicate_members_and_core_failure(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as handle:
            info = tarfile.TarInfo("duplicate")
            handle.addfile(info, io.BytesIO())
            handle.addfile(info, io.BytesIO())
        with tarfile.open(fileobj=io.BytesIO(archive.getvalue())) as handle:
            with self.assertRaisesRegex(ValueError, "membership"):
                delivery.checked_archive(handle, dict(members=[dict(path="duplicate")]))
        with self.assertRaisesRegex(ValueError, "successful unchanged core"):
            validation.core_gates(dict(status="FAILED_RETAINED"), {}, lambda _: b"", "run/")


if __name__ == "__main__":
    unittest.main()
