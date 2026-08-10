import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShardedRuntimeWiringTests(unittest.TestCase):
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
