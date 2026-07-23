from __future__ import annotations

import unittest

from scripts.run_sst_payload_roundtrip import validate_payload_result


class SstPayloadRoundTripValidationTests(unittest.TestCase):
    def test_closed_payload_ledger_passes(self) -> None:
        result = {
            "success": True,
            "mode": "payload_roundtrip",
            "payload_bytes": 1600,
            "axi_read_bytes": 1600,
            "axi_write_bytes": 1600,
            "zero_filled_write_bytes": 0,
            "axi_beats": 50,
            "backend_requests": 50,
        }
        self.assertEqual(
            validate_payload_result(
                result, dram_reads=25, dram_writes=25, channels=2
            ),
            [],
        )

    def test_zero_filled_write_is_rejected(self) -> None:
        result = {
            "success": True,
            "mode": "payload_roundtrip",
            "payload_bytes": 1600,
            "axi_read_bytes": 1600,
            "axi_write_bytes": 1600,
            "zero_filled_write_bytes": 64,
            "axi_beats": 50,
            "backend_requests": 50,
        }
        problems = validate_payload_result(
            result, dram_reads=25, dram_writes=25, channels=2
        )
        self.assertIn("explicit_write_payload", problems)


if __name__ == "__main__":
    unittest.main()
