#include "spine_sim/spine_split.hpp"

#include <algorithm>
#include <bit>
#include <limits>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kActiveRecordBytes = 32;
constexpr std::uint64_t kMetadataWordBytes = 8;
constexpr std::uint64_t kVertexWordBytes = 4;
constexpr std::uint64_t kActiveOutputBytes = 8;
constexpr std::uint64_t kResultBytes = 96 * 4;
constexpr std::uint32_t kTileVertices = 65'536;
constexpr std::uint64_t kMetadataWordsPerSlice = 8;
constexpr std::uint64_t kFamilyCount = 32;
constexpr std::uint64_t kLevelCount = 11;
constexpr std::uint64_t kPartitionCount = 16;
constexpr std::uint64_t kPageCount = (1U << 24) / 256;
constexpr std::uint64_t kMetadataSliceWords =
    kFamilyCount * kLevelCount * kMetadataWordsPerSlice;
constexpr std::uint64_t kMetadataBaseWords =
    kMetadataSliceWords + 2 * kPartitionCount;
constexpr std::uint64_t kTouchedSlotWords = 5 + kPageCount;
constexpr std::uint64_t kTouchedWords = kMetadataBaseWords +
                                        2 * kPartitionCount +
                                        2 * kPartitionCount * kTouchedSlotWords;
constexpr std::uint64_t kSliceEpochBaseWords = kTouchedWords;
constexpr std::uint64_t kSliceEpochWords = (kFamilyCount * kLevelCount + 1) / 2;
constexpr std::uint64_t kPageEpochBaseWords =
    kSliceEpochBaseWords + kSliceEpochWords;
constexpr std::size_t kRangeTaskCapacity = 65'536;
constexpr std::size_t kRangeTaskActiveGate = 16'384;
constexpr std::uint64_t kRangeTaskPayloadBudget = 1'048'576;
constexpr std::size_t kRangeTaskMaxTiles = 256;
constexpr std::uint64_t kRangeTaskMaxStart = std::uint64_t{1} << 26;
constexpr std::uint32_t kRangeTaskMaxLength = std::uint32_t{1} << 24;

constexpr std::uint32_t kRangeTaskPathExact = 1;
constexpr std::uint32_t kRangeTaskPathFallback = 2;
constexpr std::uint32_t kRangeTaskPathError = 3;
constexpr std::uint32_t kRangeTaskFallbackActiveGate = 1;
constexpr std::uint32_t kRangeTaskFallbackCapacity = 2;
constexpr std::uint32_t kRangeTaskFallbackPayloadBudget = 3;
constexpr std::uint32_t kRangeTaskErrorActiveBounds = 2;
constexpr std::uint32_t kRangeTaskErrorMetadata = 3;
constexpr std::uint32_t kRangeTaskErrorDestination = 4;
constexpr std::uint32_t kRangeTaskErrorPrefix = 5;
constexpr std::uint32_t kRangeTaskErrorDescriptor = 6;

std::uint32_t saturating_add(std::uint32_t left, std::uint16_t right) {
  if (left == SpineSplitSsspCompute::kInfinity ||
      left > SpineSplitSsspCompute::kInfinity - right) {
    return SpineSplitSsspCompute::kInfinity;
  }
  return left + right;
}

std::vector<std::uint8_t> encode_u32(std::uint32_t value) {
  return {
      static_cast<std::uint8_t>(value & 0xffU),
      static_cast<std::uint8_t>((value >> 8) & 0xffU),
      static_cast<std::uint8_t>((value >> 16) & 0xffU),
      static_cast<std::uint8_t>((value >> 24) & 0xffU),
  };
}

std::uint32_t decode_u32(const std::vector<std::uint8_t> &data,
                         std::size_t offset = 0) {
  if (offset + sizeof(std::uint32_t) > data.size()) {
    throw std::invalid_argument("uint32 payload is truncated");
  }
  return static_cast<std::uint32_t>(data[offset]) |
         (static_cast<std::uint32_t>(data[offset + 1]) << 8) |
         (static_cast<std::uint32_t>(data[offset + 2]) << 16) |
         (static_cast<std::uint32_t>(data[offset + 3]) << 24);
}

std::uint64_t decode_u64(const std::vector<std::uint8_t> &data,
                         std::size_t offset = 0) {
  if (offset + sizeof(std::uint64_t) > data.size()) {
    throw std::invalid_argument("uint64 payload is truncated");
  }
  std::uint64_t value = 0;
  for (std::size_t byte = 0; byte < sizeof(std::uint64_t); ++byte) {
    value |= static_cast<std::uint64_t>(data[offset + byte]) << (byte * 8);
  }
  return value;
}

std::vector<std::uint8_t> encode_u32_words(
    const std::vector<std::uint32_t> &values) {
  std::vector<std::uint8_t> data(values.size() * sizeof(std::uint32_t));
  for (std::size_t index = 0; index < values.size(); ++index) {
    const std::vector<std::uint8_t> word = encode_u32(values[index]);
    std::copy(word.begin(), word.end(),
              data.begin() + static_cast<std::ptrdiff_t>(index * word.size()));
  }
  return data;
}

}  // namespace

SpineSplitReader::SpineSplitReader(std::string name, ClockId clock_id,
                                   const SpineL0Maintenance &maintenance,
                                   const SpineL0State &state,
                                   SpineReaderPorts ports,
                                   std::vector<std::uint32_t> active_sources,
                                   Fifo<PartConvWord> &edge_out,
                                   Fifo<SourceValueWord> &value_in)
    : Component(std::move(name), clock_id),
      maintenance_(maintenance),
      state_(state),
      ports_(ports),
      active_sources_(std::move(active_sources)),
      edge_out_(edge_out),
      value_in_(value_in) {
  if (active_sources_.empty() || ports_.active_bins == nullptr ||
      ports_.metadata == nullptr || edge_out_.clock_id() != clock_id ||
      value_in_.clock_id() != clock_id) {
    throw std::invalid_argument("invalid Spine split reader configuration");
  }
  for (FixedAxiPort *port : ports_.graph) {
    if (port == nullptr) {
      throw std::invalid_argument("Spine reader graph AXI port is null");
    }
  }
}

