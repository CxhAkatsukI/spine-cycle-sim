#include "events.hpp"
#include <iostream>

namespace rb = original_r_board;

template<class Function> void rejected(Function function) {
  try { function(); } catch (const std::runtime_error&) { return; }
  throw std::runtime_error("invalid control was accepted");
}

int main() {
  try {
    rb::require(rb::binding("author_initial") == rb::Binding::author_initial &&
        rb::binding("csr_degree") == rb::Binding::csr_degree, "named binding mismatch");
    rejected([] { rb::binding("corrected"); });
    rb::require(rb::apply(512, 4) == 108 && rb::apply(512, 128) == 3 && rb::apply(512, 0) == 0,
                "explicit fixed-point bindings changed");
    rejected([] { rb::apply(INT32_MAX, 1); });
    rejected([] { rb::apply(65536, 1); });
    rejected([] { rb::apply(1, 0x80000000u); });
    const auto guarded = rb::guarded({1, 2});
    rb::require(guarded.size() == 18 && guarded[1] == 2 && guarded.back() == rb::guard, "missing complete guard line");
    rb::Model model;
    model.little = 4;
    rb::require(rb::board_lanes(model) == 4, "A4 lane count mismatch");
    model.little = 11; model.big = 3;
    rb::require(rb::board_lanes(model) == 14, "original lane count mismatch");
    model.big = 0;
    rejected([&] { rb::board_lanes(model); });
    model.aligned = 65536; model.published = 589824; model.allocation = model.published;
    model.initial.resize(model.allocation); model.degrees.resize(model.allocation);
    model.expected.resize(model.allocation + rb::guard_words);
    model.validate_capacity();
    model.allocation = model.aligned;
    rejected([&] { model.validate_capacity(); });
    rb::require(rb::window({{1, 2, 3, 10}, {2, 3, 5, 8}, {4, 5, 12, 15}}).busy_ns == 10 &&
        rb::window({{1, 2, 3, 10}, {2, 3, 5, 8}, {4, 5, 12, 15}}).span_ns == 12,
        "overlapping kernels must not be summed");
    rejected([] { rb::window({}); });
    rejected([] { rb::window({{1, 2, 10, 10}}); });
    rejected([] { rb::window({{2, 1, 3, 10}}); });
    rb::Words expected{1, 2, rb::guard};
    model.verify(expected, expected, "same payload rejected");
    for (unsigned index = 0; index < expected.size(); ++index) {
      auto bad = expected; bad[index] ^= 1;
      rejected([&] { model.verify(bad, expected, "payload or guard mismatch"); });
    }
    std::cout << "original_r_board_model_tests PASS\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
