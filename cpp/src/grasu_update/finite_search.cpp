#include "finite_search/network.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace spine::sim::grasu_update_detail::finite {

FiniteSearch::FiniteSearch(std::string name, ClockId clock, std::size_t cu,
    std::size_t count, std::uint64_t update_base, std::uint64_t row_base,
    std::uint64_t binary_base, FixedAxiPort& updates, FixedAxiPort& metadata,
    Fifo<LocatedUpdate>& output, SearchMetadataChannels channels)
    : Search(std::move(name), clock), cu_(cu), count_(count),
      update_base_(update_base), row_base_(row_base), binary_base_(binary_base),
      metadata_channels_(channels),
      updates_(updates), metadata_(metadata), output_(output) {
  if (cu >= 4) throw std::invalid_argument("finite search CU out of range");
  for (const auto channel : {channels.row, channels.binary})
    if (channel && *channel >= metadata.master().config().channels)
      throw std::invalid_argument("finite search metadata channel out of range");
  input_ = channel<Input>("input", 2, 64);
  for (std::size_t lane = 0; lane < kLanes; ++lane) {
    const auto label = std::to_string(lane);
    edges_[lane] = channel<Input>("updates/" + label, 2, 64);
    responses_[lane] = channel<std::uint64_t>("responses/" + label, 2, 64);
    requests_[lane] = channel<Request>("requests/" + label, 2, 34);
    results_[lane] = channel<LocatedUpdate>("results/" + label, 2, 96);
    credits_[lane] = channel<bool>("credits/" + label, 2, 1);
    state_.workers[lane].index = lane;
  }
  for (std::size_t group = 0; group < kGroups; ++group) {
    const auto label = std::to_string(group);
    group_requests_[group] = channel<Request>("group_requests/" + label, 2, 40);
    group_responses_[group] = channel<Response>("group_responses/" + label, 2, 71);
  }
  memory_requests_ = channel<Request>("memory_requests", 32, 40);
  memory_responses_ = channel<Response>("memory_responses", 32, 71);
}

bool FiniteSearch::done() const noexcept {
  return state_.published == count_ && state_.scatter_groups_done == 255;
}

std::vector<SearchChannelObservation> FiniteSearch::channels() const {
  std::vector<SearchChannelObservation> result;
  for (const auto& observe : observations_) result.push_back(observe());
  return result;
}

void FiniteSearch::evaluate(const CycleContext&) {
  next_ = state_;
  if (failed() || done()) return;
  try {
    read_updates(); distribute(); workers(); merge();
    gather_groups(); gather(); memory(); scatter(); scatter_groups();
  } catch (const std::exception& error) { failure_ = error.what(); }
}

void FiniteSearch::commit(const CycleContext& context) {
  const bool was_done = done();
  // All stages observe pre-edge state. Internal queues never fall through.
  for (auto* queue : queues_)
    if (queue->latched_commit_ready()) queue->commit(context);
  if (!failed()) state_ = next_;
  if (!was_done && done()) {
    if (state_.metadata_issued != state_.metadata_received ||
        state_.update_issued != state_.update_received ||
        std::any_of(state_.update_replies.ready.begin(), state_.update_replies.ready.end(),
                    [](bool ready) { return ready; }) ||
        std::any_of(state_.metadata_replies.ready.begin(), state_.metadata_replies.ready.end(),
                    [](bool ready) { return ready; }))
      failure_ = "finite search closed with a pending AXI response";
    for (const auto& observe : observations_) {
      const auto channel = observe();
      if (channel.occupancy || channel.stats.pushes != channel.stats.pops) {
        failure_ = "finite search closed with an undrained channel: " + channel.name;
        break;
      }
    }
  }
}

std::uint64_t response_word(const AxiResponse& response) {
  if (!response.success || response.operation != MemoryOperation::kRead ||
      response.read_data.size() != 8)
    throw std::runtime_error("finite search malformed AXI response");
  std::uint64_t result = 0;
  for (unsigned byte = 0; byte < 8; ++byte)
    result |= std::uint64_t(response.read_data[byte]) << (byte * 8);
  return result;
}

template <std::size_t Capacity>
void Replies<Capacity>::accept(const AxiResponse& response, std::uint64_t published,
                               std::uint64_t issued) {
  const auto id = response.transaction_id;
  if (id < published || id >= issued || ready[id % Capacity])
    throw std::runtime_error("finite search duplicate or unowned AXI response");
  words[id % Capacity] = response_word(response);
  ready[id % Capacity] = true;
}
template struct Replies<kUpdateCredits>;
template struct Replies<kMetadataCredits>;

}  // namespace spine::sim::grasu_update_detail::finite

namespace spine::sim::grasu_update_detail {
std::unique_ptr<Search> make_finite_search(std::string name, ClockId clock,
    std::size_t cu, std::size_t count, std::uint64_t update_base,
    std::uint64_t row_base, std::uint64_t binary_base, FixedAxiPort& updates,
    FixedAxiPort& metadata, Fifo<LocatedUpdate>& output, SearchMetadataChannels channels) {
  return std::make_unique<finite::FiniteSearch>(std::move(name), clock, cu, count,
      update_base, row_base, binary_base, updates, metadata, output, channels);
}
}  // namespace spine::sim::grasu_update_detail
