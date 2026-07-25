"""Reproducible experiment corpora and comparison contracts."""

from .shared_workloads import (
    DEFAULT_REAL_SOURCES,
    SliceGraph,
    SliceRecord,
    build_shared_comparison_corpus,
    load_slice,
    validate_shared_comparison_manifest,
)

__all__ = [
    "DEFAULT_REAL_SOURCES",
    "SliceGraph",
    "SliceRecord",
    "build_shared_comparison_corpus",
    "load_slice",
    "validate_shared_comparison_manifest",
]
