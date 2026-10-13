#pragma once

#include <fstream>

#include "input.hpp"

namespace common_g {

struct Diagnostics {
  std::array<std::uint64_t, 4> search_done{};
  std::array<std::uint64_t, 2> first_update{}, last_update{}, completed{};
  std::array<std::uint64_t, 2> cache_loaded{}, write_started{};
  std::array<std::uint64_t, 4> metadata_port_cycles{}, metadata_full_cycles{}, metadata_peak_parents{};
  std::uint64_t dispatch_done{};
  std::vector<GraSuPortObservation> ports;

  static void first(std::uint64_t& value, bool condition, std::uint64_t cycle) {
    if (!value && condition) value = cycle;
  }
  void update(unsigned index, std::uint64_t count, std::uint64_t cycle) {
    first(first_update[index], count != 0, cycle);
    if (count != completed[index]) last_update[index] = cycle;
    completed[index] = count;
  }
  void pressure(unsigned index, std::size_t parents, std::size_t limit) {
    ++metadata_port_cycles[index];
    if (parents >= limit) ++metadata_full_cycles[index];
    metadata_peak_parents[index] = std::max<std::uint64_t>(metadata_peak_parents[index], parents);
  }
  void sample(const GraSuPmaUpdateSystem& system, std::uint64_t cycle) {
    const auto progress = system.progress();
    first(dispatch_done, progress.dispatch_done, cycle);
    for (unsigned index = 0; index < 4; ++index) {
      first(search_done[index], progress.searches_done[index], cycle);
      pressure(index, progress.metadata_parents[index], progress.metadata_parent_limits[index]);
      if (index < 2) {
        update(index, progress.completed[index], cycle);
        first(cache_loaded[index], progress.pma_reads[index] == g::kHotSegments, cycle);
        first(write_started[index], progress.issued_write_bytes[index] != 0, cycle);
      }
    }
  }
  void sample(const System& system, std::uint64_t cycle) {
    first(dispatch_done, system.dispatch->finished(), cycle);
    for (unsigned index = 0; index < 4; ++index) first(search_done[index], system.searches[index]->finished(), cycle);
    for (unsigned half = 0; half < 2; ++half) {
      std::uint64_t hot = 0;
      for (const auto* pe : system.cache[half]) hot += pe->counters().writes;
      update(half, hot, cycle);
      first(cache_loaded[half], system.stores[half]->loaded(), cycle);
    }
    for (const auto& link : system.memory.links) {
      const auto& name = link.master->name();
      if (name.starts_with("search") && name.find(".table") != std::string::npos)
        pressure(name.at(6) - '0', link.master->pending_requests(), link.master->config().max_pending_requests);
      if (name == "half0.hot" || name == "half1.hot")
        first(write_started[name.at(4) - '0'], link.master->stats().write_bytes != 0, cycle);
    }
  }
  void finish(const GraSuPmaUpdateSystem& system) { ports = system.port_observations(); }
  void finish(const System& system) {
    for (const auto& link : system.memory.links) ports.push_back({link.master->name(), link.bank,
        link.master->config(), link.master->stats(), link.requests->stats().push_stalls});
  }
  void write(const std::string& path) const {
    std::ofstream out(path);
    out << "{\"sampling\":\"after every committed cycle; overlapping markers are not additive\"";
    const auto array = [&out](const char* name, const auto& values) {
      out << ",\"" << name << "\":[";
      for (std::size_t i = 0; i < values.size(); ++i) out << (i ? "," : "") << values[i];
      out << ']';
    };
    array("search_done", search_done); array("first_hot_update", first_update); array("last_hot_update", last_update);
    array("hot_completed", completed); array("cache_loaded", cache_loaded); array("write_started", write_started);
    array("metadata_port_cycles", metadata_port_cycles); array("metadata_full_cycles", metadata_full_cycles);
    array("metadata_peak_parents", metadata_peak_parents);
    out << ",\"dispatch_done\":" << dispatch_done << ",\"ports\":[";
    for (std::size_t i = 0; i < ports.size(); ++i) {
      const auto& p = ports[i];
      out << (i ? "," : "") << "{\"name\":\"" << p.name << "\",\"channel\":" << p.channel
          << ",\"width\":" << p.config.data_width_bytes << ",\"parent_limit\":" << p.config.max_pending_requests
          << ",\"burst_limit\":" << p.config.max_outstanding_bursts << ",\"reorder_limit\":" << p.config.read_reorder_capacity
          << ",\"requests\":" << p.stats.requests_accepted << ",\"responses\":" << p.stats.requests_completed
          << ",\"beats_issued\":" << p.stats.beats_issued << ",\"beats_completed\":" << p.stats.beats_completed
          << ",\"read_bytes\":" << p.stats.read_bytes << ",\"write_bytes\":" << p.stats.write_bytes
          << ",\"parent_stalls\":" << p.stats.request_queue_stalls << ",\"fifo_stalls\":" << p.request_fifo_stalls
          << ",\"backend_stalls\":" << p.stats.backend_submit_stalls << ",\"reorder_stalls\":" << p.stats.read_reorder_stalls
          << ",\"peak_bursts\":" << p.stats.max_outstanding_bursts << '}';
    }
    out << "]}\n";
    if (!out) throw std::runtime_error("cannot save G diagnostics");
  }
};
}  // namespace common_g
