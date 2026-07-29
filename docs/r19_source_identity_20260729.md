# R19-32 source identity

The formal R19 endpoint is now tied to the exact local source file rather than
only to the paper's nominal `2^24` generated-edge count. The file has SHA-256
`00a8886a5d0836e2839d50401142056f76cccd854845701b7a6100ca6db31125`,
contains 15,483,988 one-based `dst src` records, and spans IDs 1 through
524,288 on both endpoints.

After swapping to `src dst`, subtracting one, and removing 503 self-loops, GNU
`sort -u` reports 15,483,485 edges. There are no duplicate non-self records.
An older contract value, 15,481,655, differed by 1,830 and had no source hash or
reproduction evidence; it has been corrected before formal runs. The exact
audit is in `docs/evidence/r19_source_identity_20260729.json`.

The publication materializer rechecks the source hash and all normalization
counts before admitting the graph. Reproduce the complete materialization with:

```bash
cd /home/chuxiao/spine-cycle-sim-publication
python3 scripts/materialize_publication_workload.py \
  --dataset rmat_19_32 \
  --out-dir /data/tmp/chuxiao/large_graph_campaign_v1/workloads/rmat_19_32 \
  --sort-parallel 16 \
  --sort-memory 8G \
  --progress-path \
    /data/tmp/chuxiao/large_graph_campaign_v1/workloads/rmat_19_32.progress.json
```

The expected terminal summary is `status=pass`, `vertices=524288`,
`directed_edges=15483485`, and `reciprocal_edges=29732038`. The generated
`materialization_manifest.json` records every graph, update batch, count, byte
size, and SHA-256 digest; generated graph files remain outside Git.
