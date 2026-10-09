// clang-format off
#include "sst/core/sst_config.h"
// clang-format on

#include "sst_memory_backend.hpp"

#include <algorithm>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace spine::sim::sst_adapter {

SstMemoryBackend::SstMemoryBackend(
    ClockId clock_id, std::vector<SST::Interfaces::StandardMem *> interfaces,
    std::uint64_t channel_capacity_bytes,
    std::size_t accepts_per_channel_per_cycle,
    std::size_t max_outstanding_per_channel, std::size_t response_queue_depth,
    std::string address_mapping_mode, std::string address_mapping_table,
    std::size_t interleave_first_channel, std::size_t interleave_channels,
    std::uint64_t interleave_bytes,
    std::unique_ptr<DirectDramSim3Engine> direct_engine)
    : MemoryBackend("sst-hbm-backend", clock_id),
      interfaces_(std::move(interfaces)),
      direct_engine_(std::move(direct_engine)),
      channel_capacity_bytes_(channel_capacity_bytes),
      accepts_per_channel_per_cycle_(accepts_per_channel_per_cycle),
      max_outstanding_per_channel_(max_outstanding_per_channel),
      response_queue_depth_(response_queue_depth),
      address_mapper_(interfaces_.size(), channel_capacity_bytes,
                      address_mapping_mode, address_mapping_table,
                      interleave_first_channel, interleave_channels,
                      interleave_bytes),
      channel_outstanding_(interfaces_.size(), 0),
      staged_channel_submissions_(interfaces_.size(), 0),
      arbiter_(interfaces_.size(), accepts_per_channel_per_cycle) {
  if (interfaces_.empty() ||
      (direct_engine_ == nullptr &&
       std::none_of(
           interfaces_.begin(), interfaces_.end(),
           [](const auto *interface) { return interface != nullptr; })) ||
      channel_capacity_bytes_ == 0 || accepts_per_channel_per_cycle_ == 0 ||
      max_outstanding_per_channel_ == 0 || response_queue_depth_ == 0) {
    throw std::invalid_argument("invalid SST memory backend configuration");
  }
}

bool SstMemoryBackend::try_reserve(const BackendRequestHeader &request) {
  if (!initiator_registered(request.initiator_id) ||
      request.channel >= interfaces_.size() || request.bytes == 0) {
    throw std::invalid_argument("invalid SST backend request");
  }
  const PhysicalHbmAddress physical =
      address_mapper_.map(request.channel, request.address, request.bytes);
  BackendRequestHeader mapped_request = request;
  mapped_request.channel = physical.channel;
  mapped_request.address = physical.address;
  if (!channel_active(mapped_request.channel)) {
    throw std::invalid_argument(
        "SST backend request targets an unbound memory channel");
  }
  if (!arbiter_.try_acquire(mapped_request)) {
    ++submit_stalls_;
    return false;
  }
  InitiatorState &initiator = ensure_initiator_state(request.initiator_id);
  const std::size_t staged_for_channel =
      staged_channel_submissions_[mapped_request.channel];
  if (staged_for_channel >= accepts_per_channel_per_cycle_ ||
      channel_outstanding_[mapped_request.channel] + staged_for_channel >=
          max_outstanding_per_channel_) {
    ++submit_stalls_;
    return false;
  }
  ++staged_channel_submissions_[mapped_request.channel];
  if (initiator.staged_submissions == 0) {
    active_staged_initiators_.push_back(request.initiator_id);
  }
  ++initiator.staged_submissions;
  return true;
}

void SstMemoryBackend::submit_reserved(BackendRequest request) {
  if ((request.operation == MemoryOperation::kRead &&
       !request.write_data.empty()) ||
      (request.operation == MemoryOperation::kWrite &&
       request.write_data.size() != request.bytes)) {
    throw std::invalid_argument("invalid SST backend request payload");
  }
  staged_submissions_.push_back(std::move(request));
}

[[nodiscard]] bool SstMemoryBackend::reservation_intent_pending(
    std::uint32_t initiator_id, std::size_t channel) const noexcept {
  if (address_mapper_.enabled()) {
    return false;
  }
  return arbiter_.intent_pending(initiator_id, channel);
}

void SstMemoryBackend::account_same_cycle_reservation_stalls(
    std::uint32_t initiator_id, std::size_t channel, std::uint64_t count) {
  arbiter_.account_duplicate_waits(initiator_id, channel, count);
  submit_stalls_ += count;
}

