# G+R FPGA Event Diagnostics

One warmup pair is excluded; retain samples 1, 2 and 3. Each median is computed separately.

G events include the GraSU pipeline; ResPR also includes device degree update. SSSP/CC completion-barrier events are reported separately and may overlap G events.

The total kernel event union counts overlapping kernel execution only once. Per-kernel adapter, gather, apply and HBM duration sums are not additive stage times.

Kernel-uncovered wall is computed per sample as resident wall minus total kernel event union. It includes DMA, final readback and launch/wait gaps; it is not pure host orchestration time.

Convergence readback is a host wall interval, not a kernel event; ResPR does not log it separately. Missing metrics remain absent, not zero. Final-state readback is included in wall.

Both architectures retain all three measured wall times, including slow samples. Wall variability uses population standard deviation divided by the mean; this coefficient is not a confidence interval or evidence of the cause of timing variation.

These diagnostics do not establish a causal before/after improvement, publication matching, or per-stage simulator timing calibration.

`profile.json` retains the three measured samples and input hashes; `profile_medians.csv` retains all 24 declared cases, including failures. `wall_variability.csv` retains both architectures for all 24 cases; failed-case measurements remain blank, not zero. Its coefficient of variation is a fraction, not a percentage.
