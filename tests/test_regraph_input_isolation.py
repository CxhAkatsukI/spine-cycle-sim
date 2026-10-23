"""Input-only evidence cannot replace a complete-R comparison."""

from copy import deepcopy
import json
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import input_isolation_analysis as study
from tests.test_regraph_reader_ports import cases as historical
from tests.test_regraph_prefetch_compact import reference


def cases():
    old = historical()
    for row in old:
        obs = row["observations"]
        for w in obs["workers"]:
            w["read_beats"] = w["physical_slots"] // 16 + 33
            w["read_bytes"] = w["read_beats"] * 64
        obs["read_bytes"] = sum(w["read_bytes"] for w in obs["workers"])
        for key in ("accepted_beats", "intents", "grants", "consumed_grants"):
            obs["transport"][key] = obs["read_bytes"] // 64
    indexed = {(r["latency"], r["reverse"], "single" if r["ports"] == 1 else "dual-port", 1):
               r["observations"] for r in old}
    rows = []
    for latency, reverse, mode, period in study.MATRIX:
        obs = deepcopy(indexed[(latency, reverse, mode if mode != "current-input" else "dual-port", 1)])
        if mode == "current-input":
            obs.update(schema_version=6, physical_masters=12, masters_per_frontend=3,
                directory_tiles=2, bank_lines=512, pipeline_capacity=3, pipeline_latency=2,
                refill_policy="full-burst", cycles=100 if period == 1 else 500)
            for w in obs["workers"]:
                w.update(sink_done=obs["cycles"], parents_per_port=[16, 8, 4],
                    reader_pipeline_peak=3, publisher_pipeline_peak=3, max_bank_lines=512,
                    extent_beats=1, directory_beats=32, pma_beats=w["physical_slots"] // 16,
                    rows=256, empty_rows=20, pma_requests=8, short_pma_requests=0,
                    publisher_output_stalls=0 if period == 1 else 40)
        rows.append(dict(latency=latency, reverse=reverse, mode=mode,
                         sink_period=period, observations=obs))
    complete = reference()
    for row in deepcopy(complete):
        row["arm"] = "prefetch_sssp_write_issue"
        row["observations"]["result"]["cycles"] *= 2
        complete.append(row)
    return rows, old, complete


class InputIsolationTests(unittest.TestCase):
    def test_valid_current_input_ledger_and_no_retention_claim(self):
        rows, old, complete = cases()
        for row in rows:
            self.assertEqual(study.parse("PREFETCH_COMPACT " + json.dumps(row["observations"])), row["observations"])
        result = study.summarize(rows, old, complete)
        self.assertEqual(result["historical_rows_exact"], 8)
        self.assertFalse(result["integrated_R_retention_passed"])
        self.assertFalse(result["hardware_calibrated"])

    def test_explicit_topology_and_limits_required(self):
        current = cases()[0][2]["observations"]
        for key, value in (("physical_masters", 16), ("directory_tiles", 1), ("bank_lines", 1024),
                           ("pipeline_capacity", True), ("refill_policy", "available-space")):
            obs = deepcopy(current); obs[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                study.parse("PREFETCH_COMPACT " + json.dumps(obs))

    def test_counter_and_credit_mutations_rejected(self):
        current = cases()[0][2]["observations"]
        for key, value in (("extent_beats", 0), ("directory_beats", 1), ("pma_beats", 3),
                           ("parents_per_port", [16, 16, 17]), ("parents_per_port", [16, 16]),
                           ("rows", 0), ("short_pma_requests", 5), ("max_bank_lines", 513)):
            obs = deepcopy(current); obs["workers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                study.parse("PREFETCH_COMPACT " + json.dumps(obs))

    def test_exact_old_controls_and_registration_required(self):
        for index in (0, 6):
            rows, old, complete = cases()
            rows[index]["observations"]["cycles"] += 1
            with self.assertRaises(ValueError): study.summarize(rows, old, complete)
        rows, old, complete = cases()
        with self.assertRaisesRegex(ValueError, "matrix"):
            study.summarize(rows[:-1], old, complete)

    def test_backpressure_and_logical_bytes_required(self):
        for mutation in ("backpressure", "bytes"):
            rows, old, complete = cases()
            for row in rows:
                if row["mode"] != "current-input": continue
                if mutation == "bytes": row["observations"]["read_bytes"] += 64
                elif row["sink_period"] == 5:
                    for w in row["observations"]["workers"]: w["publisher_output_stalls"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                study.summarize(rows, old, complete)

    def test_matching_complete_reference_required(self):
        rows, old, complete = cases()
        complete[-1]["observations"]["result"]["rounds"] = 45
        with self.assertRaises(ValueError): study.summarize(rows, old, complete)


if __name__ == "__main__":
    unittest.main()
