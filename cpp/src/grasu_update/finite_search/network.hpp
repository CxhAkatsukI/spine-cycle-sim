#pragma once

#include <array>
#include <functional>
#include <vector>

#include "spine_sim/grasu_update/search.hpp"

namespace spine::sim::grasu_update_detail::finite {

inline constexpr std::size_t kLanes = 64, kWidth = 8, kGroups = 8;
inline constexpr std::size_t kMetadataCredits = 32, kUpdateCredits = 16;

struct Input { std::uint64_t raw{}; bool end{}; };
struct Request {
  std::uint32_t address{};
  std::size_t lane{};
  bool binary{}, end{};
};
struct Response { std::uint64_t data{}; std::size_t lane{}; bool end{}; };
enum class Phase { kIdle, kRow, kWaitRow, kBinary, kWaitBinary, kEmit, kEnd, kDone };
struct Worker {
  Phase phase{Phase::kIdle};
  std::size_t index{};
  std::uint64_t raw{}, last_head{};
  std::uint32_t begin{}, end{}, mid{};
};
struct Arbiter { unsigned finished{}, cursor{}; bool ended{}; };
template <std::size_t Capacity> struct Replies {
  std::array<std::uint64_t, Capacity> words{};
  std::array<bool, Capacity> ready{};
  void accept(const AxiResponse& response, std::uint64_t published, std::uint64_t issued);
};
struct State {
  std::array<Worker, kLanes> workers;
  std::array<Arbiter, kGroups> groups;
  Arbiter central;
  std::array<std::size_t, kMetadataCredits> pending_lanes{};
  Replies<kUpdateCredits> update_replies;
  Replies<kMetadataCredits> metadata_replies;
  std::size_t update_issued{}, update_received{}, distributed{}, end_lane{}, published{};
  std::uint64_t metadata_issued{}, metadata_received{}, rows{}, probes{};
  bool memory_done{}, scatter_done{};
  unsigned scatter_groups_done{};
};

template <typename T, std::size_t N>
using Channels = std::array<std::unique_ptr<Fifo<T>>, N>;

class FiniteSearch final : public Search {
public:
  FiniteSearch(std::string name, ClockId clock, std::size_t cu, std::size_t count,
               std::uint64_t update_base, std::uint64_t row_base,
               std::uint64_t binary_base, FixedAxiPort& updates,
               FixedAxiPort& metadata, Fifo<LocatedUpdate>& output,
               SearchMetadataChannels channels);
  bool done() const noexcept override;
  bool failed() const noexcept override { return !failure_.empty(); }
  const std::string& failure() const noexcept override { return failure_; }
  std::uint64_t row_reads() const noexcept override { return state_.rows; }
  std::uint64_t binary_probes() const noexcept override { return state_.probes; }
  std::vector<SearchChannelObservation> channels() const override;
  void evaluate(const CycleContext&) override;
  void commit(const CycleContext&) override;

private:
  template <typename T> std::unique_ptr<Fifo<T>> channel(
      const std::string& suffix, std::size_t depth, std::size_t bits) {
    auto result = std::make_unique<Fifo<T>>(name() + "/" + suffix, clock_id(), depth);
    queues_.push_back(result.get());
    observations_.push_back([pointer = result.get(), bits] {
      return SearchChannelObservation{pointer->name(), pointer->depth(), bits,
                                      pointer->size(), pointer->stats()};
    });
    return result;
  }
  void read_updates();
  void distribute();
  void workers();
  void merge();
  void gather_groups();
  void gather();
  void memory();
  void scatter();
  void scatter_groups();
  LocatedUpdate located(const Worker&) const;
  static void advance(Worker&);

  std::size_t cu_{}, count_{};
  std::uint64_t update_base_{}, row_base_{}, binary_base_{};
  SearchMetadataChannels metadata_channels_;
  FixedAxiPort &updates_, &metadata_;
  Fifo<LocatedUpdate>& output_;
  std::vector<Component*> queues_;
  std::vector<std::function<SearchChannelObservation()>> observations_;
  std::unique_ptr<Fifo<Input>> input_;
  Channels<Input, kLanes> edges_;
  Channels<std::uint64_t, kLanes> responses_;
  Channels<Request, kLanes> requests_;
  Channels<LocatedUpdate, kLanes> results_;
  Channels<bool, kLanes> credits_;
  Channels<Request, kGroups> group_requests_;
  Channels<Response, kGroups> group_responses_;
  std::unique_ptr<Fifo<Request>> memory_requests_;
  std::unique_ptr<Fifo<Response>> memory_responses_;
  State state_, next_;
  std::string failure_;
};

std::uint64_t response_word(const AxiResponse& response);

}  // namespace spine::sim::grasu_update_detail::finite
