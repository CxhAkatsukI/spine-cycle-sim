#include "resident.hpp"
#include "host_prepared/input.hpp"
#include <iostream>

int main() {
  using namespace continuous_sssp;
  try {
    require(prepared_g::supported_update_count(512) && prepared_g::supported_update_count(8192) &&
            !prepared_g::supported_update_count(128) && prepared_g::supported_update_count(128, true) &&
            !prepared_g::supported_update_count(0, true) && !prepared_g::supported_update_count(256, true),
            "warm control must be explicit without broadening the original input contract");
    const Edges old{{{0, 1}, 5}, {{1, 2}, 7}, {{0, 2}, 20}, {{2, 3}, 2}};
    const auto initial = shortest_paths(5, old, 0);
    require(initial == Values({0, 5, 12, 14, kInf}), "independent initial oracle");
    const auto check = [&](const Edges& next, bool fallback, const std::vector<unsigned>& seeds) {
      const auto plan = prepare(old, next, initial, 0);
      require(plan.fallback == fallback && plan.seeds == seeds, "wrong preparation policy");
      const auto reference = relax(next, plan, 32);
      require(reference.values == shortest_paths(5, next, 0) &&
              reference.active_counts.back() == 0, "incorrect converged resident state");
      return reference;
    };
    require(check(old, false, {}).active_counts == std::vector<unsigned>{0}, "net-zero must terminate");
    auto decrease = old;
    decrease[{0, 2}] = 1;
    require(check(decrease, false, {0}).active_counts == std::vector<unsigned>({1, 1, 0}),
            "wrong synchronous convergence trajectory");
    auto insertion = old;
    insertion[{1, 4}] = 1;
    check(insertion, false, {1});
    auto deletion = old;
    deletion.erase({1, 2});
    check(deletion, true, {0});
    auto increase = old;
    increase[{1, 2}] = 12;
    check(increase, true, {0});
    auto unreachable = old;
    unreachable[{4, 3}] = 1;
    require(check(unreachable, false, {4}).active_counts == std::vector<unsigned>{0},
            "unreachable seed must not propagate");
    auto state = initial;
    state[1] |= kActive;
    bool rejected = false;
    try { (void)prepare(old, old, state, 0); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "unconverged previous state accepted");
    rejected = false;
    try { (void)relax(decrease, prepare(old, decrease, initial, 0), 1); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "round limit not enforced");
    rejected = false;
    try { (void)shortest_paths(5, {{{0, 5}, 1}}, 0); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "invalid endpoint accepted");
    rejected = false;
    try { (void)shortest_paths(5, {{{0, 1}, 4096}}, 0); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "invalid weighted ABI accepted");
    std::cout << "CONTINUOUS_GR_RESIDENT_UNIT_PASS\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
