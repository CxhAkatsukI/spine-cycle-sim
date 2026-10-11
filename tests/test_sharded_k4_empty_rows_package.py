"""Recompute the archived row control without local boards, binaries or data paths."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep_analysis import (
    inspect_fixture, incremental_slopes, summarize_case,
)

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "empty_rows"


class EmptyRowPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.report = json.loads((PACKAGE / "empty_rows.json").read_text())
        cls.index = json.loads((PACKAGE / "empty_rows_raw_index.json").read_text())
        pins = {item["archive_path"]: item["sha256"] for item in cls.index["files"]}
        archive = PACKAGE / "raw_empty_rows.tar.gz"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != cls.index["archive"]["sha256"]:
            raise ValueError("empty-row archive changed")
        found = set()
        with tarfile.open(archive) as stream:
            for member in stream:
                path = PurePosixPath(member.name)
                if (not member.isfile() or path.is_absolute() or ".." in path.parts
                        or member.name in found or member.name not in pins):
                    raise ValueError("unsafe, repeated or unindexed archive entry")
                found.add(member.name)
                content = stream.extractfile(member).read()
                if hashlib.sha256(content).hexdigest() != pins[member.name]:
                    raise ValueError("frozen raw member changed")
                if path.parts[0] == "campaign":
                    target = cls.directory / Path(*path.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
        if found != set(pins) or len(pins) != len(cls.index["files"]):
            raise ValueError("incomplete raw package")

    def test_full_matrix_and_recomputed_statistics(self):
        rows = [summarize_case(self.directory / str(v), v) for v in (4096, 8192, 16384, 32768)]
        self.assertEqual(rows, self.report["rows"])
        self.assertEqual(incremental_slopes(rows), self.report["slopes"])
        self.assertEqual(self.report["status"], "EMPTY_ROW_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC")
        for field in ("hardware_timing_admitted", "original_A4_match_admitted", "timing_fit_performed"):
            self.assertIs(self.report[field], False)

    def test_all_fpga_and_model_bytes_and_invariant_pma(self):
        payloads, sources, plugins = set(), [], set()
        for vertices in (4096, 8192, 16384, 32768):
            directory = self.directory / str(vertices)
            audit = inspect_fixture(directory / "input.graph", directory / "prepared.bin")
            payloads.add(audit["fixed_payload_sha256"])
            outputs = set()
            attempts = json.loads((directory / "board/summary.json").read_text())["attempts"]
            self.assertEqual({(a["arm"], a["repeat"]) for a in attempts},
                             {(arm, r) for arm in ("original", "candidate") for r in range(3)})
            self.assertEqual(len(attempts), 6)
            for arm in ("original", "candidate"):
                for repeat in range(3):
                    outputs.add((directory / f"board/r{repeat}_{arm}/result.txt").read_bytes())
                outputs.add((directory / arm / "result.json.values.txt").read_bytes())
                self.assertEqual((directory / arm / "resident.bin").read_bytes(),
                                 (directory / "prepared.bin").read_bytes())
                model = json.loads((directory / arm / "result.json").read_text())
                for field in ("success", "done", "ledger_closed", "replicas_equal"):
                    self.assertIs(model[field], True)
                counters = model["counters"]
                self.assertEqual(counters["axi_requests"], counters["axi_completions"])
                self.assertEqual(counters["axi_beats"], counters["axi_completed_beats"])
                manifest = json.loads((directory / arm / "manifest.json").read_text())
                sources.append(manifest["source"])
                plugins.add(manifest["plugin"]["plugin_sha256"])
            self.assertEqual(len(outputs), 1)
        self.assertEqual(len(payloads), 1)
        self.assertTrue(all(source == sources[0] for source in sources))
        parent = json.loads((PARENT / "independent_channels/channels.json").read_text())
        self.assertEqual(plugins, {parent["legacy"]["candidate_identity"]["plugin_sha256"]})

    def test_frozen_dependencies_and_unhidden_timing_mismatch(self):
        paths = [PARENT / "independent_channels/channels_raw_index.json",
                 PARENT / "sst_raw_index.json",
                 PARENT.parents[1] / "adapter_optimization/board_raw_index.json"]
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths],
                         [pin["sha256"] for pin in self.index["dependencies"]])
        for slope in self.report["slopes"]:
            values = slope["arms"]["original"]
            self.assertGreater(values["board_duration_ns_per_added_row"],
                               1.8 * values["model_duration_ns_per_added_row"])
            self.assertEqual(slope["arms"]["candidate"]["model_duration_ns_per_added_row"], 0)


if __name__ == "__main__":
    unittest.main()
