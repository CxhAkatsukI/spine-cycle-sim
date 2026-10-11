#include "spine_sim/shared_axi_port.hpp"

#include <limits>
#include <set>

namespace spine::sim {

SharedAxiPort::SharedAxiPort(std::string name, ClockId clock, FixedAxiPort &physical,
                             std::vector<AxiEndpoint> clients, std::size_t capacity)
    : Component(std::move(name), clock), physical_(physical), clients_(std::move(clients)),
      capacity_(capacity) {
  if (!capacity_ || clients_.empty() || physical_.master().clock_id() != clock)
    throw std::invalid_argument("shared AXI port needs clients, finite credit and one clock");
  std::set<const void *> queues{&physical_.requests(), &physical_.responses(), &physical_.read_beats()};
  for (const auto &client : clients_) {
    if (client.requests().clock_id() != clock || client.responses().clock_id() != clock ||
        !queues.insert(&client.requests()).second || !queues.insert(&client.responses()).second)
      throw std::invalid_argument("shared AXI clients alias queues or cross clock domains");
    if (client.read_beats() && (!physical_.read_beat_stream_enabled() ||
        client.read_beats()->clock_id() != clock || !queues.insert(client.read_beats()).second))
      throw std::invalid_argument("shared AXI read-beat queue is not an independent compatible client");
  }
}

bool SharedAxiPort::idle() const noexcept {
  return routes_.empty() && !staged_request_ && physical_.idle() &&
      std::all_of(clients_.begin(), clients_.end(), [](const auto &client) {
        return client.requests().empty() && client.responses().empty() &&
               (!client.read_beats() || client.read_beats()->empty());
      });
}

void SharedAxiPort::stage_request() {
  for (std::size_t step = 0; step < clients_.size(); ++step) {
    const auto index = (next_client_ + step) % clients_.size();
    auto &client = clients_[index];
    const auto *front = client.requests().front();
    if (!front) continue;
    if (routes_.size() == capacity_) { ++counters_.capacity_stalls; return; }
    if (physical_.requests().full()) { ++counters_.request_stalls; return; }
    if (!front->bytes || (front->stream_read_beats &&
        (front->operation != MemoryOperation::kRead || !client.read_beats())))
      throw std::invalid_argument("shared AXI request has invalid size or stream destination");
    for (const auto &[id, route] : routes_) {
      (void)id;
      if (route.client == index && route.original_id == front->transaction_id)
        throw std::logic_error("shared AXI client reused an outstanding transaction ID");
    }
    if (next_id_ == std::numeric_limits<std::uint64_t>::max())
      throw std::overflow_error("shared AXI physical transaction ID exhausted");
    Route route{.client = index, .original_id = front->transaction_id,
                .address = front->address, .bytes = front->bytes,
                .operation = front->operation, .stream = front->stream_read_beats,
                .beats_done = !front->stream_read_beats};
    AxiRequest request = *front;
    request.transaction_id = next_id_;
    if (!physical_.requests().try_push(std::move(request)))
      throw std::logic_error("shared physical request queue has another producer");
    AxiRequest consumed;
    if (!client.requests().try_pop(consumed))
      throw std::logic_error("shared client request queue has another consumer");
    staged_request_ = route;
    return;
  }
}

void SharedAxiPort::stage_response() {
  const auto *front = physical_.responses().front();
  if (!front) return;
  const auto found = routes_.find(front->transaction_id);
  if (found == routes_.end() || found->second.parent_done ||
      found->second.operation != front->operation)
    throw std::runtime_error("shared AXI response has no matching live route");
  const auto &route = found->second;
  AxiResponse response = *front;
  response.transaction_id = route.original_id;
  if (!clients_[route.client].responses().try_push(std::move(response))) {
    ++counters_.response_stalls;
    return;
  }
  AxiResponse consumed;
  if (!physical_.responses().try_pop(consumed))
    throw std::logic_error("shared physical response queue has another consumer");
  staged_response_ = consumed.transaction_id;
}

void SharedAxiPort::stage_beat() {
  const auto *front = physical_.read_beats().front();
  if (!front) return;
  const auto found = routes_.find(front->transaction_id);
  if (found == routes_.end() || !found->second.stream || found->second.beats_done)
    throw std::runtime_error("shared AXI beat has no matching live route");
  const auto &route = found->second;
  if (front->read_data.empty() || front->parent_offset != route.beat_bytes ||
      front->address != route.address + route.beat_bytes ||
      front->read_data.size() > route.bytes - route.beat_bytes ||
      front->last != (route.beat_bytes + front->read_data.size() == route.bytes))
    throw std::runtime_error("shared AXI beat is out of order or outside its parent");
  AxiReadBeatResponse beat = *front;
  beat.transaction_id = route.original_id;
  if (!clients_[route.client].read_beats()->try_push(std::move(beat))) {
    ++counters_.beat_stalls;
    return;
  }
  AxiReadBeatResponse consumed;
  if (!physical_.read_beats().try_pop(consumed))
    throw std::logic_error("shared physical beat queue has another consumer");
  staged_beat_ = {consumed.transaction_id, consumed.read_data.size()};
}

void SharedAxiPort::evaluate(const CycleContext &) {
  staged_request_.reset();
  staged_response_.reset();
  staged_beat_.reset();
  stage_response();
  stage_beat();
  stage_request();
}

void SharedAxiPort::retire(std::uint64_t id) {
  const auto found = routes_.find(id);
  if (found != routes_.end() && found->second.parent_done && found->second.beats_done) {
    routes_.erase(found);
    ++counters_.completed;
  }
}

void SharedAxiPort::commit(const CycleContext &) {
  if (staged_request_) {
    routes_.emplace(next_id_++, *staged_request_);
    next_client_ = (staged_request_->client + 1) % clients_.size();
    ++counters_.accepted;
    counters_.max_pending = std::max(counters_.max_pending, routes_.size());
  }
  if (staged_response_) {
    routes_.at(*staged_response_).parent_done = true;
    ++counters_.parent_responses;
  }
  if (staged_beat_) {
    auto &route = routes_.at(staged_beat_->first);
    route.beat_bytes += staged_beat_->second;
    route.beats_done = route.beat_bytes == route.bytes;
    ++counters_.read_beats;
  }
  if (staged_response_) retire(*staged_response_);
  if (staged_beat_) retire(staged_beat_->first);
  staged_request_.reset();
  staged_response_.reset();
  staged_beat_.reset();
}

} // namespace spine::sim
