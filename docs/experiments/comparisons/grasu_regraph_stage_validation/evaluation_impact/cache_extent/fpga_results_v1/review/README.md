# Final Package Review

The 24-case package passed automated isolated reproduction and visual review
on 2026-10-26 (trifoliate local time, UTC+08). This receipt supplements the
original `manifest.json`; the archive and its original status are unchanged.
It does not claim another board run or new timing calibration.

## Checks Completed

- All 615 archive members and the original readable artifacts match their
  recorded sizes and SHA-256 values. The terminal verifier admitted all 24
  cases and all 96 paired runs, including excluded warmups.
- The bundled plot and profile modules run outside the simulator checkout,
  without importing `spine_cycle_sim`. The PNG, diagnostic CSVs and profile
  README reproduce byte for byte. JSON contents agree except the new source
  directory. Commands and hashes are in `roundtrip.json`.
- The reproduced PDF differs only in the randomized six-letter `txtt` font
  subset tag: decompressed PDF bytes are identical after normalizing those
  three name occurrences. Independent 300-dpi PDF rasterizations are byte
  identical. No numeric, drawing, glyph or font-program differences are
  normalized. TX Typewriter is embedded and subsetted.
- Visual inspection of the original PNG confirms eight groups and all 24
  bars, readable labels and legend, a visible unity reference, no text
  collisions and no missing/timeout/projected placeholders. The figure
  matches the CSV: eight SSSP wins, four CC wins and four ResPR wins for Spine.

## Retained First Review Failure

The first reviewer required a byte-identical PDF and stopped at that check.
Its outputs remain under the machine-local `final-roundtrip-review-v1/`;
the original reviewer is retained in the archive's `validation/` directory.
Inspection of both decompressed PDFs found only the randomized font subset
name. The second reviewer adds the narrowly scoped PDF comparison above,
plus a raster comparison. It does not change the renderer or package data.
Four regression tests reject numeric changes, another font and inconsistent
subset tags, and accept the single randomized tag difference.

## Recheck

Install the rendering dependencies described in the parent README, plus
MuPDF (`mutool`) and Poppler (`pdffonts`). Use a fresh output directory:

```bash
python3 /path/to/this-package/review/test_delivery_pdf_review_v2.py
python3 /path/to/this-package/review/review-fpga-delivery-v2.py \
  --package /path/to/this-package --output /path/to/fresh-review
```

`roundtrip.json` is the original automated receipt, whose status deliberately
leaves visual review pending. This document records the subsequent visual
inspection; neither historical status is rewritten. Hashes pin the original
manifest, archive, reviewer, renderer and analyzer. This review directory was
added afterward and is not a member of the original archive.
The package's `.gitattributes` preserves the generated CSV files' standard
CRLF endings so Git does not change their hash-pinned bytes.
