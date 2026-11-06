#pragma once
#include "session.hpp"
#include <filesystem>
#include <fstream>
#include <stdexcept>
namespace feed {
struct IoFailure : std::runtime_error {
    Error error;
    explicit IoFailure(Error e) : std::runtime_error(e.detail), error(std::move(e)) {};
};
struct CapturedDatagram {
    std::vector<std::byte> data;
    bool truncated = false;
};
class CaptureReader {
  public:
    explicit CaptureReader(const std::filesystem::path &);
    ~CaptureReader();
    CaptureReader(const CaptureReader &) = delete;
    CaptureReader &operator=(const CaptureReader &) = delete;
    Result<std::optional<CapturedDatagram>> next();

  private:
    int fd_ = -1;
    uint64_t bytes_ = 8, records_ = 0;
};
class CaptureWriter {
  public:
    explicit CaptureWriter(const std::filesystem::path &);
    ~CaptureWriter();
    CaptureWriter(const CaptureWriter &) = delete;
    CaptureWriter &operator=(const CaptureWriter &) = delete;
    std::optional<Error> append(Bytes, bool);
    std::optional<Error> finish();
    uint64_t bytes() const {
        return bytes_;
    }

  private:
    int fd_ = -1;
    uint64_t bytes_ = 8, records_ = 0;
};
struct TransportMetrics {
    uint64_t received = 0, received_bytes = 0, foreign = 0, requests_sent = 0;
};
struct RunOutcome {
    View view;
    Counters counters;
    std::vector<Audit> audit;
    TransportMetrics transport;
    bool offline = true;
    size_t depth = 5;
    bool include_orders = false;
    std::string engine = "indexed";
};
struct LiveConfig {
    uint16_t listen_port, source_port, recovery_port;
    SessionConfig session;
    size_t receive_buffer = 65507;
    uint64_t receive_bytes = 64 * 1024 * 1024, receive_count = 2000000;
    size_t depth = 5;
    bool include_orders = false;
};
RunOutcome replay_capture(const std::filesystem::path &, IBook &, SessionConfig, size_t depth,
                          bool include_orders);
RunOutcome run_udp(const LiveConfig &, IBook &, CaptureWriter &);
std::optional<Error> write_report(const std::filesystem::path &new_directory, const RunOutcome &,
                                  uint64_t max_bytes = 8 * 1024 * 1024);
std::string book_json(const BookSnapshot &, uint64_t max_bytes = 8 * 1024 * 1024);
} // namespace feed
