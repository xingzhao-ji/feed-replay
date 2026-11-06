#pragma once
#include "book.hpp"
#include "codec.hpp"
namespace feed {
struct SessionConfig {
    SessionId session{};
    Limits limits{};
    bool live = false;
    uint64_t retry_ns = 50000000, silence_ns = 1500000000, gap_ns = 1000000000,
             overall_ns = 10000000000;
    uint32_t max_attempts = 3, max_requests = 128;
};
struct RecoveryRequest {
    Sequence first;
    uint16_t count;
    std::array<std::byte, 20> wire;
};
struct Audit {
    uint64_t time_ns;
    std::string event;
    Sequence expected, high_water_next;
    uint64_t count;
};
struct Effects {
    std::vector<RecoveryRequest> requests;
};
struct Counters {
    uint64_t datagrams = 0, bytes = 0, messages = 0, accepted = 0, old_messages = 0,
             future_packets = 0, requests = 0;
};
struct View {
    Sequence expected = 1, high_water_next = 1;
    std::optional<Sequence> end_next;
    std::string status;
    bool live_fresh = false, quote_usable = false;
    std::optional<Error> error;
    BookSnapshot book;
};
class Session {
  public:
    Session(IBook &, SessionConfig);
    Effects ingest(Bytes, uint64_t now_ns, bool truncated = false);
    Effects on_time(uint64_t now_ns);
    View view(uint64_t now_ns, size_t depth = 5, bool include_orders = true) const;
    void cancel();
    void stop(Error error);
    const std::vector<Audit> &audit() const {
        return audit_;
    }
    const Counters &counters() const {
        return counters_;
    }
    std::string status(uint64_t now_ns) const;

  private:
    IBook &book_;
    SessionConfig config_;
    Sequence expected_ = 1, high_ = 1;
    std::optional<Sequence> end_;
    std::optional<Error> error_;
    uint64_t now_ = 0;
    std::optional<uint64_t> last_activity_, gap_start_, stall_start_;
    Sequence recovery_cursor_ = 0;
    uint32_t attempts_ = 0;
    uint64_t retry_due_ = 0;
    bool cancelled_ = false, recovery_failed_ = false;
    Counters counters_;
    std::vector<Audit> audit_;
    bool terminal_failure() const;
    void fail(Error, bool recovery = false);
    bool record(std::string, uint64_t count = 0);
    bool time_check(uint64_t);
    Effects recover();
};
} // namespace feed