void SpineSplitReader::reset_round(std::vector<std::uint32_t> active_sources) {
  if (!done_ || failed_ || waiting_memory_ || !memory_tasks_.empty() ||
      active_sources.empty()) {
    throw std::logic_error("reader round reset requires a successful drain");
  }
  active_sources_ = std::move(active_sources);
  counters_ = {};
  for (std::size_t tile = 0; tile < tiles_.size(); ++tile) {
    tiles_[tile].tile_base = static_cast<std::uint32_t>(tile * kTileVertices);
    tiles_[tile].ranges.clear();
  }
  tile_counts_.fill(0);
  tile_offsets_.fill(0);
  tile_cursors_.fill(0);
  range_probes_.clear();
  range_tasks_.clear();
  source_values_.clear();
  memory_tasks_.clear();
  phase_ = Phase::kWaitMaintenance;
  staged_action_ = Action::kNone;
  probe_index_ = 0;
  construction_position_ = 0;
  construction_run_valid_ = false;
  construction_run_tile_ = 0;
  construction_run_start_ = 0;
  construction_run_length_ = 0;
  construction_previous_dst_ = 0;
  construction_have_previous_dst_ = false;
  bin_index_ = 0;
  scatter_index_ = 0;
  tile_index_ = 0;
  range_index_ = 0;
  range_edge_index_ = 0;
  source_index_ = 0;
  waiting_memory_ = false;
  done_ = false;
  failed_ = false;
  failure_.clear();
}

void SpineSplitReader::evaluate(const CycleContext &) {
  staged_action_ = Action::kNone;
  if (done_ || failed_) {
    return;
  }
  if (waiting_memory_) {
    if (memory_tasks_.empty()) {
      throw std::logic_error("reader memory wait has no task");
    }
    if (memory_tasks_.front().port->responses().try_pop(staged_response_)) {
      staged_action_ = Action::kComplete;
    }
    return;
  }
  if (!memory_tasks_.empty()) {
    const MemoryTask &task = memory_tasks_.front();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = MemoryOperation::kRead,
            .address = task.address,
            .bytes = task.bytes,
            .write_data = {},
        })) {
      staged_action_ = Action::kIssue;
    }
    return;
  }
  if (phase_ == Phase::kWaitSource) {
    if (value_in_.try_pop(staged_value_)) {
      staged_action_ = Action::kPopValue;
    }
    return;
  }
  if (phase_ == Phase::kRequestSource || phase_ == Phase::kTileBegin ||
      phase_ == Phase::kEdgeEmit || phase_ == Phase::kTileEnd ||
      phase_ == Phase::kDone) {
    staged_stream_word_ = current_stream_word();
    if (edge_out_.try_push(staged_stream_word_)) {
      staged_action_ = Action::kPush;
    }
    return;
  }
  staged_action_ = Action::kAdvance;
}

void SpineSplitReader::commit(const CycleContext &context) {
  switch (staged_action_) {
    case Action::kNone:
      return;
    case Action::kIssue:
      expected_transaction_id_ = next_transaction_id_++;
      waiting_memory_ = true;
      return;
    case Action::kComplete:
      if (!staged_response_.success ||
          staged_response_.transaction_id != expected_transaction_id_) {
        failed_ = true;
        done_ = true;
        failure_ = "reader AXI response failed or changed transaction order";
        return;
      }
      consume_memory_response(memory_tasks_.front(), staged_response_);
      waiting_memory_ = false;
      memory_tasks_.pop_front();
      return;
    case Action::kPopValue:
      if (source_index_ >= active_sources_.size() ||
          staged_value_.source != active_sources_[source_index_]) {
        failed_ = true;
        done_ = true;
        failure_ = "reader source-value response did not match its request";
        return;
      }
      source_values_[staged_value_.source] = staged_value_.value;
      ++counters_.source_responses;
      ++source_index_;
      phase_ = source_index_ == active_sources_.size() ? Phase::kSetupReads
                                                       : Phase::kRequestSource;
      return;
    case Action::kPush:
      switch (phase_) {
        case Phase::kRequestSource:
          ++counters_.source_requests;
          phase_ = Phase::kWaitSource;
          break;
        case Phase::kTileBegin:
          ++counters_.tiles_emitted;
          range_index_ = 0;
          range_edge_index_ = 0;
          phase_ = Phase::kEdgeRead;
          break;
        case Phase::kEdgeEmit:
          ++counters_.edges_emitted;
          if (tiles_.at(tile_index_).ranges.at(range_index_).hot) {
            ++counters_.hot_edges_emitted;
          } else {
            ++counters_.cold_edges_emitted;
          }
          ++range_edge_index_;
          phase_ = Phase::kEdgeRead;
          break;
        case Phase::kTileEnd:
          ++tile_index_;
          phase_ = Phase::kTileScan;
          break;
        case Phase::kDone:
          counters_.end_cycle = context.domain_cycle;
          done_ = true;
          break;
        default:
          throw std::logic_error(
              "reader pushed a word from a non-stream phase");
      }
      return;
    case Action::kAdvance:
      advance(context);
      return;
  }
}

void SpineSplitReader::enqueue_read(FixedAxiPort &port, std::uint64_t address,
                                    std::uint64_t bytes,
                                    MemoryPayloadKind payload_kind,
                                    std::size_t probe_index,
                                    std::uint32_t edge_source) {
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .address = address,
      .bytes = bytes,
      .edge_source = edge_source,
      .probe_index = probe_index,
      .payload_kind = payload_kind,
  });
  if (&port == ports_.active_bins) {
    counters_.active_bin_read_bytes += bytes;
  } else if (&port == ports_.metadata) {
    counters_.metadata_read_bytes += bytes;
  } else {
    counters_.graph_read_bytes += bytes;
  }
}

