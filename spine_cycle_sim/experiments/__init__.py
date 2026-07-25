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
from .profile_capabilities import (
    AlgorithmCapability,
    CapabilityCatalog,
    CapabilityError,
    ImplementationStatus,
    ProfileCapability,
    load_capability_catalog,
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
    "AlgorithmCapability",
    "CapabilityCatalog",
    "CapabilityError",
    "ImplementationStatus",
    "ProfileCapability",
    "load_capability_catalog",
]
