# Large-graph source format audit

Before materialization, the six Dynamic-ACTS archives were inspected directly.
The frozen source hashes were unchanged, but the initial contract had two
invalid or missing archive members and projection labels that did not reproduce the
paper's edge-count convention.

- `soc-LiveJournal1.tar.gz` contains
  `soc-LiveJournal1/soc-LiveJournal1.mtx`, not a `.txt` member.
- `com-Orkut.tar.gz` uses `com-Orkut/com-Orkut.mtx`; this member is now
  explicit rather than relying on an archive-name guess.
- Pokec stores 30,622,564 entries while the paper reports about 61M edges.
- LiveJournal1 stores 68,993,773 entries while the paper reports about 137M.
- ljournal-2008 stores 79,023,142 entries while the paper reports about 158M.

Those three general matrices now explicitly use the same reciprocal projection
already required for Orkut. Hollywood remains governed by its Matrix Market
`symmetric` header. UK-2002 remains directed and uses its 298,113,762 stored
entries. The machine-readable audit is in
`docs/evidence/large_graph_source_format_audit_20260729.json`.

This is a pre-execution input correction, not a performance-dependent parameter
change. Formal rows will record raw stored entries, projected edges, duplicate
and self-loop removal, exact vertex-ID normalization, and generated artifact
hashes.
