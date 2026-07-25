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
from .hls_weighted_workloads import HlsWeightedFixture, hls_weighted_fixtures
from .real_small_batches import (
    RealSmallBatch,
    build_real_small_batches,
    validate_real_small_batch_manifest,
)
from .hls_real_comparison import (
    pair_row as hls_real_pair_row,
    validate_grasu_hls_result,
    validate_spine_dynamic_result,
)
from .hls_pagerank_real_comparison import (
    pair_row as hls_pagerank_real_pair_row,
    residual_pair_row as hls_residual_pagerank_real_pair_row,
    validate_grasu_pagerank_result,
    validate_grasu_residual_result,
    validate_spine_pagerank_result,
    validate_spine_residual_result,
)
from .memory_traffic import (
    BACKEND_LINE_BYTES,
    memory_traffic_metrics,
    phase_memory_is_valid,
    phase_memory_metrics,
    split_memory_metrics,
)
from .real_memory_analysis import (
    load_matrix as load_real_memory_matrix,
    normalize_system_row as normalize_real_memory_system_row,
    pair_memory_rows,
    summarize_pairs as summarize_real_memory_pairs,
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
    "HlsWeightedFixture",
    "hls_weighted_fixtures",
    "RealSmallBatch",
    "build_real_small_batches",
    "validate_real_small_batch_manifest",
    "hls_real_pair_row",
    "validate_grasu_hls_result",
    "validate_spine_dynamic_result",
    "hls_pagerank_real_pair_row",
    "hls_residual_pagerank_real_pair_row",
    "validate_grasu_pagerank_result",
    "validate_grasu_residual_result",
    "validate_spine_pagerank_result",
    "validate_spine_residual_result",
    "BACKEND_LINE_BYTES",
    "memory_traffic_metrics",
    "phase_memory_is_valid",
    "phase_memory_metrics",
    "split_memory_metrics",
    "load_real_memory_matrix",
    "normalize_real_memory_system_row",
    "pair_memory_rows",
    "summarize_real_memory_pairs",
]
