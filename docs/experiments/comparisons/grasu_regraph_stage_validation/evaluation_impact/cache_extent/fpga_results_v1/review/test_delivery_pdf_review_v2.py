"""Reject changes other than the single randomized txtt font subset tag."""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "delivery_pdf_review", Path(__file__).with_name("review-fpga-delivery-v2.py"))
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


class PdfReviewTests(unittest.TestCase):
    sample = b"/BaseFont /AAAAAA+txtt /FontName /AAAAAA+txtt /FontName /AAAAAA+txtt 1.234"

    def test_random_tag_only_is_equal(self):
        self.assertEqual(reviewer.normalize_txtt_subset(self.sample),
                         reviewer.normalize_txtt_subset(self.sample.replace(b"AAAAAA", b"BBBBBB")))

    def test_numeric_difference_is_not_normalized(self):
        self.assertNotEqual(reviewer.normalize_txtt_subset(self.sample),
                            reviewer.normalize_txtt_subset(self.sample.replace(b"1.234", b"1.235")))

    def test_another_font_is_rejected(self):
        with self.assertRaises(ValueError):
            reviewer.normalize_txtt_subset(self.sample.replace(b"txtt", b"cmtt"))

    def test_inconsistent_tags_are_rejected(self):
        with self.assertRaises(ValueError):
            reviewer.normalize_txtt_subset(self.sample.replace(b"AAAAAA", b"BBBBBB", 1))


if __name__ == "__main__":
    unittest.main()
