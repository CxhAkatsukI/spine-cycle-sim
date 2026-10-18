#pragma once

#include "model.hpp"

namespace original_r_k4 {
inline std::string buffer_name(const Buffer& value) {
  return (value.shard == no_shard ? "" : "shard" + std::to_string(value.shard) + "_") + value.name;
}

template<class Function>
void each_buffer(const Model& model, Function function) {
  for (const auto& value : model.preparation.buffers) function(value);
  for (const auto& value : model.state) function(value);
}

inline void write_expectations(const Model& model, const std::filesystem::path& output) {
  require(std::filesystem::create_directory(output / "expected_buffers"), "fresh expectation directory required");
  each_buffer(model, [&](const Buffer& value) {
    rb::wt::write_words(output / "expected_buffers" / (buffer_name(value) + ".u32le"), value.target());
  });
}

inline void describe_buffers(std::ostream& json, const Model& model) {
  json << "[";
  bool first = true;
  each_buffer(model, [&](const Buffer& value) {
    json << (first ? "" : ",") << "{\"name\":\"" << buffer_name(value) << "\",\"bank\":" << value.bank
         << ",\"logical_words\":" << value.logical_words << ",\"allocated_words\":" << value.allocated_words
         << ",\"words\":" << value.initial.size() << ",\"mutable\":" << (value.expected.empty() ? "false" : "true") << "}";
    first = false;
  });
  json << "]";
}
}  // namespace original_r_k4
