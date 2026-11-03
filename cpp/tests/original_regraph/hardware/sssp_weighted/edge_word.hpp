#pragma once

#include <cstdint>

namespace a4_weighted {
constexpr std::uint32_t destination_bits = 19;
constexpr std::uint32_t destination_mask = (1u << destination_bits) - 1;
constexpr std::uint32_t weight_mask = (1u << 12) - 1;
constexpr std::uint32_t dummy = 1u << 31;

// The host must check the global destination belongs to the task partition.
constexpr bool encodable(std::uint32_t destination, std::uint32_t weight)
{
    return destination <= destination_mask && weight > 0 && weight <= weight_mask;
}

constexpr std::uint32_t pack(std::uint32_t destination, std::uint32_t weight)
{
    return (weight << destination_bits) | destination;
}

constexpr std::uint32_t weight(std::uint32_t word)
{
    return (word >> destination_bits) & weight_mask;
}

constexpr std::uint32_t gather_destination(std::uint32_t word)
{
    // The author gather uses bit 19 for the dummy flag after localization.
    return (word & destination_mask) | ((word & dummy) >> (31 - destination_bits));
}
}  // namespace a4_weighted
