#pragma once

#include "reader.hpp"

namespace evaluation_impact::prefetch_compact {
inline void check_directory_ownership() {
  using spine::sim::detail::prefetch_compact::DirectoryTiles;
  auto rejected = [](auto operation) {
    bool caught = false;
    try { operation(); } catch (const std::logic_error&) { caught = true; }
    check(caught, "invalid directory ownership was accepted");
  };
  rejected([] { DirectoryTiles directory(2050, 3); });
  DirectoryTiles directory(2050, 2);
  rejected([&] { directory.advance(); });
  const std::vector<std::uint8_t> data(64);
  while (auto read = directory.next()) directory.reserve(*read);
  check(!directory.next(), "directory exceeded two finite tiles");
  for (auto base : {0U, 1024U})
    for (std::size_t line = 0; line < 128; ++line) directory.accept(base, line, data, 5);
  rejected([&] { directory.accept(0, 0, data, 5); });
  check(!directory.ready(0, 7) && directory.ready(0, 8), "directory bypassed selector latency");
  directory.advance();
  check(directory.base() == 1024 && directory.ready(1024, 8), "prefetched tile was not retained");
  const auto tail = directory.next();
  check(tail && tail->base == 2048 && tail->first == 0 && tail->count == 1,
        "directory partial tail extended beyond physical graph");
  rejected([&] { directory.accept(0, 1, data, 9); });
  directory.reserve(*tail);
  directory.accept(2048, 0, data, 9);
  directory.advance();
  check(directory.base() == 2048 && directory.end() == 2050 && directory.ready(2049, 12) &&
        !directory.next(), "directory wrap or final partial tile mismatch");
}
}  // namespace evaluation_impact::prefetch_compact
