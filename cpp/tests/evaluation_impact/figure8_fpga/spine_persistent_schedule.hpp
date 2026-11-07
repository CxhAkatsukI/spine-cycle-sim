#pragma once

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace persistent_schedule {

struct Span {
    std::size_t begin;
    std::size_t end;
};

// Offsets retain original trace order; sorting belongs inside each returned span.
inline std::vector<Span> spans(std::size_t begin, std::size_t end,
                               std::size_t physical_limit = 8192) {
    if (begin >= end || physical_limit == 0) {
        throw std::invalid_argument("schedule requires a nonempty span and positive limit");
    }
    const auto size = end - begin;
    const auto count = size / physical_limit + (size % physical_limit != 0);
    std::vector<Span> result;
    if (count > result.max_size()) {
        throw std::length_error("schedule exceeds host vector capacity");
    }
    result.reserve(count);
    while (begin < end) {
        const auto next = begin + std::min(physical_limit, end - begin);
        result.push_back({begin, next});
        begin = next;
    }
    return result;
}

}  // namespace persistent_schedule
