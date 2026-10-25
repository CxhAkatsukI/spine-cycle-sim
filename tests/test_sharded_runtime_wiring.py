import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ShardedRuntimeWiringTests(unittest.TestCase):
    def _update_parameters(self, overrides: dict[str, str]) -> dict:
        parameters = {}
        probe = SimpleNamespace(addParams=parameters.update)
        fake_sst = SimpleNamespace(Component=lambda *_: probe)
        with tempfile.TemporaryDirectory() as output:
            environment = {
                "GRASU_SST_MEMORY_BACKEND": "direct_dramsim3",
                "GRASU_SST_DRAM_OUTPUT": output,
                **overrides,
            }
            with patch.dict(os.environ, environment, clear=True), patch.dict(
                sys.modules, {"sst": fake_sst}
            ):
                runpy.run_path(str(ROOT / "sst/grasu_regraph_vertical.py"))
        return parameters

    def test_cached_update_topology_is_explicit_and_defaults_remain_off(self) -> None:
        parameters = self._update_parameters({})
        self.assertEqual(parameters["grasu_compact_parallel_search"], 0)
        self.assertEqual(parameters["grasu_compact_search_contexts"], 16)
        self.assertEqual(parameters["grasu_compact_cached_hot"], 0)
        self.assertEqual(parameters["grasu_compact_cache_valid_extent"], 0)

    def test_cached_update_environment_reaches_component_parameters(self) -> None:
        parameters = self._update_parameters({
            "GRASU_SST_COMPACT_PARALLEL_SEARCH": "1",
            "GRASU_SST_COMPACT_SEARCH_CONTEXTS": "64",
            "GRASU_SST_COMPACT_CACHED_HOT": "1",
            "GRASU_SST_COMPACT_CACHE_VALID_EXTENT": "1",
        })
        for name in ("parallel_search", "cached_hot", "cache_valid_extent"):
            self.assertEqual(parameters[f"grasu_compact_{name}"], 1)
        self.assertEqual(parameters["grasu_compact_search_contexts"], 64)

    def test_sst_core_and_graph_expose_fail_closed_placement(self) -> None:
        core = (ROOT / "cpp/sst/online_memory_probe.cpp").read_text(
            encoding="utf-8"
        )
        graph = (ROOT / "sst/grasu_regraph_vertical.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"grasu_sharded_runtime_placement"', core)
        self.assertIn('"grasu_runtime_channel_capacity_bytes"', core)
        self.assertIn("GRASU_SST_SHARDED_RUNTIME_PLACEMENT", graph)
        self.assertIn("GRASU_SST_RUNTIME_CHANNEL_CAPACITY_BYTES", graph)

    def test_all_publication_runners_forward_sharded_placement(self) -> None:
        runners = (
            "scripts/run_sst_grasu_regraph_hls_weighted.py",
            "scripts/run_sst_connected_components.py",
            "scripts/run_sst_grasu_regraph_hls_pagerank.py",
            "scripts/run_sst_grasu_regraph_hls_residual_pagerank.py",
        )
        for relative in runners:
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(runner=relative):
                self.assertIn("GRASU_SST_SHARDED_RUNTIME_PLACEMENT", source)
                self.assertIn("GRASU_SST_RUNTIME_CHANNEL_CAPACITY_BYTES", source)
                self.assertIn('"grasu_sharded_runtime_placement"', source)
                self.assertIn('"grasu_runtime_channel_capacity_bytes"', source)


if __name__ == "__main__":
    unittest.main()