[[nodiscard]] std::size_t
SstMemoryBackend::response_count(std::uint32_t initiator_id) const noexcept {
  const InitiatorState *state = find_initiator_state(initiator_id);
  return state == nullptr ? 0 : state->responses.size();
}

[[nodiscard]] const BackendResponse &
SstMemoryBackend::response_at(std::uint32_t initiator_id,
                              std::size_t index) const {
  const InitiatorState *state = find_initiator_state(initiator_id);
  if (state == nullptr || index >= state->responses.size()) {
    throw std::out_of_range("SST backend response index out of range");
  }
  return state->responses[index];
}

[[nodiscard]] const BackendResponse &
SstMemoryBackend::staged_response_at(std::uint32_t initiator_id,
                                     std::size_t index) const {
  const InitiatorState *state = find_initiator_state(initiator_id);
  if (state != nullptr && index < state->retired_responses.size()) {
    return state->retired_responses[index];
  }
  return response_at(initiator_id, index);
}

bool SstMemoryBackend::stage_pop_responses(std::uint32_t initiator_id,
                                           std::size_t count) {
  InitiatorState &state = ensure_initiator_state(initiator_id);
  if (state.staged_response_pop != 0 || count > state.responses.size()) {
    return false;
  }
  state.staged_response_pop = count;
  active_response_pops_.push_back(initiator_id);
  return true;
}

[[nodiscard]] std::size_t SstMemoryBackend::outstanding() const noexcept {
  return staged_submissions_.size() + arbiter_.pending_grants() +
         inflight_.size() + direct_inflight_count_;
}

[[nodiscard]] std::size_t
SstMemoryBackend::outstanding_for(std::uint32_t initiator_id) const noexcept {
  const InitiatorState *state = find_initiator_state(initiator_id);
  return (state == nullptr ? 0 : state->staged_submissions) +
         arbiter_.pending_grants_for(initiator_id) +
         (state == nullptr ? 0 : state->outstanding);
}

[[nodiscard]] bool
SstMemoryBackend::has_dynamic_prepare_guard() const noexcept {
  return true;
}

[[nodiscard]] bool SstMemoryBackend::has_dynamic_commit_guard() const noexcept {
  return true;
}

[[nodiscard]] bool SstMemoryBackend::prepare_ready() const noexcept {
  return !external_arrivals_.empty() || !active_retired_initiators_.empty();
}

[[nodiscard]] bool SstMemoryBackend::commit_ready() const noexcept {
  return !active_response_pops_.empty() || !staged_submissions_.empty() ||
         arbiter_.pending_intents() != 0;
}

void SstMemoryBackend::prepare(const CycleContext &) {
  for (const std::uint32_t initiator_id : active_retired_initiators_) {
    ensure_initiator_state(initiator_id).retired_responses.clear();
  }
  active_retired_initiators_.clear();
  for (auto iterator = external_arrivals_.begin();
       iterator != external_arrivals_.end();) {
    auto &queue = ensure_initiator_state(iterator->initiator_id).responses;
    if (queue.size() >= response_queue_depth_) {
      ++response_queue_stalls_;
      ++iterator;
      continue;
    }
    queue.push_back(*iterator);
    notify_response_available(iterator->initiator_id);
    iterator = external_arrivals_.erase(iterator);
  }
}

void SstMemoryBackend::evaluate(const CycleContext &) {}

