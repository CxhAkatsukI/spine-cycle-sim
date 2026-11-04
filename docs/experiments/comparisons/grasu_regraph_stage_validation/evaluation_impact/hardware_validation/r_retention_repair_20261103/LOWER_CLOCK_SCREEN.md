# Lower-Clock R Screen

This diagnostic compares both R arms at the same actual clock vector below
the nominal HBM target. It does not change the 450-MHz acceptance rule or
authorize a resident matrix. Each predeclared arm is measured once. The
logical input, one-superstep semantics, event boundary, output checks and
board must match before computing the 15% retention test.

## Clock-Control Check

The runtime `DRM_IOCTL_XOCL_RECLOCK` request on trifoliate's
`0000:c1:00.1` failed with `Timer expired`; the next clock read returned
all zeros and a bounded `xrt-smi examine` timed out. There was no timed
algorithm run, no further write was attempted on that board, and the
runtime-reclock helper is not included. The separately leased board at
`0000:82:00.1` reported normal nominal clocks before its own test.

The alternate control is an **offline packaging** change: set the
`SYSTEM/hbm_aclk` entry of the public image's `CLOCK_FREQ_TOPOLOGY` with
XRT `xclbinutil`, without relinking its design. The verifier checks that
every non-clock section, including the compute bitstream, memory map,
and CU connectivity, is byte-identical. The derived image has a new
UUID; the original is untouched. The candidate must use the vendor's
own packaged clock, not a locally modified candidate. The public package
does not establish the candidate's safe or actual operating frequency.

The first public arm was a single skewed-sources residual-PageRank
superstep with the original four-Little A4 host and the frozen
`csr_degree` fixture. The guard and output checks passed on
`0000:82:00.1`. The observed clock vector was `150/500/445/0 MHz` both
after programming and after the timed host (which reopens the image).
The device event span was **510,895 ns**. Programming and the clock
reads are outside the timed window. This is one reference arm only;
there is no measured candidate speed ratio at this clock yet.

## Receipts

Paths below are relative to
`/data/chuxiao/checks/source-retention-repair-20261104` on trifoliate.

| Item | Receipt | Status |
| --- | --- | --- |
| Runtime-reclock check | `hbm-control-qualification-440-v2/results.json` | Failed, no algorithm run |
| ResPR public 445-MHz package | `hbm-respr-a4-445-repackage-v1/package.json` | Ten non-clock sections byte-identical |
| ResPR public 445-MHz skewed-sources run | `hbm-respr-a4-445-skew-board-v1/results.json` | Passed, reference arm only |
| CC public 430-MHz package | `hbm-cc-a4-430-repackage-v1/package.json` | Verified offline, not yet measured |

The ResPR board receipt SHA-256 is
`f97471f56f75dc7e1c1c3f1234203ab0d66d5df1ba1ba84d3bbd6173b8e45d00`.
The service was `gr-retention-hbm-respr-a4-445-20261104-v1.service`,
invocation `1a0f5b4f0f15481d894a24a042d2113c`; its peak was 186.5 MiB.

The offline entry point is `source_retention.repackage_hbm`, with native
verifier source `cpp/tests/publication_sources/source_retention/verify_clock_repackage.cpp`.
The opt-in board preparation helper `source_retention.matched_hbm` checks
the complete counter vector before and after a timed host. Neither entry
point changes the nominal qualification path or the frozen figures.
