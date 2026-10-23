#include "spine_sim/spine_residual_apply.hpp"

#include <bit>
#include <limits>
#include <stdexcept>

namespace spine::sim {

void SpineResidualApplyBitmap::begin_tile(std::size_t vertices) {
  if (!vertices || vertices > std::numeric_limits<std::uint32_t>::max()) {
    throw std::invalid_argument("residual bitmap needs a finite nonempty tile");
  }
  vertices_ = vertices;
  words_.resize((vertices + 63) / 64);
  clear_cursor_ = count_ = 0;
  begin_scan();
}

bool SpineResidualApplyBitmap::clearing() const noexcept {
  return clear_cursor_ < words_.size();
}

void SpineResidualApplyBitmap::clear_word() {
  if (!clearing()) throw std::logic_error("residual bitmap clear overrun");
  words_[clear_cursor_++] = 0;
}

void SpineResidualApplyBitmap::mark(std::size_t vertex) {
  if (clearing() || vertex >= vertices_) {
    throw std::logic_error("residual bitmap mark outside prepared tile");
  }
  auto& word = words_[vertex / 64];
  const auto bit = std::uint64_t{1} << (vertex % 64);
  count_ += (word & bit) == 0;
  word |= bit;
}

void SpineResidualApplyBitmap::begin_scan() {
  read_cursor_ = consumed_ = cached_word_ = 0;
}

bool SpineResidualApplyBitmap::needs_word() const noexcept {
  return !clearing() && consumed_ < count_ && cached_word_ == 0;
}

void SpineResidualApplyBitmap::read_word() {
  if (!needs_word() || read_cursor_ >= words_.size()) {
    throw std::logic_error("residual bitmap read overrun");
  }
  cached_word_ = words_[read_cursor_++];
}

std::optional<std::uint32_t> SpineResidualApplyBitmap::selected() const noexcept {
  if (cached_word_ == 0) return std::nullopt;
  return static_cast<std::uint32_t>((read_cursor_ - 1) * 64 +
                                    std::countr_zero(cached_word_));
}

void SpineResidualApplyBitmap::consume() {
  if (!selected()) throw std::logic_error("residual bitmap consume without bit");
  cached_word_ &= cached_word_ - 1;
  ++consumed_;
}

}  // namespace spine::sim
