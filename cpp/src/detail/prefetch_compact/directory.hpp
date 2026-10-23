#pragma once

namespace spine::sim::detail::prefetch_compact {

struct DirectoryRead {
  std::size_t base{}, first{}, count{};
};

// Returned tiles retain ownership until their selector and AXI parents drain.
// The optional second tile hides reads, not their bandwidth or latency cost.
class DirectoryTiles {
public:
  DirectoryTiles(std::size_t vertices, std::size_t capacity)
      : vertices_(vertices), tiles_(checked_capacity(capacity)) {
    for (std::size_t i = 0; i < capacity; ++i) tiles_[i].base = i * 1024;
  }
  std::size_t base() const { return tiles_[current_].base; }
  std::size_t end() const { return std::min(base() + 1024, vertices_); }
  std::optional<DirectoryRead> next() const {
    for (std::size_t i = 0; i < tiles_.size(); ++i) {
      const auto& tile = tiles_[(current_ + i) % tiles_.size()];
      const auto count = lines(tile);
      if (tile.issued < count)
        return DirectoryRead{tile.base, tile.issued, std::min<std::size_t>(16, count - tile.issued)};
    }
    return std::nullopt;
  }
  void reserve(DirectoryRead read) {
    auto& tile = find(read.base);
    check(read.first == tile.issued && read.count && read.first + read.count <= lines(tile),
          "directory reservation outside owned tile");
    tile.issued += read.count;
  }
  void accept(std::size_t base, std::size_t index, const std::vector<std::uint8_t>& data,
              std::uint64_t cycle) {
    auto& tile = find(base);
    check(index < tile.issued && index < 128 && !tile.valid[index], "candidate directory overwrite");
    for (unsigned lane = 0; lane < 8; ++lane)
      tile.values[index * 8 + lane] = word(data, lane * 8) |
          (std::uint64_t{word(data, lane * 8 + 4)} << 32);
    tile.valid[index] = true;
    tile.ready[index] = cycle + 3;
  }
  bool ready(std::size_t source, std::uint64_t cycle) const {
    check(source >= base() && source < end(), "selector outside current directory tile");
    const auto index = (source - base()) / 8;
    return tiles_[current_].valid[index] && cycle >= tiles_[current_].ready[index];
  }
  std::uint64_t value(std::size_t source) const { return tiles_[current_].values[source - base()]; }
  bool fully_issued() const { return tiles_[current_].issued == lines(tiles_[current_]); }
  void advance() {
    auto& old = tiles_[current_];
    check(fully_issued() && std::size_t(std::count(old.valid.begin(), old.valid.end(), true)) == lines(old),
          "directory tile released before its beats drained");
    const auto next_base = old.base + 1024 * tiles_.size();
    old = Tile{};
    old.base = next_base;
    current_ = (current_ + 1) % tiles_.size();
  }

private:
  static std::size_t checked_capacity(std::size_t capacity) {
    check(capacity == 1 || capacity == 2, "unsupported directory tile capacity");
    return capacity;
  }
  struct Tile {
    std::size_t base{}, issued{};
    std::array<std::uint64_t, 1024> values{};
    std::array<bool, 128> valid{};
    std::array<std::uint64_t, 128> ready{};
  };
  std::size_t lines(const Tile& tile) const {
    return tile.base >= vertices_ ? 0 : (std::min<std::size_t>(1024, vertices_ - tile.base) + 7) / 8;
  }
  Tile& find(std::size_t base) {
    for (auto& tile : tiles_) if (tile.base == base) return tile;
    throw std::logic_error("directory response has no owned tile");
  }
  const std::size_t vertices_;
  std::vector<Tile> tiles_;
  std::size_t current_{};
};
}  // namespace spine::sim::detail::prefetch_compact
