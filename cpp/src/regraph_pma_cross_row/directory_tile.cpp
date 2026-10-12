#include "directory_tile.hpp"

#include <algorithm>
#include <stdexcept>

namespace spine::sim::detail {

PmaDirectoryTile::PmaDirectoryTile(std::size_t rows) : rows_(rows) {
  if (rows != 128 && rows != 1024) throw std::invalid_argument("unsupported finite directory cache");
}

std::size_t PmaDirectoryTile::count(std::size_t base, std::size_t vertices, std::size_t rows) {
  if ((rows != 128 && rows != 1024) || base >= vertices || base % rows)
    throw std::logic_error("invalid directory tile bounds");
  return std::min(rows, vertices - base);
}

std::size_t PmaDirectoryTile::bytes(std::size_t base, std::size_t vertices, std::size_t rows) {
  return (count(base, vertices, rows) + 7) / 8 * 64;
}

bool PmaDirectoryTile::load(std::span<const std::uint8_t> payload, std::size_t count,
                            std::size_t slots) {
  if (!count || count > rows_.size() || payload.size() != (count + 7) / 8 * 64)
    throw std::runtime_error("directory tile response differs from bounded burst");
  bool occupied = false;
  for (std::size_t lane = 0; lane < count; ++lane) {
    std::uint64_t packed = 0;
    for (unsigned byte = 0; byte < 8; ++byte)
      packed |= std::uint64_t(payload[lane * 8 + byte]) << (byte * 8);
    rows_[lane] = packed;
    const auto begin = packed >> 32;
    const auto end = std::min<std::size_t>(std::uint32_t(packed), slots);
    occupied |= (begin >> 4) < ((end + 15) >> 4);
  }
  return occupied;
}

std::uint64_t PmaDirectoryTile::row(std::size_t offset) const { return rows_.at(offset); }

} // namespace spine::sim::detail