void SpineSplitReader::consume_memory_response(const MemoryTask &task,
                                               const AxiResponse &response) {
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine reader payload size mismatch");
  }
  const bool probe_payload =
      task.payload_kind == MemoryPayloadKind::kIndexBitmapSelected ||
      task.payload_kind == MemoryPayloadKind::kIndexBitmapPrefix ||
      task.payload_kind == MemoryPayloadKind::kIndexPageBase ||
      task.payload_kind == MemoryPayloadKind::kIndexRow ||
      task.payload_kind == MemoryPayloadKind::kIndexNextRow;
  if (probe_payload && task.probe_index >= range_probes_.size()) {
    throw std::logic_error("Spine reader response references an invalid probe");
  }
  switch (task.payload_kind) {
    case MemoryPayloadKind::kNone:
      return;
    case MemoryPayloadKind::kIndexBitmapSelected: {
      RangeProbe &probe = range_probes_[task.probe_index];
      probe.bitmap_words.assign(probe.lane_word + 1, 0);
      probe.bitmap_words[probe.lane_word] = decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      ++counters_.graph_index_bitmap_words;
      return;
    }
    case MemoryPayloadKind::kIndexBitmapPrefix: {
      RangeProbe &probe = range_probes_[task.probe_index];
      const std::size_t words =
          response.read_data.size() / kSpineGraphWordBytes;
      if (probe.bitmap_words.size() != probe.lane_word + 1 ||
          words != probe.lane_word) {
        throw std::logic_error("Spine bitmap-rank prefix has wrong length");
      }
      for (std::size_t word = 0; word < words; ++word) {
        probe.bitmap_words[word] =
            decode_u64(response.read_data, word * kSpineGraphWordBytes);
      }
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      counters_.graph_index_bitmap_words += words;
      return;
    }
    case MemoryPayloadKind::kIndexPageBase:
      range_probes_[task.probe_index].page_base_word =
          decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kIndexRow:
      range_probes_[task.probe_index].row_word = decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kIndexNextRow:
      range_probes_[task.probe_index].next_row_word =
          decode_u64(response.read_data);
      counters_.graph_index_payload_read_bytes += response.read_data.size();
      return;
    case MemoryPayloadKind::kConstructionEdge:
      construction_edge_ =
          decode_spine_level_edge(response.read_data, task.edge_source);
      counters_.graph_edge_payload_read_bytes += response.read_data.size();
      counters_.graph_construction_payload_read_bytes +=
          response.read_data.size();
      ++counters_.range_task_construction_payloads;
      return;
    case MemoryPayloadKind::kReplayEdge:
      loaded_edge_ =
          decode_spine_level_edge(response.read_data, task.edge_source);
      counters_.graph_edge_payload_read_bytes += response.read_data.size();
      counters_.graph_replay_payload_read_bytes += response.read_data.size();
      ++counters_.range_task_replay_payloads;
      if (tile_index_ >= tiles_.size() ||
          loaded_edge_.dst < tiles_[tile_index_].tile_base ||
          loaded_edge_.dst >= maintenance_.vertices() ||
          static_cast<std::uint64_t>(loaded_edge_.dst) >=
              static_cast<std::uint64_t>(tiles_[tile_index_].tile_base) +
                  kTileVertices) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorDestination;
        failed_ = true;
        done_ = true;
        failure_ = "range-task replay returned an edge outside its tile";
      }
      return;
  }
}

void SpineSplitReader::prepare_range_probes() {
  counters_.range_task_active_records = active_sources_.size();
  if (active_sources_.size() > kRangeTaskActiveGate) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackActiveGate;
    failed_ = true;
    done_ = true;
    failure_ = "device-dirty exact path exceeded the active-record gate";
    return;
  }
  for (const std::uint32_t source : active_sources_) {
    if (source >= maintenance_.vertices() ||
        source >= maintenance_.config().max_vertices) {
      counters_.range_task_path = kRangeTaskPathError;
      counters_.range_task_error = kRangeTaskErrorActiveBounds;
      failed_ = true;
      done_ = true;
      failure_ = "active source is outside the configured graph";
      return;
    }
  }

  const auto visit = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      for (const std::uint32_t source : active_sources_) {
        ++counters_.range_task_family_probes;
        for (std::size_t level_index = 0; level_index < families[family].size();
             ++level_index) {
          const auto &level = families[family][level_index];
          if (level.size() > std::numeric_limits<std::uint32_t>::max()) {
            counters_.range_task_path = kRangeTaskPathError;
            counters_.range_task_error = kRangeTaskErrorMetadata;
            failed_ = true;
            done_ = true;
            failure_ = "occupied level exceeds the range-task edge-count field";
            return;
          }
          const std::uint32_t lane =
              source % maintenance_.config().page_vertices;
          range_probes_.push_back(RangeProbe{
              .source = source,
              .source_value = source_values_.at(source),
              .family = family,
              .level = level_index,
              .hot = hot,
              .layout =
                  spine_level_layout(maintenance_.config(), hot, level_index),
              .edge_count = static_cast<std::uint32_t>(level.size()),
              .page = source / maintenance_.config().page_vertices,
              .lane_word = lane / 64,
              .lane_bit = lane % 64,
              .bitmap_words = {},
              .page_base_word = 0,
              .row_word = 0,
              .next_row_word = 0,
              .rank = 0,
              .row = 0,
              .start = 0,
              .end = 0,
          });
          if (!level.empty()) {
            ++counters_.range_task_row_lookups;
          }
        }
      }
    }
  };
  visit(state_.cold_levels, false);
  if (!failed_ && state_.hot_enabled) {
    visit(state_.hot_levels, true);
  }
}

void SpineSplitReader::enqueue_probe_index_reads() {
  if (probe_index_ >= range_probes_.size()) {
    throw std::logic_error("range probe index is out of bounds");
  }
  RangeProbe &probe = range_probes_[probe_index_];
  probe.bitmap_words.clear();
  probe.page_base_word = 0;
  probe.row_word = 0;
  probe.next_row_word = 0;
  probe.rank = 0;
  const std::uint64_t logical_family =
      probe.hot ? 16 + probe.family : probe.family;
  const std::uint64_t slice = logical_family * kLevelCount + probe.level;
  const std::uint64_t page_epoch_index = slice * kPageCount + probe.page;
  enqueue_read(
      *ports_.metadata,
      maintenance_.config().metadata_base +
          (kPageEpochBaseWords + (page_epoch_index >> 1)) * kMetadataWordBytes,
      kMetadataWordBytes);
  counters_.row_lookup_metadata_bytes += kMetadataWordBytes;

  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.bitmap_offset_words +
                static_cast<std::uint64_t>(probe.page) * 4 + probe.lane_word) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexBitmapSelected,
               probe_index_);
}

void SpineSplitReader::resolve_probe_index() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if (probe.bitmap_words.size() != probe.lane_word + 1) {
    throw std::logic_error("range probe bitmap prefix has the wrong length");
  }
  const std::uint64_t selected = probe.bitmap_words[probe.lane_word];
  if ((selected & (std::uint64_t{1} << probe.lane_bit)) == 0) {
    ++counters_.graph_index_bitmap_misses;
    phase_ = Phase::kProbeAdvance;
    return;
  }
  if (probe.lane_word != 0) {
    enqueue_read(
        *ports_.graph[probe.family],
        (probe.layout.bitmap_offset_words +
         static_cast<std::uint64_t>(probe.page) * 4) *
            kSpineGraphWordBytes,
        static_cast<std::uint64_t>(probe.lane_word) * kSpineGraphWordBytes,
        MemoryPayloadKind::kIndexBitmapPrefix, probe_index_);
    phase_ = Phase::kProbeRankResolve;
    return;
  }
  resolve_probe_rank();
}

