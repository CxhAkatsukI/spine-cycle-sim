# Candidate 67 compact evidence

This directory contains one representative Candidate 67 native+PGO run, its
strict Candidate 24 equivalence report, and all three wall-clock repetitions.
The PGO profiles, optimized plugin, and raw run directories remain under
`/data/tmp/chuxiao`.

Both Spine and normalized GraSU+ReGraph execute during profile training. Native
PGO changes host code generation only; modeled architecture outputs remain
byte-identical.
