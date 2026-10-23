#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

namespace spine::sim {

enum class SpineResidualApplyMode { kDense, kDirtyBitmap };

// One tile-local 64-bit bitmap RAM: one clear/read word per cycle, and one
// forwarded read-modify-write mark per completed edge reduction.
class SpineResidualApplyBitmap {
 public:
  void begin_tile(std::size_t vertices);
  [[nodiscard]] bool clearing() const noexcept;
  void clear_word();
  void mark(std::size_t vertex);
  void begin_scan();
  [[nodiscard]] bool needs_word() const noexcept;
  void read_word();
  [[nodiscard]] std::optional<std::uint32_t> selected() const noexcept;
  void consume();
  [[nodiscard]] std::size_t count() const noexcept { return count_; }
  [[nodiscard]] std::size_t storage_bytes() const noexcept {
    return words_.size() * sizeof(std::uint64_t);
  }

 private:
  std::vector<std::uint64_t> words_;
  std::size_t vertices_{};
  std::size_t clear_cursor_{};
  std::size_t read_cursor_{};
  std::size_t count_{};
  std::size_t consumed_{};
  std::uint64_t cached_word_{};
};

}  // namespace spine::sim
