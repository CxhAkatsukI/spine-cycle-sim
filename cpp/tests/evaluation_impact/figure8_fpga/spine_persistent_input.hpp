#pragma once

namespace {

static SetupInsertionBatch read_persistent_insertion_trace(
    const std::string &path, size_t batches
) {
    std::ifstream in(path);
    uint64_t vertices = 0, edges = 0, updates = 0;
    require(static_cast<bool>(in >> vertices >> edges >> updates) &&
                vertices > 0 && vertices <= MAX_N && edges > 0 && updates > 0 &&
                batches > 0 && batches <= updates,
            "invalid persistent graph header or batch count");
    // MAX_SORT_N is a per-invocation device limit, not a whole-trace limit.
    require(updates / batches + (updates % batches != 0) <=
                (uint64_t)HOST_PARTITIONED_RATIO2_MAX_SORT_N,
            "persistent batch exceeds MAX_SORT_N");
    SetupInsertionBatch trace;
    trace.vertices = (int)vertices;
    require(edges <= trace.old_edges.max_size() &&
                updates <= trace.inserts.max_size(),
            "persistent graph exceeds host vector capacity");
    trace.old_edges.reserve((size_t)edges);
    trace.inserts.reserve((size_t)updates);
    auto read_edges = [&](auto &out, uint64_t count, bool update) {
        for (uint64_t i = 0; i < count; ++i) {
            uint64_t src = 0, dst = 0, weight = 0, type = 1;
            require(static_cast<bool>(in >> src >> dst >> weight) &&
                        (!update || static_cast<bool>(in >> type)) &&
                        src < vertices && dst < vertices &&
                        weight > 0 && weight <= 0x0fffU && type == 1,
                    "persistent graph requires weight12 edges and inserts only");
            out.push_back({(uint32_t)src, (uint32_t)dst, (uint16_t)weight, 1});
        }
    };
    read_edges(trace.old_edges, edges, false);
    read_edges(trace.inserts, updates, true);
    std::string trailing;
    require(!(in >> trailing), "unexpected trailing persistent graph input");
    return trace;
}

static size_t persistent_batch_boundary(size_t index, size_t updates,
                                        size_t batches) {
    return (size_t)((unsigned __int128)index * updates / batches);
}

}  // namespace
