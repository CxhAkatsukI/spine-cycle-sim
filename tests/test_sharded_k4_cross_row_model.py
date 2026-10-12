"""Cross-row selection never inherits routed hardware validation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_contract import PROFILE_ID, SCHEDULE, TARGET
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters, load_profile
from spine_cycle_sim.experiments.sharded_k4_stages.sst_timing import run_sst_case

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / f"configs/architectures/{PROFILE_ID}.json"


class CrossRowModelTests(unittest.TestCase):
    def test_only_candidate_selects_new_state_machine(self):
        config = {"profile": str(PROFILE), "fixture": "resident.bin", "output": "out.json",
                  "dram_output": "dram", "max_cycles": 10000, "arm": "original"}
        old = component_parameters(ROOT, config)
        new = component_parameters(ROOT, {**config, "arm": "candidate"})
        self.assertEqual(old.pop("cross_row_pipeline"), 0)
        self.assertEqual(new.pop("cross_row_pipeline"), 1)
        self.assertEqual(old, new)
        self.assertEqual(old["row_line_read"], 1)
        self.assertNotIn("row_line_model", old)
        self.assertNotIn("routed_empty_exit", old)

    def test_expanded_identity_is_not_bitstream(self):
        profile = load_profile(ROOT, PROFILE)
        basis = load_profile(ROOT, ROOT / profile["basis"]["path"])
        self.assertEqual(profile["target"], TARGET)
        self.assertFalse(profile["target"]["routed"])
        self.assertEqual(profile["memory"], basis["memory"])
        self.assertEqual(profile["fixed_model"]["cross_row_schedule"], SCHEDULE)
        self.assertEqual(profile["topology_reference"], basis["target"])

    def test_changed_schedule_and_claim_rejected(self):
        original = json.loads(PROFILE.read_text())
        for mutate in (lambda p: p["cross_row_schedule"].update(block_drain_cycles=1),
                       lambda p: p["target"].update(routed=True),
                       lambda p: p["basis"].update(sha256="changed"),
                       lambda p: p.update(evidence_tier="hardware_validated"),
                       lambda p: p.update(fixed_model={})):
            profile = copy.deepcopy(original)
            mutate(profile)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "profile.json"
                path.write_text(json.dumps(profile))
                with self.assertRaises(ValueError):
                    load_profile(ROOT, path)

    def test_board_replay_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            out = Path(directory) / "out"
            with self.assertRaisesRegex(ValueError, "unrouted"):
                run_sst_case(root=ROOT, integration=missing, plugin_dir=missing, exporter=missing,
                             profile_path=PROFILE, graph=missing, source=0, board_run=missing,
                             output=out, arm="candidate")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
