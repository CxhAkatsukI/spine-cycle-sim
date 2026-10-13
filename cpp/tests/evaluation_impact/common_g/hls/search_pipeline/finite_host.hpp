#pragma once

// Host-only FIFO delegates exercise the unchanged HLS stage functions with
// bounded backpressure. Host thread scheduling is not an RTL timing model.
#include "types.hpp"
#include <condition_variable>
#include <cstring>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <pthread.h>
#include <stdexcept>
#include <thread>
#include <vector>

namespace search_pipeline {
inline void configure_host_threads() {
  // The bounded runner's process stack limit is not a sensible per-FIFO-thread
  // default. This affects only Linux C-simulation, never synthesized hardware.
  pthread_attr_t attributes;
  if (pthread_attr_init(&attributes)) throw std::runtime_error("thread attributes");
  const int stack = pthread_attr_setstacksize(&attributes, 1048576);
  const int apply = stack ? stack : pthread_setattr_default_np(&attributes);
  pthread_attr_destroy(&attributes);
  if (apply) throw std::runtime_error("bounded host thread stack");
}

struct ChannelStats {
  unsigned capacity{};
  unsigned high_water{};
  unsigned long writes{}, reads{}, blocked_writes{};
};

struct HostReport {
  std::vector<ChannelStats> channels;
};

inline HostReport& last_host_report() {
  static HostReport report;
  return report;
}

struct QueueBase {
  virtual ~QueueBase() = default;
  virtual ChannelStats stats() = 0;
};

template<class T>
class FiniteQueue final : public QueueBase, public hls::stream_delegate<sizeof(T)> {
public:
  explicit FiniteQueue(unsigned capacity = 2) { stats_.capacity = capacity; }
  void write(const void* value) override {
    std::unique_lock<std::mutex> lock(mutex_);
    if (data_.size() == stats_.capacity) ++stats_.blocked_writes;
    ready_.wait(lock, [&] { return data_.size() < stats_.capacity; });
    T copy;
    std::memcpy(&copy, value, sizeof(T));
    data_.push_back(copy);
    ++stats_.writes;
    if (data_.size() > stats_.high_water) stats_.high_water = data_.size();
    ready_.notify_all();
  }
  bool read(void* value) override {
    std::unique_lock<std::mutex> lock(mutex_);
    ready_.wait(lock, [&] { return !data_.empty(); });
    take(value);
    return true;
  }
  bool read_nb(void* value) override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (data_.empty()) return false;
    take(value);
    return true;
  }
  size_t size() override {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_.size();
  }
  ChannelStats stats() override {
    std::lock_guard<std::mutex> lock(mutex_);
    return stats_;
  }
private:
  void take(void* value) {
    std::memcpy(value, &data_.front(), sizeof(T));
    data_.pop_front();
    ++stats_.reads;
    ready_.notify_all();
  }
  ChannelStats stats_;
  std::mutex mutex_;
  std::condition_variable ready_;
  std::deque<T> data_;
};

class HostNetwork {
public:
  ~HostNetwork() { for (auto& detach : detachers_) detach(); }
  template<class T>
  void bind(hls::stream<T>& stream, unsigned capacity = 2) {
    auto queue = std::unique_ptr<FiniteQueue<T>>(new FiniteQueue<T>(capacity));
    stream.set_delegate(queue.get());
    detachers_.emplace_back([&stream] { stream.set_delegate(nullptr); });
    queues_.push_back(std::move(queue));
  }
  template<class Function> void launch(Function function) { threads_.emplace_back(function); }
  void join() {
    for (auto& thread : threads_) thread.join();
    HostReport report;
    for (auto& queue : queues_) {
      const auto stats = queue->stats();
      if (stats.writes != stats.reads || stats.high_water > stats.capacity)
        throw std::runtime_error("finite search channel did not conserve/drain");
      report.channels.push_back(stats);
    }
    last_host_report() = std::move(report);
  }
private:
  std::vector<std::unique_ptr<QueueBase>> queues_;
  std::vector<std::thread> threads_;
  std::vector<std::function<void()>> detachers_;
};
}  // namespace search_pipeline
