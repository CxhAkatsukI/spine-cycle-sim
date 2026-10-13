# Evidence Reading Order

1. [Final validation](final_validation/index.json): final runner, complete
   84-row matrix, original/current exact regression and both isolated HLS
   attempts. Empty input is explicitly excluded from performance gates.
   Performance and hardware admission remain false.
2. [Initial capsule](index.json): first complete 84-row run before compiler
   version capture and mandatory runner validation were added. All observation
   records and state hashes match final validation exactly.
3. [Runner validation replay](validated_replay/index.json): intermediate replay
   before the empty-input gate fix. All 84 observations match the final replay;
   the gate fix changes no cycle, state, traffic or pass/fail conclusion here.
4. `retained_*.json` in the initial capsule preserve the two failed source-helper
   attempts and the earlier 72-row intermediate matrix. The replay also retains
   the initial complete matrix. None is silently replaced or promoted.

Each index pins its own report files. Absolute raw paths locate inputs,
binaries, stdout/stderr, resource reports and HLS objects on the experiment
machine. Report copies are portable for inspection; raw machine-local artifacts
are not bundled as portable build inputs.

Start with the [checkpoint conclusions](../README.md), not the largest JSON.
