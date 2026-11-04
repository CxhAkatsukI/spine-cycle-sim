# Replacement Links on Seele

November 4, 2026: the table records independently submitted hardware
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
| ResPR, directory spans (stopped before board admission) | `respr` | `respr-20261104-v1` | `10993eafdc354a6fb94254c72aecad24` |
| ResPR, tail publication | `respr-tail` | `respr-tail-20261104-v1` | `33c5cc4e09c3423c900c9a80c9dfae49` |
| ResPR, tail publication and source-read bursts | `respr-tail-source-bursts-v2` | `respr-tail-bursts-20261104-v2` | `393500a5963249a1a9d7bcebdcfeb934` |

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

The waiting runner, `board_execution.active_min_follow`, also accepts the
returned candidate and reference flags. For each returned arm, the
`--*-unit` and `--*-invocation` identify the local collector, not the
remote compile unit. It checks the completed collector receipt before
requesting one board pair. Rebind a queued test to a returned image only
before either arm has been requested, and keep the earlier queue receipt.
If the collector is still running, use `--pending-return-candidate CAPSULE
XPFM PREDECESSOR` or `--pending-return-reference CAPSULE` instead. The
queue pins the build inputs before waiting. It obtains the digest only
after that exact collector succeeds, checks it against the returned
receipt, then runs the same provenance and image admission as for an
explicit digest. The independent G runner also accepts
`--pending-return-candidate`.

The independent G runner,
`spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate`,
accepts the same `--returned-candidate` arguments. Set `--route` to the
returned directory and pin the local collector with `--unit` and
`--invocation`. The SSSP and CC resident and matrix runners take that same
`--route`, then replay the verified returned-image provenance from R and
require the G receipt to refer to that exact image.

No Figure 7--11 replacement or reuse decision is based on these link jobs.

## ResPR Source-Property Read Repair

