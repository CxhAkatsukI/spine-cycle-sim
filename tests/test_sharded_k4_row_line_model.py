"""Keep new line-reader selection distinct from all routed identities."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters, load_profile
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_contract import PROFILE_ID, TARGET
from spine_cycle_sim.experiments.sharded_k4_stages.sst_timing import run_sst_case

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / f"configs/architectures/{PROFILE_ID}.json"


class RowLineModelTests(unittest.TestCase):
    def test_only_candidate_changes_directory_requests(self):
        config = {"profile": str(PROFILE), "fixture": "resident.bin", "output": "out.json",
                  "dram_output": "dram", "max_cycles": 10000, "arm": "original"}
        reference = component_parameters(ROOT, config)
        candidate = component_parameters(ROOT, {**config, "arm": "candidate"})
        self.assertEqual(reference.pop("row_line_read"), 0)
        self.assertEqual(candidate.pop("row_line_read"), 1)
        self.assertEqual(reference, candidate)
        self.assertEqual(reference["profile_id"], PROFILE_ID)
        self.assertEqual((reference["row_prefetch"], reference["stop_after_last"]), (1, 1))
        self.assertNotIn("routed_empty_exit", reference)

    def test_no_inherited_bitstream_identity_or_timing_change(self):
        expanded = load_profile(ROOT, PROFILE)
        basis = load_profile(ROOT, ROOT / expanded["basis"]["path"])
        self.assertEqual(expanded["target"], TARGET)
        self.assertFalse(expanded["target"]["routed"])
        self.assertEqual(expanded["memory"], basis["memory"])
        self.assertEqual(expanded["fixed_model"], {**basis["fixed_model"], "adapter_empty_segment_exit_cycles": 0})
        self.assertEqual(expanded["topology_reference"], basis["target"])

    def test_silent_changes_or_routed_claim_rejected(self):
        original = json.loads(PROFILE.read_text())
        for mutate in (lambda p: p["basis"].update(sha256="changed"),
                       lambda p: p["target"].update(candidate_adapter_xo_sha256="changed"),
                       lambda p: p["target"].update(routed=True),
                       lambda p: p["shared_adapter_flags"].update(empty_segment_exit_cycles=73),
                       lambda p: p["arm_row_line_read"].update(original=1),
                       lambda p: p.update(fixed_model={"apply_latency": 1}),
                       lambda p: p.update(evidence_tier="hardware_validated")):
            profile = copy.deepcopy(original)
            mutate(profile)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "profile.json"
                path.write_text(json.dumps(profile))
                with self.assertRaises(ValueError):
                    load_profile(ROOT, path)

    def test_unrouted_board_replay_rejected_before_any_output(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            output = Path(directory) / "must_not_exist"
            with self.assertRaisesRegex(ValueError, "unrouted"):
                run_sst_case(root=ROOT, integration=missing, plugin_dir=missing, exporter=missing,
                             profile_path=PROFILE, graph=missing, source=0, board_run=missing,
                             output=output, arm="candidate")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
