from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import matched_hbm, repackage_hbm


class MatchedHbmTest(unittest.TestCase):
    def setUp(self):
        self.args = (Path("image.xclbin"), {"uuid": "image"}, 440,
                     Path("output"), "r", 7,
                     Path("/dev/dri/renderD129"), "0000:c1:00.1")

    def test_packaged_profile_is_verified_after_programming(self):
        with (patch.object(matched_hbm, "execute", return_value="program") as execute,
              patch.object(matched_hbm.clocks, "capture", return_value="readback"),
              patch.object(matched_hbm.clocks, "replay", return_value={
                  "driver_reported_mhz": [150, 500, 440, 0],
              })):
            result = matched_hbm.prepare(*self.args)
        self.assertEqual(result, {"program": "program", "before": "readback"})
        execute.assert_called_once()

    def test_candidate_at_wrong_clock_is_rejected_without_reclock(self):
        with (patch.object(matched_hbm, "execute") as execute,
              patch.object(matched_hbm.clocks, "capture"),
              patch.object(matched_hbm.clocks, "replay", return_value={
                  "driver_reported_mhz": [150, 500, 450, 0],
              })):
            with self.assertRaisesRegex(ValueError, "actual clock profile"):
                matched_hbm.prepare(*self.args)
        execute.assert_called_once()

    def test_nominal_uses_full_hardware_clock_profile(self):
        args = (*self.args[:2], 450, *self.args[3:])
        with (patch.object(matched_hbm, "execute"),
              patch.object(matched_hbm.clocks, "capture", return_value="readback"),
              patch.object(matched_hbm.clocks, "replay") as replay):
            replay.return_value = {"driver_reported_mhz": [150, 500, 450, 0]}
            matched_hbm.prepare(*args, nominal=True)
            replay.return_value = {"driver_reported_mhz": [149, 500, 450, 0]}
            with self.assertRaisesRegex(ValueError, "nominal clock profile"):
                matched_hbm.prepare(*args, nominal=True)

    def test_after_rejects_host_reload_to_nominal_or_changed_board(self):
        before = {"bdf": self.args[-1], "uuid": "image", "binary": "sha",
                  "driver_reported_mhz": [150, 500, 440, 0]}
        for after, error in (
            ({**before, "driver_reported_mhz": [150, 500, 450, 0]}, "actual clock profile"),
            ({**before, "bdf": "0000:82:00.1"}, "board or image changed"),
        ):
            with (self.subTest(after=after),
                  patch.object(matched_hbm.clocks, "replay", side_effect=[before, after]),
                  self.assertRaisesRegex(ValueError, error)):
                matched_hbm.validate_after({"before": "receipt"}, "after", 440)

    def test_after_accepts_same_full_profile(self):
        record = {"bdf": self.args[-1], "uuid": "image", "binary": "sha",
                  "driver_reported_mhz": [150, 500, 440, 0]}
        with patch.object(matched_hbm.clocks, "replay", return_value=record):
            matched_hbm.validate_after({"before": "receipt"}, "after", 440)

    def test_only_hbm_of_nominal_topology_can_be_changed(self):
        payload = {"clock_freq_topology": {"m_count": "3", "m_clock_freq": [
            {"m_freq_Mhz": "450", "m_type": "SYSTEM", "m_name": "hbm_aclk"},
            {"m_freq_Mhz": "500", "m_type": "KERNEL", "m_name": "KERNEL_CLK"},
            {"m_freq_Mhz": "150", "m_type": "DATA", "m_name": "DATA_CLK"},
        ]}}
        original = payload["clock_freq_topology"]["m_clock_freq"]
        derived = repackage_hbm.retarget(payload, 445)["clock_freq_topology"]["m_clock_freq"]
        self.assertEqual(derived, [{**original[0], "m_freq_Mhz": "445"}, *original[1:]])
        self.assertEqual(original[0]["m_freq_Mhz"], "450")
        with self.assertRaisesRegex(ValueError, "actual clock profile"):
            repackage_hbm.retarget(payload, 450)
        original[2]["m_freq_Mhz"] = "140"
        with self.assertRaisesRegex(ValueError, "exact nominal"):
            repackage_hbm.retarget(payload, 445)


if __name__ == "__main__":
    unittest.main()
