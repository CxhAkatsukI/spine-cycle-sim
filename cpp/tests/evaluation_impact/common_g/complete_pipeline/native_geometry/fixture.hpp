#pragma once

#include "host_prepared/handoff.hpp"
#include "layout.hpp"

namespace native_g {
struct Fixture : Layout {
  Fixture() {
    complete_g::require(MAX_CACHE_SEGMENT == kCacheSegments,
                        "native test requires complete routed cache capacity");
  }
};
}  // namespace native_g