void SpineSplitReader::resolve_probe_rank() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint64_t selected = probe.bitmap_words.at(probe.lane_word);
  std::uint32_t rank = 0;
  for (std::size_t word = 0; word < probe.lane_word; ++word) {
    rank += std::popcount(probe.bitmap_words[word]);
  }
  if (probe.lane_bit != 0) {
    rank +=
        std::popcount(selected & ((std::uint64_t{1} << probe.lane_bit) - 1));
  }
  probe.rank = rank;
  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.page_base_offset_words + (probe.page >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexPageBase,
               probe_index_);
  phase_ = Phase::kProbePageResolve;
}

void SpineSplitReader::resolve_probe_page() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint32_t page_base =
      (probe.page & 1U) == 0
          ? static_cast<std::uint32_t>(probe.page_base_word)
          : static_cast<std::uint32_t>(probe.page_base_word >> 32);
  const std::uint64_t row = static_cast<std::uint64_t>(page_base) + probe.rank;
  if (row > std::numeric_limits<std::uint32_t>::max()) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    failed_ = true;
    done_ = true;
    failure_ = "range probe row index overflowed";
    return;
  }
  probe.row = static_cast<std::uint32_t>(row);
  enqueue_probe_row_reads();
  phase_ = Phase::kProbeRowResolve;
}

void SpineSplitReader::enqueue_probe_row_reads() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  enqueue_read(*ports_.graph[probe.family],
               (probe.layout.row_offset_offset_words + (probe.row >> 1)) *
                   kSpineGraphWordBytes,
               kSpineGraphWordBytes, MemoryPayloadKind::kIndexRow,
               probe_index_);
  if ((probe.row & 1U) != 0) {
    enqueue_read(*ports_.graph[probe.family],
                 (probe.layout.row_offset_offset_words + (probe.row >> 1) + 1) *
                     kSpineGraphWordBytes,
                 kSpineGraphWordBytes, MemoryPayloadKind::kIndexNextRow,
                 probe_index_);
  }
}

void SpineSplitReader::resolve_probe_row() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  if ((probe.row & 1U) == 0) {
    probe.start = static_cast<std::uint32_t>(probe.row_word);
    probe.end = static_cast<std::uint32_t>(probe.row_word >> 32);
  } else {
    probe.start = static_cast<std::uint32_t>(probe.row_word >> 32);
    probe.end = static_cast<std::uint32_t>(probe.next_row_word);
  }
  if (probe.end < probe.start || probe.end > probe.edge_count) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorMetadata;
    failed_ = true;
    done_ = true;
    failure_ = "HBM row offsets do not fit the cached level edge count";
    return;
  }
  if (probe.end == probe.start) {
    phase_ = Phase::kProbeAdvance;
    return;
  }
  const std::uint64_t row_length = probe.end - probe.start;
  if (row_length >
      kRangeTaskPayloadBudget - counters_.range_task_construction_payloads) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackPayloadBudget;
    failed_ = true;
    done_ = true;
    failure_ = "device-dirty exact path exceeded its construction budget";
    return;
  }
  construction_position_ = probe.start;
  construction_run_valid_ = false;
  construction_run_length_ = 0;
  construction_have_previous_dst_ = false;
  phase_ = Phase::kConstructionRead;
}

void SpineSplitReader::flush_construction_run() {
  if (!construction_run_valid_ || construction_run_length_ == 0) {
    return;
  }
  if (construction_run_tile_ >= kRangeTaskMaxTiles ||
      construction_run_start_ >= kRangeTaskMaxStart ||
      construction_run_length_ >= kRangeTaskMaxLength) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorDescriptor;
    failed_ = true;
    done_ = true;
    failure_ = "constructed range does not fit the 128-bit descriptor";
    return;
  }
  if (range_tasks_.size() >= kRangeTaskCapacity) {
    counters_.range_task_path = kRangeTaskPathFallback;
    counters_.range_task_fallback_reason = kRangeTaskFallbackCapacity;
    failed_ = true;
    done_ = true;
    failure_ = "device-dirty exact path exhausted range descriptors";
    return;
  }
  const RangeProbe &probe = range_probes_.at(probe_index_);
  range_tasks_.push_back(RangeTask{
      .absolute_word = construction_run_start_,
      .length = construction_run_length_,
      .source = probe.source,
      .source_value = probe.source_value,
      .tile = construction_run_tile_,
      .graph_bank = static_cast<std::uint8_t>(probe.family),
      .hot = probe.hot,
  });
  ++tile_counts_[construction_run_tile_];
  ++counters_.range_task_count;
  construction_run_valid_ = false;
  construction_run_length_ = 0;
}

void SpineSplitReader::consume_construction_edge() {
  RangeProbe &probe = range_probes_.at(probe_index_);
  const std::uint64_t destination = construction_edge_.dst;
  const std::uint64_t partition_base =
      static_cast<std::uint64_t>(probe.family) *
      maintenance_.config().vertex_partition_size;
  const std::uint64_t partition_end = std::min<std::uint64_t>(
      maintenance_.vertices(),
      partition_base + maintenance_.config().vertex_partition_size);
  const bool invalid_partition = !probe.hot && (destination < partition_base ||
                                                destination >= partition_end);
  if (destination >= maintenance_.vertices() || invalid_partition ||
      (construction_have_previous_dst_ &&
       construction_edge_.dst < construction_previous_dst_)) {
    counters_.range_task_path = kRangeTaskPathError;
    counters_.range_task_error = kRangeTaskErrorDestination;
    failed_ = true;
    done_ = true;
    failure_ = "construction scan found an invalid or unsorted destination";
    return;
  }
  construction_previous_dst_ = construction_edge_.dst;
  construction_have_previous_dst_ = true;
  const auto tile = static_cast<std::uint16_t>(destination / kTileVertices);
  const std::uint64_t absolute =
      probe.layout.edge_offset_words + construction_position_;
  if (!construction_run_valid_) {
    construction_run_valid_ = true;
    construction_run_tile_ = tile;
    construction_run_start_ = absolute;
    construction_run_length_ = 1;
  } else if (tile == construction_run_tile_) {
    ++construction_run_length_;
  } else {
    flush_construction_run();
    if (failed_) {
      return;
    }
    construction_run_valid_ = true;
    construction_run_tile_ = tile;
    construction_run_start_ = absolute;
    construction_run_length_ = 1;
  }

  ++construction_position_;
  if (construction_position_ == probe.end) {
    flush_construction_run();
    if (!failed_) {
      phase_ = Phase::kProbeAdvance;
    }
  } else {
    phase_ = Phase::kConstructionRead;
  }
}

