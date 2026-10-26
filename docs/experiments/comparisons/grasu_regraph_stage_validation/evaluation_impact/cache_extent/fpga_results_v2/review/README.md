# Host Follow-Up Package Review

All 24 cases passed terminal verification, and this package passed isolated
reproduction and visual review on 2026-10-26. This note supplements, rather
than rewrites, the original manifest and automated receipt. No new FPGA run,
model fit or simulator timing calibration is claimed by the review.

## Completed Checks

- All 638 archive members and indexed readable artifacts match their sizes
  and SHA-256 values. The archive retains all 96 paired runs, including
  warmups, the frozen plans and the pre-board admission failure.
- The bundled plot and profile modules run outside the checkouts without
  importing `spine_cycle_sim`. The PNG, two diagnostic CSVs and profile README
  reproduce byte for byte. JSON differs only in its source-directory field.
- The PDF differs only in its randomized six-letter `txtt` subset tag at
  three matching name occurrences. All other decompressed bytes agree, and
  independent 300-dpi rasterizations are byte-identical. TX Typewriter is
  embedded. Numeric, glyph, drawing and font-program changes are not ignored.
- Visual inspection confirms eight groups with all 24 bars, readable labels
  and legend, a unity reference, no text collisions and no missing/projected
  placeholders. All bars favor Spine, consistent with the CSV. The ResPR
  bars remain zero-propagation update/correction/completion measurements.
- Four reviewer regression tests pass: only the consistent randomized tag
  change is accepted; numeric changes, another font and inconsistent tags
  are rejected. The same reviewer and plot/profile source bytes were used
  in v1. No tolerance was relaxed for this follow-up.

The review ran with a 2-GiB hard limit, 1.5-GiB high watermark and zero swap;
systemd reported a 124.8-MiB peak and successful exit. The machine-local
output is `/data/chuxiao/checks/spine-cc-respr-host-20261026/roundtrip-v1`.

## Recheck

Use Python 3.12 or later with the parent README's rendering dependencies,
MuPDF (`mutool`) and Poppler (`pdffonts`). Select a fresh output directory:

```bash
python3 -B /path/to/this-package/review/test_delivery_pdf_review_v2.py
python3 -B /path/to/this-package/review/review-fpga-delivery-v2.py \
  --package /path/to/this-package --output /path/to/fresh-review
```

`roundtrip.json` preserves the automated result
`AUTOMATED_ROUNDTRIP_PASS_VISUAL_REVIEW_PENDING`; this note records the later
visual inspection. The original manifest likewise retains its pre-review
status. Neither field is a pending experiment after this supplement.
The review note, receipt and tests were added after packaging and are not
members of the original archive. `.gitattributes` preserves hash-pinned
CSV files' standard CRLF endings.

| Artifact | SHA-256 |
| --- | --- |
| Original manifest | `44eed2ad05551775f41a96d911469e67d7c10fbe8ebeb1810ba24adb79f1da1c` |
| Archive | `242f29a3f67309c2b736ebf4dee14f4db3428260148de24e46b63f5d9204b4e9` |
| Reviewer | `0cfbcd91aec664c57ed346793e1d711c7d9beeda3175f7f85b38b3376ddda4f0` |
| Figure PNG | `58a0316ab86aaf0d5ec8c408f29680df27256880da4f9beb2da9b15254bca94a` |

For the original source/binary/input checks, extract `evidence/README.md`,
`evidence/files.json` and the raw case records. Rechecking external binaries
and graph paths needs the recorded machine; the portable review does not
pretend to rerun hardware or recreate those large files.
