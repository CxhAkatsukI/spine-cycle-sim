from pathlib import Path
import unittest

from scripts.run_hls_pagerank_real_comparison import _profile as pagerank_profile
from scripts.run_hls_weighted_real_comparison import _profile as weighted_profile


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "configs" / "architectures"


class RealComparisonProfileOverrideTests(unittest.TestCase):
    def test_explicit_spine_profile_uses_embedded_identity(self) -> None:
        path = PROFILES / "spine_candidate10_opt_v2_reader_working_set.json"
        profile, mhz = pagerank_profile(path, None)
        self.assertEqual(
            profile["profile_id"],
            "spine_candidate10_opt_v2_reader_working_set",
        )
        self.assertEqual(mhz, 150.0)

    def test_explicit_grasu_profile_uses_embedded_identity(self) -> None:
        path = (
            PROFILES
            / "grasu_regraph_candidate10_k1_multipart_weighted_v4.json"
        )
        profile, mhz = weighted_profile(path, None)
        self.assertEqual(
            profile["profile_id"],
            "grasu_regraph_candidate10_k1_multipart_weighted_v4",
        )
        self.assertEqual(mhz, 150.0)

    def test_default_profile_identity_still_fails_closed(self) -> None:
        path = PROFILES / "spine_candidate10_opt_v2_reader_working_set.json"
        with self.assertRaisesRegex(ValueError, "profile identity mismatch"):
            pagerank_profile(path, "spine_candidate10_normalized_v1")


if __name__ == "__main__":
    unittest.main()
