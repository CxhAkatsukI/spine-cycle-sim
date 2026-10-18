#include "model.hpp"
#include <iostream>

namespace {
using namespace original_r_k4;
template<class Action> void rejected(Action action) {
  bool failed = false;
  try { action(); } catch (const std::exception&) { failed = true; }
  require(failed, "corruption or unsupported domain was not rejected");
}

void test_arithmetic() {
  require(bits(payload(128, 3)) == bits(36.0F), "binary32 payload formula mismatch");
  require(rb::apply(128, 3) == 35, "fixed control must not be equated to float payload");
  require(bits(payload(128, 0)) == 0, "zero divisor payload mismatch");
  rejected([] { (void)payload((1u << 24) + 1, 0); });
  rejected([] { (void)exact_float((1u << 24) + 1); });
  rejected([] { (void)payload(100000, 1); });
  rejected([] { (void)rb::apply(20000000, 0); });
  rejected([] { (void)rb::apply(0, 0x80000000u); });
  const auto saved = std::fegetround();
  require(std::fesetround(FE_DOWNWARD) == 0, "could not set rounding test environment");
  require(std::fegetround() != FE_TONEAREST, "rounding test environment did not change");
  require(std::fesetround(saved) == 0, "could not restore rounding test environment");
}

void test_banks() {
  BankLedger ledger;
  ledger.admit(0, 200ull << 20);
  ledger.admit(0, 200ull << 20);
  rejected([&] { ledger.admit(0, 113ull << 20); });
  rejected([&] { ledger.admit(1, buffer_bytes); });
  rejected([&] { ledger.admit(32, 1); });
  BankLedger exact;
  exact.admit(0, (256ull << 20) - 64);
  exact.admit(0, (256ull << 20) - 64);
  exact.admit(0, 128);
  rejected([&] { exact.admit(0, 64); });
}

void test_model(const std::filesystem::path& input) {
  auto model = Model::load(input, Binding::csr_degree);
  require(model.original.vertices == 6 && model.original.aligned == 65536, "unexpected test fixture");
  require(model.preparation.graph.external_to_internal == Words({4, 0, 1, 2, 3, 5}),
          "fixture must exercise the real nonidentity production permutation");
  require(model.gathered_external == Words({bits(128.0F), bits(64.0F), bits(128.0F), bits(256.0F), 0, 0}),
          "external CSR rank oracle mismatch");
  require(model.payload_external[0] == 0 && model.payload_external[1] == bits(27.0F) &&
          model.payload_external[2] == bits(108.0F), "external CSR payload mismatch");
  require(model.worker_partitions == std::array<unsigned, 4>{1, 0, 0, 0}, "idle worker geometry mismatch");
  require(model.preparation.plan.max_cache_segments == 131072 &&
          model.preparation.plan.channel_load_bytes.size() == 23 &&
          model.preparation.plan.channel_policy == prod::WeightedPmaChannelPolicy::lane_aware_u55c &&
          model.preparation.plan.shards[0].row_words % 8 == 0,
          "production cache, lane or row-line profile mismatch");
  const auto& rank = model.buffer("rank");
  require(rank.initial.size() == 65536 + rb::guard_words && rank.target()[65535] == 0 &&
          rank.target().back() == rb::guard, "full rank capacity or guard mismatch");
  for (const auto& buffer : model.state) {
    buffer.verify(buffer.target());
    auto corrupt = buffer.target();
    corrupt.back() ^= 1;
    rejected([&] { buffer.verify(corrupt); });
    corrupt = buffer.target();
    corrupt[buffer.logical_words - 1] ^= 1;
    rejected([&] { buffer.verify(corrupt); });
  }
  const auto& stats = model.buffer("stats").target();
  require(stats[0] == 0 && stats[1] == 6 && stats[2] == bits(576.0F) &&
          stats[3] == bits(128.0F) && stats[4] == 6 && stats[5] == rb::guard,
          "FullPR stats or unwritten stats tail mismatch");
  auto& graph = model.preparation.graph;
  const auto original_map = graph.external_to_internal;
  graph.external_to_internal[0] = graph.external_to_internal[1];
  rejected([&] { validate_permutation(graph); });
  graph.external_to_internal = original_map;
  graph.internal_to_external[0] = 0;
  rejected([&] { validate_permutation(graph); });
  graph.internal_to_external[0] = 1;
  const auto csr = Csr::load(input, model.original);
  const auto edges = csr.edges(model.original);
  auto& shard = graph.shards[0];
  const auto original_bounds = shard.row_bounds[0];
  shard.row_bounds[0] ^= 1;
  rejected([&] { validate_static_graph(graph, edges); });
  shard.row_bounds[0] = original_bounds;
  const auto original_word = shard.initial_pma_words[0];
  shard.initial_pma_words[0] = prod::kWeightedPmaEmpty;
  rejected([&] { validate_static_graph(graph, edges); });
  shard.initial_pma_words[0] = original_word;
  shard.binary_heads[0] ^= 1;
  rejected([&] { validate_static_graph(graph, edges); });
  shard.binary_heads[0] ^= 1;
  auto duplicate = edges;
  duplicate.push_back(edges.front());
  rejected([&] { (void)Preparation::build(6, duplicate, 65536); });
  rejected([&] { (void)Preparation::build(6, edges, 6); });
  for (auto& buffer : model.preparation.buffers) {
    const auto saved = buffer.initial.back();
    buffer.initial.back() ^= 1;
    rejected([&] { model.preparation.validate_buffers(); });
    buffer.initial.back() = saved;
  }
  auto& unused = model.preparation.buffers[1];
  require(unused.name == "pma0", "unexpected test region order");
  const auto saved_unused = unused.initial[unused.logical_words - 1];
  unused.initial[unused.logical_words - 1] = 0;
  rejected([&] { model.preparation.validate_buffers(); });
  unused.initial[unused.logical_words - 1] = saved_unused;
  for (auto& buffer : model.preparation.buffers) {
    if (buffer.name != "row") continue;
    require(buffer.logical_words > 2 * shard.row_bounds.size(), "fixture must exercise row-line padding");
    buffer.initial[buffer.logical_words - 1] = 1;
    rejected([&] { model.preparation.validate_buffers(); });
    buffer.initial[buffer.logical_words - 1] = 0;
  }
  std::array<std::uint64_t, 32> accounted{};
  for (const auto& buffer : model.preparation.buffers)
    accounted[buffer.bank] += buffer.initial.size() * 4;
  for (const auto& buffer : model.state) accounted[buffer.bank] += buffer.initial.size() * 4;
  require(accounted == model.preparation.ledger.bytes, "guarded bank ledger differs from actual allocations");
  model.preparation.validate_buffers();
  auto bad_csr = csr;
  bad_csr.offsets[1] = 999;
  rejected([&] { (void)bad_csr.edges(model.original); });
  model.original.edge_words[1] = 1;  // Equal-valued zero sources cannot mask edge identity changes.
  rejected([&] { (void)csr.edges(model.original); });
  const auto saved_rounding = std::fegetround();
  require(std::fesetround(FE_DOWNWARD) == 0, "could not change rounding mode");
  rejected([&] { (void)Model::load(input, Binding::csr_degree); });
  require(std::fesetround(saved_rounding) == 0, "could not restore rounding mode");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    original_r_k4::require(argc == 2, "model_tests INPUT");
    test_arithmetic();
    test_banks();
    test_model(argv[1]);
    std::cout << "matched K4 model invariants passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
