# Replacement Links on Seele

November 4, 2026: the table records four independently launched hardware
links. A link receipt is not a U55C timing or correctness result. The two
first launch attempts ended when their login session closed; their logs are
retained but the table lists only the re-launched or persistent invocations.

Remote root: `/data/chuxiao/source-retention-20261104-v1/` on `seele`.
Local root: `/data/chuxiao/checks/source-retention-repair-20261104/` on
`trifoliate`. Local capsules are under `seele-inputs-v1/<case>`. Remote
inputs are under `inputs/<case>` and route attempts are under `builds/`.

| Case | Route attempt | Remote service suffix | Systemd invocation |
| --- | --- | --- | --- |
| SSSP | `sssp-v2` | `sssp-20261104-v2` | `fdbc4adab9744df19243e2f47dc53ce2` |
| CC | `cc-v2` | `cc-20261104-v2` | `f48048524d464a52bbb29a7d5e915dd5` |
| ResPR, directory spans | `respr` | `respr-20261104-v1` | `10993eafdc354a6fb94254c72aecad24` |
| ResPR, tail publication | `respr-tail` | `respr-tail-20261104-v1` | `33c5cc4e09c3423c900c9a80c9dfae49` |

The route units are `gr-retention-seele-<suffix>.service`. Monitor
`builds/<attempt>/execution.json` and `route.progress.json` on seele. Each
link uses a 40 GiB hard limit, 36 GiB high watermark, no cgroup swap and a
128 GiB live system reserve. Both the parent configuration and the XOs are
frozen; relocation changes only paths. The U55C platform closure has the
same bytes on both hosts. The two ResPR packets include a separately
hash-checked IP cache seed; it is a build optimization, not evidence.

The local units `gr-retention-return-<case>-20261104-v1.service` wait for
their exact remote invocations to exit successfully. They independently
check the sealed receipt digest, the byte identities of returned files,
the local export, the recorded command and connectivity configuration, the
toolchain preflight, and terminal resource evidence. Their status is in
`seele-return-v1-<case>/transfer.json`. Returned files go in `returned/`
there. Neither a failed link nor a mismatched artifact is passed to a board
runner. The sealer runs from a separate copy of the code so that it does
not modify the pinned build runner.

For an SSSP or CC active-min board pair, pass the returned directory as
`--candidate-route` and supply `--returned-candidate SHA256 CAPSULE XPFM
PREDECESSOR` to `board_execution.active_min_pair` (under
`spine_cycle_sim.experiments.original_regraph_execution.hardware`). This
checks the loaded candidate topology and timing against its local K4
predecessor before comparing with public A4. The board gate itself requires
one run per arm, matching correctness and driver-reported clocks on the
same U55C, and a resident device event-span ratio no greater than 1.15.
The active-min probe is not a convergence result. The ResPR tail path has
a different ABI; do not send it to that active-min runner.

No Figure 7--11 replacement or reuse decision is based on these link jobs.

## Public A4 CC Control

The local public A4 CC unit was still waiting for enough memory. A parallel
source build on seele uses the clean author-generated four-Little/zero-Big
topology and the same local min-label CC adaptation, Apply interface
directive, HBM mapping, and 150 MHz request. This is a public-source
resource control, not a reconstruction of the published 11+3 experiment.

- Unit: `gr-retention-seele-public-a4-cc-20261104-v1.service`
- Invocation: `1d70096721da4453ae0798d5dcd18873`
- Local source preflight: `a4-cc-preflight-seele-v2/results.json`
- Remote source capsule: `a4-cc-v2/seele-a4-cc-source-v2/`
- Capsule SHA-256: `ed75fe94cddebc5fcbed3ec6d4ba5c895f43c58c06ad1122468a20e65579982a`
- Build output: `builds/public-a4-cc-v1/results.json`

`source_build.portable_inputs` pins the source snapshot, compiler command,
and full U55C platform closure before transfer. It also compares the
Vitis, Vivado, and Vitis HLS launchers and `ap_int.h` byte for byte across
hosts. `source_build.portable_execution` regenerates only the absolute
paths in the existing wrappers and commands, uses the 40/36 GiB
containment with the 128 GiB reserve, and inspects each XO's ABI and HLS
report before linking. A completed link is still pending local binary
metadata, timing and source replay before any board test. Retain both
build logs, but measure only one admitted public image per fixture.

`gr-retention-return-public-a4-cc-20261104-v1.service` (invocation
`961b075fb0dd492ea5b8113ea765a4ad`) waits for the public CC build and
writes its progress to `seele-return-v1-public-a4-cc/transfer.json`.
The return includes the XOs, HLS reports, binary, final timing report
and raw build logs. The collector verifies source and file identities
but never programs a board. To use the return as the public CC arm,
point `--reference-route` at its `returned/` directory and pass
`--returned-reference SHA256 CAPSULE` to `active_min_pair`. That
runner re-extracts the local binary metadata and rechecks the kernel
ABI, target part, HBM mapping and 150 MHz timing before board admission.
