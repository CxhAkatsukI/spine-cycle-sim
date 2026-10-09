#include "physical_hbm_mapper.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace spine::sim::sst_adapter {

PhysicalHbmAddressMapper::PhysicalHbmAddressMapper(
    std::size_t logical_channels, std::uint64_t channel_capacity_bytes,
    const std::string &mode, const std::string &mapping_table,
    std::size_t first_channel, std::size_t channel_count,
    std::uint64_t interleave_bytes)
    : logical_channels_(logical_channels),
      channel_capacity_bytes_(channel_capacity_bytes),
      entries_by_channel_(logical_channels) {
  if (mode.empty() || mode == "identity") {
    if (!mapping_table.empty()) {
      throw std::invalid_argument(
          "identity HBM mapping unexpectedly has a mapping table");
    }
    return;
  }
  if (mode != "interleaved_arena_v1" || logical_channels == 0 ||
      channel_capacity_bytes == 0 || channel_count == 0 ||
      first_channel > logical_channels ||
      channel_count > logical_channels - first_channel ||
      interleave_bytes == 0 ||
      (interleave_bytes & (interleave_bytes - 1)) != 0 ||
      mapping_table.empty()) {
    throw std::invalid_argument("invalid interleaved HBM address mapping");
  }
  enabled_ = true;
  first_channel_ = first_channel;
  channel_count_ = channel_count;
  interleave_bytes_ = interleave_bytes;
  std::stringstream table(mapping_table);
  std::string encoded_entry;
  while (std::getline(table, encoded_entry, ';')) {
    std::stringstream fields(encoded_entry);
    std::array<std::uint64_t, 4> values{};
    std::string field;
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (!std::getline(fields, field, ':') || field.empty()) {
        throw std::invalid_argument("malformed HBM mapping-table entry");
      }
      std::size_t consumed{};
      values[index] = std::stoull(field, &consumed, 10);
      if (consumed != field.size()) {
        throw std::invalid_argument("non-numeric HBM mapping-table field");
      }
    }
    if (std::getline(fields, field, ':') || values[0] >= logical_channels ||
        values[1] >= values[2] ||
        values[3] > std::numeric_limits<std::uint64_t>::max() -
                        (values[2] - values[1])) {
      throw std::invalid_argument("invalid HBM mapping-table range");
    }
    entries_by_channel_[values[0]].push_back(Entry{
        .logical_begin = values[1],
        .logical_end = values[2],
        .global_begin = values[3],
    });
  }
  for (auto &entries : entries_by_channel_) {
    std::sort(entries.begin(), entries.end(),
              [](const Entry &left, const Entry &right) {
                return left.logical_begin < right.logical_begin;
              });
    for (std::size_t index = 1; index < entries.size(); ++index) {
      if (entries[index - 1].logical_end > entries[index].logical_begin) {
        throw std::invalid_argument(
            "overlapping logical ranges in HBM mapping table");
      }
    }
  }
}

[[nodiscard]] bool PhysicalHbmAddressMapper::enabled() const noexcept {
  return enabled_;
}

[[nodiscard]] PhysicalHbmAddress
PhysicalHbmAddressMapper::map(std::size_t logical_channel,
                              std::uint64_t logical_address,
                              std::uint32_t bytes) const {
  if (logical_channel >= logical_channels_ || bytes == 0 ||
      logical_address > std::numeric_limits<std::uint64_t>::max() - bytes) {
    throw std::invalid_argument("invalid logical HBM request");
  }
  if (!enabled_) {
    return PhysicalHbmAddress{
        .channel = logical_channel,
        .address = logical_address % channel_capacity_bytes_,
    };
  }
  const std::uint64_t logical_end = logical_address + bytes;
  const auto &entries = entries_by_channel_[logical_channel];
  const auto found =
      std::find_if(entries.begin(), entries.end(), [&](const Entry &entry) {
        return logical_address >= entry.logical_begin &&
               logical_end <= entry.logical_end;
      });
  if (found == entries.end()) {
    throw std::invalid_argument(
        "logical HBM request is outside the interleaved address map: "
        "channel=" +
        std::to_string(logical_channel) + " address=" +
        std::to_string(logical_address) + " bytes=" + std::to_string(bytes));
  }
  const std::uint64_t global_address =
      found->global_begin + (logical_address - found->logical_begin);
  const std::uint64_t byte_in_line = global_address % interleave_bytes_;
  if (bytes > interleave_bytes_ - byte_in_line) {
    throw std::invalid_argument(
        "HBM request crosses an interleaved physical line");
  }
  const std::uint64_t global_line = global_address / interleave_bytes_;
  const std::size_t channel =
      first_channel_ + static_cast<std::size_t>(global_line % channel_count_);
  const std::uint64_t address =
      (global_line / channel_count_) * interleave_bytes_ + byte_in_line;
  if (address > channel_capacity_bytes_ - bytes) {
    throw std::invalid_argument(
        "mapped HBM request exceeds physical pseudo-channel capacity");
  }
  return PhysicalHbmAddress{.channel = channel, .address = address};
}

} // namespace spine::sim::sst_adapter
