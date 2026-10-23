#include "../detail/routed_regraph_system.hpp"

#include <limits>
#include <set>

namespace spine::sim {

RoutedReGraphConfig::RoutedReGraphConfig() {
  compute.compute_pipelines = 4;
  compute.shared_downstream = true;
  compute.sharded_runtime_placement = true;
  compute.source_state_channel = 23;
  compute.source_state_mirror_channel = 24;
  compute.source_state_buffer_stride = 0x2000'0000ULL;
  compute.max_supersteps = 128;
}

void RoutedReGraphSystem::Impl::admit() {
  const auto &c = config.compute;
  if (config.apply_topology != RoutedApplyTopology::kSharedMaster &&
      config.apply_topology != RoutedApplyTopology::kSplitMastersExperimental)
    throw std::invalid_argument("unsupported routed Apply master topology");
  if (config.source_loading != RoutedSourceLoading::kEdgeCoupled &&
      config.source_loading != RoutedSourceLoading::kIndependentExperimental)
    throw std::invalid_argument("unsupported routed source-cache loading schedule");
  if (config.input_path != RoutedInputPath::kPhysicalSlots &&
      config.input_path != RoutedInputPath::kPrefetchCompactedExperimental &&
      config.input_path != RoutedInputPath::kDualPrefetchElasticExperimental &&
      config.input_path != RoutedInputPath::kTriplePrefetchElasticExperimental)
    throw std::invalid_argument("unsupported routed input path");
  const bool compact = config.input_path != RoutedInputPath::kPhysicalSlots;
  if ((config.experimental_directory_tiles != 1 && config.experimental_directory_tiles != 2) ||
      (config.experimental_directory_tiles == 2 &&
       config.input_path != RoutedInputPath::kTriplePrefetchElasticExperimental))
    throw std::invalid_argument("directory lookahead requires two finite tiles and a dedicated input master");
  const auto masters = (config.source_topology == RoutedSourceTopology::kTwoPairwise ? 7U : 9U) +
      (config.input_path == RoutedInputPath::kTriplePrefetchElasticExperimental ? 8U :
       config.input_path == RoutedInputPath::kDualPrefetchElasticExperimental ? 4U : 0U) +
      (config.apply_topology == RoutedApplyTopology::kSplitMastersExperimental ? 1U : 0U);
  if (compact && (!config.adapter.cross_row.bank_read_beats ||
                  !config.adapter.read_pipeline_cycles || c.max_pending_requests < 16 ||
                  c.max_outstanding_bursts < 16))
    throw std::invalid_argument("experimental prefetch input requires streaming beats and sixteen parent slots");
  if (config.source_topology != RoutedSourceTopology::kFourDedicated &&
      config.source_topology != RoutedSourceTopology::kTwoPairwise)
    throw std::invalid_argument("unsupported routed source-reader topology");
  if (config.reuse_resident_pma && backend.outstanding() != 0)
    throw std::invalid_argument("resident PMA handoff requires a drained memory backend");
  if (layout.vertices == 0 || layout.vertices > std::numeric_limits<std::uint32_t>::max() ||
      layout.partition_vertices != 65536 || layout.partitions.empty() || layout.partitions.size() > 1020 ||
      layout.partitions.size() != (layout.vertices + 65535) / 65536 ||
      c.memory_channels != 32 || c.compute_pipelines != 4 || !c.shared_downstream ||
      !c.sharded_runtime_placement || c.partition_vertices != 65536 || c.source_buffer_vertices != 4096 ||
      c.source_state_channel != 23 || c.source_state_mirror_channel != 24 || c.vertex_state_channel != 30 ||
      c.edge_lanes != 8 || c.gather_banks != 8 || !c.max_supersteps ||
      !c.max_pending_requests || !c.max_outstanding_bursts || !c.response_beats_per_cycle ||
      !c.gather_vertices_per_reset_cycle || c.gather_vertices_per_merge_cycle != 2 || !c.gather_pipeline_latency ||
      !c.apply_request_window || !c.apply_pipeline_capacity || !c.hbm_wrapper_pipeline_capacity ||
      !config.internal_fifo_depth || !config.external_fifo_depth || !config.shared_master_capacity ||
      !config.adapter_stream_depth || !config.gather_stream_depth || !config.mux_stream_depth ||
      config.first_initiator_id > std::numeric_limits<std::uint32_t>::max() - masters ||
      config.fixed_rounds > c.max_supersteps ||
      c.runtime_channel_capacity_bytes > kGraSuReGraphU55cChannelCapacityBytes ||
      config.adapter.format != ReGraphPmaFormat::kWeighted)
    throw std::invalid_argument("unsupported measured SSSP K4 topology, dimensions or finite capacities");
  padded_vertices = layout.partitions.size() * 65536;
  const auto state_bytes = padded_vertices * 4;
  if (state_bytes > kGraSuReGraphU55cChannelCapacityBytes / 2 ||
      c.source_state_buffer_stride < state_bytes || c.source_state_base % 64 ||
      c.source_state_buffer_stride % 64 || c.vertex_state_base % 64 ||
      c.source_state_buffer_stride > std::numeric_limits<std::uint64_t>::max() - state_bytes ||
      c.source_state_base > std::numeric_limits<std::uint64_t>::max() - c.source_state_buffer_stride - state_bytes ||
      c.vertex_state_base > std::numeric_limits<std::uint64_t>::max() - state_bytes ||
      config.status_address > std::numeric_limits<std::uint64_t>::max() - 4 ||
      config.status_address % 4 ||
      (config.status_address < c.vertex_state_base + state_bytes &&
       config.status_address + 4 > c.vertex_state_base))
    throw std::invalid_argument("invalid or overlapping resident state allocations");
  if (initial.primary.size() != layout.vertices || !initial.auxiliary.empty())
    throw std::invalid_argument("SSSP resident state shape differs from the logical graph");
  std::set<std::uint32_t> active;
  for (auto vertex : initial.active_vertices)
    if (vertex >= layout.vertices || !active.insert(vertex).second)
      throw std::invalid_argument("invalid or duplicate SSSP active vertex");
  std::uint64_t largest_initial = 0, largest_weight = 0;
  for (auto value : initial.primary) {
    if (value != GraphAlgorithmPolicy::kSsspInfinity && value >= detail::kReGraphInfinity)
      throw std::invalid_argument("SSSP state does not fit the routed signed payload ABI");
    if (value != GraphAlgorithmPolicy::kSsspInfinity) largest_initial = std::max(largest_initial, std::uint64_t(value));
  }

  for (std::size_t p = 0; p < layout.partitions.size(); ++p) {
    auto &part = layout.partitions[p];
    const auto expected_vertices = std::min<std::size_t>(65536, layout.vertices - p * 65536);
    if (part.vertices != layout.vertices || part.destination_base != p * 65536 ||
        part.destination_vertices != expected_vertices || part.row_slot_bounds.size() != layout.vertices ||
        part.pma_word_abi != GraSuPmaWordAbi::kWeightedFullWord ||
        part.segments.size() > std::numeric_limits<std::uint32_t>::max() / 16)
      throw std::invalid_argument("PMA shard does not match the measured weighted destination partition");
    std::size_t next = 0, last_source = 0;
    for (std::size_t source = 0; source < layout.vertices; ++source) {
      const auto [begin, end] = part.row_slot_bounds[source];
      if (begin != next || end < begin || end % 16 || end > part.segments.size() * 16)
        throw std::invalid_argument("PMA row bounds are not contiguous segment-aligned slots");
      next = end;
      if (end != begin) last_source = source;
    }
    if (next != part.segments.size() * 16)
      throw std::invalid_argument("PMA extent differs from the allocated segments");
    if ((last_source / 4096 + 2) * 4096 > padded_vertices)
      throw std::invalid_argument("Scatter source lookahead exceeds the measured host allocation");
    for (const auto &segment : part.segments)
      for (auto word : segment) {
        if (word & 0x80000000U) continue;
        if ((word & 0x7ffffU) >= part.destination_vertices)
          throw std::invalid_argument("PMA live destination is outside its logical shard");
        largest_weight = std::max(largest_weight, std::uint64_t((word >> 19) & 0xfffU));
        if (compact && ((word >> 19) & 0xfffU) == 0)
          throw std::invalid_argument("experimental compact input currently admits positive weights only");
      }

    // The routed host reserves a real all-dummy source-0 segment even if that
    // row has no live edge. Keep its traffic and source-cache cost visible.
    if (part.row_slot_bounds[0].second == 0) {
      if (config.reuse_resident_pma)
        throw std::invalid_argument("resident PMA must already contain the routed source-0 dummy reservation");
      if (part.segments.size() == std::numeric_limits<std::uint32_t>::max() / 16)
        throw std::invalid_argument("dummy reservation would overflow PMA slot count");
      std::array<std::uint32_t, 16> dummy;
      dummy.fill(kGraSuPmaEmpty);
      part.segments.insert(part.segments.begin(), dummy);
      for (auto &[begin, end] : part.row_slot_bounds) { begin += 16; end += 16; }
      part.row_slot_bounds[0].first = 0;
    }
    // Runtime placement only needs the binary allocation shape here; binary
    // contents are maintenance state, not read by this compute-only system.
    part.binary_heads.resize(part.segments.size());
  }
  // Legacy arithmetic saturates at a different infinity from the HLS UDF.
  // Admit only a conservative domain where no executed walk can hit that
  // difference; do not silently clip a candidate and call it HLS-equivalent.
  const auto horizon = config.fixed_rounds ? config.fixed_rounds : c.max_supersteps;
  if (largest_weight && horizon > (detail::kReGraphInfinity - 1 - largest_initial) / largest_weight)
    throw std::invalid_argument("routed SSSP near-infinity arithmetic is outside the admitted domain");
  auto updates = c.runtime_physical_updates_per_shard;
  if (updates.empty()) updates.resize(layout.partitions.size());
  plan = build_grasu_regraph_runtime_plan(layout, updates,
      c.cache_segments_per_half, 23, c.runtime_channel_capacity_bytes);
}

} // namespace spine::sim
