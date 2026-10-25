import struct
import unittest

from spine_cycle_sim.experiments.publication_board_probe.dense_analysis import inspect
from spine_cycle_sim.experiments.publication_board_probe.dense_inputs import descriptor
from spine_cycle_sim.experiments.publication_board_probe.launch import summarize


class DenseControlTests(unittest.TestCase):
    def layout(self, dense):
        summary = {"dense_partitions": dense, "sparse_groups": 2, "little": 11, "big": 3,
                   "vertices": 735324, "logical_edges": 5158388, "aligned_vertices": 786432}
        tasks = [dict(partition=0, subpartition=0, kernel=0, dst_offset=0, dst_len=65536,
                      offset_words=index * 16, words=16, kind="dense") for index in range(dense * 11 + 6)]
        return {"summary": summary, "tasks": tasks}

    def test_descriptor_preserves_published_extent_not_only_aligned_vertices(self):
        for dense, published, tasks in ((1, 1114112, 17), (3, 1245184, 39)):
            payload = descriptor(self.layout(dense))
            words = struct.unpack(f"<{len(payload) // 4}I", payload)
            self.assertEqual(words[4:12], (786432, published, published, tasks, dense, 2, 11, 3))
            self.assertEqual(len(words), 12 + tasks * 8)

    def test_descriptor_rejects_undeclared_density_or_incomplete_tasks(self):
        for dense in (0, 2, 4):
            with self.assertRaises(ValueError):
                descriptor(self.layout(dense))
        layout = self.layout(3)
        layout["tasks"].pop()
        with self.assertRaises(ValueError):
            descriptor(layout)

    def raw(self, dense):
        rows = []
        for repeat in range(4):
            for mode in ("baseline", "prebound", "author_order"):
                if repeat == 0 and mode != "baseline":
                    continue
                events = [{"role": role, "lane": lane, "start_ns": index, "end_ns": index + 100}
                          for role, lanes, count in (("little", range(11), dense), ("big", range(11, 14), 2),
                                                     ("hbm_wrapper", [0], 1), ("apply", [0], 1))
                          for lane in lanes for index in range(count)]
                rows.append({"mode": mode, "repeat": repeat, "independent_oracle_pass": True,
                             "events": events, "event_span_ms": 5, "resident_wall_ms": 6,
                             "gteps": 1, "first_wave_start_spread_ms": 0.1, "post_enqueue_wait_ms": 4})
        return {"status": "HOST_LAUNCH_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH", "publication_match": False,
                "case": {"binding": "author_initial", "offline": {"dense": dense, "sparse": 2, "little": 11, "big": 3}},
                "rows": rows, "summaries": summarize(rows)}

    def test_analysis_accepts_three_little_waves_not_only_old_one_wave_shape(self):
        for dense in (1, 3):
            result = inspect(self.raw(dense), dense)
            self.assertEqual(result["correctness_passing_executions"], 10)
            self.assertEqual(len(result["warm_baseline_timeline"]), 3)

    def test_analysis_rejects_missing_oracle_or_events_and_changed_medians(self):
        for mutation in ("oracle", "event", "median", "repeat", "density"):
            raw = self.raw(3)
            if mutation == "oracle":
                raw["rows"][0]["independent_oracle_pass"] = False
            elif mutation == "event":
                raw["rows"][0]["events"].pop()
            elif mutation == "median":
                raw["summaries"][0]["gteps"] = 2
            elif mutation == "repeat":
                raw["rows"].pop()
            else:
                raw["case"]["offline"]["dense"] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                inspect(raw, 3)


if __name__ == "__main__":
    unittest.main()
