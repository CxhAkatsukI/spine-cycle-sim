# Profile evidence amendment repair

## Scope

Several multi-hour GraSU+ReGraph K1 children started before commit `236db10`
and completed while its profile evidence hashes were being repinned. The
architecture parameters and executable were unchanged. The only profile-field
change was `evidence[].sha256` for the runtime packed-address contract. The
children passed both correctness oracles and closed the DRAM and registered
arbitration ledgers, but the publication parent rejected them on the obsolete
arbitration cross-ledger and, for some runs, `profile_sha256`.

No simulator cycle result is edited. The repair reruns only the publication
parent over the immutable child artifacts.

## Fail-closed proof

The frozen ledger is
`configs/contracts/profile_evidence_amendments_v1.json`. The parent repair:

1. obtains the prior profile bytes from Git revision `32ec019`;
2. requires their SHA-256 to equal the child-observed profile SHA-256;
3. obtains the amended bytes from commit `236db10` and requires them to equal
   the current publication profile;
4. removes only the top-level `evidence` field and requires the remaining
   canonical JSON bytes to be identical;
5. reruns all ordinary parent gates, including dual-oracle correctness, DRAM
   request closure, registered arbitration closure, profile ID/path, graph
   identity, HBM binding, and final-state extraction.

The amendment option is rejected unless `--reuse-child` is also present.

## Reproduction

```bash
python3 scripts/repair_registered_arbitration_admission.py \
  --campaign-dir /data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_weighted_wave \
  --campaign-dir /data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_au_insert_endpoints \
  --campaign-dir /data/tmp/chuxiao/large_graph_campaign_v1/formal_v3_au_grasu_nonmonotonic

scripts/analyze_active_publication_campaigns.sh
python3 scripts/render_live_large_graph_report.py
latexmk -pdf -interaction=nonstopmode -halt-on-error -cd \
  docs/paper/large_graph_campaign_results.tex
```

Each repaired job records `registered_arbitration_repair.json` beside its
launcher log. A reused case records `admission.reused_child=true`; the one child
whose manifest retains the prior SHA additionally records the full
`admission.profile_evidence_amendment` proof.

## Result

Nine K1 results were recovered without rerunning simulation: AskUbuntu
insertion batches 1, 8, and 64, plus delete and weight-change batches 1, 8, and
64. All repaired case results have zero architecture and mathematical-oracle
mismatches and an empty parent-problem list. After refresh, the live publication
aggregate contains 66 passing executions, 40 complete Spine-versus-competitor
pairs, 9 update groups, and 437 component-activity rows. It remains `PARTIAL`
until the still-running large-graph executions finish.
