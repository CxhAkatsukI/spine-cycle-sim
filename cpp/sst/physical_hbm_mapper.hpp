#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace spine::sim::sst_adapter {

struct PhysicalHbmAddress {
  std::size_t channel{};
  std::uint64_t address{};
};

class PhysicalHbmAddressMapper {
public:
  PhysicalHbmAddressMapper(std::size_t logical_channels,
                           std::uint64_t channel_capacity_bytes,
                           const std::string &mode,
                           const std::string &mapping_table,
                           std::size_t first_channel, std::size_t channel_count,
                           std::uint64_t interleave_bytes);

  [[nodiscard]] bool enabled() const noexcept;

  [[nodiscard]] PhysicalHbmAddress map(std::size_t logical_channel,
                                       std::uint64_t logical_address,
                                       std::uint32_t bytes) const;

private:
  struct Entry {
    std::uint64_t logical_begin{};
    std::uint64_t logical_end{};
    std::uint64_t global_begin{};
  };

  std::size_t logical_channels_{};
  std::uint64_t channel_capacity_bytes_{};
  bool enabled_{};
  std::size_t first_channel_{};
  std::size_t channel_count_{};
  std::uint64_t interleave_bytes_{};
  std::vector<std::vector<Entry>> entries_by_channel_;
};

} // namespace spine::sim::sst_adapter
