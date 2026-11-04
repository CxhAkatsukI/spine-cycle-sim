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
