# Original Artifact History

## Finding

Switching to an earlier public revision does not recover the missing publication
configuration or input converter. This bounded read-only audit strengthens the
source identity boundary; it is not a performance match or a new timing model.

| Artifact | Reachable commits checked | Inspected author path/blob versions | Finding |
| --- | ---: | ---: | --- |
| GraSU | 31 | 26 | Inspected segment declarations are all 16, not paper8; no temporal-conversion terms occur in these author texts |
| ReGraph | 21 | 57 | AE/Release to current author implementation differs only in host handling of the optional `numD` argument |
| Deleted GraSU ZIP | 450 indexed members | 18 source/saved-history texts | Same 16-slot declarations; no recovered temporal converter or original workload |

The accepted author HEADs remain pinned and clean. Fetching their complete Git
history does not replace a source file, generated kernel, plugin or result.
The ordinary stage controls and full temporal-count collector retain their
existing identities.

## GraSU

The public upload history includes a 24,046,082-byte `GraSU.zip` that was later
deleted. It is still reachable at
`0ebd62d2af91b068f45da275897b32c8f4b5bc53:GraSU.zip`, SHA-256
`049efb61af382117cd5e3faa7b5d35f36e2856f6788472718d0135480ef5fe83`.
We inspected its complete member inventory and eighteen declared text members:
nine source files and nine Eclipse local-history texts. The archive expands
to 92,668,852 bytes, but no historical executable, build product or project
metadata program was executed.

The older author tree uses `MAX_SEGMENT_SIZE=16` and a sixteen-entry PMA class;
the current source uses `SEGMENT_SIZE=16`. The early leaf kernel stores full
64-bit edge records, while the later cache/DDR implementation drops the source
word from device slots. These are distinct implementations; neither is admitted
as the paper's eight 32-bit entries merely because it is an older revision.

The complete historical path inventory contains no supplied temporal converter
or converted publication graph. The inspected source/saved-history texts have
no hits for the declared temporal terms. This is a bounded negative finding,
not proof that an author never had a converter: private files, unreachable Git
objects, unobserved branches and unexecuted binaries are outside this audit.
In particular, a keyword search alone is not treated as proof that arbitrary
binary contents contain no input data.

The [complete-trace denominator clue](PUBLICATION_WORKLOADS.md) is still useful,
but this history check does not recover its operation sequence. The next valid
publication-G admission needs actual converted inputs or a documented converter
and the original timing/aggregation rule. A newly chosen prefix or synthetic
operation stream cannot become the original workload just by matching its count.

## ReGraph

Both public tags `AE` and `Release` point to
`d04d971466bab71dd7c7a03ffd962546a7050814`. The accepted current source remains
`365456826cef495285383d939907f847e05ad74b`. Within the declared author
implementation directories, the only file changed between them is
`host/host.cpp`:

```cpp
// Release requires argv[3]; current source permits an omitted argument.
int numD = 1;
if (argc > 3) numD = atoi(argv[3]);
```

The raw report retains the exact diff. Thus, when our independent control
explicitly passes `numD=1`, this revision change does not explain a different
partition cut. The Little/Big arithmetic, merger, Apply, preprocessing and
top-level scheduling TODO are unchanged over that release-to-HEAD comparison.
Dataset and vendor-utility additions are listed in the Git inventory but are
not silently counted as algorithm changes.

The later batch-compilation helper enumerates heterogeneous pipeline counts;
it supplies neither graph-specific dense/sparse cuts nor original run profiling
logs. The wall-timer boundary and missing graph-selected configuration described
in [the event-window audit](PUBLICATION_WORKLOADS.md) remain unresolved for a
paper-rate comparison. The complete A4 and 11+3 source-functional results remain
valid in their declared scopes, not as a 10% U280 publication-speed certificate.

## Review And Reproduce

Read [the observations](publication_history.json) and
[verification](publication_history_verification.json); the
[raw package](raw_publication_history.tar.gz) includes the audit source,
contracts, tests, both complete accepted observations, the earlier narrower
inspection and resource logs. Large historical Git objects and external
checkouts are regenerated, not copied into this repository.

```bash
git -C build/publication_sources/grasu fetch --unshallow origin
git -C build/publication_sources/regraph fetch --unshallow --tags origin
python3 scripts/audit_upstream_publication_history.py \
  --out results/upstream_stage_controls/reproduce_publication_history
python3 -m unittest discover -s tests -p test_upstream_publication_history.py
```

Only run `--unshallow` on a shallow checkout; skip those two fetch commands
when its history is already complete. The auditor refuses shallow, dirty,
wrong-pin or unexpected-commit-set inputs. It never fetches or checks out
implicitly. Limits are 2 GiB address space, 16 GiB additional available memory,
180 seconds, 100 commits, 10,000 entries per tree, 2 MiB per text and bounded
archive expansion. The two accepted observations must match exactly, excluding
the separately recorded execution-resource measurements.
Both inspections completed in about 1.5 seconds, below 70 MiB maximum
individual-process RSS. Twelve new history tests, 114 related Python tests
and fifteen tests in the unchanged accepted C++ build pass.

Owner: `spine_cycle_sim/experiments/publication_admission/history/`. Git-object
access, source/archive inspection and bounded orchestration are separate small
modules behind a thin CLI. They do not alter the frozen temporal collector or
introduce another simulator mode. Use [current study status](README.md) for the
remaining G/A/A4/B/C work.

Primary source repositories: [GraSU](https://github.com/qgwang-hust/GraSU),
[ReGraph](https://github.com/Xtra-Computing/ReGraph).
