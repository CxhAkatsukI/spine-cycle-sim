# Spine CC Build Resume

Checkpoint: November 5, 2026, 11:00 UTC. **Build running, not a routed image
or a new board result.** This resumes the same CC source/configuration and
does not change the admitted G+R baseline. The earlier AU loss and seven
capacity failures remain in the evidence index.

## Why The Original Build Stopped

The agent raised its owned build's soft memory threshold from 88 to 100 GiB
to relieve reclaim pressure, but left the separate guard expecting 88 GiB.
The guard correctly stopped the owned build with `LIMITS_CHANGED`. This was
an operational mistake, not an HLS correctness failure or an OOM. The earlier
[adjustment snapshot](../cc_build_resource_adjustment.json) records the
requested change, not a successful continuation.

The [interrupted logs](interrupted_logs.tar.gz) preserve the original build,
unit journal and guard journal. Archive SHA-256:
`2836ac7b447b54fcbb4009dc94204ef7eb9ca07133b5e821b2a43ac701e95112`.
The build log inside has SHA-256
`d044fcaad68fcccc52ab4a03c6b955274198667166b1640c81aec365be93dc04`.
No incomplete build is admitted from these logs.

## Corrected Supervision

The checked-in `hardware/source_retention/build_resume.py` owns one explicit
policy from which both systemd properties and watchdog checks are derived:
104 GiB maximum, 100 GiB soft threshold, zero swap, 128 GiB live host reserve,
8 GiB additional background budget, and a 24-hour deadline. Admission checks
finite peer limits and leases before starting the compiler. Unknown peers
block admission. Only this owned process group is stopped on a breach.
This profile requires the >=480-GiB remote host; it is not the separate
40/36-GiB build exception and is not used on trifoliate.

The [frozen make script](cc-stream-build-resume-20261105.sh) pins the original
build root and unchanged Vitis 2024.1, U55C platform, 150-MHz CC engine and
one synth/implementation job. Script SHA-256:
`cb5d0934874f51b4ec857af826b7b26f79f416d8ab3e6aa87d1ea2d6b15edb0c`.
The launched supervisor SHA-256 is
`141a4ae3fc56d74cabcbf2632873894e0bac906e2ed65c2f34be0d346f5f32eb`.
The [launch identities](launch.json) distinguish the stopped and resumed
invocations. Runtime records stay in new output paths, not the old logs.

Generate launch properties from the supervisor rather than typing a second
copy of the memory limits. From the frozen remote source checkout, a fresh
resume can be launched with unique unit/output names:

```bash
module=spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.build_resume
mapfile -t properties < <(python3 -m "$module" --print-properties)
flags=()
for property in "${properties[@]}"; do flags+=(--property="$property"); done
systemd-run --user --unit="$fresh_unit" --working-directory="$PWD" \
  "${flags[@]}" /usr/bin/python3 -m "$module" \
  --script /data/chuxiao/cc-stream-build-resume-20261105.sh --output "$fresh_output"
```

This resumes unfinished link work in the original build tree. It is not a
standalone source rebuild recipe. Do not run two invocations against that
tree or overwrite a completed image.

## Next Gates

The collector watches the exact new invocation and expected engine filename,
checks the clean completion, original ABI log and hash-pinned resume
artifacts, and then applies the existing route/clock/correctness gates.
Only after admission does it run one AU Spine sample against the retained
G+R sample. The queued matrix then tests the other seven datasets once each.
Neither a successful make nor a queued follow-up is a measured speedup.
The large rdmaint synthesis also remains a placement/resource risk.
