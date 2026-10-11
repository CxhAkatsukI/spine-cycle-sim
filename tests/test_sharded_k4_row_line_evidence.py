"""Reject changed sources and weakened resource records in portable delivery."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.evidence import bounded, sources


class RowLineEvidenceTests(unittest.TestCase):
    def test_frozen_source_closure_and_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            path = run / "source.cpp"
            path.write_text("unchanged\n")
            pin = {"path": "/original/source.cpp", "sha256": sha256_file(path)}
            tool = {"path": "/vendor/xsim", "sha256": "external_tool_hash"}
            manifest = {"pins": [pin, tool], "source_copies": [pin | {"archive_path": "source.cpp"}]}
            self.assertEqual(sources(run, manifest, ("xsim",)), {pin["path"]: path})
            for changed in (
                manifest | {"source_copies": []},
                manifest | {"pins": [pin, pin, tool]},
                manifest | {"source_copies": [pin | {"archive_path": "../source.cpp"}]},
                manifest | {"source_copies": [pin | {"archive_path": str(path)}]},
            ):
                with self.assertRaises(ValueError):
                    sources(run, changed, ("xsim",))
            path.write_text("changed\n")
            with self.assertRaises(ValueError):
                sources(run, manifest, ("xsim",))

    def test_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "source").write_text("same")
            (run / "link").symlink_to(run / "source")
            pin = {"path": "/source", "sha256": sha256_file(run / "source")}
            with self.assertRaises(ValueError):
                sources(run, {"pins": [pin], "source_copies": [pin | {"archive_path": "link"}]})

    def test_watchdog_boundaries_cannot_be_relabeled(self):
        record = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                  "command": ["tool", "--flag"], "cwd": "/original", "timeout_seconds": 120,
                  "tree_memory_gib": 4, "reserve_gib": 16,
                  "minimum_available_bytes": 17 * 1024**3, "peak_tree_rss_kib": 3 * 1024**2}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "resources.json"
            path.write_text(json.dumps(record))
            bounded(path, record["command"], "/original", 120, 4)
            for key, value in (
                ("exit_code", 1), ("stop_reason", "timeout"), ("cleanup_snapshot_error", "failed"),
                ("command", ["another_tool"]), ("cwd", "/changed"), ("timeout_seconds", 300),
                ("tree_memory_gib", 8), ("reserve_gib", 0),
                ("minimum_available_bytes", 15 * 1024**3), ("peak_tree_rss_kib", 5 * 1024**2),
            ):
                path.write_text(json.dumps(record | {key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    bounded(path, record["command"], "/original", 120, 4)


if __name__ == "__main__":
    unittest.main()
