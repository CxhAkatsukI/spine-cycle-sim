# Fig. 7 ResPR FPGA host refresh

[Current Fig. 7 CSV](../../fig7_complete.csv) |
[Current Fig. 7 CSV with RN](../../fig7_roadnet_ca_20261110/followup/fig7_nine_datasets.csv) |
[Raw FPGA run logs](data/) | [Input and binary receipts](receipts/)

On November 15, 2026, we reran Spine ResPR once per dataset on the FPGA
for all eight original Fig. 7 datasets and the roadNet-CA (RN) supplement.
All nine final states passed the CPU reference check. Across the original
eight, the new host reduced Spine latency by 2.03x to 6.97x (median 3.56x).
RN improved 11.48x. AU went from 6.088 ms to 1.223 ms in this replay.

- Only the Spine host changed (`0226332`, sparse CPU correction); the run
  reused the original FPGA image for each dataset.
- Each replay used the original eight-insertion batch and fixed threshold
  of `1e-6`. The timed window includes per-batch CPU correction through
  final readback. Old-graph/cache preparation and the final CPU check
  are outside that window. Use `new_spine_ms`, not
  `new_full_process_seconds`, for the Fig. 7 latency.
- Both versions recorded zero propagation rounds on all nine batches.
  These timings do not measure a speedup in nonempty propagation.
- The current Fig. 7 tables replace the earlier Spine ResPR timings and
  recompute the speedup against the original G+R measurements. G+R was not
  rerun. The `spine_raw_log` column locates the new FPGA evidence;
  original values are preserved in the
  [resident checkpoint](../resident_checkpoint_v3/fig7_resident_checkpoint.csv)
  and [RN paired receipt](../../fig7_roadnet_ca_20261110/board/respr_measured.json).

The paper, dated archives, old previews, and Figs. 8--11 are unchanged.
