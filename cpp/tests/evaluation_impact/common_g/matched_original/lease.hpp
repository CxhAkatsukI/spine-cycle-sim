#pragma once

#include <charconv>
#include <cstdlib>
#include <string_view>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace matched_g {
inline void require_lease(unsigned index) {
  require(index < 2, "known matched G board index required");
  const char* value = std::getenv("MATCHED_G_LEASE_FD");
  require(value != nullptr, "external matched G board lease required");
  const std::string_view text(value);
  unsigned fd{};
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), fd);
  require(parsed.ec == std::errc{} && parsed.ptr == text.data() + text.size() && fd <= INT32_MAX,
          "invalid matched G lease descriptor");
  struct stat descriptor{}, path{};
  const auto lock = "/tmp/chuxiao-sharded-k4-board-" + std::to_string(index) + ".lock";
  require(fstat(fd, &descriptor) == 0 && stat(lock.c_str(), &path) == 0 && S_ISREG(descriptor.st_mode) &&
          descriptor.st_dev == path.st_dev && descriptor.st_ino == path.st_ino && flock(fd, LOCK_EX | LOCK_NB) == 0,
          "matched G lease does not exclusively lock requested board");
}
}  // namespace matched_g
