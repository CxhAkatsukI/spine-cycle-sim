#include "compute.hpp"
#include <iomanip>
#include <memory>

int main(int argc, char** argv) {
  using namespace continuous_g;
  using namespace continuous_sssp;
  try {
    const bool board = argc == 5 && std::string(argv[1]) == "--board";
    require(board || (argc == 3 && std::string(argv[1]) == "--model-check"),
            "usage: --model-check input | --board input xclbin device-index");
    unsigned index = 0;
    if (board) {
      require(std::string(argv[4]) == "0" || std::string(argv[4]) == "1", "known device index required");
      index = argv[4][0] - '0';
    }
    std::cout << std::fixed << std::setprecision(9);
    const auto setup_begin = Clock::now();
    Model model(argv[2], true);
    Values resident = shortest_paths(model.graph.vertices, model.state, 0);
    std::unique_ptr<Device> device;
    std::unique_ptr<Compute> compute;
    if (board) {
      device = std::make_unique<Device>(argv[3], index, model);
      compute = std::make_unique<Compute>(*device, model, resident);
    }
    std::cout << "CONTINUOUS_GR_SETUP {\"board\":" << (board ? "true" : "false")
              << ",\"one_time_setup_ms\":" << milliseconds(setup_begin)
              << ",\"shards\":" << model.graph.shards.size() << ",\"source\":0"
              << ",\"round_limit\":" << kRoundLimit << ",\"initial_state\":\"old_graph_converged\"";
    if (board) std::cout << ",\"device_bdf\":\"" << device->session.bdf << "\""
                        << ",\"hbm_bytes\":" << model.plan.total_allocated_bytes + kCapacity * 4 * 5 + 4;
    std::cout << "}" << std::endl;
    for (unsigned batch = 0; batch < 3; ++batch) {
      const auto begin = Clock::now();
      auto after = model.state;
      for (unsigned i = model.ends[batch]; i < model.ends[batch + 1]; ++i)
        prepared_g::mutate(after, model.input.updates[i]);
      const auto plan = prepare(model.state, after, resident, 0);
      const auto updates = model.pack_batch(batch);
      const double preparation_ms = milliseconds(begin);
      std::vector<Event> transfers, g_events, r_events;
      if (board) {
        transfers = device->transfer(updates);
        g_events = device->run(updates);
      }
      const double g_ready_ms = milliseconds(begin);
      Reference observed;
      double e2e_ms = 0;
      if (board) {
        auto seeded = compute->seed(plan);
        transfers.insert(transfers.end(), seeded.begin(), seeded.end());
        observed = compute->run(r_events, transfers);
        e2e_ms = milliseconds(begin);
      }
      const auto oracle_begin = Clock::now();
      model.advance(batch, updates);
      require(model.state == after, "G and SSSP graph transactions differ");
      const auto reference = relax(after, plan, kRoundLimit);
      const auto expected = shortest_paths(model.graph.vertices, after, 0);
      require(reference.values == expected, "resident relaxation differs from independent Dijkstra oracle");
      if (board) {
        require(observed.values == expected, "board SSSP differs from independent Dijkstra oracle");
        require(observed.active_counts == reference.active_counts, "board SSSP convergence trajectory mismatch");
      } else observed = reference;
      const double oracle_ms = milliseconds(oracle_begin);
      const auto verify_begin = Clock::now();
      const auto words = model.check(board ? device->readback(model) : model.expected);
      if (board) compute->verify_replicas(observed.values);
      const double verification_ms = milliseconds(verify_begin);
      resident = observed.values;
      for (const auto& [stage, events] : std::array<std::pair<const char*, const std::vector<Event>*>, 3>{
          {{"transfer", &transfers}, {"G", &g_events}, {"R", &r_events}}})
        for (const auto& event : *events) {
          const auto time = event.times();
          std::cout << "CONTINUOUS_GR_EVENT {\"batch\":" << batch << ",\"stage\":\"" << stage
                    << "\",\"role\":\"" << event.role << "\",\"index\":" << event.shard
                    << ",\"queued_ns\":" << time[0] << ",\"submit_ns\":" << time[1]
                    << ",\"start_ns\":" << time[2] << ",\"end_ns\":" << time[3] << "}" << std::endl;
        }
      const auto gw = event_window(g_events), rw = event_window(r_events);
      std::cout << "CONTINUOUS_GR_ROW {\"batch\":" << batch << ",\"board\":" << (board ? "true" : "false")
                << ",\"updates\":" << model.ends[batch + 1] - model.ends[batch]
                << ",\"edges\":" << model.state.size() << ",\"fallback\":" << (plan.fallback ? "true" : "false")
                << ",\"seed_sources\":" << plan.seeds.size() << ",\"rounds\":" << observed.active_counts.size()
                << ",\"checked_words\":" << words << ",\"checked_vertices\":" << resident.size()
                << ",\"host_preparation_ms\":" << preparation_ms << ",\"g_ready_wall_ms\":" << g_ready_ms
                << ",\"host_inclusive_e2e_ms\":" << e2e_ms << ",\"g_busy_ms\":" << gw[0]
                << ",\"r_busy_ms\":" << rw[0] << ",\"oracle_ms\":" << oracle_ms
                << ",\"verification_ms\":" << verification_ms
                << ",\"converged\":true,\"restored_pma\":false,\"state_pass\":true,\"active_counts\":[";
      for (unsigned i = 0; i < observed.active_counts.size(); ++i)
        std::cout << (i ? "," : "") << observed.active_counts[i];
      std::cout << "]}" << std::endl;
    }
    std::cout << (board ? "CONTINUOUS_GR_BOARD_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"
                       : "CONTINUOUS_GR_HOST_MODEL_PASS_NOT_BOARD") << std::endl;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
