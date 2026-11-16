# Fig. 7 ResPR: FPGA comparison with nonzero propagation

[Eight-dataset matrix data](respr_nonzero_fpga.csv) · [Run status](matrix_status.csv) · [Raw evidence](evidence/)

The follow-up reuses each dataset's original Fig. 7 eight-insertion batch
and both FPGA images, with one measured pair per dataset. The two hosts
share the same FP32 old-graph rank checkpoint. Both must pass CPU reference
checks, start from a checkpoint with no active residual at the chosen
threshold, and execute at least one propagation round. Seed and round counts
are recorded separately for the two hosts. G+R's correction pass is not
counted as a propagation round. Unusable points appear only in the status file.

We start at an absolute per-vertex threshold of `1e-7`. If it is outside
the activity window, we choose the largest predeclared ladder value
(`1e-6`, `3e-7`, `1e-7`, `3e-8`, `1e-8`, `3e-9`, `1e-9`)
strictly between the maximum residual before and after the batch.
The threshold is identical on both sides for a dataset and is chosen before
timing. Thresholds can differ across datasets; this is not a fixed-threshold
matrix. The original Fig. 7 CSV and plots have not been replaced.

The matrix records the FPGA PCIe address and rejects cross-device pairs.
For the PK/LJ/LJ08 retry, the G+R host reads the supplied checkpoint directly
instead of computing an old rank that it immediately discards. This change
is outside the measured interval; the FPGA image and both oracle checks are
unchanged. The [host patch](evidence/gr-host-direct-checkpoint.patch) and
[retry runner](evidence/run-respr-matrix-resume.sh) are archived. On AU,
the [original](evidence/au-original-prep.log) and
[direct-load](evidence/au-shared-rank-prep.log) CPU preflight logs match.

## Results

All eight original datasets have a valid pair on the same U55C. The two
implementations match on initial active count and propagation rounds for
each dataset; both pass CPU reference checks. Delta.hls is 1.15x to 15.06x
faster on seven datasets. SU differs by only 0.4% (23.92 vs. 24.01 ms)
and is effectively tied in this single-run comparison. No pair has a
slower measured Delta.hls time. There are no repeat-based error bars.

## AU pilot

[AU-only data](au_respr.csv)

AU used the original eight insertions and U55C images. Only the benchmark
hosts were rebuilt. The absolute per-vertex threshold was
`1e-7`, with damping `0.85`. It was the largest tested threshold that produced
a nonempty frontier in the CPU preflight. The old graph had no active
residuals; the batch activated eight vertices. Both sides had four
propagation rounds and passed their respective CPU checks. G+R reports the
preceding correction pass separately. Delta.hls served 1,569 logical edges
across the four rounds (about 0.19% of the updated graph edge count).

| Implementation | Resident wall time | Active vertices after seed | Propagation rounds |
| --- | ---: | ---: | ---: |
| Delta.hls | 21.3865 ms | 8 | 4 |
| G+R | 31.495064 ms | 8 | 4 |

Delta.hls was **1.47x faster** for this batch. This is a single measured pair,
not a multi-graph result or an estimate of run-to-run variation.

**Timing.** The comparison starts with the old graph and old rank resident,
then includes applying the updates, residual correction, propagation, host
dispatch and final state readback. Graph upload, old-state setup and the
final CPU checks are outside the window. Delta.hls pre-stages its update
descriptors and builds its old-graph correction cache before the timer; the
timed batch correction still runs on the host. G+R measures the corresponding
host wall interval as `setup_inclusive_ms` (the graph is already loaded).
Neither value is kernel-event time. The exact work inside each host's
interval differs; these are the existing Fig. 7 resident paths.

**Replay.** The experiment directory on trifoliate is
`/data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX`.
Run `sha256sum -c run-inputs.sha256` from that directory to verify the
original graph, two bitstreams, shared FP32 rank checkpoint and host binaries.
The checkpoint was exported by the Delta.hls preflight using the same
deterministic old-graph initializer used by its board run; the G+R host loads
and checks that file. The archived patches are against the commits listed
in `evidence/source-commits.txt`. The AU replay script, the
[matrix runner](evidence/run-respr-matrix.sh), and recorded commands
retain the single-run configuration; use the shared U55C lock and memory
admission checks again before replaying. The bitstreams and graph are
referenced rather than vendored. Matrix artifacts live under `respr-matrix/`
in the scratch directory and can be collected with
`python3 collect_matrix.py /data/chuxiao/fig7-respr-propagation-fig10b-20261116.cnPau7QX`.
