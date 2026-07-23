from __future__ import annotations

import unittest

from scripts.run_sst_memory_smoke import validate_case


class SstMemorySmokeValidationTests(unittest.TestCase):
    def test_matching_three_layer_counts_pass(self) -> None:
        result = {
            "success": True,
            "requests_issued": 4,
            "requests_completed": 4,
            "requests_failed": 0,
            "axi_beats": 8,
            "backend_requests": 8,
            "axi_read_bytes": 256,
            "axi_write_bytes": 0,
        }
        dram = {"dram_reads": 8, "dram_writes": 0, "dram_channels": 2}
        self.assertEqual(
            validate_case(result, dram, requests=4, request_bytes=64, channels=2),
            [],
        )

    def test_backend_drop_is_rejected(self) -> None:
        result = {
            "success": True,
            "requests_issued": 4,
            "requests_completed": 4,
            "requests_failed": 0,
            "axi_beats": 8,
            "backend_requests": 7,
            "axi_read_bytes": 256,
            "axi_write_bytes": 0,
        }
        dram = {"dram_reads": 7, "dram_writes": 0, "dram_channels": 2}
        problems = validate_case(
            result, dram, requests=4, request_bytes=64, channels=2
        )
        self.assertIn("backend_matches_axi", problems)

    def test_dram_drop_is_rejected(self) -> None:
        result = {
            "success": True,
            "requests_issued": 4,
            "requests_completed": 4,
            "requests_failed": 0,
            "axi_beats": 4,
            "backend_requests": 4,
            "axi_read_bytes": 256,
            "axi_write_bytes": 0,
        }
        dram = {"dram_reads": 3, "dram_writes": 0, "dram_channels": 1}
        problems = validate_case(
            result, dram, requests=4, request_bytes=64, channels=1
        )
        self.assertIn("dram_matches_backend", problems)


if __name__ == "__main__":
    unittest.main()
