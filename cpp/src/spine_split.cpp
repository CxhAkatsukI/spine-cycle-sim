#include "spine_sim/spine_split.hpp"

#include <algorithm>
#include <limits>
#include <map>
#include <stdexcept>
#include <utility>

namespace spine::sim {

namespace {

constexpr std::uint64_t kGraphWordBytes = 16;
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

std::uint32_t saturating_add(std::uint32_t left, std::uint16_t right) {
  if (left == SpineSplitSsspCompute::kInfinity ||
      left > SpineSplitSsspCompute::kInfinity - right) {
    return SpineSplitSsspCompute::kInfinity;
  }
  return left + right;
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
  tiles_.clear();
  source_values_.clear();
  phase_ = Phase::kWaitMaintenance;
  staged_action_ = Action::kNone;
  tile_index_ = 0;
  edge_index_ = 0;
  source_index_ = 0;
  done_ = false;
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
        return;
      }
      waiting_memory_ = false;
      memory_tasks_.pop_front();
      return;
    case Action::kPopValue:
      if (source_index_ >= active_sources_.size() ||
          staged_value_.source != active_sources_[source_index_]) {
        failed_ = true;
        done_ = true;
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
          edge_index_ = 0;
          phase_ = Phase::kEdgeRead;
          break;
        case Phase::kEdgeEmit:
          ++counters_.edges_emitted;
          if (tiles_.at(tile_index_).edges.at(edge_index_).hot) {
            ++counters_.hot_edges_emitted;
          } else {
            ++counters_.cold_edges_emitted;
          }
          ++edge_index_;
          phase_ = Phase::kEdgeRead;
          break;
        case Phase::kTileEnd:
          ++tile_index_;
          phase_ =
              tile_index_ == tiles_.size() ? Phase::kDone : Phase::kTileBegin;
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
                                    std::uint64_t bytes) {
  memory_tasks_.push_back(
      MemoryTask{.port = &port, .address = address, .bytes = bytes});
  if (&port == ports_.active_bins) {
    counters_.active_bin_read_bytes += bytes;
  } else if (&port == ports_.metadata) {
    counters_.metadata_read_bytes += bytes;
  } else {
    counters_.graph_read_bytes += bytes;
  }
}

void SpineSplitReader::build_tiles() {
  std::map<std::uint32_t, std::vector<TileTask::Edge>> by_tile;
  const SpineL0Config config;
  const auto visit = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      for (std::size_t level_index = 0; level_index < families[family].size();
           ++level_index) {
        const auto &level = families[family][level_index];
        if (level.empty()) {
          continue;
        }
        const SpineLevelLayout layout =
            spine_level_layout(config, hot, level_index);
        for (std::size_t index = 0; index < level.size(); ++index) {
          const SpineEdgeRecord &edge = level[index];
          if (!source_values_.contains(edge.src)) {
            continue;
          }
          const std::uint32_t tile_base =
              (edge.dst / kTileVertices) * kTileVertices;
          by_tile[tile_base].push_back(TileTask::Edge{
              .payload = edge,
              .graph_word_address = layout.edge_offset_words + index,
              .graph_bank = family,
              .hot = hot,
          });
        }
      }
    }
  };
  visit(state_.cold_levels, false);
  if (state_.hot_enabled) {
    visit(state_.hot_levels, true);
  }
  tiles_.clear();
  for (auto &[tile_base, edges] : by_tile) {
    tiles_.push_back(
        TileTask{.tile_base = tile_base, .edges = std::move(edges)});
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
            level.empty() ? slice_base + 7 * kMetadataWordBytes : slice_base;
        enqueue_read(*ports_.metadata, address, bytes);
        counters_.level_cache_read_bytes += bytes;
        if (!level.empty()) {
          enqueue_read(
              *ports_.metadata,
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

void SpineSplitReader::enqueue_index_reads() {
  const SpineL0Config config;
  const auto visit = [&](const auto &families, bool hot) {
    for (std::size_t family = 0; family < families.size(); ++family) {
      for (std::size_t level_index = 0; level_index < families[family].size();
           ++level_index) {
        const auto &level = families[family][level_index];
        if (level.empty()) {
          continue;
        }
        std::vector<std::uint32_t> row_sources;
        for (const SpineEdgeRecord &edge : level) {
          if (row_sources.empty() || row_sources.back() != edge.src) {
            row_sources.push_back(edge.src);
          }
        }
        const SpineLevelLayout layout =
            spine_level_layout(config, hot, level_index);
        for (std::size_t row = 0; row < row_sources.size(); ++row) {
          const std::uint32_t source = row_sources[row];
          if (!source_values_.contains(source)) {
            continue;
          }
          const std::uint64_t page = source / 256;
          const std::uint64_t lane_word = (source % 256) / 64;
          const std::uint64_t logical_family =
              hot ? state_.cold_levels.size() + family : family;
          const std::uint64_t slice =
              logical_family * kLevelCount + level_index;
          const std::uint64_t page_epoch_index = slice * kPageCount + page;
          enqueue_read(*ports_.metadata,
                       (kPageEpochBaseWords + (page_epoch_index >> 1)) *
                           kMetadataWordBytes,
                       kMetadataWordBytes);
          counters_.row_lookup_metadata_bytes += kMetadataWordBytes;
          enqueue_read(*ports_.graph[family],
                       (layout.bitmap_offset_words + page * 4 + lane_word) *
                           kGraphWordBytes,
                       kGraphWordBytes);
          enqueue_read(
              *ports_.graph[family],
              (layout.page_base_offset_words + (page >> 1)) * kGraphWordBytes,
              kGraphWordBytes);
          enqueue_read(
              *ports_.graph[family],
              (layout.row_offset_offset_words + (row >> 1)) * kGraphWordBytes,
              kGraphWordBytes);
          enqueue_read(
              *ports_.graph[family],
              (layout.mask_offset_words + (row >> 2)) * kGraphWordBytes,
              kGraphWordBytes);
        }
      }
    }
  };
  visit(state_.cold_levels, false);
  if (state_.hot_enabled) {
    visit(state_.hot_levels, true);
  }
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
      const SpineEdgeRecord &edge =
          tiles_.at(tile_index_).edges.at(edge_index_).payload;
      return PartConvWord{
          .kind = PartConvWordKind::kEdge,
          .first = edge.dst,
          .second = saturating_add(source_values_.at(edge.src), edge.weight),
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
          return;
        }
        counters_.start_cycle = context.domain_cycle;
        source_index_ = 0;
        phase_ = Phase::kRequestSource;
      }
      return;
    case Phase::kSetupReads:
      enqueue_read(*ports_.active_bins, 0,
                   active_sources_.size() * kActiveRecordBytes);
      enqueue_read(*ports_.metadata, 0, 8 * kMetadataWordBytes);
      enqueue_level_cache_reads();
      build_tiles();
      enqueue_index_reads();
      tile_index_ = 0;
      phase_ = tiles_.empty() ? Phase::kDone : Phase::kTileBegin;
      return;
    case Phase::kEdgeRead:
      if (edge_index_ == tiles_.at(tile_index_).edges.size()) {
        phase_ = Phase::kTileEnd;
        return;
      }
      enqueue_read(
          *ports_.graph[tiles_[tile_index_].edges[edge_index_].graph_bank],
          tiles_[tile_index_].edges[edge_index_].graph_word_address *
              kGraphWordBytes,
          kGraphWordBytes);
      phase_ = Phase::kEdgeEmit;
      return;
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
        })) {
      staged_action_ = Action::kIssue;
    }
    return;
  }
  if (source_reply_pending_) {
    staged_value_word_ = SourceValueWord{.source = pending_source_,
                                         .value = values_.at(pending_source_)};
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

void SpineSplitSsspCompute::enqueue_memory(FixedAxiPort &port,
                                           MemoryOperation operation,
                                           std::uint64_t address,
                                           std::uint64_t bytes) {
  memory_tasks_.push_back(MemoryTask{
      .port = &port,
      .operation = operation,
      .address = address,
      .bytes = bytes,
  });
  if (&port == ports_.vertex_state) {
    if (operation == MemoryOperation::kRead) {
      counters_.vertex_read_bytes += bytes;
    } else {
      counters_.vertex_write_bytes += bytes;
    }
  } else if (&port == ports_.active_out) {
    counters_.active_out_write_bytes += bytes;
  } else if (&port == ports_.active_bitmap) {
    counters_.bitmap_bytes += bytes;
  } else if (&port == ports_.result) {
    counters_.result_write_bytes += bytes;
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
      enqueue_memory(*ports_.active_bitmap, MemoryOperation::kWrite, 0, 8);
      enqueue_memory(*ports_.result, MemoryOperation::kWrite, 0, kResultBytes);
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
                   tile_base_ * kVertexWordBytes,
                   tile_size_ * kVertexWordBytes);
    counters_.swept_vertex_words += tile_size_;
  }
  for (std::size_t index = 0; index < changed_vertices_.size(); ++index) {
    const std::uint32_t vertex = changed_vertices_[index];
    if (!full_path_) {
      enqueue_memory(*ports_.vertex_state, MemoryOperation::kWrite,
                     vertex * kVertexWordBytes, kVertexWordBytes);
    }
  }
  if (!changed_vertices_.empty()) {
    enqueue_memory(*ports_.active_out, MemoryOperation::kWrite,
                   active_base * kActiveOutputBytes,
                   changed_vertices_.size() * kActiveOutputBytes);
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
  std::uint32_t &current =
      full_path_ ? values_.at(edge.first) : gathered_values_.at(edge.first);
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
      gathered_values_[gather_vertices_[gather_index_]] =
          values_[gather_vertices_[gather_index_]];
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
