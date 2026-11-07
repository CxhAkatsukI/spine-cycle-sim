#include "spine_persistent_schedule.hpp"

#include <iostream>
#include <limits>
#include <string>

using persistent_schedule::spans;

static void check(bool condition) {
    if (!condition) throw std::runtime_error("schedule regression failed");
}

template <typename Exception, typename Function>
static void rejects(Function function) {
    try { function(); } catch (const Exception &) { return; }
    throw std::runtime_error("expected schedule rejection");
}

static void matrix(std::size_t updates, std::size_t batches, std::size_t expected) {
    std::vector<std::size_t> edges, replay;
    for (std::size_t i = 0; i < updates; ++i) edges.push_back(updates - i);
    std::size_t launches = 0, covered = 0;
    for (std::size_t batch = 0; batch < batches; ++batch) {
        const auto begin = batch * updates / batches;
        const auto end = (batch + 1) * updates / batches;
        const auto physical = spans(begin, end);
        check(physical.front().begin == begin && physical.back().end == end);
        for (const auto &span : physical) {
            check(span.begin == covered && span.end > span.begin);
            check(span.end <= end && span.end - span.begin <= 8192);
            for (auto i = span.begin; i < span.end; ++i) replay.push_back(edges[i]);
            covered = span.end;
            ++launches;
        }
    }
    check(launches == expected && covered == updates && replay == edges);
}

static void guards() {
    rejects<std::invalid_argument>([] { spans(0, 0); });
    rejects<std::invalid_argument>([] { spans(4, 3); });
    rejects<std::invalid_argument>([] { spans(0, 1, 0); });
    const auto maximum = std::numeric_limits<std::size_t>::max();
    rejects<std::length_error>([=] { spans(0, maximum, 1); });
    const auto tail = spans(maximum - 5, maximum, 2);
    check(tail.size() == 3 && tail[0].begin == maximum - 5);
    check(tail[0].end == tail[1].begin && tail[1].end == tail[2].begin);
    check(tail[1].end == maximum - 1 && tail[2].end == maximum);
    const auto exact = spans(7, 11, 2);
    check(exact.size() == 2 && exact.back().end == 11);
    check(spans(9, 10).size() == 1);
}

static void l1_invariant() {
    const auto full = spans(0, 16384);
    check(full.size() == 2 && full[0].end - full[0].begin == 8192);
    check(full[1].end - full[0].begin == 16384);
    for (const std::size_t batches : {10, 100, 1000}) {
        std::size_t l0 = 0;
        for (std::size_t batch = 0; batch < batches; ++batch) {
            for (const auto &span : spans(batch * 131072 / batches,
                                          (batch + 1) * 131072 / batches)) {
                const auto incoming = span.end - span.begin;
                check(incoming <= 8192);
                if (l0 == 0) l0 = incoming;
                else { check(l0 + incoming <= 16384); l0 = 0; }
            }
        }
    }
}

int main(int argc, char **argv) {
    try {
        check(argc == 2);
        const std::string name = argv[1];
        if (name == "matrix") {
            matrix(131072, 10, 20);
            matrix(131072, 100, 100);
            matrix(131072, 1000, 1000);
            matrix(4096, 10, 10);
        } else if (name == "guards") guards();
        else if (name == "l1") l1_invariant();
        else throw std::invalid_argument("unknown regression case");
        std::cout << "PASS " << name << '\n';
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
