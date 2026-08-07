from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_candidate10_physical_memory.py"
SPEC = importlib.util.spec_from_file_location("physical_memory_analyzer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PhysicalMemoryAnalyzerTest(unittest.TestCase):
    def _write_results(self, root: Path, sha: str) -> None:
        binding = {
            "plugin_sha256": sha,
            "plugin_path": "/tmp/plugin/libspine_cycle.so",
            "search_path": "/tmp/plugin:/tmp/sst-elements",
            "command_option": "--lib-path=/tmp/plugin:/tmp/sst-elements",
        }
        for system, filename in (
            ("spine", "summary.json"),
            ("grasu_regraph", "manifest.json"),
        ):
            directory = root / "run" / system
            directory.mkdir(parents=True)
            (directory / filename).write_text(
                json.dumps(
                    {
                        "sst_plugin_sha256": sha,
                        "sst_library_binding": binding,
                    }
                ),
                encoding="utf-8",
            )

    def test_plugin_fingerprint_requires_identical_exact_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = "a" * 64
            self._write_results(root, sha)
            result = MODULE._validated_plugin_fingerprint(
                (("full_pagerank", root),), {"run"}
            )
            self.assertEqual(result["plugin_sha256"], sha)
            self.assertEqual(result["validated_child_results"], 2)

    def test_plugin_fingerprint_rejects_child_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_results(root, "a" * 64)
            path = root / "run" / "grasu_regraph" / "manifest.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sst_plugin_sha256"] = "b" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid SST plugin identity"):
                MODULE._validated_plugin_fingerprint(
                    (("full_pagerank", root),), {"run"}
                )
