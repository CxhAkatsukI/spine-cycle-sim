"""First-contact ordering, compaction and full-matrix prediction boundaries."""

from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_contract import case_names
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_inputs import (
    BATCHES, DATASETS, compact_contacts, select_contacts)
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_inputs import contract
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_inputs import facts
from spine_cycle_sim.experiments.shared_workloads import load_slice
from tests.test_grasu_sharded_real import observations

PARENT = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch")


def event(seq, timestamp, src, dst):
    return seq, timestamp, (src << 32) | dst


class ChronologicalInputTests(unittest.TestCase):
    def test_loops_repeated_contacts_and_equal_timestamp_ties(self):
        events = [event(7, 1, 42, 42), event(0, 2, 42, 11), event(1, 2, 42, 11),
                  event(4, 2, 11, 42), event(2, 3, 80000, 42), event(3, 4, 42, 90000)]
        contacts, stats = select_contacts(events, base_edges=2, updates=1)
        self.assertEqual(contacts, [(0, 2, 42, 11), (4, 2, 11, 42), (2, 3, 80000, 42)])
        self.assertEqual(stats, {"scanned_events": 5, "excluded_self_loops": 1, "excluded_repeat_contacts": 1})
        ids, records = compact_contacts(contacts)
        self.assertEqual(ids, {42: 0, 11: 1, 80000: 2})
        self.assertEqual([(r.src, r.dst, r.weight, r.diff) for r in records],
                         [(0, 1, 1, 1), (1, 0, 1, 1), (2, 0, 1, 1)])

    def test_missing_contacts_order_inversions_and_duplicate_positions_fail(self):
        cases = ([event(0, 1, 1, 2)], [event(0, 2, 1, 2), event(1, 1, 2, 1)],
                 [event(0, 1, 1, 2), event(0, 1, 2, 1)])
        for events in cases:
            with self.assertRaises(ValueError): select_contacts(events, 1, 1)
        with self.assertRaises(ValueError): select_contacts([], 0, 1)
        with self.assertRaises(ValueError): select_contacts([], 1, -1)

    def test_compaction_is_fixed_for_both_prefixes_and_capacity_fails_closed(self):
        contacts = [(n, n, 1, n + 2) for n in range(65534)]
        with self.assertRaises(ValueError): compact_contacts(contacts)
        ids, records = compact_contacts(contacts[:32])
        self.assertEqual(len(ids), 33)
        self.assertEqual(records[0], records[:4][0])
        self.assertNotIn(65535, ids)

    def test_declared_larger_batches_and_all_datasets_are_not_selected_by_results(self):
        self.assertEqual(BATCHES, (4096, 65536))
        self.assertEqual(DATASETS, ("AU", "SU", "WK"))
        self.assertEqual(len(case_names()), 6)

    def test_explicit_scope_uses_unchanged_analysis_and_rejects_omitted_cases(self):
        declared = deepcopy(contract())
        rename = dict(zip(sorted(declared["cases"]), sorted(case_names())))
        declared["cases"] = {rename[name]: row for name, row in declared["cases"].items()}
        for row in declared["matrix"]:
            row["case"] = rename[row["case"]]
        rows = observations(declared)
        result = analyze(rows, declared, names=case_names())
        self.assertEqual(result["prediction_rows"], 36)
        self.assertFalse(result["production_baseline_admitted"])
        self.assertFalse(result["publication_match_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])
        for bad in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError): analyze(bad, declared, names=case_names())
        with self.assertRaises(ValueError): analyze(rows, declared)


class ChronologicalDeliveryTests(unittest.TestCase):
    def test_larger_runtime_mismatches_are_reported_not_dropped_or_admitted(self):
        report = json.loads((PARENT / "chronological_inputs/evidence/matrix.json").read_text())
        self.assertEqual(report["status"], "CHRONOLOGICAL_G_PREDICTIONS_CHECKED_NOT_BASELINE_ADMISSION")
        self.assertTrue(report["four_bank_ten_percent_target_met"])
        self.assertFalse(report["runtime_ten_percent_diagnostic_met"])
        failures = {(r["case"], r["latency"]) for r in report["comparisons"]
                    if not 0.9 <= r["runtime_over_original"] <= 1.1}
        self.assertEqual(failures, {(f"{dataset}-chronological-insert-65536", latency)
                                   for dataset in DATASETS for latency in (64, 128)})
        self.assertEqual(len(report["rows"]), 36)

    def test_full_capsules_recompute_without_external_inputs(self):
        for name in ("evidence", "regression", "parser_regression"):
            folder = PARENT / "chronological_inputs" / name
            index = json.loads((folder / "index.json").read_text())
            report = json.loads((folder / "matrix.json").read_text())
            checked = (analyze(report["rows"], report["contract"], names=case_names()) if name == "evidence"
                       else analyze(report["rows"], report["contract"]))
            for key, value in checked.items():
                self.assertEqual(report[key], value)
                self.assertEqual(index[key], value)
            self.assertFalse(index["new_spine_comparison_executed"])
            self.assertEqual(report["errors"], [])
            for entry in index["reports"]:
                path = folder / entry["file"]
                self.assertEqual(sha256_file(path), entry["sha256"])
                self.assertEqual(path.stat().st_size, entry["bytes"])
            with tarfile.open(folder / "raw_runs.tar.gz") as archive:
                self.assertEqual(sorted(archive.getnames()), sorted(e["member"] for e in index["raw_members"]))
                for entry in index["raw_members"]:
                    payload = archive.extractfile(entry["member"]).read()
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                    self.assertEqual(len(payload), entry["bytes"])
                for pin in report["input_pins"]:
                    self.assertEqual(hashlib.sha256(archive.extractfile(pin["member"]).read()).hexdigest(), pin["sha256"])
                for row in report["rows"]:
                    label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                    tag, _, body = archive.extractfile("raw/" + label + ".stdout.txt").read().decode().strip().partition(" ")
                    self.assertEqual(tag, "REAL_G_RESULT")
                    self.assertEqual(json.loads(body), row["observation"])
                for step in report["steps"]:
                    resource = Path(step["stdout"]).name.replace(".stdout.txt", ".resources.json")
                    self.assertEqual(json.loads(archive.extractfile("raw/" + resource).read()), step)
                    self.assertEqual(step["exit_code"], 0)
                    self.assertFalse(step["timed_out"])
                    self.assertEqual(step["memory_limit_gib"], 2)
                    self.assertGreaterEqual(step["reserve_gib"], 8)

    def test_archived_provenance_reconstructs_every_base_batch_and_work_count(self):
        folder = PARENT / "chronological_inputs/evidence"
        report = json.loads((folder / "matrix.json").read_text())
        with tarfile.open(folder / "raw_runs.tar.gz") as archive, tempfile.TemporaryDirectory() as temporary:
            for dataset in DATASETS:
                prefix = "inputs/" + dataset + "/"
                text = archive.extractfile(prefix + "contacts.csv").read().decode("ascii")
                contacts = [tuple(map(int, row)) for row in list(csv.reader(io.StringIO(text)))[1:]]
                self.assertEqual(len(contacts), 8192 + max(BATCHES))
                self.assertEqual([(r[1], r[0]) for r in contacts], sorted({(r[1], r[0]) for r in contacts}))
                self.assertEqual(len({r[2:] for r in contacts}), len(contacts))
                self.assertTrue(all(r[2] != r[3] for r in contacts))
                ids, records = compact_contacts(contacts)
                base_path = Path(temporary) / "base.slice"
                base_path.write_bytes(archive.extractfile(prefix + "base.slice").read())
                graph = load_slice(base_path)
                self.assertEqual(graph.vertices, len(ids))
                self.assertEqual(graph.records, records[:8192])
                for size in BATCHES:
                    update_path = Path(temporary) / "updates.slice"
                    update_path.write_bytes(archive.extractfile(prefix + f"insert-{size}.slice").read())
                    batch = load_slice(update_path)
                    self.assertEqual(batch.records, records[8192:8192 + size])
                    case = report["contract"]["cases"][f"{dataset}-chronological-insert-{size}"]
                    for key, value in facts(graph, batch).items():
                        self.assertEqual(case[key], value)

    def test_all_36_preceding_observations_and_states_are_identical(self):
        before = json.loads((PARENT / "real_inputs/evidence/matrix.json").read_text())
        def values(report):
            return {(r["case"], r["latency"], r["arm"]): (r["observation"], r["state_sha256"])
                    for r in report["rows"]}
        for name in ("regression", "parser_regression"):
            after = json.loads((PARENT / f"chronological_inputs/{name}/matrix.json").read_text())
            self.assertEqual(len(after["rows"]), 36)
            self.assertEqual(values(before), values(after))

    def test_input_rejection_is_retained_without_becoming_a_numerical_failure(self):
        folder = PARENT / "chronological_inputs/preflight"
        index = json.loads((folder / "index.json").read_text())
        report = json.loads((folder / "failed_matrix.json").read_text())
        self.assertEqual(index["status"], "PRETIMING_INPUT_REJECTION_RETAINED")
        self.assertEqual(index["numerical_observations"], 0)
        self.assertEqual(index["rejected_matrix_rows"], 36)
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertEqual(report["rows"], [])
        self.assertEqual(len(report["errors"]), 36)
        for entry in index["reports"]:
            path = folder / entry["file"]
            self.assertEqual(sha256_file(path), entry["sha256"])
            self.assertEqual(path.stat().st_size, entry["bytes"])
        with tarfile.open(folder / "raw_runs.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(e["member"] for e in index["raw_members"]))
            for entry in index["raw_members"]:
                payload = archive.extractfile(entry["member"]).read()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                self.assertEqual(len(payload), entry["bytes"])
            failed = [s for s in report["steps"] if s["exit_code"]]
            self.assertEqual(len(failed), 36)
            for step in failed:
                path = "attempt-v1/raw/" + Path(step["stderr"]).name
                self.assertEqual(archive.extractfile(path).read().decode().strip(),
                                 "Spine maintenance input must be sorted by src,dst")
            passed = [json.loads(archive.extractfile(name).read()) for name in archive.getnames()
                      if name.startswith(("reader-tests-v1/raw/", "smoke-v2/raw/")) and
                      name.endswith(".resources.json")]
            self.assertEqual(len(passed), 9)
            self.assertTrue(all(s["exit_code"] == 0 and not s["timed_out"] and
                                s["memory_limit_gib"] == 2 and s["reserve_gib"] >= 8 for s in passed))


if __name__ == "__main__":
    unittest.main()
