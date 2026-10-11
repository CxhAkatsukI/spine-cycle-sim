#pragma once

#include "spine_sim/fixed_axi_port.hpp"

namespace spine::sim {

// A non-owning queue view, not an AXI master or an independent bandwidth budget.
class AxiEndpoint {
public:
  AxiEndpoint(Fifo<AxiRequest> &requests, Fifo<AxiResponse> &responses,
              Fifo<AxiReadBeatResponse> *read_beats = nullptr)
      : requests_(&requests), responses_(&responses), read_beats_(read_beats) {}
  AxiEndpoint(FixedAxiPort &port)
      : AxiEndpoint(port.requests(), port.responses(),
                    port.read_beat_stream_enabled() ? &port.read_beats() : nullptr) {}
  [[nodiscard]] Fifo<AxiRequest> &requests() const noexcept { return *requests_; }
  [[nodiscard]] Fifo<AxiResponse> &responses() const noexcept { return *responses_; }
  [[nodiscard]] Fifo<AxiReadBeatResponse> *read_beats() const noexcept { return read_beats_; }

private:
  Fifo<AxiRequest> *requests_;
  Fifo<AxiResponse> *responses_;
  Fifo<AxiReadBeatResponse> *read_beats_;
};

} // namespace spine::sim
