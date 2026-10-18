#pragma once

#include "../hardware/events.hpp"

namespace original_r_k4 {
enum class Role { hbm, apply, adapter, gather, mux };

inline const char* name(Role role) {
  switch (role) {
    case Role::hbm: return "hbm_wrapper";
    case Role::apply: return "apply";
    case Role::adapter: return "adapter";
    case Role::gather: return "little";
    case Role::mux: return "frontend_mux";
  }
  throw std::runtime_error("invalid K4 schedule role");
}

struct Command {
  Role role;
  unsigned partition{}, worker{};
  std::vector<std::size_t> waits;
  bool operator==(const Command&) const = default;
};

struct Schedule {
  std::array<unsigned, 4> worker_partitions{};
  std::vector<Command> commands;

  static Schedule build(unsigned partitions) {
    original_r_board::require(partitions > 0 && partitions <= UINT32_MAX / 65536,
                              "nonzero bounded K4 partition count required");
    Schedule result;
    result.commands = {{Role::hbm, 0, 0, {}}, {Role::apply, 0, 0, {}}};
    for (unsigned partition = 0; partition < partitions; ++partition) {
      const auto worker = partition % 4;
      ++result.worker_partitions[worker];
      const auto previous = 2ull + 3ull * (partition >= 4 ? partition - 4 : 0);
      result.commands.push_back({Role::adapter, partition, worker,
                                partition >= 4 ? std::vector<std::size_t>{previous} : std::vector<std::size_t>{}});
      result.commands.push_back({Role::gather, partition, worker,
                                partition >= 4 ? std::vector<std::size_t>{previous + 1} : std::vector<std::size_t>{}});
      result.commands.push_back({Role::mux, partition, worker,
                                partition ? std::vector<std::size_t>{1 + 3ull * partition} : std::vector<std::size_t>{}});
    }
    return result;
  }

  void validate(unsigned partitions) const {
    const auto canonical = build(partitions);
    original_r_board::require(commands == canonical.commands && worker_partitions == canonical.worker_partitions,
                              "K4 schedule differs from production stream ordering");
  }

  void verify_events(unsigned partitions, const std::vector<original_r_board::Times>& times) const {
    validate(partitions);
    original_r_board::require(times.size() == commands.size(), "complete K4 event set required");
    for (std::size_t index = 0; index < commands.size(); ++index) {
      times[index].validate();
      for (const auto dependency : commands[index].waits)
        original_r_board::require(dependency < index && times[dependency].end <= times[index].start,
                                  "K4 event violates partition reuse or shared-mux dependency");
    }
  }
};
}  // namespace original_r_k4
