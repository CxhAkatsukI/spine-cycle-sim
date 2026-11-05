# CC Build Memory Follow-Up

The November 5 `spine-cc-stream-admit-resume-20261105-v1.service`
invocation `fc098f3fc0c44cb4a8e2c405ea8d787e` ended at 20:51 CST with
systemd `Result=oom-kill` and `MemoryPeak=111669149696` bytes: its full
104-GiB cgroup limit. This was a contained build failure, not an FPGA
measurement or a whole-host memory exhaustion. Immediately afterward the
499-GiB host reported 483 GiB available. The predecessor's last JSON says
`BUILDING` because the supervisor was killed with its group; that stale
checkpoint is not a successful completion receipt. Original logs remain in
`/data/chuxiao/cc-stream-resume-20261105-v1/` on seele.

## Explicit Replacement Policy

`hardware/source_retention/build_resume.py` now offers the separate
`192g-v1` profile: **192-GiB max, 184-GiB high, zero task swap, 128-GiB
live host reserve and 8-GiB background reservation**. It still requires a
host with at least 480 GiB RAM, reserves full finite peer limits atomically,
rejects unbounded compiler peers and checks containment/reserve throughout.
The unchanged default is `104g-v1`. Tests check both limits and reject a
collector configured for a different memory profile.

This changes only the compiler's resource ceiling. Source, ABI, algorithm,
clock target, HBM wiring, synthesis/implementation concurrency and the
frozen [make script](../cc_resume_v1/cc-stream-build-resume-20261105.sh)
remain unchanged. It does not promise routing or timing closure.

From a fresh frozen checkout on the high-memory host:

```sh
module=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.build_resume
python3 -m "$module" --memory-profile 192g-v1 --print-properties
# Supply those exact properties and a fresh unit/output to systemd-run.
python3 -m "$module" --memory-profile 192g-v1 \
  --script /data/chuxiao/cc-stream-build-resume-20261105.sh \
  --output /data/chuxiao/cc-stream-resume-20261105-v2
```

The latter command must run inside the declared cgroup; it does not create
containment itself. The matching `cc_au_collect` invocation must explicitly
select `--resume-memory-profile 192g-v1`; clean completion, exact unit and
invocation, original ABI log, artifact hashes, correctness smoke and the
resident comparison remain separate gates. Pending routing or the old
104-GiB failure cannot supply a CC speedup bar.
