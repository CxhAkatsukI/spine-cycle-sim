"""Opt-in checks against a fresh, explicitly selected SST element library."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from spine_cycle_sim.sst_library import forced_sst_library_binding


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = os.environ.get("SPINE_SST_CACHE_TEST_LIBRARY", "")


@unittest.skipUnless(PLUGIN, "set SPINE_SST_CACHE_TEST_LIBRARY to a fresh plugin directory")
class SstCachedUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sst = Path(os.environ.get("SPINE_SST_CACHE_TEST_BINARY", "/data/feiyang/sst/bin/sst"))
        cls.binding = forced_sst_library_binding(cls.sst, Path(PLUGIN))
        output = os.environ.get("SPINE_SST_CACHE_TEST_OUTPUT")
        if output:
            cls.output = Path(output)
            cls.output.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory()
            cls.addClassCleanup(temporary.cleanup)
            cls.output = Path(temporary.name)

    def _run(
        self, name: str, overrides: dict[str, str], *, binding: dict | None = None
    ) -> tuple[int, dict | None, str]:
        case = self.output / name
        case.mkdir()
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("GRASU_SST_", "SPINE_CAMPAIGN_"))
        }
        parameters = {
            "GRASU_SST_MODE": "grasu_regraph_hls_weighted_sssp",
            "GRASU_SST_UPDATE_ONLY": "1",
            "GRASU_SST_MAX_CYCLES": "10000",
            "GRASU_SST_OUTPUT": str(case / "result.json"),
            "GRASU_SST_DRAM_OUTPUT": str(case / "dram"),
            **overrides,
        }
        environment.update(parameters)
        selected = binding or self.binding
        command = [str(self.sst), selected["command_option"],
                   str(ROOT / "sst/grasu_regraph_vertical.py")]
        sources = ("sst/grasu_regraph_vertical.py",
                   "tests/data/grasu_regraph_unit_initial.slice",
                   "tests/data/grasu_regraph_unit_update.slice")
        manifest = {
            "command": command, "environment_overrides": parameters,
            "binding": selected,
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                              for path in sources},
        }
        (case / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with (case / "stdout.log").open("w") as stdout, (case / "stderr.log").open("w") as stderr:
            completed = subprocess.run(command, cwd=ROOT, env=environment,
                                       stdout=stdout, stderr=stderr, timeout=120, check=False)
        result = case / "result.json"
        return (completed.returncode,
                json.loads(result.read_text()) if result.exists() else None,
                (case / "stderr.log").read_text() + (case / "stdout.log").read_text())

    def _assert_update(self, result: dict) -> None:
        self.assertTrue(result["success"])
        self.assertEqual(result["measurement_window"], "pure_update_only")
        self.assertEqual(result["timing_evidence"],
                         "execution_driven_update_engine_sst_hbm_not_cycle_calibrated")
        self.assertEqual(result["backend"], "sst_memHierarchy_dramsim3")
        self.assertEqual(result["logical_updates"], 2)
        self.assertEqual(result["correctness_mismatches"], 0)
        self.assertTrue(result["update_state_match"])
        self.assertTrue(result["memory_locality_ledger_match"])
        self.assertTrue(result["backend_arbitration"]["ledger_closed"])
        self.assertEqual(result["backend_requests"],
                         result["backend_traffic"]["combined"]["requests"])
        self.assertEqual(result["compute_cycles"], 0)

    def test_bounded_cache_configuration_and_traffic(self) -> None:
        for contexts in (16, 64):
            with self.subTest(contexts=contexts):
                code, result, log = self._run(f"bounded_{contexts}", {
                    "GRASU_SST_COMPACT_PARALLEL_SEARCH": "1",
                    "GRASU_SST_COMPACT_SEARCH_CONTEXTS": str(contexts),
                    "GRASU_SST_COMPACT_CACHED_HOT": "1",
                    "GRASU_SST_COMPACT_CACHE_VALID_EXTENT": "1",
                })
                self.assertEqual(code, 0, log)
                self._assert_update(result)
                self.assertEqual(result["update_observability"]["configuration"], {
                    "compact_parallel_search": True, "compact_search_contexts": contexts,
                    "compact_cached_hot": True, "compact_cache_valid_extent": True,
                    "cache_segments_per_half": 131072,
                })
                self.assertEqual(result["update_pma_reads"], 32)
                self.assertEqual(result["update_pma_writes"], 32)

    def test_sharded_runtime_preserves_update_state_and_ledger(self) -> None:
        code, result, log = self._run("sharded_bounded", {
            "GRASU_SST_COMPACT_PARALLEL_SEARCH": "1",
            "GRASU_SST_COMPACT_CACHED_HOT": "1",
            "GRASU_SST_COMPACT_CACHE_VALID_EXTENT": "1",
            "GRASU_SST_SHARDED_RUNTIME_PLACEMENT": "1",
            "GRASU_SST_PARTITION_VERTICES": "4",
            "GRASU_SST_COMPUTE_PIPELINES": "4",
            "GRASU_SST_SHARED_DOWNSTREAM": "1",
        })
        self.assertEqual(code, 0, log)
        self._assert_update(result)
        # Host-selected single-window children do not use the legacy router.
        self.assertEqual(result["update_observability"]["destination_partitions_touched"], 2)
        self.assertEqual(result["update_pma_reads"], 48)
        self.assertEqual(result["update_pma_writes"], 48)

    def test_bounded_transfer_without_cached_topology_is_rejected(self) -> None:
        code, _, log = self._run("invalid_bounded_without_cache", {
            "GRASU_SST_COMPACT_CACHE_VALID_EXTENT": "1",
        })
        self.assertNotEqual(code, 0)
        self.assertIn("bounded cache transfer requires the cached hot topology", log)

    def test_short_layout_cannot_silently_select_full_cache(self) -> None:
        code, _, log = self._run("invalid_short_full_cache", {
            "GRASU_SST_COMPACT_PARALLEL_SEARCH": "1",
            "GRASU_SST_COMPACT_CACHED_HOT": "1",
        })
        self.assertNotEqual(code, 0)
        self.assertIn("cached hot candidate requires source16 single-window capacity", log)

    def test_default_results_equal_frozen_baseline(self) -> None:
        baseline = os.environ.get("SPINE_SST_CACHE_BASELINE_LIBRARY")
        if not baseline:
            self.skipTest("set SPINE_SST_CACHE_BASELINE_LIBRARY for default-path equivalence")
        binding = forced_sst_library_binding(self.sst, Path(baseline))
        old_code, old, old_log = self._run("baseline_default", {}, binding=binding)
        code, result, log = self._run("candidate_default", {})
        self.assertEqual(old_code, 0, old_log)
        self.assertEqual(code, 0, log)
        self._assert_update(result)
        configuration = result["update_observability"].pop("configuration")
        self.assertEqual(configuration, {
            "compact_parallel_search": False, "compact_search_contexts": 16,
            "compact_cached_hot": False, "compact_cache_valid_extent": False,
            "cache_segments_per_half": 131072,
        })
        self.assertEqual(result, old)


if __name__ == "__main__":
    unittest.main()
