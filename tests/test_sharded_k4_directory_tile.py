"""Conserve the larger directory cache's work and require actual schedules."""

import copy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.analysis import ROW_BASE
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.validation import (
    ALL_TRIALS, compare, functional, model_schedule, schedules,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.analysis import metadata
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.archive_parts import assembled, split


def cases(tile):
    result = []
    for trial, (vertices, placement, length, latency, stall) in enumerate(ALL_TRIALS):
        sources = [src for src in range(vertices) if placement == 0 or
                   placement == 1 and src + 1 == vertices or placement == 2 and src == 0 or
                   placement == 3 and src % 7 == 0]
        end = min(vertices, (sources[-1] // tile + 1) * tile) if sources else 0
        lines = [(vertices - 1) // 8, *range((end + 7) // 8)] if vertices else []
        requests = [{"address": ROW_BASE + line * 64, "size": 64, "beats": 1} for line in lines]
        requests += [{"address": 0x10000 + segment * 64, "size": 64, "beats": 1}
                     for segment in range(len(sources) * length)]
        result.append({"trial": trial, "vertices": vertices, "placement": placement,
                       "length": length, "latency": latency, "stall": stall,
                       "packets": len(sources) * length * 2, "pma_beats": len(sources) * length,
                       "pma_transfer_bytes": len(sources) * length * 64,
                       "cycles": 1000 + trial, "requests": requests,
                       "row_transfer_bytes": len(lines) * 64, "row_requests": len(lines)})
    return result


class DirectoryTileTransportTests(unittest.TestCase):
    def test_named_parts_preserve_all_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "source.gz"
            archive.write_bytes(bytes(range(32)))
            parts = split(archive, root / "published", part_bytes=8, archive_name="finite.gz")
            record = {"archive_parts": parts, "archive_bytes": 32, "archive_sha256": sha256_file(archive)}
            with assembled(root / "published", record, archive_name="finite.gz") as result:
                self.assertEqual(result.read_bytes(), archive.read_bytes())
            (root / "published" / parts[0]["path"]).write_bytes(b"changed!")
            with self.assertRaisesRegex(ValueError, "part identity"):
                with assembled(root / "published", record, archive_name="finite.gz"):
                    self.fail("changed part admitted")

    def test_unsafe_transport_name_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("", ".", "..", "../archive", "/archive"):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "local archive"):
                    split(Path(temporary) / "input", Path(temporary) / "output", archive_name=name)


class DirectoryTileTests(unittest.TestCase):
    def test_progressive_responses_are_explicit_not_a_legacy_change(self):
        old = metadata("tile", 1024, True, True)
        new = metadata("tile", 1024, True, True, True)
        self.assertNotIn("bank_read_beats", old)
        self.assertEqual(new, old | {"bank_read_beats": True})
        for arm in ("original", "cross_row"):
            self.assertEqual(metadata(arm), metadata(arm, 1024, True, True, True))
            self.assertEqual(metadata(arm), metadata(arm, 1024, True, True, True, 256))
        self.assertEqual(metadata("tile", 1024, True, True, True, 256),
                         new | {"bank_fifo_lines": 256})

    def test_finite_model_requires_the_realized_topology(self):
        depths = {"load_directory_tile_loop": 3, "read_tiled_sources_loop": 2,
                  "publish_packet_loop": 2, "load_join_directory_loop": 2,
                  "read_cached_bank_loop": 3, "read_external_bank_loop": 3}
        result = {"status": "HLS_SCHEDULE_PASS_NOT_BOARD", "tile_rows": 1024,
                  "packet_pipeline": True, "bank_stream": True,
                  "schedule": {key: {"ii": 1, "depth": depth} for key, depth in depths.items()}}
        self.assertEqual(model_schedule(result), (1024, True, True))
        self.assertEqual(model_schedule(result | {"bank_fifo_lines": 256}), (1024, True, True))
        for value in (0, 127, 512, True, "256"):
            with self.subTest(bank_lines=value), self.assertRaisesRegex(ValueError, "realized"):
                model_schedule(result | {"bank_fifo_lines": value})
        for key, value in (("status", "FAILED_RETAINED"), ("tile_rows", 128),
                           ("packet_pipeline", False), ("bank_stream", "true")):
            bad = copy.deepcopy(result)
            bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "realized"):
                model_schedule(bad)
        for loop in depths:
            bad = copy.deepcopy(result)
            bad["schedule"][loop]["ii"] = 2
            with self.subTest(loop=loop), self.assertRaisesRegex(ValueError, "realized"):
                model_schedule(bad)
            del bad["schedule"][loop]
            with self.assertRaisesRegex(ValueError, "realized"):
                model_schedule(bad)

    def test_tail_prefetch_is_not_free(self):
        result = compare(cases(8), cases(128))
        self.assertEqual(len(result), 18)
        self.assertGreater(result[16]["candidate_row_bytes"], result[16]["reference_row_bytes"])

    def test_burst_and_single_beat_work_are_equivalent(self):
        candidate = cases(128)
        for row in candidate:
            directory = [req for req in row["requests"] if req["address"] >= ROW_BASE]
            if len(directory) > 2:
                row["requests"] = [directory[0], dict(directory[1], beats=len(directory) - 1),
                                   *[req for req in row["requests"] if req["address"] < ROW_BASE]]
        self.assertEqual(len(compare(cases(8), candidate)), 18)

    def test_missing_tail_and_changed_pma_are_rejected(self):
        candidate = cases(128)
        candidate[16]["requests"].pop(1)
        with self.assertRaisesRegex(ValueError, "prefetched"):
            compare(cases(8), candidate)
        candidate = cases(128)
        candidate[1]["requests"][-1]["address"] += 64
        with self.assertRaisesRegex(ValueError, "PMA beat"):
            compare(cases(8), candidate)
        with self.assertRaisesRegex(ValueError, "complete"):
            compare(cases(8)[:-1], cases(128))

    def test_declared_semantics_are_not_relaxed(self):
        reference = cases(8)
        for key in ("packets", "stall", "latency", "pma_transfer_bytes"):
            candidate = cases(128)
            candidate[5][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(reference, candidate)

    def test_three_functional_formats_with_boundary_cases(self):
        record = "ROW_PREFETCH_EQUIVALENCE status=PASS cases=362 packets=6786 skip_empty=1 row_line=1 cross_row=1\n"
        functional(record * 3)
        for text in (record * 2, (record * 3).replace("362", "254", 1)):
            with self.assertRaises(ValueError):
                functional(text)

    def test_real_schedule_and_duplicate_or_missing_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xml = """<profile><UserAssignments><TargetClockPeriod>6.67</TargetClockPeriod>
                </UserAssignments><PerformanceEstimates><SummaryOfTimingAnalysis>
                <EstimatedClockPeriod>5.8</EstimatedClockPeriod></SummaryOfTimingAnalysis>
                <SummaryOfLoopLatency>{loops}</SummaryOfLoopLatency></PerformanceEstimates></profile>"""
            loops = "".join(f"<{label}><PipelineII>1</PipelineII><PipelineDepth>74</PipelineDepth></{label}>"
                            for label in ("load_directory_tile_loop", "read_tiled_sources_loop"))
            path = root / "one_csynth.xml"
            path.write_text(xml.format(loops=loops))
            self.assertEqual(schedules(root)["read_tiled_sources_loop"]["ii"], 1)
            (root / "two_csynth.xml").write_text(path.read_text())
            with self.assertRaisesRegex(ValueError, "one actual"):
                schedules(root)
            (root / "two_csynth.xml").unlink()
            path.write_text(xml.format(loops=""))
            with self.assertRaisesRegex(ValueError, "one actual"):
                schedules(root)


if __name__ == "__main__":
    unittest.main()
