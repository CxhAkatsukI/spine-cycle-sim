#pragma once

#include "spine_sim/original_regraph/frontend_types.hpp"

namespace spine::sim::original_regraph {

struct PropertyWrite {
  PropertyLine data{};
  std::uint32_t index{};
  bool end{};
};

struct TransactionPort {
  Fifo<AxiRequest>& requests;
  Fifo<AxiResponse>& responses;
};

struct WriteTarget {
  TransactionPort port;
  std::uint64_t address{};
  std::uint64_t bytes{};
};

inline constexpr PipelineTiming kWriteIndexTiming{2, 1, 3};
// The generated Apply accepts R data at iteration 72 and writes at 98.
// Memory service is explicit; do not add its full 99-cycle HLS depth again.
inline constexpr PipelineTiming kApplyPostReadTiming{26, 1, 27};
inline constexpr std::size_t kApplyLineCredits = 100;
inline constexpr std::size_t kWriterLineCredits = 72;

std::uint32_t apply_pr_property(std::uint32_t sum, std::uint32_t degree,
                                std::uint32_t argument);

}  // namespace spine::sim::original_regraph
