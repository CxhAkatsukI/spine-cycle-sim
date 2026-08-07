from __future__ import annotations

import configparser
from pathlib import Path
import tempfile
import unittest

from scripts.run_hls_pagerank_real_comparison import _dram_config_contract


ROOT = Path(__file__).resolve().parents[1]


class DramSummaryOnlyTests(unittest.TestCase):
    def test_summary_only_changes_no_architectural_parameter(self) -> None:
        baseline = configparser.ConfigParser()
        summary = configparser.ConfigParser()
        baseline.read(ROOT / "configs/memory/HBM2_1ch_x128.ini")
        summary_path = ROOT / "configs/memory/HBM2_1ch_x128_summary_only.ini"
        summary.read(summary_path)

        for section in baseline.sections():
            for key, value in baseline.items(section):
                if (section, key) == ("other", "output_level"):
                    continue
                self.assertEqual(summary.get(section, key), value)
        self.assertEqual(summary.getint("other", "output_level"), 0)

        contract = _dram_config_contract(summary_path)
        self.assertEqual(contract["output_level"], 0)
        self.assertEqual(
            contract["output_level_effect"], "statistics_serialization_only"
        )

    def test_contract_rejects_unsupported_output_level(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.ini"
            path.write_text(
                "[other]\nepoch_period = 1000\noutput_level = -1\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "output contract"):
                _dram_config_contract(path)


if __name__ == "__main__":
    unittest.main()
