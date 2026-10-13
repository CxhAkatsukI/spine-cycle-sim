# Hot-Owner Evidence Guide

Start with [the interpretation](../README.md). This folder freezes a
prediction checkpoint, not baseline or hardware timing admission.

1. [index.json](index.json): hashes, 152 observations, 84 exact old replays,
   twelve extraction checks, all comparisons and explicit failed admission.
2. [matrix.json](matrix.json): four-arm declared inputs, source/binary pins,
   complete state hashes, cycles/traffic/work and bounded execution records.
3. [previous_search.json](previous_search.json): immutable 84-row source for
   exact old-path regression, not replaced by a new success claim.
4. [extraction.json](extraction.json): twelve default-path observations before
   enabling parallel hot owners, checked against the earlier search campaign.
5. `raw/`: stdout/stderr for every matrix command, including compiler and
   CMake version/configuration/build capture. Per-step resource records are
   embedded in `matrix.json`; complete PMA binaries stay at the indexed raw
   paths outside Git and were hash-checked at packaging.

`index.json` covers the frozen report/log copies, not this reading guide or
the separately owned [verification report](../verification.json). Do not
rewrite an index after changing a model. Package a new output directory.

Raw text is copied byte-for-byte, including compiler/tool whitespace. The
repository attributes disable whitespace warnings only for these raw and
verification text logs; source and documentation checks remain enabled.
