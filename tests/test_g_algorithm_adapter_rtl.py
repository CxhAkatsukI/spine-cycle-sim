"""Fresh XO and containment gates, without invoking vendor simulation tools."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.study import RTL_PREFIX
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import adapter_rtl


def fixture(root):
    compilation, output, tools = (root / name for name in ("compile", "output", "tools"))
    for directory in (compilation, output, tools):
        directory.mkdir()
    xo = compilation / "adapter.xo"
    with ZipFile(xo, "w") as archive:
        archive.writestr(RTL_PREFIX + "pma_to_regraph_adapter.v", "module pma_to_regraph_adapter; endmodule")
        archive.writestr(RTL_PREFIX + "helper.vh", "// fixture")
    (compilation / "manifest.json").write_text(json.dumps({"algorithm": "connected_components",
        "integration_revision": "fixture-revision", "compiles": [{"kernel": "pma_to_regraph_adapter", "xo": str(xo)}]}))
    for name in ("xvlog", "xelab", "xsim"):
        (tools / name).write_text("fixture executable")
    flags = {"GRASU_REGRAPH_" + name: value for name, value in {
        "SHARDED_PMA": "1", "DESTINATION_ONLY": "1", "BANK_STREAM": "1",
        "BANK_FIFO_LINES": "256", "DIRECTORY_TILE_ROWS": "1024", "ROW_LINE_READ": "1"}.items()}
    checked = {"status": "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW", "inputs": [identity(xo)],
               "interfaces": {"pma_to_regraph_adapter": {"macros": flags}}}
    (output / "compile-review").mkdir()
    (output / "compile-review/results.json").write_text(json.dumps(checked))
    return compilation, output, tools, checked


class AdapterRtlTests(unittest.TestCase):
    def test_fresh_xo_full_top_benches_and_all_declared_trials_are_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            compilation, output, tools, checked = fixture(Path(temporary))
            with patch.object(adapter_rtl.review, "run", return_value=checked):
                result = adapter_rtl.prepare(compilation, compilation, output, tools)
            self.assertEqual(len(result["trials"]), 23)
            self.assertIn((1025, 1, 1, 128, 1000), result["trials"])
            self.assertIn((129, 0, 3, 128, 1000), result["trials"])
            self.assertEqual(result["algorithm"], "connected_components")
            self.assertEqual(result["commands"]["compile"][0], str(tools / "xvlog"))
            self.assertIn("pma_to_regraph_adapter.v", result["commands"]["compile"])
            self.assertNotIn("helper.vh", result["commands"]["compile"])
            self.assertTrue(all(result[key] is False for key in adapter_rtl.CLAIMS))
            pinned = {Path(row["path"]).name for row in result["pins"]}
            self.assertTrue({"adapter.xo", "adapter_axi_tb.sv", "bank_stream_axi_tb.sv",
                             "destination_bank_stream_axi_tb.sv", "run.tcl"} <= pinned)
            self.assertEqual(result["commands"]["compile"][2], "destination_bank_stream_axi_tb.sv")
            self.assertNotIn("bank_stream_axi_tb.sv", result["commands"]["compile"])
            self.assertIn("local_dst19_plus_partition_offset", result["packet_scope"])
            bench = (output / "rtl/destination_bank_stream_axi_tb.sv").read_text()
            self.assertIn("`define PMA_ADAPTER_DESTINATION_ONLY_TEST", bench)
            self.assertEqual(result["compile_review_status"], checked["status"])

    def test_wrong_destination_row_width_or_fifo_contract_is_rejected(self):
        for key, value in (("SHARDED_PMA", "0"), ("DESTINATION_ONLY", "0"), ("BANK_STREAM", "0"),
                           ("BANK_FIFO_LINES", "128"), ("DIRECTORY_TILE_ROWS", "128"), ("ROW_LINE_READ", "0")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                compilation, output, tools, checked = fixture(Path(temporary))
                checked["interfaces"]["pma_to_regraph_adapter"]["macros"]["GRASU_REGRAPH_" + key] = value
                with patch.object(adapter_rtl.review, "run", return_value=checked), self.assertRaisesRegex(ValueError, "ABI"):
                    adapter_rtl.prepare(compilation, compilation, output, tools)
                self.assertFalse((output / "rtl").exists())

    def test_duplicate_or_missing_adapter_cannot_use_unrelated_xo(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as temporary:
                compilation, output, tools, checked = fixture(Path(temporary))
                path = compilation / "manifest.json"
                manifest = json.loads(path.read_text())
                manifest["compiles"] = manifest["compiles"] * 2 if duplicate else []
                path.write_text(json.dumps(manifest))
                with patch.object(adapter_rtl.review, "run", return_value=checked), self.assertRaisesRegex(ValueError, "one freshly"):
                    adapter_rtl.prepare(compilation, compilation, output, tools)

    def test_failed_or_uncontained_run_is_not_accepted(self):
        good = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                "tree_memory_gib": 4, "reserve_gib": 32, "timeout_seconds": 180,
                "peak_tree_rss_kib": 1000, "minimum_available_bytes": 40 * 1024**3}
        adapter_rtl.require_execution(good)
        for key, value in (("exit_code", 1), ("stop_reason", "timeout"), ("cleanup_snapshot_error", "failed"),
                           ("tree_memory_gib", 8), ("reserve_gib", 16), ("timeout_seconds", 120),
                           ("peak_tree_rss_kib", 5 * 1024**2), ("minimum_available_bytes", 31 * 1024**3)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                adapter_rtl.require_execution({**good, key: value})

    def test_cgroup_failure_precedes_vendor_environment_or_compilation_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            group = root / "cgroup"
            group.mkdir()
            (group / "memory.events").write_text("oom 0\noom_kill 0\n")
            with patch.object(adapter_rtl, "current", return_value=group), patch.object(adapter_rtl, "Lease"), \
                    patch.object(adapter_rtl, "verify", side_effect=ValueError("unbounded")), \
                    patch.object(adapter_rtl.environment, "capture") as capture, self.assertRaisesRegex(ValueError, "unbounded"):
                adapter_rtl.run(root, root, root / "output", root, root, root, root)
            capture.assert_not_called()
            result = json.loads((root / "output/execution.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertTrue(all(result[key] is False for key in adapter_rtl.CLAIMS))


if __name__ == "__main__":
    unittest.main()
