"""Passive observations must not change any of the twelve convergence rows."""

import copy
import csv
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import wait_analysis as analysis
from tests.test_regraph_compact_convergence import fixture


def waits():
    result = {}
    for key in analysis.MATRIX:
        if key[2] == "a4_io16":
            continue
        tables = {name: [{field: 0 for field in fields} for _ in range(count)]
                  for (name, fields), count in zip(analysis.TABLES.items(), (4, 2, 1))}
        for name in ("frontend_waits", "source_waits"):
            field = analysis.TABLES[name][0]
            for index, row in enumerate(tables[name]):
                row[field] = index
        result[key] = tables
    return result


class WaitObservationTests(unittest.TestCase):
    def test_complete_replay_keeps_nonadmission_flags(self):
        rows, _ = fixture()
        result = analysis.summarize(rows, copy.deepcopy(rows), waits())
        self.assertEqual(result["all_numerical_rows_replayed_exactly"], 12)
        self.assertEqual(result["wait_registration_order_pairs"], 4)
        self.assertEqual(len(result["observations"]), 4)
        for field in ("exclusive_stage_breakdown", "hardware_timing_admitted", "production_baseline_admitted"):
            self.assertIs(result[field], False)

    def test_missing_duplicate_or_reordered_matrix_rejected(self):
        rows, _ = fixture()
        for matrix in (rows[:-1], rows[:-1] + rows[:1], rows[::-1]):
            for side in (0, 1):
                arguments = [rows, rows]; arguments[side] = matrix
                with self.subTest(side=side), self.assertRaisesRegex(ValueError, "twelve-row"):
                    analysis.summarize(*arguments, waits())
        incomplete = waits(); incomplete.pop(next(iter(incomplete)))
        with self.assertRaisesRegex(ValueError, "eight-row"):
            analysis.summarize(rows, rows, incomplete)

    def test_candidate_and_legacy_state_or_observation_drift_rejected(self):
        for index in range(12):
            for field in ("observations", "outputs"):
                rows, _ = fixture(); changed = copy.deepcopy(rows)
                if field == "observations": changed[index][field]["result"]["cycles"] += 1
                else: changed[index][field][0]["sha256"] = "changed"
                with self.subTest(index=index, field=field), self.assertRaisesRegex(ValueError, "passive"):
                    analysis.summarize(changed, rows, waits())

    def test_unclosed_conservation_order_and_cycle_bound_rejected(self):
        for kind, message in (("packets", "Scatter"), ("parents", "parents"),
                              ("order", "registration"), ("bound", "exceed")):
            rows, _ = fixture(); observations = waits()
            tables = observations[(64, 1, "prefetch_compact")]
            if kind == "packets": tables["frontend_waits"][0]["packets"] = 1
            elif kind == "parents": tables["source_waits"][0]["parents"] = 1
            elif kind == "order": tables["frontend_waits"][0]["edge_waits"] = 1
            else: tables["backend_waits"][0]["apply_read_stalls"] = 10**20
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, message):
                analysis.summarize(rows, rows, observations)

    def test_csv_schema_values_shape_and_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.csv"
            for name, tables in waits()[(64, 0, "bank_stream")].items():
                def write(rows, fields=analysis.TABLES[name]):
                    with path.open("w", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=fields)
                        writer.writeheader(); writer.writerows(rows)
                write(tables)
                self.assertEqual(analysis.read_table(path, name), tables)
                for bad in ("-1", "+1", "00", "1.0", "", " 1", "\u0661"):
                    changed = copy.deepcopy(tables); changed[0][analysis.TABLES[name][-1]] = bad
                    write(changed)
                    with self.subTest(name=name, bad=bad), self.assertRaisesRegex(ValueError, "unsigned"):
                        analysis.read_table(path, name)
                for changed in (tables[:-1], tables + tables[:1]):
                    write(changed)
                    with self.assertRaisesRegex(ValueError, "observation rows"):
                        analysis.read_table(path, name)
                if name != "backend_waits":
                    write(tables[::-1])
                    with self.assertRaisesRegex(ValueError, "observation rows"):
                        analysis.read_table(path, name)
                write(tables, tuple(reversed(analysis.TABLES[name])))
                with self.assertRaisesRegex(ValueError, "schema"):
                    analysis.read_table(path, name)


if __name__ == "__main__":
    unittest.main()
