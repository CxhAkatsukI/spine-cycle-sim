#include "physical_hbm_mapper.hpp"

#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using spine::sim::sst_adapter::PhysicalHbmAddressMapper;

namespace {

void require(bool condition, const char *message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

template <typename Function> void require_invalid(Function function) {
  try {
    function();
  } catch (const std::invalid_argument &) {
    return;
  }
  throw std::runtime_error("invalid mapping was accepted");
}

void identity_mapping() {
  PhysicalHbmAddressMapper mapper(4, 1024, "identity", "", 0, 0, 64);
  require(!mapper.enabled(), "identity unexpectedly enabled");
  const auto physical = mapper.map(3, 1028, 4);
  require(physical.channel == 3 && physical.address == 4,
          "identity mapping changed the legacy modulo behavior");
  require_invalid([&] { (void)mapper.map(4, 0, 4); });
  require_invalid([&] { (void)mapper.map(0, 0, 0); });
  require_invalid([&] {
    (void)mapper.map(0, std::numeric_limits<std::uint64_t>::max(), 4);
  });
  require_invalid([] {
    PhysicalHbmAddressMapper invalid(4, 1024, "identity", "0:0:64:0", 0, 0, 64);
  });
}

void interleaved_mapping() {
  PhysicalHbmAddressMapper mapper(4, 1024, "interleaved_arena_v1",
                                  "0:0:256:0;1:0:128:256", 2, 2, 64);
  require(mapper.enabled(), "interleaved mapping was not enabled");
  const auto first = mapper.map(0, 0, 64);
  const auto second = mapper.map(0, 64, 64);
  const auto third = mapper.map(0, 128, 64);
  const auto next_region = mapper.map(1, 0, 64);
  require(first.channel == 2 && first.address == 0, "first physical line");
  require(second.channel == 3 && second.address == 0, "second physical line");
  require(third.channel == 2 && third.address == 64, "third physical line");
  require(next_region.channel == 2 && next_region.address == 128,
          "logical regions did not share the physical arena");
  require_invalid([&] { (void)mapper.map(2, 0, 4); });
  require_invalid([&] { (void)mapper.map(0, 240, 32); });
  require_invalid([&] { (void)mapper.map(0, 48, 32); });
}

void invalid_tables() {
  for (const std::string table :
       {"0:0:64", "0:0:64:0:1", "0:x:64:0", "4:0:64:0", "0:64:64:0",
        "0:0:128:0;0:64:192:128"}) {
    require_invalid([&] {
      PhysicalHbmAddressMapper invalid(4, 1024, "interleaved_arena_v1", table,
                                       0, 4, 64);
    });
  }
  require_invalid([] {
    PhysicalHbmAddressMapper invalid(4, 1024, "interleaved_arena_v1",
                                     "0:0:64:0", 3, 2, 64);
  });
  require_invalid([] {
    PhysicalHbmAddressMapper invalid(4, 1024, "interleaved_arena_v1",
                                     "0:0:64:0", 0, 4, 48);
  });
  PhysicalHbmAddressMapper small(4, 64, "interleaved_arena_v1", "0:0:256:0", 0,
                                 2, 64);
  require_invalid([&] { (void)small.map(0, 128, 4); });
}

} // namespace

int main() {
  try {
    identity_mapping();
    interleaved_mapping();
    invalid_tables();
    std::cout << "PASS SST physical HBM mapping\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
