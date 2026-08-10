#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <utility>

namespace spine::sim {

using ClockId = std::size_t;
using TimestampFs = std::uint64_t;

struct CycleContext {
  TimestampFs now_fs{};
  std::uint64_t domain_cycle{};
  ClockId clock_id{};
};

class Component {
 public:
  Component(std::string name, ClockId clock_id)
      : name_(std::move(name)), clock_id_(clock_id) {}
  virtual ~Component() = default;

  Component(const Component&) = delete;
  Component& operator=(const Component&) = delete;
  Component(Component&&) = delete;
  Component& operator=(Component&&) = delete;

  [[nodiscard]] const std::string& name() const noexcept { return name_; }
  [[nodiscard]] ClockId clock_id() const noexcept { return clock_id_; }

  // Phase participation is fixed for a component's lifetime. The scheduler
  // uses these declarations only to omit virtual calls to known no-op phases;
  // every simulated clock edge and the prepare/evaluate/commit ordering remain
  // unchanged.
  [[nodiscard]] virtual bool has_prepare_phase() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_evaluate_phase() const noexcept {
    return true;
  }
  [[nodiscard]] virtual bool has_commit_phase() const noexcept { return true; }
  [[nodiscard]] virtual bool has_dynamic_prepare_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_dynamic_evaluate_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_latched_evaluate_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_dynamic_commit_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool has_latched_commit_guard() const noexcept {
    return false;
  }
  [[nodiscard]] virtual bool prepare_ready() const noexcept { return true; }
  [[nodiscard]] virtual bool evaluate_ready() const noexcept { return true; }
  [[nodiscard]] virtual bool commit_ready() const noexcept { return true; }
  // A dynamic guard may expose a stable readiness token to avoid a virtual
  // call in the scheduler hot path. The component owns and updates the token.
  [[nodiscard]] virtual const bool* evaluate_ready_token() const noexcept {
    return nullptr;
  }
  [[nodiscard]] virtual const bool* commit_ready_token() const noexcept {
    return nullptr;
  }
  [[nodiscard]] bool latched_commit_ready() const noexcept {
    return latched_commit_ready_;
  }
  [[nodiscard]] bool latched_evaluate_ready() const noexcept {
    return latched_evaluate_ready_;
  }

  virtual void prepare(const CycleContext&) {}
  virtual void evaluate(const CycleContext& context) = 0;
  virtual void commit(const CycleContext& context) = 0;

 protected:
  void set_latched_evaluate_ready(bool ready) noexcept {
    if (ready == latched_evaluate_ready_) {
      return;
    }
    latched_evaluate_ready_ = ready;
    if (latched_evaluate_notifier_ != nullptr) {
      latched_evaluate_notifier_(latched_evaluate_notifier_owner_,
                                 latched_evaluate_slot_, ready);
    }
  }

  void set_latched_commit_ready(bool ready) noexcept {
    const bool notify = ready && !latched_commit_ready_ &&
                        latched_commit_notifier_ != nullptr;
    latched_commit_ready_ = ready;
    if (notify) {
      latched_commit_notifier_(latched_commit_notifier_owner_,
                               latched_commit_slot_);
    }
  }

 private:
  friend class Scheduler;
  using LatchedCommitNotifier = void (*)(void *, std::size_t) noexcept;
  using LatchedEvaluateNotifier =
      void (*)(void *, std::size_t, bool) noexcept;

  void bind_latched_evaluate_notifier(
      void *owner, std::size_t slot,
      LatchedEvaluateNotifier notifier) noexcept {
    latched_evaluate_notifier_owner_ = owner;
    latched_evaluate_slot_ = slot;
    latched_evaluate_notifier_ = notifier;
  }
  void unbind_latched_evaluate_notifier() noexcept {
    latched_evaluate_notifier_owner_ = nullptr;
    latched_evaluate_slot_ = std::numeric_limits<std::size_t>::max();
    latched_evaluate_notifier_ = nullptr;
  }

  void bind_latched_commit_notifier(void *owner, std::size_t slot,
                                    LatchedCommitNotifier notifier) noexcept {
    latched_commit_notifier_owner_ = owner;
    latched_commit_slot_ = slot;
    latched_commit_notifier_ = notifier;
  }
  void unbind_latched_commit_notifier() noexcept {
    latched_commit_notifier_owner_ = nullptr;
    latched_commit_slot_ = std::numeric_limits<std::size_t>::max();
    latched_commit_notifier_ = nullptr;
  }

  std::string name_;
  ClockId clock_id_;
  bool latched_commit_ready_{};
  bool latched_evaluate_ready_{};
  void *latched_evaluate_notifier_owner_{};
  std::size_t latched_evaluate_slot_{
      std::numeric_limits<std::size_t>::max()};
  LatchedEvaluateNotifier latched_evaluate_notifier_{};
  void *latched_commit_notifier_owner_{};
  std::size_t latched_commit_slot_{std::numeric_limits<std::size_t>::max()};
  LatchedCommitNotifier latched_commit_notifier_{};
};

}  // namespace spine::sim
