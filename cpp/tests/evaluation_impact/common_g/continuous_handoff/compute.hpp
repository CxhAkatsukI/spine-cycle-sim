#pragma once

#include "continuous_board/device.hpp"
#include "resident.hpp"

namespace continuous_sssp {
using continuous_g::checked;
using continuous_g::Event;
constexpr unsigned kCapacity = 65536;
constexpr unsigned kRoundLimit = 2048;

struct Compute {
  continuous_g::Device& g;
  const continuous_g::Model& model;
  std::array<std::array<cl::Buffer, 2>, 2> props;
  cl::Buffer apply_state, active;
  cl::Kernel adapter, little, mux, apply, hbm;
  unsigned read = 0;

  cl::Buffer buffer(unsigned bank, std::size_t bytes) {
    require(bank == 23 || bank == 24 || bank == 30, "SSSP state bank outside routed connectivity");
    cl_mem_ext_ptr_t extension{};
    extension.flags = bank | XCL_MEM_TOPOLOGY;
    cl_int error = CL_SUCCESS;
    cl::Buffer result(g.session.context, CL_MEM_READ_WRITE | CL_MEM_EXT_PTR_XILINX,
                      bytes, &extension, &error);
    checked(error, "allocate SSSP state");
    return result;
  }

  Values internal(const Values& external) const {
    require(external.size() == model.graph.vertices, "SSSP state size mismatch");
    Values result(kCapacity, 0);
    for (unsigned vertex = 0; vertex < external.size(); ++vertex)
      result[model.graph.external_to_internal.at(vertex)] = external[vertex];
    return result;
  }

  Compute(continuous_g::Device& update_device, const continuous_g::Model& graph, const Values& initial)
      : g(update_device), model(graph),
        apply_state(buffer(30, kCapacity * 4)), active(buffer(30, 4)),
        adapter(g.session.kernel("pma_to_regraph_adapter:{pma_to_regraph_adapter_1}")),
        little(g.session.kernel("lksg_stream:{lksg_stream_1}")),
        mux(g.session.kernel("regraph_frontend_mux:{regraph_frontend_mux_1}")),
        apply(g.session.kernel("kernelApply:{kernelApply_1}")),
        hbm(g.session.kernel("kernelHBMWrapper:{kernelHBMWrapper_1}")) {
    require(model.graph.shards.size() == 1 && model.input.partition_vertices == kCapacity,
            "first continuous handoff requires one native destination partition");
    const auto values = internal(initial);
    for (auto& pair : props) for (unsigned replica = 0; replica < 2; ++replica) {
      pair[replica] = buffer(23 + replica, kCapacity * 4);
      checked(g.session.transfers.enqueueWriteBuffer(pair[replica], CL_FALSE, 0,
          values.size() * 4, values.data()), "initialize resident SSSP replica");
    }
    checked(g.session.transfers.enqueueWriteBuffer(apply_state, CL_FALSE, 0,
        values.size() * 4, values.data()), "initialize resident apply state");
    checked(g.session.transfers.finish(), "finish initial SSSP upload");
    auto& shard = g.shards.at(0);
    for (unsigned port = 0; port < 4; ++port)
      checked(adapter.setArg(port, shard.pma[port]), "set resident PMA handoff");
    checked(adapter.setArg(4, shard.rows), "set resident row handoff");
    checked(adapter.setArg(5, static_cast<unsigned>(model.graph.vertices)), "set adapter vertices");
    const auto slots = static_cast<unsigned>(model.plan.shards.at(0).pma_slot_count);
    checked(adapter.setArg(6, slots), "set adapter slot count");
    checked(adapter.setArg(7, continuous_g::kCacheSegments), "set adapter full cache");
    checked(adapter.setArg(8, 0U), "set adapter destination base");
    checked(adapter.setArg(9, static_cast<unsigned>(model.graph.vertices)), "set adapter destination vertices");
    checked(little.setArg(1, slots), "set little slot count");
    checked(little.setArg(2, 0U), "set little compressed groups");
    checked(little.setArg(3, 0U), "set little destination base");
    checked(little.setArg(4, true), "reset gather each round");
    checked(mux.setArg(4, 0U), "set mux frontend");
    checked(mux.setArg(5, kCapacity / 2), "set gather packet count");
    checked(apply.setArg(0, apply_state), "set apply state");
    checked(apply.setArg(1, active), "set active count");
    checked(apply.setArg(2, 1U), "set dense partition count");
    checked(apply.setArg(3, 0U), "set sparse partition count");
    checked(apply.setArg(4, 0U), "set apply register");
    for (unsigned worker = 0; worker < 4; ++worker)
      checked(hbm.setArg(6 + worker, worker == 0 ? 1U : 0U), "set worker partitions");
  }

