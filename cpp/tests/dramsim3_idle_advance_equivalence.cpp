#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <tuple>
#include <vector>

#include "dramsim3.h"

namespace {

struct Request {
    uint64_t cycle;
    uint64_t address;
    bool is_write;
};

using Completion = std::tuple<uint64_t, uint64_t, bool>;

std::vector<Request> Requests() {
    return {
        {0, 0x0000, true},        {0, 0x0040, true},
        {0, 0x0080, true},        {0, 0x00c0, true},
        {0, 0x0100, true},        {0, 0x0140, true},
        {0, 0x0180, true},        {0, 0x01c0, true},
        {0, 0x0200, true},        {0, 0x0240, true},
        {17, 0x0800, false},      {3899, 0x1000, false},
        {3900, 0x1040, false},    {3901, 0x1080, false},
        {7799, 0x2000, false},    {7800, 0x2040, false},
        {7801, 0x2080, false},    {999999, 0x3000, false},
        {1000000, 0x3040, false}, {1000001, 0x3080, false},
        {1000002, 0x4000, true},
    };
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: " << argv[0]
                  << " CONFIG BASELINE_OUTPUT_DIR SKIP_OUTPUT_DIR\n";
        return 2;
    }

    uint64_t baseline_cycle = 0;
    uint64_t skip_cycle = 0;
    std::vector<Completion> baseline_completions;
    std::vector<Completion> skip_completions;

    dramsim3::MemorySystem* baseline = dramsim3::GetMemorySystem(
        argv[1], argv[2],
        [&](uint64_t address) {
            baseline_completions.emplace_back(baseline_cycle, address, false);
        },
        [&](uint64_t address) {
            baseline_completions.emplace_back(baseline_cycle, address, true);
        });
    dramsim3::MemorySystem* skipped = dramsim3::GetMemorySystem(
        argv[1], argv[3],
        [&](uint64_t address) {
            skip_completions.emplace_back(skip_cycle, address, false);
        },
        [&](uint64_t address) {
            skip_completions.emplace_back(skip_cycle, address, true);
        });

    const std::vector<Request> requests = Requests();
    const uint64_t stop_cycle = 1010000;
    size_t request_index = 0;
    uint64_t skipped_cycles = 0;

    while (baseline_cycle < stop_cycle) {
        while (request_index < requests.size() &&
               requests[request_index].cycle == baseline_cycle) {
            const Request& request = requests[request_index];
            if (!baseline->WillAcceptTransaction(request.address,
                                                  request.is_write) ||
                !skipped->WillAcceptTransaction(request.address,
                                                 request.is_write)) {
                std::cerr << "scheduled transaction rejected at cycle "
                          << baseline_cycle << "\n";
                return 3;
            }
            baseline->AddTransaction(request.address, request.is_write);
            skipped->AddTransaction(request.address, request.is_write);
            ++request_index;
        }

        const uint64_t next_request =
            request_index < requests.size() ? requests[request_index].cycle
                                            : stop_cycle;
        if (skipped->IsIdle() && next_request > baseline_cycle) {
            const uint64_t step = next_request - baseline_cycle;
            for (uint64_t i = 0; i < step; ++i) {
                baseline->ClockTick();
                ++baseline_cycle;
            }
            skipped->AdvanceIdle(step);
            skip_cycle += step;
            skipped_cycles += step;
            continue;
        }

        baseline->ClockTick();
        skipped->ClockTick();
        ++baseline_cycle;
        ++skip_cycle;
    }

    baseline->PrintStats();
    skipped->PrintStats();

    if (baseline_cycle != skip_cycle) {
        std::cerr << "clock mismatch: baseline=" << baseline_cycle
                  << " skipped=" << skip_cycle << "\n";
        return 4;
    }
    if (baseline_completions != skip_completions) {
        std::cerr << "completion mismatch: baseline="
                  << baseline_completions.size()
                  << " skipped=" << skip_completions.size() << "\n";
        const size_t count =
            std::min(baseline_completions.size(), skip_completions.size());
        for (size_t i = 0; i < count; ++i) {
            if (baseline_completions[i] != skip_completions[i]) {
                std::cerr << "first mismatch at completion " << i << "\n";
                break;
            }
        }
        return 5;
    }
    if (baseline_completions.size() != requests.size()) {
        std::cerr << "missing completions: got " << baseline_completions.size()
                  << " expected " << requests.size() << "\n";
        return 6;
    }

    std::cout << "PASS completions=" << baseline_completions.size()
              << " skipped_cycles=" << skipped_cycles
              << " total_cycles=" << baseline_cycle << "\n";
    delete baseline;
    delete skipped;
    return 0;
}