void SstMemoryBackend::commit(const CycleContext &) {
  for (const std::uint32_t initiator_id : active_response_pops_) {
    InitiatorState &state = ensure_initiator_state(initiator_id);
    const std::size_t count = state.staged_response_pop;
    auto &queue = state.responses;
    auto &retired = state.retired_responses;
    retired.clear();
    retired.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
      retired.push_back(std::move(queue.front()));
      queue.pop_front();
    }
    state.staged_response_pop = 0;
    active_retired_initiators_.push_back(initiator_id);
  }
  active_response_pops_.clear();

  for (const BackendRequest &request : staged_submissions_) {
    const PhysicalHbmAddress physical =
        address_mapper_.map(request.channel, request.address, request.bytes);
    Inflight inflight{
        .backend_request_id = request.request_id,
        .initiator_id = request.initiator_id,
        .channel = physical.channel,
        .operation = request.operation,
        .bytes = request.bytes,
        .request = request,
    };
    ++channel_outstanding_[physical.channel];
    ++ensure_initiator_state(request.initiator_id).outstanding;
    BackendRequest physical_request = request;
    physical_request.channel = physical.channel;
    physical_request.address = physical.address;
    record_accepted_request(physical_request);
    ++accepted_;
    if (direct_engine_ != nullptr) {
      const std::uint64_t token = allocate_direct_inflight(std::move(inflight));
      direct_engine_->submit(token, physical.channel, physical.address,
                             request.operation == MemoryOperation::kWrite,
                             direct_submit_time_ps_);
    } else {
      SST::Interfaces::StandardMem::Request *standard_request = nullptr;
      if (request.operation == MemoryOperation::kWrite) {
        standard_request = new SST::Interfaces::StandardMem::Write(
            physical.address, request.bytes, request.write_data);
      } else {
        standard_request = new SST::Interfaces::StandardMem::Read(
            physical.address, request.bytes);
      }
      standard_request->setNoncacheable();
      const auto standard_id = standard_request->getID();
      inflight_.emplace(standard_id, inflight);
      interfaces_[physical.channel]->send(standard_request);
    }
  }
  staged_submissions_.clear();
  std::fill(staged_channel_submissions_.begin(),
            staged_channel_submissions_.end(), 0);
  for (const std::uint32_t initiator_id : active_staged_initiators_) {
    ensure_initiator_state(initiator_id).staged_submissions = 0;
  }
  active_staged_initiators_.clear();
  arbiter_.arbitrate(channel_outstanding_, max_outstanding_per_channel_);
  max_outstanding_ = std::max(max_outstanding_, outstanding());
}

void SstMemoryBackend::on_response(
    SST::Interfaces::StandardMem::Request *request) {
  const auto found = inflight_.find(request->getID());
  if (found == inflight_.end()) {
    throw std::logic_error("SST returned an unknown StandardMem request");
  }
  if (found->second.operation == MemoryOperation::kRead) {
    auto *read_response =
        dynamic_cast<SST::Interfaces::StandardMem::ReadResp *>(request);
    if (read_response == nullptr ||
        read_response->data.size() != found->second.bytes) {
      throw std::logic_error("SST returned a malformed read response");
    }
  } else if (dynamic_cast<SST::Interfaces::StandardMem::WriteResp *>(request) ==
             nullptr) {
    throw std::logic_error("SST returned a malformed write response");
  }
  complete_inflight(found->second, request->getSuccess());
  inflight_.erase(found);
  delete request;
}

void SstMemoryBackend::advance_direct_to(std::uint64_t time_ps) {
  if (direct_engine_ == nullptr) {
    return;
  }
  direct_engine_->advance_to(time_ps);
  direct_engine_->take_completions(direct_completions_);
  for (const DirectDramSim3Engine::Completion &completion :
       direct_completions_) {
    if (completion.token >= direct_inflight_.size() ||
        !direct_inflight_[completion.token].has_value()) {
      throw std::logic_error(
          "direct DRAMSim3 returned an unknown request token");
    }
    complete_inflight(*direct_inflight_[completion.token], true);
    release_direct_inflight(completion.token);
  }
  direct_submit_time_ps_ = time_ps;
}

void SstMemoryBackend::print_direct_stats() {
  if (direct_engine_ != nullptr) {
    direct_engine_->print_stats();
  }
}

[[nodiscard]] const char *SstMemoryBackend::backend_label() const noexcept {
  return direct_engine_ == nullptr ? "sst_memHierarchy_dramsim3"
                                   : "direct_dramsim3_transport";
}

[[nodiscard]] std::uint64_t SstMemoryBackend::accepted() const noexcept {
  return accepted_;
}

[[nodiscard]] std::uint64_t SstMemoryBackend::submit_stalls() const noexcept {
  return submit_stalls_;
}

[[nodiscard]] std::uint64_t
SstMemoryBackend::response_queue_stalls() const noexcept {
  return response_queue_stalls_;
}

[[nodiscard]] std::size_t SstMemoryBackend::max_outstanding() const noexcept {
  return max_outstanding_;
}

[[nodiscard]] const RegisteredChannelArbiterStats &
SstMemoryBackend::arbitration_stats() const noexcept {
  return arbiter_.stats();
}

