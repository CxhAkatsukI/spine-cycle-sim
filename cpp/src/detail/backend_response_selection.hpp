#pragma once

#include "spine_sim/memory_backend.hpp"

namespace spine::sim::detail {
inline bool valid_response_selection(std::span<const std::size_t> indices,
                                     std::size_t size) {
  for (std::size_t i = 0; i < indices.size(); ++i)
    if (indices[i] >= size || (i && indices[i] <= indices[i - 1]))
      return false;
  return !indices.empty();
}

inline void retire_selected_responses(std::deque<BackendResponse> &queue,
                                      std::span<const std::size_t> indices,
                                      std::vector<BackendResponse> &retired) {
  retired.clear();
  retired.reserve(indices.size());
  for (std::size_t i = 0; i < indices.size(); ++i) {
    const auto position =
        queue.begin() + static_cast<std::ptrdiff_t>(indices[i] - i);
    retired.push_back(std::move(*position));
    queue.erase(position);
  }
}

inline std::size_t
operation_response_count(const std::deque<BackendResponse> &queue,
                         MemoryOperation operation) {
  return std::count_if(queue.begin(), queue.end(), [operation](const auto &r) {
    return r.operation == operation;
  });
}

inline void retire_response_credits(std::array<std::size_t, 2> &counts,
                                    std::span<const BackendResponse> retired,
                                    std::size_t remaining) {
  for (const auto &response : retired) {
    auto &count = counts[response.operation == MemoryOperation::kWrite];
    if (count == 0)
      throw std::logic_error("backend response direction credit underflow");
    --count;
  }
  if (counts[0] + counts[1] != remaining)
    throw std::logic_error(
        "backend response direction credits do not conserve");
}
} // namespace spine::sim::detail