  std::vector<Event> seed(const Plan& plan) {
    std::vector<Event> events;
    if (plan.fallback) {
      auto values = internal(plan.initial);
      for (auto* target : {&props[read][0], &props[read][1], &apply_state}) {
        events.push_back({"fallback_dma", 0, {}});
        checked(g.session.transfers.enqueueWriteBuffer(*target, CL_FALSE, 0,
            values.size() * 4, values.data(), nullptr, &events.back().event), "reset fallback state");
      }
      checked(g.session.transfers.finish(), "finish fallback upload");
    } else {
      for (auto external : plan.seeds) for (auto& target : props[read]) {
        events.push_back({"seed_dma", 0, {}});
        checked(g.session.transfers.enqueueWriteBuffer(target, CL_FALSE,
            model.graph.external_to_internal.at(external) * 4, 4, &plan.initial.at(external),
            nullptr, &events.back().event), "activate resident source");
      }
      checked(g.session.transfers.finish(), "finish seed upload");
    }
    return events;
  }

  Reference run(std::vector<Event>& kernels, std::vector<Event>& transfers) {
    Reference result;
    for (unsigned round = 0; round < kRoundLimit; ++round) {
      for (unsigned worker = 0; worker < 4; ++worker)
        checked(hbm.setArg(worker, props[read][worker % 2]), "bind resident source state");
      for (unsigned replica = 0; replica < 2; ++replica)
        checked(hbm.setArg(4 + replica, props[1 - read][replica]), "bind next state");
      for (const auto& [name, kernel] : std::array<std::pair<const char*, cl::Kernel*>, 5>{
          {{"hbm", &hbm}, {"apply", &apply}, {"adapter", &adapter}, {"little", &little}, {"mux", &mux}}}) {
        kernels.push_back({name, round, {}});
        checked(g.session.barriers.enqueueTask(*kernel, nullptr, &kernels.back().event), "enqueue SSSP round");
      }
      checked(g.session.barriers.flush(), "flush SSSP producers and consumers");
      checked(g.session.barriers.finish(), "finish SSSP round");
      unsigned count = 0;
      transfers.push_back({"active_readback", round, {}});
      checked(g.session.transfers.enqueueReadBuffer(active, CL_TRUE, 0, 4, &count,
          nullptr, &transfers.back().event), "read convergence count");
      require(count <= model.graph.vertices, "active count outside real graph");
      result.active_counts.push_back(count);
      read = 1 - read;
      if (!count) break;
    }
    require(!result.active_counts.empty() && result.active_counts.back() == 0,
            "board SSSP did not converge within the declared round limit");
    Values values(kCapacity);
    transfers.push_back({"result_readback", 0, {}});
    checked(g.session.transfers.enqueueReadBuffer(props[read][0], CL_TRUE, 0,
        values.size() * 4, values.data(), nullptr, &transfers.back().event), "publish SSSP result");
    result.values.resize(model.graph.vertices);
    for (unsigned vertex = 0; vertex < model.graph.vertices; ++vertex)
      result.values[vertex] = values.at(model.graph.external_to_internal.at(vertex));
    require(std::all_of(values.begin(), values.end(), [](auto value) { return !(value & kActive); }),
            "active result despite zero convergence count");
    for (unsigned vertex = model.graph.vertices; vertex < kCapacity; ++vertex)
      require(values[vertex] == 0, "padded vertex changed");
    return result;
  }

  void verify_replicas(const Values& external) {
    const auto expected = internal(external);
    for (auto* target : {&props[read][1], &apply_state}) {
      Values values(kCapacity);
      checked(g.session.transfers.enqueueReadBuffer(*target, CL_TRUE, 0,
          values.size() * 4, values.data()), "verify SSSP state replica");
      require(values == expected, "SSSP replica/apply state mismatch");
    }
  }
};
}  // namespace continuous_sssp