void SpineSplitReader::enqueue_level_cache_reads() {
  const auto visit = [&](const auto &families, bool hot) {
    for (std::size_t family_index = 0; family_index < families.size();
         ++family_index) {
      const std::size_t logical_family =
          hot ? families.size() + family_index : family_index;
      for (std::size_t level_index = 0;
           level_index < families[family_index].size(); ++level_index) {
        const auto &level = families[family_index][level_index];
        const std::uint64_t slice = logical_family * kLevelCount + level_index;
        const std::uint64_t slice_base =
            slice * kMetadataWordsPerSlice * kMetadataWordBytes;
        const std::uint64_t bytes =
            level.empty() ? kMetadataWordBytes : 8 * kMetadataWordBytes;
        const std::uint64_t address =
            maintenance_.config().metadata_base +
            (level.empty() ? slice_base + 7 * kMetadataWordBytes : slice_base);
        enqueue_read(*ports_.metadata, address, bytes);
        counters_.level_cache_read_bytes += bytes;
        if (!level.empty()) {
          enqueue_read(
              *ports_.metadata,
              maintenance_.config().metadata_base +
                  (kSliceEpochBaseWords + (slice >> 1)) * kMetadataWordBytes,
              kMetadataWordBytes);
          counters_.level_cache_read_bytes += kMetadataWordBytes;
          ++counters_.occupied_levels;
        }
      }
    }
  };
  visit(state_.cold_levels, false);
  visit(state_.hot_levels, true);
}

PartConvWord SpineSplitReader::current_stream_word() const {
  switch (phase_) {
    case Phase::kRequestSource:
      return PartConvWord{.kind = PartConvWordKind::kSourceRequest,
                          .first = active_sources_.at(source_index_)};
    case Phase::kTileBegin:
      return PartConvWord{.kind = PartConvWordKind::kTileBegin,
                          .first = tiles_.at(tile_index_).tile_base};
    case Phase::kEdgeEmit: {
      const RangeTask &range = tiles_.at(tile_index_).ranges.at(range_index_);
      return PartConvWord{
          .kind = PartConvWordKind::kEdge,
          .first = loaded_edge_.dst,
          .second = saturating_add(range.source_value, loaded_edge_.weight),
      };
    }
    case Phase::kTileEnd:
      return PartConvWord{.kind = PartConvWordKind::kTileEnd,
                          .first = tiles_.at(tile_index_).tile_base};
    case Phase::kDone:
      return PartConvWord{.kind = PartConvWordKind::kDoneAll};
    default:
      throw std::logic_error("reader phase does not produce a stream word");
  }
}

