import json
from pathlib import Path
import shutil
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.delivery import verify
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.preparation import KEYS, MATRIX


class SearchBindingTests(unittest.TestCase):
    def test_portable_capsule_replays_all_calls_without_machine_local_paths(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/hardware_validation/search_binding_evidence")
        self.assertEqual(verify(folder)["calls"], 216)
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "evidence"
            shutil.copytree(folder, copy)
            index = json.loads((copy / "index.json").read_text())
            index["production_baseline_admitted"] = True
            (copy / "index.json").write_text(json.dumps(index))
            with self.assertRaises(ValueError):
                verify(copy)
            index["production_baseline_admitted"] = False
            (copy / "index.json").write_text(json.dumps(index))
            with (copy / index["archive"]).open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaises(ValueError):
                verify(copy)

    def stdout(self):
        lines = []
        for values in MATRIX:
            row = dict(zip(KEYS, values))
            row["probes"] = row["updates"] * (row["generation"] + 1)
            lines.append("SEARCH_PIPELINE_PASS updates={updates} probes={probes} stalled={stalled} "
                         "channels=339 output_blocked=0 host_vendor_keep_bits=16".format(**row))
            lines.append("SEARCH_BINDING_ROW " + json.dumps(row))
        return "\n".join(lines)

    def test_complete_matrix_leaves_timing_and_production_admission_closed(self):
        result = analyze(self.stdout())
        self.assertEqual(result["calls"], 216)
        self.assertEqual(len(result["rows"]), 216)
        for key in ("hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted"):
            self.assertIs(result[key], False)

    def test_incomplete_duplicate_bad_ledger_and_alias_work_are_rejected(self):
        stdout = self.stdout()
        for wrong in ("\n".join(stdout.splitlines()[:-2]), stdout + "\n" + stdout,
                      stdout.replace("channels=339", "channels=338", 1),
                      stdout.replace("keep_bits=16", "keep_bits=12", 1),
                      stdout.replace('"probes": 0', '"probes": 1', 1),
                      stdout.replace('"alias": 0', '"alias": true', 1),
                      stdout.replace("SEARCH_PIPELINE_PASS", "OTHER_PASS", 1)):
            with self.subTest(wrong=wrong[:90]), self.assertRaises(ValueError):
                analyze(wrong)
        lines = stdout.splitlines()
        row = json.loads(lines[13].removeprefix("SEARCH_BINDING_ROW "))
        row["probes"] += 1
        lines[12] = lines[12].replace("probes=1", "probes=2")
        lines[13] = "SEARCH_BINDING_ROW " + json.dumps(row)
        with self.assertRaises(ValueError):
            analyze("\n".join(lines))

    def test_production_shape_uses_shared_network_and_retains_all_arguments(self):
        root = Path(__file__).resolve().parents[1]
        folder = root / "cpp/tests/evaluation_impact/common_g/hls"
        wrapper = (folder / "search_binding/top.cpp").read_text()
        self.assertIn("search_pipeline::network(edges, binary_0, row_offset_0, edge_size, segment_head_stream_out)", wrapper)
        self.assertIn("bundle=gmem_binary", wrapper)
        for family in ("binary", "row_offset"):
            for index in range(4):
                self.assertIn(f"s_axilite port={family}_{index} ", wrapper)
        self.assertIn("search_pipeline::network", (folder / "search_pipeline/top.cpp").read_text())
