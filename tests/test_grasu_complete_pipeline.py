import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline import preparation
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline import delivery
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.analysis import (
    COUNTS, MARKER, WARNING_PAIR, analyze, diagnostics, expected_edges, expected_ports,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged


class CompletePipelineTests(unittest.TestCase):
    def rows(self):
        return [dict(registered=arm, generation=generation, batch=batch,
                     updates=count, edges=expected_edges(batch),
                     **dict(zip(("hot_even", "cold_even", "hot_odd", "cold_odd"),
                                expected_ports(batch))))
                for arm in range(2) for generation in range(2)
                for batch, count in enumerate(COUNTS)]

    def stdout(self, rows):
        return "\n".join([*("COMPLETE_G_ROW " + json.dumps(row) for row in rows), MARKER])

    def stderr(self):
        return "\n".join(WARNING_PAIR * 544)

    def test_declared_scope_includes_empty_cold_hot_and_metadata_refresh(self):
        rows = self.rows()
        self.assertEqual(analyze(self.stdout(rows), self.stderr()), rows)
        self.assertEqual(expected_edges(0), 40)
        self.assertEqual(expected_edges(1), 43)
        self.assertEqual(expected_edges(2), 46)
        self.assertEqual(expected_ports(0), [0, 0, 0, 0])
        for batch in (1, 2):
            self.assertTrue(all(expected_ports(batch)))
            self.assertEqual(sum(expected_ports(batch)), COUNTS[batch])
        self.assertIn("timing_admitted=false", MARKER)
        self.assertIn("internal_cache_ddr_fifos=unbounded", MARKER)

    def test_missing_duplicate_reordered_and_corrupt_ledgers_rejected(self):
        for fault in ("missing", "duplicate", "order", "updates", "edges", "cold_even"):
            rows = copy.deepcopy(self.rows())
            if fault == "missing": rows.pop()
            elif fault == "duplicate": rows.append(copy.deepcopy(rows[-1]))
            elif fault == "order": rows[0], rows[1] = rows[1], rows[0]
            else: rows[-1][fault] += 1
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                analyze(self.stdout(rows), self.stderr())
        stdout = self.stdout(self.rows())
        for wrong in (stdout.replace(MARKER, ""), stdout + "\n" + MARKER):
            with self.assertRaises(ValueError): analyze(wrong, self.stderr())
        with self.assertRaises(ValueError): analyze(stdout, "unexpected HLS diagnostic")

    def test_only_exact_vendor_warning_counts_admitted(self):
        self.assertEqual(diagnostics(self.stderr())["retained_vendor_width_warning_pairs"], 544)
        self.assertEqual(diagnostics(self.stderr().replace("\n", "")), diagnostics(self.stderr()))
        for wrong in ("", self.stderr() + "\n" + WARNING_PAIR[0],
                      self.stderr().replace(WARNING_PAIR[1], "other warning", 1)):
            with self.assertRaises(ValueError): diagnostics(wrong)

    def test_freeze_keeps_same_named_runners_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / "cpp/tests/evaluation_impact/common_g"
            upstream, integration = root / "upstream", root / "integration"
            production = integration / "repos/GraSU/GraSU/GraSU_kernels/src"
            paths = [tests / "complete_pipeline/control.cpp", tests / "hls/search_pipeline/types.hpp",
                     *(upstream / name for name in ("kernel_config.h", "kernel_process_cache.cpp")),
                     *(production / name for name in
                       ("kernel_config.h", "kernel_dispatch.cpp", "kernel_process_ddr.cpp")),
                     *(tests / "hls" / name for name in ("cache_full.cpp", "cache_bank.hpp", "cache_lane.hpp")),
                     *(tests / "hls/search_binding" / name for name in ("top.cpp", "top.hpp")),
                     integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
                     *(root / "spine_cycle_sim/experiments" / name for name in
                       ("upstream_controls/execution.py", "campaign_runtime.py",
                        "evaluation_impact/common_g/weighted_abi/preparation.py",
                        "evaluation_impact/common_g/search_pipeline/synthesis.py"))]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(path), encoding="ascii")
            with patch.object(preparation, "ROOT", root):
                pins = preparation.prepare(root / "attempt", upstream, integration)
            self.assertEqual(len(pins), len({pin["path"] for pin in pins}))
            unchanged(pins)
            names = [pin["path"] for pin in pins if pin["path"].endswith("preparation.py")]
            self.assertEqual(len(names), 2)
            self.assertNotEqual(Path(names[0]).read_text(), Path(names[1]).read_text())

    def test_compile_preserves_real_capacity_and_adapter_configuration(self):
        command = preparation.command(Path("source"), Path("vendor"), "g++", Path("probe"))
        self.assertIn("-DCACHE_BANK_REGISTERED", command)
        self.assertIn("-DGRASU_REGRAPH_BANK_STREAM=1", command)
        self.assertIn("-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024", command)
        self.assertIn("-DGRASU_REGRAPH_BANK_FIFO_LINES=256", command)
        self.assertFalse(any("MAX_CACHE_SEGMENT=" in item for item in command))

    def test_delivery_preserves_failed_attempt_and_rejects_archive_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt = root / "failed"
            source = attempt / "source/control.cpp"
            source.parent.mkdir(parents=True)
            source.write_text("frozen source", encoding="ascii")
            report = {"status": "FAILED_RETAINED", "errors": ["retained checker failure"],
                      "source": [{"path": str(source), "sha256": sha256_file(source)}],
                      **dict.fromkeys(delivery.CLAIMS, False)}
            (attempt / "results.json").write_text(json.dumps(report))
            index = delivery.package(root / "evidence", [attempt])
            self.assertEqual(index["attempts"][0]["status"], "FAILED_RETAINED")
            self.assertEqual(index, delivery.verify(root / "evidence"))
            archive = root / "evidence" / index["attempts"][0]["archive"]
            archive.write_bytes(archive.read_bytes() + b"corruption")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                delivery.verify(root / "evidence")

    def test_delivery_rejects_claim_promotion_and_duplicate_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source/control.cpp"
            source.parent.mkdir()
            source.write_text("frozen source", encoding="ascii")
            report = {"status": "FAILED_RETAINED", "errors": ["retained failure"],
                      "source": [{"path": str(source), "sha256": sha256_file(source)}],
                      **dict.fromkeys(delivery.CLAIMS, False)}
            for key in delivery.CLAIMS:
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "claim boundary"):
                    delivery.validate(root, {**report, key: True})
            with self.assertRaisesRegex(ValueError, "duplicate frozen"):
                delivery.validate(root, {**report, "source": report["source"] * 2})


if __name__ == "__main__":
    unittest.main()
