"""Reproducible experiment corpora and comparison contracts."""

from .shared_workloads import (
    DEFAULT_REAL_SOURCES,
    SliceGraph,
    SliceRecord,
    build_shared_comparison_corpus,
    load_slice,
    validate_shared_comparison_manifest,
)
from .comparison import (
    RunInvocation,
    build_invocation,
    implementation_fingerprint,
    pair_rows,
    select_runs,
    validate_system_result,
)

__all__ = [
    "DEFAULT_REAL_SOURCES",
    "SliceGraph",
    "SliceRecord",
    "build_shared_comparison_corpus",
    "load_slice",
    "validate_shared_comparison_manifest",
    "RunInvocation",
    "build_invocation",
    "implementation_fingerprint",
    "pair_rows",
    "select_runs",
    "validate_system_result",
]
