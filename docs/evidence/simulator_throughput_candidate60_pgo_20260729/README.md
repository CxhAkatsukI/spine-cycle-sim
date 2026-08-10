# Candidate 60 compact evidence

This directory contains one representative Candidate 60 PGO run, its strict
Candidate 24 equivalence report, and the three measured repetitions. The PGO
training data, optimized plugin, and raw run directories remain under
`/data/tmp/chuxiao`.

Both Spine and normalized GraSU+ReGraph were executed during profile training.
The PGO build changes host code generation only; modeled architecture results
remain byte-identical.