void SpineSplitReader::advance(const CycleContext &context) {
  switch (phase_) {
    case Phase::kWaitMaintenance:
      if (maintenance_.done()) {
        if (maintenance_.failed()) {
          failed_ = true;
          done_ = true;
          failure_ = "reader cannot start after failed maintenance";
          return;
        }
        counters_.start_cycle = context.domain_cycle;
        source_index_ = 0;
        phase_ = Phase::kRequestSource;
      }
      return;
    case Phase::kSetupReads:
      prepare_range_probes();
      if (failed_) {
        return;
      }
      enqueue_read(*ports_.active_bins, 0,
                   active_sources_.size() * kActiveRecordBytes);
      enqueue_read(*ports_.metadata, maintenance_.config().metadata_base,
                   8 * kMetadataWordBytes);
      enqueue_level_cache_reads();
      bin_index_ = 0;
      phase_ = Phase::kBinClear;
      return;
    case Phase::kBinClear:
      tile_counts_[bin_index_] = 0;
      tile_offsets_[bin_index_] = 0;
      tile_cursors_[bin_index_] = 0;
      tiles_[bin_index_].tile_base =
          static_cast<std::uint32_t>(bin_index_ * kTileVertices);
      tiles_[bin_index_].ranges.clear();
      ++counters_.range_task_clear_cycles;
      ++bin_index_;
      if (bin_index_ == kRangeTaskMaxTiles) {
        probe_index_ = 0;
        phase_ = Phase::kProbeBegin;
      }
      return;
    case Phase::kProbeBegin:
      if (probe_index_ == range_probes_.size()) {
        bin_index_ = 0;
        phase_ = Phase::kBinPrefix;
        return;
      }
      ++counters_.range_task_level_checks;
      if (range_probes_[probe_index_].edge_count == 0) {
        ++probe_index_;
        return;
      }
      enqueue_probe_index_reads();
      phase_ = Phase::kProbeIndexResolve;
      return;
    case Phase::kProbeIndexResolve:
      resolve_probe_index();
      return;
    case Phase::kProbeRankResolve:
      resolve_probe_rank();
      return;
    case Phase::kProbePageResolve:
      resolve_probe_page();
      return;
    case Phase::kProbeRowResolve:
      resolve_probe_row();
      return;
    case Phase::kConstructionRead: {
      const RangeProbe &probe = range_probes_.at(probe_index_);
      if (construction_position_ >= probe.end) {
        throw std::logic_error("construction scan advanced past its row");
      }
      enqueue_read(*ports_.graph[probe.family],
                   (probe.layout.edge_offset_words + construction_position_) *
                       kSpineGraphWordBytes,
                   kSpineGraphWordBytes, MemoryPayloadKind::kConstructionEdge,
                   probe_index_, probe.source);
      phase_ = Phase::kConstructionConsume;
      return;
    }
    case Phase::kConstructionConsume:
      consume_construction_edge();
      return;
    case Phase::kProbeAdvance:
      ++probe_index_;
      phase_ = Phase::kProbeBegin;
      return;
    case Phase::kBinPrefix: {
      const std::uint32_t prefix =
          bin_index_ == 0
              ? 0
              : tile_offsets_[bin_index_ - 1] + tile_counts_[bin_index_ - 1];
      const std::uint64_t next =
          static_cast<std::uint64_t>(prefix) + tile_counts_[bin_index_];
      tile_offsets_[bin_index_] = prefix;
      tile_cursors_[bin_index_] = prefix;
      ++counters_.range_task_prefix_cycles;
      ++bin_index_;
      if (next > range_tasks_.size() || next > kRangeTaskCapacity) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorPrefix;
        failed_ = true;
        done_ = true;
        failure_ = "range-task prefix sum exceeded the task count";
        return;
      }
      if (bin_index_ == kRangeTaskMaxTiles) {
        if (next != range_tasks_.size()) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorPrefix;
          failed_ = true;
          done_ = true;
          failure_ = "range-task prefix sum did not close";
          return;
        }
        scatter_index_ = 0;
        phase_ = Phase::kBinScatter;
      }
      return;
    }
    case Phase::kBinScatter:
      if (scatter_index_ == range_tasks_.size()) {
        bin_index_ = 0;
        phase_ = Phase::kBinVerify;
        return;
      } else {
        const RangeTask &task = range_tasks_[scatter_index_];
        if (task.tile >= kRangeTaskMaxTiles) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorDescriptor;
          failed_ = true;
          done_ = true;
          failure_ = "range-task scatter received an invalid tile";
          return;
        }
        const std::uint32_t limit =
            tile_offsets_[task.tile] + tile_counts_[task.tile];
        if (tile_cursors_[task.tile] >= limit ||
            tile_cursors_[task.tile] >= kRangeTaskCapacity) {
          counters_.range_task_path = kRangeTaskPathError;
          counters_.range_task_error = kRangeTaskErrorPrefix;
          failed_ = true;
          done_ = true;
          failure_ = "range-task scatter cursor exceeded its tile bin";
          return;
        }
        tiles_[task.tile].ranges.push_back(task);
        ++tile_cursors_[task.tile];
        ++scatter_index_;
        ++counters_.range_task_scatter_cycles;
      }
      return;
    case Phase::kBinVerify:
      if (tile_cursors_[bin_index_] !=
              tile_offsets_[bin_index_] + tile_counts_[bin_index_] ||
          tiles_[bin_index_].ranges.size() != tile_counts_[bin_index_]) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorPrefix;
        failed_ = true;
        done_ = true;
        failure_ = "range-task tile cursor verification failed";
        return;
      }
      ++counters_.range_task_verify_cycles;
      ++bin_index_;
      if (bin_index_ == kRangeTaskMaxTiles) {
        tile_index_ = 0;
        counters_.range_task_path = kRangeTaskPathExact;
        phase_ = Phase::kTileScan;
      }
      return;
    case Phase::kTileScan:
      if (tile_index_ == tiles_.size()) {
        phase_ = Phase::kDone;
      } else if (tiles_[tile_index_].ranges.empty()) {
        ++tile_index_;
      } else {
        phase_ = Phase::kTileBegin;
      }
      return;
    case Phase::kEdgeRead: {
      if (range_index_ == tiles_.at(tile_index_).ranges.size()) {
        phase_ = Phase::kTileEnd;
        return;
      }
      if (range_edge_index_ ==
          tiles_[tile_index_].ranges[range_index_].length) {
        ++range_index_;
        range_edge_index_ = 0;
        return;
      }
      const RangeTask &range = tiles_[tile_index_].ranges[range_index_];
      if (range.graph_bank >= ports_.graph.size() || range.length == 0) {
        counters_.range_task_path = kRangeTaskPathError;
        counters_.range_task_error = kRangeTaskErrorDescriptor;
        failed_ = true;
        done_ = true;
        failure_ = "range-task replay received an invalid descriptor";
        return;
      }
      enqueue_read(
          *ports_.graph[range.graph_bank],
          (range.absolute_word + range_edge_index_) * kSpineGraphWordBytes,
          kSpineGraphWordBytes, MemoryPayloadKind::kReplayEdge, probe_index_,
          range.source);
      phase_ = Phase::kEdgeEmit;
      return;
    }
    case Phase::kRequestSource:
    case Phase::kWaitSource:
    case Phase::kTileBegin:
    case Phase::kEdgeEmit:
    case Phase::kTileEnd:
    case Phase::kDone:
      return;
  }
}

SpineSplitSsspCompute::SpineSplitSsspCompute(
    std::string name, ClockId clock_id, std::size_t vertices,
    std::uint32_t source, std::size_t tiny_threshold, SpineComputePorts ports,
    Fifo<PartConvWord> &edge_in, Fifo<SourceValueWord> &value_out)
    : Component(std::move(name), clock_id),
      vertices_(vertices),
      source_(source),
      tiny_threshold_(tiny_threshold),
      ports_(ports),
      edge_in_(edge_in),
      value_out_(value_out),
      values_(vertices, kInfinity) {
  if (vertices_ == 0 || source_ >= vertices_ || tiny_threshold_ == 0 ||
      ports_.vertex_state == nullptr || ports_.active_out == nullptr ||
      ports_.active_bitmap == nullptr || ports_.result == nullptr ||
      edge_in_.clock_id() != clock_id || value_out_.clock_id() != clock_id) {
    throw std::invalid_argument("invalid Spine split compute configuration");
  }
  ports_.vertex_state->fill_payload(
      0, static_cast<std::uint64_t>(vertices_) * kVertexWordBytes, 0xffU);
  ports_.vertex_state->initialize_payload(
      static_cast<std::uint64_t>(source_) * kVertexWordBytes, encode_u32(0));
  values_[source_] = 0;
}

void SpineSplitSsspCompute::reset_round() {
  if (!done_ || failed_ || waiting_memory_ || !memory_tasks_.empty() ||
      source_reply_pending_) {
    throw std::logic_error("compute round reset requires a successful drain");
  }
  counters_ = {};
  next_active_.clear();
  reset_tile();
  phase_ = Phase::kInput;
  staged_action_ = Action::kNone;
  pending_source_ = 0;
  gather_index_ = 0;
  done_ = false;
}

