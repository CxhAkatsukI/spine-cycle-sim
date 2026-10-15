#pragma once

#include "../search_pipeline/types.hpp"

extern "C" void bin_search(
    const unsigned long* edges,
    const search_pipeline::Raw* binary_0, const search_pipeline::Raw* binary_1,
    const search_pipeline::Raw* binary_2, const search_pipeline::Raw* binary_3,
    const search_pipeline::Raw* row_offset_0, const search_pipeline::Raw* row_offset_1,
    const search_pipeline::Raw* row_offset_2, const search_pipeline::Raw* row_offset_3,
    unsigned edge_size, hls::stream<search_pipeline::Packet>& segment_head_stream_out);
