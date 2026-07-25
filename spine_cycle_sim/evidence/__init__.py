"""Parsers and ledgers for measured hardware evidence."""

from .fpga import (
    FpgaEvidenceError,
    analyze_fpga_manifest,
    parse_accelerator_utilization,
    parse_timing_summary,
    parse_xclbin_info,
    read_report,
)
from .energy import (
    EnergyEvidenceError,
    activity_count,
    aggregate_dramsim3,
    analyze_energy_manifest,
    build_cacti_p,
    cacti_source_identity,
    parse_cacti_output,
    render_cacti_config,
    reproduce_cacti_characterizations,
    run_cacti,
)
from .matched_energy import (
    CURRENT_GRASU_ARRAY_GEOMETRIES,
    MatchedEnergyError,
    aggregate_detailed_dramsim3,
    analyze_matched_pagerank_energy,
    flatten_component_rows,
    flatten_system_rows,
    grasu_selected_array_energy,
    load_current_grasu_characterizations,
)

__all__ = [
    "FpgaEvidenceError",
    "analyze_fpga_manifest",
    "parse_accelerator_utilization",
    "parse_timing_summary",
    "parse_xclbin_info",
    "read_report",
    "EnergyEvidenceError",
    "activity_count",
    "aggregate_dramsim3",
    "analyze_energy_manifest",
    "build_cacti_p",
    "cacti_source_identity",
    "parse_cacti_output",
    "render_cacti_config",
    "reproduce_cacti_characterizations",
    "run_cacti",
    "CURRENT_GRASU_ARRAY_GEOMETRIES",
    "MatchedEnergyError",
    "aggregate_detailed_dramsim3",
    "analyze_matched_pagerank_energy",
    "flatten_component_rows",
    "flatten_system_rows",
    "grasu_selected_array_energy",
    "load_current_grasu_characterizations",
]