void SpineSplitSsspCompute::evaluate(const CycleContext &) {
  staged_action_ = Action::kNone;
  if (done_ || failed_) {
    return;
  }
  if (waiting_memory_) {
    if (memory_tasks_.empty()) {
      throw std::logic_error("compute memory wait has no task");
    }
    if (memory_tasks_.front().port->responses().try_pop(staged_response_)) {
      staged_action_ = Action::kComplete;
    }
    return;
  }
  if (!memory_tasks_.empty()) {
    const MemoryTask &task = memory_tasks_.front();
    if (task.port->requests().try_push(AxiRequest{
            .transaction_id = next_transaction_id_,
            .operation = task.operation,
            .address = task.address,
            .bytes = task.bytes,
            .write_data = task.write_data,
        })) {
      staged_action_ = Action::kIssue;
    }
    return;
  }
  if (source_reply_pending_) {
    staged_value_word_ = SourceValueWord{.source = pending_source_,
                                         .value = pending_source_value_};
    if (value_out_.try_push(staged_value_word_)) {
      staged_action_ = Action::kPushValue;
    }
    return;
  }
  if (phase_ == Phase::kInput) {
    if (edge_in_.try_pop(staged_edge_word_)) {
      staged_action_ = Action::kPopEdge;
    }
    return;
  }
  staged_action_ = Action::kAdvance;
}

void SpineSplitSsspCompute::commit(const CycleContext &context) {
  switch (staged_action_) {
    case Action::kNone:
      return;
    case Action::kIssue:
      expected_transaction_id_ = next_transaction_id_++;
      waiting_memory_ = true;
      return;
    case Action::kComplete:
      if (!staged_response_.success ||
          staged_response_.transaction_id != expected_transaction_id_) {
        failed_ = true;
        done_ = true;
        return;
      }
      consume_memory_response(memory_tasks_.front(), staged_response_);
      waiting_memory_ = false;
      memory_tasks_.pop_front();
      return;
    case Action::kPopEdge:
      if (counters_.source_requests == 0 && counters_.start_cycle == 0) {
        counters_.start_cycle = context.domain_cycle;
      }
      handle_edge_word(staged_edge_word_);
      return;
    case Action::kPushValue:
      source_reply_pending_ = false;
      ++counters_.source_responses;
      phase_ = Phase::kInput;
      return;
    case Action::kAdvance:
      advance(context);
      return;
  }
}

void SpineSplitSsspCompute::enqueue_memory(
    FixedAxiPort &port, MemoryOperation operation, std::uint64_t address,
    std::uint64_t bytes, std::vector<std::uint8_t> write_data) {
  if ((operation == MemoryOperation::kRead && !write_data.empty()) ||
      (operation == MemoryOperation::kWrite && write_data.size() != bytes)) {
    throw std::invalid_argument("invalid Spine compute memory payload");
  }
  const std::size_t payload_bytes = write_data.size();
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
      .write_data = std::move(write_data),
  });
  if (&port == ports_.vertex_state) {
    if (operation == MemoryOperation::kRead) {
      counters_.vertex_read_bytes += bytes;
    } else {
      counters_.vertex_write_bytes += bytes;
      counters_.vertex_payload_write_bytes += payload_bytes;
    }
  } else if (&port == ports_.active_out) {
    counters_.active_out_write_bytes += bytes;
  } else if (&port == ports_.active_bitmap) {
    counters_.bitmap_bytes += bytes;
  } else if (&port == ports_.result) {
    counters_.result_write_bytes += bytes;
  }
}

void SpineSplitSsspCompute::consume_memory_response(
    const MemoryTask &task, const AxiResponse &response) {
  if (task.operation == MemoryOperation::kWrite) {
    if (!response.read_data.empty()) {
      throw std::logic_error("Spine compute write response carried payload");
    }
    return;
  }
  if (response.read_data.size() != task.bytes) {
    throw std::logic_error("Spine compute read response payload size mismatch");
  }
  if (task.port != ports_.vertex_state) {
    return;
  }
  counters_.vertex_payload_read_bytes += response.read_data.size();
  if (phase_ == Phase::kSourceRead) {
    pending_source_value_ = decode_u32(response.read_data);
    values_.at(pending_source_) = pending_source_value_;
    return;
  }
  if (phase_ == Phase::kGatherAdvance) {
    const std::uint32_t vertex = gather_vertices_.at(gather_index_);
    const std::uint32_t value = decode_u32(response.read_data);
    gathered_values_[vertex] = value;
    values_.at(vertex) = value;
    return;
  }
  if (phase_ == Phase::kFullLoad) {
    if (response.read_data.size() != tile_size_ * kVertexWordBytes) {
      throw std::logic_error("Spine full-tile payload size mismatch");
    }
    tile_values_.resize(tile_size_);
    for (std::size_t index = 0; index < tile_size_; ++index) {
      tile_values_[index] =
          decode_u32(response.read_data, index * kVertexWordBytes);
      values_.at(tile_base_ + index) = tile_values_[index];
    }
  }
}

void SpineSplitSsspCompute::handle_edge_word(const PartConvWord &word) {
  switch (word.kind) {
    case PartConvWordKind::kSourceRequest:
      if (word.first >= vertices_) {
        failed_ = true;
        done_ = true;
        return;
      }
      pending_source_ = word.first;
      ++counters_.source_requests;
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                     pending_source_ * kVertexWordBytes, kVertexWordBytes);
      phase_ = Phase::kSourceRead;
      return;
    case PartConvWordKind::kTileBegin:
      if (tile_open_ || word.first >= vertices_) {
        failed_ = true;
        done_ = true;
        return;
      }
      tile_base_ = word.first;
      tile_size_ = std::min<std::size_t>(kTileVertices, vertices_ - tile_base_);
      tile_edges_.clear();
      gather_vertices_.clear();
      gathered_values_.clear();
      changed_vertices_.clear();
      relax_index_ = 0;
      full_path_ = false;
      overflow_edge_pending_ = false;
      tile_open_ = true;
      phase_ = Phase::kInput;
      return;
    case PartConvWordKind::kEdge:
      if (!tile_open_ || word.first < tile_base_ ||
          static_cast<std::uint64_t>(word.first) >=
              static_cast<std::uint64_t>(tile_base_) + kTileVertices ||
          word.first >= vertices_) {
        failed_ = true;
        done_ = true;
        return;
      }
      if (full_path_) {
        relax_edge(word);
        ++counters_.full_stream_edges;
      } else if (tile_edges_.size() < tiny_threshold_) {
        tile_edges_.push_back(word);
      } else {
        begin_full_path(word);
      }
      phase_ = Phase::kInput;
      if (full_path_ && overflow_edge_pending_) {
        phase_ = Phase::kFullLoad;
      }
      return;
    case PartConvWordKind::kTileEnd:
      if (!tile_open_) {
        failed_ = true;
        done_ = true;
        return;
      }
      ++counters_.touched_tiles;
      if (full_path_) {
        prepare_store();
        phase_ = Phase::kStore;
        return;
      }
      ++counters_.fast_path_tiles;
      counters_.tiny_buffered_edges += tile_edges_.size();
      prepare_gather();
      phase_ = Phase::kGatherBegin;
      return;
    case PartConvWordKind::kDoneAll:
      if (tile_open_) {
        failed_ = true;
        done_ = true;
        return;
      }
      enqueue_memory(*ports_.active_bitmap, MemoryOperation::kRead, 0, 8);
      enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite, 0, 8,
                     std::vector<std::uint8_t>(8, 0));
      enqueue_memory(*ports_.result, MemoryOperation::kWrite, 0, kResultBytes,
                     std::vector<std::uint8_t>(kResultBytes, 0));
      phase_ = Phase::kFinish;
      return;
  }
}