The original `kernelHBMWrapper` selected the source pointer and response
FIFO inside its contiguous beat loop. Both old reader RTLs issued one beat
per logical request. HLS commit
[`9ceb5c5`](https://github.com/CxhAkatsukI/grasu-regraph-integration/commit/9ceb5c5)
selects each pointer/FIFO pair outside the loop. Its Vitis HLS 2024.1
report and generated reader RTL show 256-beat logical requests, split by
the unchanged 16-beat AXI burst limit. Both 512-bit ports retain 16
outstanding read requests. The C++ wrapper functional test passed. This
is evidence of request coalescing, not a measured speedup or a passed R
screen. The synthesis report is under
`/data/chuxiao/builds/regraph-source-read-bursts-20261104/build/kernelHBMWrapper/`
at `kernelHBMWrapper/kernelHBMWrapper/kernelHBMWrapper/solution/syn/report/csynth.rpt`.

The packet builder's `--source-wrapper` checks the replacement's complete
kernel interface and compile macros against the production XO. Compared
with the tail-publication capsule, 11 of the 12 XO hashes and the link
connectivity match; only `kernelHBMWrapper.hw.xo` changed (old SHA-256
`ebfcac0509a5179039c35c2482553b904ef591dd1ee81469c182e58865bfb315`, new
`9ad78ca5b5e2259401423308aae2b6c56a33638083ac25a86b0176b648f3ffd9`).
The HBM 23/24 mappings and the existing ResPR host stay fixed. The capsule
SHA-256 is `d40f4e7e9ebe69b2398a412d4632ee6fa44c51f261b5de1726bb3fcb103c3847`.
The first remote launch failed containment before starting a link; v2
passed the cgroup check and entered memory admission with the existing
128 GiB reserve. To free a build reservation, the directory-span-only
ResPR link was stopped before producing an admitted image. Its fixed
publication floor on the skewed fixture (0.655360 ms at 150 MHz) already
exceeds the 0.530418 ms gate. The tail variant removes that particular
lower-bound failure; it still needs a board measurement. Both build logs
are retained.

| Queue | Receipt under local check root | Local service suffix | Invocation |
| --- | --- | --- | --- |
| Route return | `seele-return-v2-respr-tail-source-bursts/transfer.json` | `return-respr-tail-bursts-20261104-v3` | `3c1e947cc3ee4643b6e560a46cc4fa78` |
| R, one candidate run per frozen A4 reference case | `tail-bursts-follow-v2/results.json` | `r-tail-bursts-20261104-v3` | `c5faa4f8979d4aee97c86ad8b55f7f95` |
| Independent G on the exact R-screened image | `g-tail-bursts-v2/results.json` | `g-tail-bursts-20261104-v3` | `d35ffd4d98884e90b748092516c737c7` |
| ResPR resident R19/Flickr, first jointly admitted tail variant | `resident-joint-board-v5/results.json` | `resident-joint-v5-20261104` | `6605064cdc3144948cd155cee3b06963` |
| ResPR resident, seven remaining matrix graphs | `respr-matrix-v3/results.json` | `respr-matrix-v3-20261104` | `4598e1f22b5446dabd4749f2470f9e0d` |

The resident queue superseded v3 before any board launch, dropping the
rejected cached candidate and keeping both the original and burst tail
variants. Its first restart failed the board runner's cgroup size check
before either arm ran; v5 uses the required 8 GiB cap. It runs one matched
comparison per fixture after both G and R gates pass on the same image.
The matrix then replays those gates and uses the selected image for the
seven remaining graphs. It does not repeat R19 or count Flickr among the
eight graphs.

## Public A4 Weighted SSSP Control

The local public-source A4 SSSP link and a separate offline admission
passed at 150 MHz. The binary is
`/data/chuxiao/builds/gr-directory-spans-20261103/public-a4-sssp-v1/build/original_r_a4_weighted_sssp.hw.xclbin`
(SHA-256 `5185d9be6f0b889f8da107fb3a6d9b5d3d62d4affe4cfc6a1910833ddcfda3b4`).
The offline receipt is `public-a4-sssp-offline-admission-v1/summary.json`
under the local root. This control has not been timed in the new pair.
The local A4 link unit has already exited; the replacement queues use
`--completed-reference 7d7aa3de8d8c1c76eac386e4b28520a662e0b02d61d56cb114dd8959445ffc74`
to pin its exact successful `build/results.json`. The board runner still
replays full local A4 source, topology, timing, and binary admission.

The integrated local SSSP attempt was interrupted only while still
waiting for its 80-GiB memory admission, with no Vivado process or
execution manifest. Its terminal receipt is
`/data/chuxiao/builds/gr-directory-spans-20261103/route-sssp-v2/execution/execution.json`.
The original `sssp-active-pair-v2`, `sssp-odd-pair-v1`,
`g-sssp-board-v2`, `sssp-resident-au-v2`, and
`sssp-singlepass-matrix-v1` receipts remain in the check root: no board arm
was requested and no matrix child ran. The new queue is bound to the
exact seele SSSP return above. Receipts below are relative to the local
check root:

| Test | Receipt | Local service | Invocation |
| --- | --- | --- | --- |
| SSSP R, sparse Amazon frontier | `sssp-active-pair-return-v3/queue.json` | `gr-retention-sssp-pair-return-v3-20261104.service` | `de763d51116042d1995d8d1948046019` |
| SSSP R, odd-vertex Amazon frontier | `sssp-odd-pair-return-v2/queue.json` | `gr-retention-sssp-odd-pair-return-v2-20261104.service` | `8a228fd591384ce2bc35caca8df8145d` |
| SSSP G, AU 131K updates | `g-sssp-board-return-v3/results.json` | `gr-retention-g-sssp-return-v3-20261104.service` | `578f47850f484fccad9d1541ff41bd74` |
| SSSP resident Spine vs G+R, eight graphs | `sssp-singlepass-matrix-return-v2/matrix.json` | `gr-retention-sssp-matrix-return-v2-20261104.service` | `21d209eca39c4d54bd13e064ca269a19` |
| Native Figure 8 AU/512 setup pair | `fig8-au512-pair-return-v2/results.json` | `gr-retention-fig8-au512-return-v2-20261104.service` | `760a261547944e3bb7f13132bfa6d4ce` |
| Native Figure 8 seven-case export | `fig8-native-matrix-return-v1/results.json` | `gr-retention-fig8-native-matrix-return-20261104.service` | `df85bec545d043d8b5fc827612d2841f` |

The matrix uses `--include-au` to request all eight datasets once, with
no warmups, only after independent G and both R receipts pass and their
raw evidence replays on the exact returned image. There is no separate
AU run in this queue.

The first matrix stopped after three pairs. Continuation `resume-v3`
measured PK and R19, then stopped with no SO board attempts while SO was
waiting for 64 GiB of available memory. Use
`sssp-singlepass-matrix-resume-v5/matrix.json` for diagnostic exports (service
`gr-retention-sssp-resume-v5-20261104.service`, invocation
`82928f3473f04c6196a20f4ad42896f5`). It imports all five completed pairs
from the pinned journal and does not remeasure them. The `resume-v4`
attempt failed before requesting a board arm: replay in a different
checkout changed absolute paths in the route-audit pins even though the
file hashes matched. The v5 continuation used the original checkout
path and retains the original route evidence.

Only SO uses a 24 GiB hard limit and 22 GiB high watermark; the 32 GiB
host reserve and no-swap cgroup are unchanged. The matching historical
SO receipt pins both peak tree RSS samples (18.96 GiB for G+R and 4.53
GiB for Spine); these are planning evidence, not a cgroup peak bound.
The runner rejects a measured SO pair if the new cgroup reports a high,
max, or OOM event. The v5 queue was stopped after six measured pairs
because its image failed the AskUbuntu R gate. LJ was waiting for memory
with no board attempts; LJ08 was never requested. The queue journals
were left unchanged. See the [SSSP follow-up](sssp-resident-followup/README.md)
for the archived pairs and the source-burst repair below for the new image.

The separate Figure 8 job waits for G alone because it does not run R.
It is capped at 8 GiB with no cgroup swap, takes the same board lease
used by the G control, and does not rerun the already measured Spine
arm. The seven-case export reuses the admitted AU/512 pair and requests
the six remaining cases once. See
[the Figure 8 timing boundary](FIGURE_IMPACT.md#figure-8-exact-inputs-for-a-native-g-check).

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

**v1 failed the final routed timing check.** The returned xclbin's DATA
clock is 150 MHz, but the 450 MHz `hbm_aclk` domain has WNS -0.081 ns,
TNS -2.333 ns and 72 failing endpoints in the final locked summary. The
worst path is an AXI address payload register crossing an SLR within the
HBM shell, with no logic levels and 1.647 ns of routing delay. The
offline checker rejected it; the collector's success means transfer
integrity only. No board run was requested for this image.

- v1 return receipt SHA-256: `85b45682a0a6bd7384f0bd4437356b35b7983adf0bf97cdac24d5c07ae19ff39`
- v1 final timing report SHA-256: `cd49d1d91397d994c8b9bfe6f82040661d9ead415b0b0dfdb4edc3d9089e2c78`
- v2 unit: `gr-retention-seele-public-a4-cc-20261104-v2.service` (invocation `6bf1fc1f8eda49e4a98e2a6e2a1151b8`)
- v2 build output: `builds/public-a4-cc-v2/results.json`
- v2 runner: `a4-cc-runner-509001b`, archive SHA-256 `f18b7fee6a1a6aab536a926db5cf2d8a7506458b45c7301f4de16565f6683305`
- v2 local return: `seele-return-v2-public-a4-cc/transfer.json`, unit `gr-retention-return-public-a4-cc-20261104-v2.service` (invocation `2ae52cb7a9d24e1aa73bfc70cf12d277`)

v2 uses the same capsule and the pinned `aggressive-route-v1` physical
implementation properties. It preserves the author placement constraints,
HBM mapping, both clock targets and compile commands. The strict final
timing check is unchanged. The two waiting R pair queues and their matrix
supervisor were superseded before requesting any timed run; the G-only
queue was not restarted.

The v2 locked routed report has WNS +0.001 ns, WHS +0.003 ns, and zero
setup, hold and pulse-width violations at the constrained clocks, including
450 MHz HBM. The report SHA-256 is
`911516d10f7f611bcfc72682d21bec9b388770ccef65671b7849d4162978c2ce`.
This is routed timing evidence. The board queue still requires a verified
bitstream return and the same-clock paired hardware results.

The v2 collector missed the exact unit's exit because seele unloaded its
successful transient service before the poll. Recovery used the exact
manager start and teardown records plus the pinned build's successful
command, resource and artifact records; no build was repeated.
`seele-return-v4-public-a4-cc/transfer.json` records the recovered return
(receipt SHA-256 `9fe3e145a6622adbfadcec25ea42bb772fb2a103f8ec0a6f7ea1a7c7ef36a103`).
Independent local offline review passed ABI, topology, clock and routed
timing checks for xclbin SHA-256
`d8ccf7dfb051801dd052047a3d18f91a3beb351649a637bd07aada775acb15a0`.
This is not a board-performance result.

The rearmed CC queues are `cc-active-pair-physical-v2/queue.json`
(invocation `78608da3edae4a5c8ff2c91dfe38969b`),
`cc-odd-pair-physical-v2/queue.json`
(`678f290059d447269b1907fc3fd0f959`), and
`cc-singlepass-matrix-physical-v2/matrix.json`
(`1d7f3bca27d94897b13cd34b76568940`). The superseded queues
did not request a timed pair. The existing integrated CC and ResPR
collectors keep their exact remote invocations; a separate
`After=`-only unit retains those service records without starting,
stopping or changing the builds.

The original local integrated CC build expired while waiting for its
memory reservation; it did not start Vivado or request a board run. Its
logs remain at `route-cc-v2/execution/` under the local build root
`/data/chuxiao/builds/gr-directory-spans-20261103/`. The replacement queue
uses the two local collectors above, whose invocations are pinned. Its
receipts under the local check root are:

| Test | Receipt | Local service | Invocation |
| --- | --- | --- | --- |
| CC R, sparse Amazon frontier | `cc-active-pair-return-v3/queue.json` | `gr-retention-cc-pair-return-v3-20261104.service` | `694632798c1b497d97bbd33f1a5f4b94` |
| CC R, odd-vertex Amazon frontier | `cc-odd-pair-return-v3/queue.json` | `gr-retention-cc-odd-pair-return-v3-20261104.service` | `d167bfb9221a4f3d9d6dd25d763e9d56` |
| CC G, AU 131K updates | `g-cc-board-return-v2/results.json` | `gr-retention-g-cc-return-v2-20261104.service` | `dfb233abc1ec408f941603989abd3de7` |
| CC resident Spine vs G+R, eight graphs | `cc-singlepass-matrix-return-v4/matrix.json` | `gr-retention-cc-matrix-return-v4-20261104.service` | `304dca3cc9f64c7b89c2dfd16bde8fbe` |

The matrix waits for both R checks and the independent G check. It will
use the exact image admitted by those three receipts and requests each
workload once, including R19 (`--include-r19`). These are queue
identities, not completed performance measurements.

## November 4 Physical Retries

The integrated SSSP locked routed report had WNS +0.002 ns and zero
setup, hold, and pulse-width violations. Bitstream generation and local
return verification were still pending at this snapshot. This is a
timing result, not a measurement of R or a Spine speedup.

The initial integrated CC and ResPR tail reports showed violations in the
450 MHz `hbm_aclk` domain (CC WNS -0.105 ns, 205 failing setup endpoints;
ResPR WNS -0.042 ns, 15 endpoints). These are not DATA-clock shortfalls.
The initial bitstream jobs reported automatic HBM derating to 429.7 MHz
(CC) and 441.6 MHz (ResPR tail), which does not meet this control's
same-clock acceptance requirement. The initial link artifacts and logs
remain archived separately from the retry.
The retries use `aggressive-route-v1` without changing the XOs, HBM
mapping or clock targets. The final locked timing check still applies.
All output paths below are relative to the roots given above.

| Integrated route | Remote attempt | Remote unit / invocation | Local transfer receipt |
| --- | --- | --- | --- |
| CC physical retry | `builds/cc-physical-v1` | `gr-retention-seele-cc-physical-20261104-v1.service` / `e26118b89c4044eeb48d1e73bda48332` | `seele-return-v2-cc-physical/transfer.json` |
| ResPR tail physical retry | `builds/respr-tail-physical-v1` | `gr-retention-seele-respr-tail-physical-20261104-v1.service` / `6a78aa373be04a30b91ad8779768bb00` | `seele-return-v2-respr-tail-physical/transfer.json` |
| ResPR tail plus source-read bursts | `builds/respr-tail-source-bursts-v3` | `gr-retention-seele-respr-tail-bursts-20261104-v3.service` / `614fad744d0d4cb79c04efd9b5395082` | `seele-return-v3-respr-tail-source-bursts/transfer.json` |

The physical retry capsule digests are `e7b429e5333434c8cf85909daa7295f1fdddccfb3e8c4b196ae0465d559af7e6`
(CC) and `29f487aa5f16500266fcd976fd85425144c0c3dec160b054c2d8707bf625f606`
(ResPR tail). They use `runner-4bb9b44`; the source-burst route uses
`runner-9a62fd3` and retains the existing burst capsule digest. Each
collector binds one exact remote invocation and replays its capsule,
command and output digests locally. Collector success alone is not
approval to program a card.

These three routes use the seele-only `seele-reserve-128g-peer-physical-v2`
admission profile. It counts a peer's finite physical cgroup cap once,
even when multiple peer tool processes share that cap. Owned builds
remain capped at 40 GiB (36 GiB high watermark) with no swap, and the
128 GiB host reserve remains in force. A queued unit is not necessarily
running Vivado. Independent R and G board receipts are required for the
exact returned image before it can enter a resident matrix.

The original CC and ResPR tail board dependencies were withdrawn before
requesting their runs. The public A4 CC control returned in
`seele-return-v4-public-a4-cc/transfer.json` and passed offline admission
at all declared clocks. This verifies the build, not a measured CC R
time. The live dependencies use the following local receipts:

| Test | Local receipt | Service invocation |
| --- | --- | --- |
| CC R, sparse Amazon frontier | `cc-active-pair-physical-v2/queue.json` | `78608da3edae4a5c8ff2c91dfe38969b` |
| CC R, odd-vertex Amazon frontier | `cc-odd-pair-physical-v2/queue.json` | `678f290059d447269b1907fc3fd0f959` |
| CC R, AskUbuntu reciprocal topology | `cc-au903k-pair-physical-v1/queue.json` | `5077405be85f4d67be1760574eeeff1e` |
| CC G, AU 131K updates | `g-cc-board-physical-v1/results.json` | `6de5ad246c514a7f8ad50c62cc315b78` |
| CC resident matrix | `cc-singlepass-matrix-physical-v3/matrix.json` | `ddb0eb18ef224353a725b845540e095e` |
| ResPR tail physical R | `tail-follow-physical-v3/results.json` | `50d1ecd2c3f74cd686d21c5640eeaf01` |
| ResPR tail physical G | `g-tail-physical-v3/results.json` | `70ddaa3c60e042bf80cd831aa9f7274a` |
| ResPR tail plus source-read bursts, return (`return-respr-tail-bursts-20261104-v4`) | `seele-return-v3-respr-tail-source-bursts/transfer.json` | `b3d3b9cd19184d78872934329751d3f1` |
| ResPR tail plus source-read bursts, R (`r-tail-bursts-20261104-v4`) | `tail-bursts-follow-v3/results.json` | `43674784b88a4e6b858c5ec56325e5e2` |
| ResPR tail plus source-read bursts, G (`g-tail-bursts-20261104-v4`) | `g-tail-bursts-v3/results.json` | `1d6896d70f644d5c931891e46ab743d6` |
| ResPR R19 and Flickr resident screen | `resident-joint-board-v7/results.json` | `6fb1f02cea23421f9ffb902041a925b8` |
| ResPR remaining seven large workloads | `respr-matrix-v5/results.json` | `6d2b2669487e43ec970d080e8e8cd392` |

The CC topology control uses the fixed-ID AskUbuntu slice from the SSSP
study (156,289 vertices, 903,774 edges, 12 A4 tasks) with the fixture's CC
state. It runs after the two Amazon controls, once per arm, using the same
reference and candidate bitstreams as those controls. The v3 matrix waits
for this receipt as well as the existing G and two R receipts; it checks
the AU raw events and outputs against the exact image and driver clocks
before requesting convergence tests. The v2 matrix was retired with every
dataset still `NOT_REQUESTED`; none of the G or R producers were restarted.

The ResPR resident screen accepts only a candidate with both same-image
stage receipts, and may use either the tail physical retry or the
source-burst repair. The SSSP R pair's `--completed-reference` pins a
finished public A4 *build*, not a previously measured reference time. The
three SSSP source-burst R queues below also use `--retained-reference` to
replay the matching measured A4 arm; only the replacement arm runs again.

## Weighted SSSP Source-Read Burst Retry

The [SSSP wrapper change](SSSP_STAGE_ADMISSION.md#source-property-read-burst-repair)
was synthesized on trifoliate and linked on seele using `runner-4bb9b44`,
the same clock targets, and the peer-aware 128 GiB reserve profile above.
The capsule is `inputs/sssp-source-bursts`, SHA-256
`e9f3a2b81af405e39a0189a1df698389ac23d1f36056548b8ba4a0fd8c23826c`.
The raw synthesis build is at
`/data/chuxiao/builds/regraph-sssp-source-read-bursts-20261104` on trifoliate.

| Dependency | Attempt or receipt | Service invocation |
| --- | --- | --- |
| Remote link | `builds/sssp-source-bursts-v1` | `gr-retention-seele-sssp-source-bursts-20261104-v1.service` / `f2dcd397414c4b05b98c52a2db2f3d8c` |
| Local return | `seele-return-v1-sssp-source-bursts/transfer.json` | `gr-retention-return-sssp-source-bursts-20261104-v1.service` / `6b8f97bbd1a344478b0e3bdf96d10928` |
| R, AskUbuntu reciprocal slice | `sssp-burst-au903k-v1/queue.json` | `6fddebcfafd549919d50e897a81208f9` |
| R, Amazon sparse frontier | `sssp-burst-amazon-v1/queue.json` | `43bc95a6b221436eafb3c4f47c418529` |
| R, Amazon alternate frontier | `sssp-burst-amazon-odd-v1/queue.json` | `f8d6e9df120f4bd197f4b408f92a574e` |
| G, AskUbuntu 131K updates | `g-sssp-board-burst-v1/results.json` | `118509bc150542bca87c4f46d26904c1` |
| Resident full AskUbuntu | `sssp-burst-resident-au-v1/queue.json` | `db661128be3c41deb2dbc7d0b9834ac3` |
| Remaining seven resident SSSP pairs | `sssp-burst-matrix-v1/matrix.json` | `bf36d9e4ead342a08cc7fc063d2dcd0c` |

The remaining-seven service is `gr-retention-sssp-burst-matrix-20261104-v1.service`.
It waits for the full AskUbuntu pair, replays its independent G and three R
admissions on the exact candidate host, bitstream and clock, and never
reruns AU. Its children retain per-case memory caps and one measured run
per arm, in ascending memory-budget order. No child is requested if the
AU result or any required admission is missing or fails.

Local receipts are relative to
`/data/chuxiao/checks/source-retention-repair-20261104`. The resident runner
checks the exact R and G producer invocations and replays all four receipts
against the same returned image before taking the board locks. Its request
is one resident pair, not a whole-matrix run. A failed admission does not
launch that pair.

## ResPR Source-Burst Timing Failure

The source-burst V3 retry finished routing with zero post-route DFX DRC
errors, but the final locked report does not meet setup timing. The raw
report is at `builds/respr-tail-source-bursts-v3/link/link/vivado/vpl/prj/prj.runs/impl_1/hw_bb_locked_timing_summary_routed.rpt`
on seele. Its SHA-256 is
`cb441e06920fb00e390f4a60ba78bb6abc037148578901fa976b426994e43663`.

| Clock | Setup WNS | Setup TNS | Failing endpoints |
| --- | ---: | ---: | ---: |
| Kernel data, 150 MHz | -0.169 ns | -18.960 ns | 485 |
| HBM AXI, 450 MHz | -0.007 ns | -0.010 ns | 2 |

There are no hold or pulse-width violations. The worst data path is
inside the ResPR Apply `merged_prop` AXI-stream input register slice,
from `FSM_sequential_state_reg[0]` to a `data_p1_reg` bit. The control net
has fanout 516; routing accounts for 6.457 ns of the 6.683 ns data delay.
The two HBM failures are separate inter-SLR shell paths. A generated
bitstream alone cannot clear the registered same-clock stage gates.

## ResPR Apply Input Retime

Integration commit `27385ff` tried reverse-only registration. Vitis
2024.1 reported HLS 207-5563, emitted the same `regslice_both` on
`merged_prop`, and left the critical-path structure in place. Do not
route this variant. Its build is retained on trifoliate at
`/data/chuxiao/builds/regraph-respr-apply-reverse-20261104`.

Integration commit `d89b155` disables registration only on the ResPR
Apply input. Vitis emitted a direct connection to `apply_bursts`, with
no input register slice, while the output slice remains registered.
The main `apply_bursts` loop still has II=1. The exported XO ports,
arguments, control protocol, and algorithm-mode definitions match the
old XO. The registered merger and depth-16 link FIFO are unchanged.
The native residual Apply policy test passed with the opt-in macro
enabled; this does not cover RTL backpressure or routed timing.

The build is at `/data/chuxiao/builds/regraph-respr-apply-unregistered-20261104`
on trifoliate (`gr-retention-respr-apply-unregistered-20261104-v1.service`,
invocation `eeae5d6a9f3844018f7b7c7ef9ac8f95`, 1.4 GiB peak).
The Apply XO SHA-256 is
`41ad927ccffa959afc22e7de4d6f85384c3afac1393aed779c31b8206a82a82d`.
The sealed link replaces only that XO from the V3 source-burst build;
the other 11 XOs, link config, platform, IP cache and requested clocks
are unchanged. See `seele-inputs-v1/respr-tail-bursts-apply-off/capsule.json`
(SHA-256 `4c700e4a1eea2cc2ae524f67e7667ee35d9a49eab43a3d97040d4760eec38c96`).

| Step | Receipt or attempt | Unit invocation |
| --- | --- | --- |
| Remote link | `builds/respr-tail-bursts-apply-off-v1` | `gr-retention-seele-respr-apply-off-20261104-v1.service` / `7ceab78a8185464a9e8fb5d337982476` |
| Return | `seele-return-v1-respr-tail-bursts-apply-off/transfer.json` | `gr-retention-return-respr-apply-off-20261104-v1.service` / `16aaa944d6c64436938b014a9d7c530b` |
| R stage | `retime-apply-off-r-v1/results.json` | `gr-retention-r-apply-off-20261104-v1.service` / `93aabeabc515482c8aed55af5c1c3024` |
| G stage | `retime-apply-off-g-v1/results.json` | `gr-retention-g-apply-off-20261104-v1.service` / `03919598d2774240a29e66b5986b2e2c` |
| R19 and Flickr resident screen | `resident-joint-board-v8/results.json` | `gr-retention-resident-joint-v8-20261104.service` / `7f4783a7a21b496a98fb7bcded9e16ee` |
| Remaining seven large workloads | `respr-matrix-v6/results.json` | `gr-retention-respr-matrix-v6-20261104.service` / `99ef84fee7e34a7485e5aaa52fccae2f` |

The remote link uses a 40 GiB hard cap, no swap, and the existing 128 GiB
reserve policy. The resident v8 and matrix v6 queues replace v7 and v5
before either attempted a board run. The resident runner accepts only
one candidate, after replaying its independently measured same-clock G
and R receipts. These are queued tests, not new hardware timings.
