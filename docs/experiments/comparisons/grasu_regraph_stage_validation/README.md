# Isolated G / R Validation

Start with the [execution and acceptance plan](PLAN.md), then the preceding
[source/comparability audit](../grasu_regraph_publication_match/README.md).
This folder will own the new study's results and conclusions, rather than
scattering them among figure-refresh and daily investigation directories.

Status: pre-execution plan. No original-G or original-ReGraph publication
match, A4/B overhead measurement, or new FPGA timing is claimed yet.

[Independent upstream source pins](source_pins.json) record fresh clean
checkouts and inspected file hashes. They are distinct from the modified local
HLS ports. Reproduce them under ignored build output:

```bash
git clone https://github.com/Xtra-Computing/ReGraph.git build/publication_sources/regraph
git -C build/publication_sources/regraph checkout --detach 365456826cef495285383d939907f847e05ad74b
git clone https://github.com/qgwang-hust/GraSU.git build/publication_sources/grasu
git -C build/publication_sources/grasu checkout --detach e95da256be9e7f2361449323b6fe0abf98c1b152
```

One source-admission question needs care: current upstream GraSU defines
`SEGMENT_SIZE=16` and packs sixteen 32-bit slots into one 512-bit segment.
Reconcile the paper's segment-size units before treating the earlier audit's
"8 versus 16" description as a confirmed architectural penalty. A source pin
or plausible explanation is not a performance match.

The [SST/Spine extraction checkpoint](../../../repository/sst_spine_refactor/README.md)
must pass exact regression before new timing models are introduced. Existing
rejected fixtures are preserved there and cannot be admitted as study samples.