void SpineSplitSsspCompute::prepare_gather() {
  gather_vertices_.clear();
  gather_vertices_.reserve(tile_edges_.size());
  for (const PartConvWord &edge : tile_edges_) {
    gather_vertices_.push_back(edge.first);
  }
  gathered_values_.clear();
  changed_vertices_.clear();
  gather_index_ = 0;
  relax_index_ = 0;
}

void SpineSplitSsspCompute::prepare_store() {
  const std::size_t active_base =
      next_active_.size() - changed_vertices_.size();
  if (full_path_ && !changed_vertices_.empty()) {
    enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite,
                   tile_base_ * kVertexWordBytes, tile_size_ * kVertexWordBytes,
                   encode_u32_words(tile_values_));
    counters_.swept_vertex_words += tile_size_;
  }
  for (std::size_t index = 0; index < changed_vertices_.size(); ++index) {
    const std::uint32_t vertex = changed_vertices_[index];
    if (!full_path_) {
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite,
                     vertex * kVertexWordBytes, kVertexWordBytes,
                     encode_u32(values_.at(vertex)));
    }
  }
  if (!changed_vertices_.empty()) {
    std::vector<std::uint8_t> active_payload(
        changed_vertices_.size() * kActiveOutputBytes, 0);
    for (std::size_t index = 0; index < changed_vertices_.size(); ++index) {
      const std::vector<std::uint8_t> vertex =
          encode_u32(changed_vertices_[index]);
      std::copy(vertex.begin(), vertex.end(),
                active_payload.begin() +
                    static_cast<std::ptrdiff_t>(index * kActiveOutputBytes));
    }
    enqueue_memory(*ports_.active_out, MemoryOperation::kWrite,
                   active_base * kActiveOutputBytes,
                   changed_vertices_.size() * kActiveOutputBytes,
                   std::move(active_payload));
  }
}

void SpineSplitSsspCompute::begin_full_path(const PartConvWord &overflow_edge) {
  full_path_ = true;
  overflow_edge_ = overflow_edge;
  overflow_edge_pending_ = true;
  ++counters_.full_path_tiles;
  counters_.swept_vertex_words += tile_size_;
  changed_vertices_.clear();
  relax_index_ = 0;
  enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                 tile_base_ * kVertexWordBytes, tile_size_ * kVertexWordBytes);
}

void SpineSplitSsspCompute::relax_edge(const PartConvWord &edge) {
  std::uint32_t &current = full_path_ ? tile_values_.at(edge.first - tile_base_)
                                      : gathered_values_.at(edge.first);
  if (edge.second < current) {
    current = edge.second;
    values_[edge.first] = edge.second;
    if (std::find(changed_vertices_.begin(), changed_vertices_.end(),
                  edge.first) == changed_vertices_.end()) {
      changed_vertices_.push_back(edge.first);
      next_active_.push_back(edge.first);
    }
  }
  ++counters_.processed_edges;
}

void SpineSplitSsspCompute::reset_tile() {
  tile_edges_.clear();
  gather_vertices_.clear();
  gathered_values_.clear();
  changed_vertices_.clear();
  tile_values_.clear();
  relax_index_ = 0;
  tile_size_ = 0;
  tile_open_ = false;
  full_path_ = false;
  overflow_edge_pending_ = false;
}

void SpineSplitSsspCompute::advance(const CycleContext &context) {
  switch (phase_) {
    case Phase::kSourceRead:
      source_reply_pending_ = true;
      phase_ = Phase::kSourceReply;
      return;
    case Phase::kSourceReply:
      return;
    case Phase::kGatherBegin:
      if (gather_index_ == gather_vertices_.size()) {
        phase_ = Phase::kRelax;
        return;
      }
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kRead,
                     gather_vertices_[gather_index_] * kVertexWordBytes,
                     kVertexWordBytes);
      phase_ = Phase::kGatherAdvance;
      return;
    case Phase::kGatherAdvance:
      ++counters_.gathered_vertex_words;
      ++gather_index_;
      phase_ = Phase::kGatherBegin;
      return;
    case Phase::kRelax:
      if (relax_index_ == tile_edges_.size()) {
        prepare_store();
        phase_ = Phase::kStore;
        return;
      }
      {
        const PartConvWord &edge = tile_edges_[relax_index_];
        relax_edge(edge);
        ++relax_index_;
      }
      return;
    case Phase::kFullLoad:
      relax_index_ = 0;
      phase_ = Phase::kFullReplay;
      return;
    case Phase::kFullReplay:
      if (relax_index_ < tile_edges_.size()) {
        relax_edge(tile_edges_[relax_index_]);
        ++counters_.full_buffer_replay_edges;
        ++relax_index_;
        return;
      }
      if (overflow_edge_pending_) {
        relax_edge(overflow_edge_);
        ++counters_.full_overflow_edges;
        overflow_edge_pending_ = false;
        return;
      }
      tile_edges_.clear();
      phase_ = Phase::kInput;
      return;
    case Phase::kStore:
      if (!full_path_) {
        counters_.scattered_vertex_words += changed_vertices_.size();
      }
      reset_tile();
      phase_ = Phase::kInput;
      return;
    case Phase::kFinish:
      counters_.end_cycle = context.domain_cycle;
      done_ = true;
      return;
    case Phase::kInput:
      return;
  }
}

}  // namespace spine::sim
