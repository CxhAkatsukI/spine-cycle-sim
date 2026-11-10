#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
tmp=$(mktemp -d)
trap 'rm -r -- "$tmp"' EXIT
sha256sum -c inputs.sha256
mapfile -t inputs < <(cut -c67- inputs.sha256)
"${CXX:-c++}" -std=c++17 -O2 -Wall -Wextra -Werror cpu_reference.cpp -o "$tmp/oracle"
{
    head -n 1 cpu_reference.csv
    printf 'fixture,'
    "$tmp/oracle" fixture.graph 0 "$tmp/fixture.tsv"
    printf 'AU,'
    "$tmp/oracle" "${inputs[0]}" 11
    printf 'RN,'
    "$tmp/oracle" "${inputs[1]}" 0
} | diff -u cpu_reference.csv -
diff -u <(printf 'vertex\told_width\tnew_width\n0\t4294967295\t4294967295\n1\t9\t9\n2\t4\t4\n3\t6\t7\n4\t6\t7\n5\t0\t0\n') "$tmp/fixture.tsv"
