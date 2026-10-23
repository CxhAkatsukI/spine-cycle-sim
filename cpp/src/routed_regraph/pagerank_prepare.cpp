#include "../detail/routed_regraph_pagerank.hpp"
#include "../detail/grasu_regraph_payload.hpp"
#include "../detail/pagerank_dangling_reduction.hpp"

#include <deque>
#include <map>

namespace spine::sim::detail {

class RoutedPageRankPrepare::Impl {
public:
  struct Slot {
    std::size_t burst{};
    std::optional<std::vector<std::uint8_t>> state, degree;
  };
  struct Ready {
    std::size_t burst{};
    std::uint64_t due{};
    std::vector<std::uint8_t> data;
  };
  Impl(std::size_t v, GraphAlgorithmPolicy p, GraSuReGraphConfig c,
       std::vector<std::int32_t> deltas, RoutedPageRankPreparePorts e)
      : vertices(v), policy(std::move(p)), config(c), delta(std::move(deltas)), ports(e) {
    for (std::size_t b = 0; b < (vertices + 15) / 16; ++b) {
      bool changed = false;
      for (std::size_t v = b * 16; v < std::min(vertices, b * 16 + 16); ++v)
        changed |= delta[v] != 0;
      if (changed) patches.push_back(b);
    }
  }
  void evaluate(const CycleContext &context) {
    issue = 0;
    for (auto &response : responses) response.reset();
    if (!running) return;
    std::array<AxiEndpoint, 5> endpoints{ports.state, ports.degree, ports.degree_write,
                                        ports.primary, ports.mirror};
    for (std::size_t i = 0; i < endpoints.size(); ++i) {
      AxiResponse response;
      if (endpoints[i].responses().try_pop(response)) responses[i] = std::move(response);
    }
    if (patch < patches.size()) {
      const auto b = patches[patch];
      if (!patch_read && !ports.degree.requests().full()) {
        if (ports.degree.requests().try_push(request(b, false, config.degree_base, {}))) issue = 1;
      } else if (patch_data && context.domain_cycle >= patch_due && !patch_write &&
                 !ports.degree_write.requests().full()) {
        if (ports.degree_write.requests().try_push(request(b, true, config.degree_base, *patch_data))) issue = 2;
      }
      return;
    }
    if (!ready.empty() && ready.front().due <= context.domain_cycle &&
        !ports.primary.requests().full() && !ports.mirror.requests().full()) {
      const auto &r = ready.front();
      auto req = request(r.burst, true, config.source_state_base, r.data);
      if (!ports.primary.requests().try_push(req) || !ports.mirror.requests().try_push(req))
        throw std::logic_error("PageRank source publication pair was not atomic");
      issue = 3;
    }
    // The window bounds queued responses, arithmetic and writes, not only AXI parents.
    const auto occupied = reads.size() + ready.size() + writes.size();
    if (next < (vertices + 15) / 16 && occupied < config.apply_request_window &&
        !ports.state.requests().full() && !ports.degree.requests().full()) {
      if (!ports.state.requests().try_push(request(next, false, config.vertex_state_base, {})) ||
          !ports.degree.requests().try_push(request(next, false, config.degree_base, {})))
        throw std::logic_error("PageRank source read pair was not atomic");
      issue |= 4;
    }
  }
  void commit(const CycleContext &context) {
    if (!running) return;
    if (patch < patches.size()) {
      if (responses[1]) {
        check(*responses[1], patches[patch], 64);
        auto data = responses[1]->read_data;
        for (std::size_t lane = 0; lane < 16; ++lane) {
          const auto v = patches[patch] * 16 + lane;
          if (v >= vertices) break;
          const auto value = std::int64_t(decode_u32(data, lane * 4)) + delta[v];
          if (value < 0 || value > UINT32_MAX) throw std::runtime_error("device degree update overflow");
          for (std::size_t byte = 0; byte < 4; ++byte) data[lane * 4 + byte] = value >> (byte * 8);
        }
        patch_data = std::move(data);
        patch_due = context.domain_cycle + config.pagerank_source_map_latency;
      }
      if (responses[2]) {
        check(*responses[2], patches[patch], 0);
        ++patch; patch_read = patch_write = false; patch_data.reset();
      }
      if (issue == 1) { patch_read = true; ++counts.degree_reads; }
      if (issue == 2) { patch_write = true; ++counts.degree_writes; }
      return;
    }
    for (std::size_t i = 0; i < 2; ++i) if (responses[i]) {
      const auto &r = *responses[i];
      const auto b = std::size_t(r.transaction_id & 0xffffffffULL);
      check(r, b, 64);
      auto found = reads.find(b);
      if (found == reads.end()) throw std::runtime_error("unowned PageRank mapping response");
      auto &slot = found->second;
      auto &data = i ? slot.degree : slot.state;
      if (data) throw std::runtime_error("duplicate PageRank mapping response");
      data = r.read_data;
      if (slot.state && slot.degree) {
        std::array<std::uint32_t, 16> payload{};
        for (std::size_t lane = 0; lane < 16; ++lane) {
          if (b * 16 + lane >= vertices) break;
          const float rank = GraphAlgorithmPolicy::word_to_float(decode_u32(*slot.state, lane * 4));
          const auto degree = decode_u32(*slot.degree, lane * 4);
          payload[lane] = GraphAlgorithmPolicy::float_to_word(
              degree ? policy.config().damping * rank / float(degree) : 0.0F);
          if (!degree) dangling_partials.add(b * 16 + lane, rank);
        }
        ready.push_back({b, context.domain_cycle + config.pagerank_source_map_latency, encode_words(payload)});
        reads.erase(found);
      }
    }
    for (std::size_t i = 3; i < 5; ++i) if (responses[i]) {
      const auto &r = *responses[i];
      const auto b = std::size_t(r.transaction_id & 0xffffffffULL);
      check(r, b, 0);
      auto found = writes.find(b);
      const auto bit = 1U << (i - 3);
      if (found == writes.end() || (found->second & bit))
        throw std::runtime_error("unowned or duplicate PageRank source write response");
      found->second |= bit;
      if (found->second == 3) { writes.erase(found); ++completed; }
    }
    if (issue & 1) {
      if (!writes.emplace(ready.front().burst, 0U).second) throw std::logic_error("duplicate source mapping write");
      ready.pop_front(); counts.source_writes += 2;
    }
    if (issue & 4) {
      if (!reads.emplace(next, Slot{next, {}, {}}).second) throw std::logic_error("duplicate source mapping read");
      ++next; ++counts.state_reads; ++counts.degree_reads;
    }
    if (completed == (vertices + 15) / 16) {
      dangling += dangling_partials.partial(reduction++);
      if (reduction == PageRankDanglingReduction::cycles) {
        running = false; done = true; counts.end = context.domain_cycle + 1;
      }
    }
  }
  AxiRequest request(std::size_t b, bool write, std::uint64_t base, std::vector<std::uint8_t> data) const {
    return {.transaction_id = 0x7500000000000000ULL | b,
            .operation = write ? MemoryOperation::kWrite : MemoryOperation::kRead,
            .address = base + b * 64, .bytes = 64, .stream_read_beats = false,
            .write_data = std::move(data)};
  }
  void check(const AxiResponse &r, std::size_t b, std::size_t bytes) const {
    if (!r.success || r.transaction_id != (0x7500000000000000ULL | b) || r.read_data.size() != bytes)
      throw std::runtime_error("malformed PageRank preparation response");
  }
  std::size_t vertices;
  GraphAlgorithmPolicy policy;
  GraSuReGraphConfig config;
  std::vector<std::int32_t> delta;
  RoutedPageRankPreparePorts ports;
  std::vector<std::size_t> patches;
  std::size_t patch{}, next{}, completed{}, reduction{};
  bool patch_read{}, patch_write{}, running{}, done{};
  std::uint64_t patch_due{};
  std::optional<std::vector<std::uint8_t>> patch_data;
  std::map<std::size_t, Slot> reads;
  std::map<std::size_t, unsigned> writes;
  std::deque<Ready> ready;
  std::array<std::optional<AxiResponse>, 5> responses;
  unsigned issue{};
  float dangling{};
  PageRankDanglingReduction dangling_partials;
  RoutedPageRankPrepareCounters counts;
};

RoutedPageRankPrepare::RoutedPageRankPrepare(ClockId clock, std::size_t vertices,
    GraphAlgorithmPolicy policy, GraSuReGraphConfig config, std::vector<std::int32_t> deltas,
    RoutedPageRankPreparePorts ports)
    : Component("pagerank-source-prepare", clock),
      impl_(std::make_unique<Impl>(vertices, std::move(policy), config, std::move(deltas), ports)) {}
RoutedPageRankPrepare::~RoutedPageRankPrepare() = default;
void RoutedPageRankPrepare::start(std::uint64_t cycle) {
  if (impl_->running || impl_->done) throw std::logic_error("PageRank preparation cannot restart");
  impl_->running = true; impl_->counts.start = cycle;
}
bool RoutedPageRankPrepare::done() const { return impl_->done; }
std::uint32_t RoutedPageRankPrepare::dangling_share() const {
  return GraphAlgorithmPolicy::float_to_word(impl_->policy.config().damping * impl_->dangling / float(impl_->vertices));
}
RoutedPageRankPrepareCounters RoutedPageRankPrepare::counters() const { return impl_->counts; }
void RoutedPageRankPrepare::evaluate(const CycleContext &context) { impl_->evaluate(context); }
void RoutedPageRankPrepare::commit(const CycleContext &context) { impl_->commit(context); }

} // namespace spine::sim::detail
