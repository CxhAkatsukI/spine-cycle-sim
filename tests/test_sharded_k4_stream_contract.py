"""Per-path stream capacity and routed-artifact identity admission."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters, load_profile
from spine_cycle_sim.experiments.sharded_k4_stages.stream_contract import audit_design, compute_streams, validate_design

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs/architectures/grasu_regraph_routed_sssp_compute_v3.json"


def design():
    cells, nets = {}, {}
    for producer, consumer, depth in compute_streams():
        name = "buffer_" + producer.replace("/", "_")
        cells[name] = {"vlnv": "xilinx.com:ip:axis_data_fifo:2.0",
                       "parameters": {"FIFO_DEPTH": {"value": str(depth)}}}
        nets[name + "_in"] = {"interface_ports": [producer, name + "/S_AXIS"]}
        nets[name + "_out"] = {"interface_ports": [name + "/M_AXIS", consumer]}
    return {"design": {"components": cells, "interface_nets": nets}}


class RoutedStreamTests(unittest.TestCase):
    def test_all_nineteen_connections_and_unchanged_depths(self):
        rows = validate_design(design())
        self.assertEqual(len(rows), 19)
        self.assertEqual(sum(row["depth"] == 32 for row in rows), 9)
        self.assertEqual(sum(row["depth"] == 16 for row in rows), 10)

    def test_wrong_depth_or_wiring_rejected(self):
        for index, (producer, _, _) in enumerate(compute_streams()):
            name = "buffer_" + producer.replace("/", "_")
            for field in ("depth", "wiring", "missing", "duplicate_net"):
                changed = design()
                if field == "depth":
                    changed["design"]["components"][name]["parameters"]["FIFO_DEPTH"]["value"] = "64"
                elif field == "wiring":
                    changed["design"]["interface_nets"][name + "_out"]["interface_ports"][-1] = "wrong/port"
                elif field == "missing":
                    del changed["design"]["components"][name]
                else:
                    changed["design"]["interface_nets"]["duplicate"] = changed["design"]["interface_nets"][name + "_in"]
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    validate_design(changed)

    def test_unpinned_design_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ulp.bd"
            path.write_text(json.dumps(design()))
            with self.assertRaises(ValueError):
                audit_design(path, "candidate")

    def test_only_version_three_selects_routed_streams(self):
        config = {"profile": str(PROFILE), "fixture": "in", "output": "out", "dram_output": "dram",
                  "arm": "candidate", "max_cycles": 1000}
        result = component_parameters(ROOT, config)
        self.assertEqual(result["routed_stream_depths"], 1)
        self.assertEqual(result["independent_read_write"], 1)
        self.assertEqual(result["profile_id"], "grasu_regraph_routed_sssp_compute_v3")
        for version in (1, 2):
            config["profile"] = str(PROFILE.with_name(f"grasu_regraph_routed_sssp_compute_v{version}.json"))
            self.assertNotIn("routed_stream_depths", component_parameters(ROOT, config))

    def test_rejects_silent_capacity_or_identity_change(self):
        profile = json.loads(PROFILE.read_text())
        mutations = [lambda p: p["fixed_model"].update(external_fifo_depth=32),
                     lambda p: p["fixed_model"].update(adapter_stream_depth=16),
                     lambda p: p["fixed_model"].update(gather_stream_depth=16),
                     lambda p: p["fixed_model"].update(mux_stream_depth=16),
                     lambda p: p["fixed_model"].update(internal_fifo_depth=32),
                     lambda p: p["target"]["routed_bd_sha256"].update(candidate="wrong")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            for mutate in mutations:
                changed = copy.deepcopy(profile)
                mutate(changed)
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    load_profile(ROOT, path)


if __name__ == "__main__":
    unittest.main()
