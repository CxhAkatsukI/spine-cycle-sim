#pragma once

#include <ap_int.h>
#include <hls_stream.h>

// One complete original cache bank: 131072 half-segments / 16 owners.
constexpr unsigned cache_bank_depth = 8192;
using CacheWord = ap_uint<512>;
using CacheUpdate = ap_uint<96>;

extern "C" void cache_bank_probe(CacheWord* memory,
                                  hls::stream<CacheUpdate>& updates);