[[nodiscard]] std::string SstMemoryBackend::arbitration_json() const {
  const RegisteredChannelArbiterStats &stats = arbiter_.stats();
  const std::size_t pending_intents = arbiter_.pending_intents();
  const std::size_t pending_grants = arbiter_.pending_grants();
  const bool ledger_closed = stats.unique_intents == stats.grants &&
                             stats.grants == stats.consumed_grants &&
                             pending_intents == 0 && pending_grants == 0;
  std::ostringstream stream;
  stream << "{\"policy\":\"registered_round_robin_per_pseudo_channel\""
         << ",\"unique_intents\":" << stats.unique_intents
         << ",\"request_waits\":" << stats.request_waits
         << ",\"grants\":" << stats.grants
         << ",\"consumed_grants\":" << stats.consumed_grants
         << ",\"pending_intents\":" << pending_intents
         << ",\"pending_grants\":" << pending_grants
         << ",\"ledger_closed\":" << (ledger_closed ? "true" : "false")
         << ",\"contended_cycles\":" << stats.contended_cycles
         << ",\"contention_losers\":" << stats.contention_losers
         << ",\"capacity_blocked_cycles\":" << stats.capacity_blocked_cycles
         << ",\"max_contenders\":" << stats.max_contenders
         << ",\"max_pending_grants\":" << stats.max_pending_grants << '}';
  return stream.str();
}

[[nodiscard]] SstMemoryBackend::InitiatorState *
SstMemoryBackend::find_initiator_state(std::uint32_t initiator_id) noexcept {
  return initiator_id < initiator_states_.size()
             ? initiator_states_[initiator_id].get()
             : nullptr;
}

[[nodiscard]] const SstMemoryBackend::InitiatorState *
SstMemoryBackend::find_initiator_state(
    std::uint32_t initiator_id) const noexcept {
  return initiator_id < initiator_states_.size()
             ? initiator_states_[initiator_id].get()
             : nullptr;
}

SstMemoryBackend::InitiatorState &
SstMemoryBackend::ensure_initiator_state(std::uint32_t initiator_id) {
  if (initiator_id >= initiator_states_.size()) {
    initiator_states_.resize(static_cast<std::size_t>(initiator_id) + 1);
  }
  std::unique_ptr<InitiatorState> &state = initiator_states_[initiator_id];
  if (state == nullptr) {
    state = std::make_unique<InitiatorState>();
  }
  return *state;
}

[[nodiscard]] bool
SstMemoryBackend::channel_active(std::size_t channel) const noexcept {
  return direct_engine_ != nullptr
             ? direct_engine_->channel_active(channel)
             : channel < interfaces_.size() && interfaces_[channel] != nullptr;
}

void SstMemoryBackend::complete_inflight(const Inflight &inflight,
                                         bool success) {
  std::vector<std::uint8_t> read_data;
  if (inflight.operation == MemoryOperation::kRead) {
    read_data = complete_read_payload(inflight.request);
  } else {
    commit_write_payload(inflight.request);
  }
  external_arrivals_.push_back(BackendResponse{
      .initiator_id = inflight.initiator_id,
      .request_id = inflight.backend_request_id,
      .success = success,
      .read_data = std::move(read_data),
  });
  if (channel_outstanding_[inflight.channel] == 0) {
    throw std::logic_error("SST channel outstanding count underflow");
  }
  --channel_outstanding_[inflight.channel];
  InitiatorState &initiator = ensure_initiator_state(inflight.initiator_id);
  if (initiator.outstanding == 0) {
    throw std::logic_error("SST initiator outstanding count underflow");
  }
  --initiator.outstanding;
}

[[nodiscard]] std::uint64_t
SstMemoryBackend::allocate_direct_inflight(Inflight inflight) {
  std::size_t slot{};
  if (free_direct_inflight_.empty()) {
    slot = direct_inflight_.size();
    direct_inflight_.emplace_back(std::move(inflight));
  } else {
    slot = free_direct_inflight_.back();
    free_direct_inflight_.pop_back();
    direct_inflight_[slot].emplace(std::move(inflight));
  }
  ++direct_inflight_count_;
  return slot;
}

void SstMemoryBackend::release_direct_inflight(std::uint64_t token) {
  const std::size_t slot = static_cast<std::size_t>(token);
  if (direct_inflight_count_ == 0) {
    throw std::logic_error("direct DRAMSim3 inflight count underflow");
  }
  direct_inflight_[slot].reset();
  free_direct_inflight_.push_back(slot);
  --direct_inflight_count_;
}

} // namespace spine::sim::sst_adapter
