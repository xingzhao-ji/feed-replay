#include "feed/session.hpp"
#include <algorithm>
#include <limits>
#include <stdexcept>
namespace feed {
namespace {
std::optional<Sequence> packet_first(Bytes b) {
    if (b.size() < 18)
        return {};
    uint64_t v = 0;
    for (size_t j = 10; j < 18; ++j)
        v = (v << 8) | std::to_integer<unsigned>(b[j]);
    return v;
}
bool add(uint64_t &n, uint64_t delta) {
    if (delta > std::numeric_limits<uint64_t>::max() - n)
        return false;
    n += delta;
    return true;
}
} // namespace
Session::Session(IBook &b, SessionConfig c) : book_(b), config_(c) {
    if (!c.retry_ns || c.retry_ns > 50000000 || !c.silence_ns || c.silence_ns > 1500000000 ||
        !c.gap_ns || c.gap_ns > 1000000000 || !c.overall_ns || c.overall_ns > 10000000000ULL ||
        !c.max_attempts || c.max_attempts > 3 || !c.max_requests || c.max_requests > 128 ||
        c.limits.max_messages > 2000000 || c.limits.max_timeline > 10000 ||
        c.limits.max_bytes > 64ULL * 1024 * 1024)
        throw std::invalid_argument("session limits exceed hard bounds");
    audit_.reserve(std::min<size_t>(c.limits.max_timeline, 1024));
}
bool Session::terminal_failure() const {
    return error_.has_value() || cancelled_;
}
void Session::fail(Error error, bool recovery) {
    if (terminal_failure())
        return;
    error_ = std::move(error);
    recovery_failed_ = recovery;
    if (audit_.size() < config_.limits.max_timeline)
        audit_.push_back({now_, recovery ? "recovery_failed" : "invalid", expected_, high_, 0});
}
bool Session::record(std::string event, uint64_t count) {
    if (audit_.size() >= config_.limits.max_timeline) {
        fail({"resource_limit", expected_, 0, "audit timeline limit"});
        return false;
    }
    audit_.push_back({now_, std::move(event), expected_, high_, count});
    return true;
}
bool Session::time_check(uint64_t now) {
    if (terminal_failure())
        return false;
    if (now < now_) {
        fail({"field_domain", expected_, 0, "clock moved backward"});
        return false;
    }
    now_ = now;
    if (!config_.live || (end_ && expected_ == *end_))
        return true;
    if (now_ >= config_.overall_ns) {
        fail({"deadline", expected_, 0, "overall live deadline"}, true);
        return false;
    }
    if (expected_ < high_ && gap_start_ && now_ - *gap_start_ >= config_.gap_ns) {
        fail({"recovery_exhausted", expected_, 0, "continuous gap deadline"}, true);
        return false;
    }
    if (expected_ < high_ && stall_start_ &&
        now_ - *stall_start_ >= config_.retry_ns * config_.max_attempts) {
        fail({"recovery_exhausted", expected_, 0, "stalled cursor deadline"}, true);
        return false;
    }
    return true;
}
Effects Session::recover() {
    Effects effects;
    if (terminal_failure() || !config_.live)
        return effects;
    if (expected_ == high_) {
        gap_start_.reset();
        stall_start_.reset();
        recovery_cursor_ = 0;
        attempts_ = 0;
        return effects;
    }
    if (!gap_start_)
        gap_start_ = now_;
    if (recovery_cursor_ != expected_) {
        recovery_cursor_ = expected_;
        attempts_ = 0;
        stall_start_ = now_;
        retry_due_ = now_;
    }
    if (now_ < retry_due_)
        return effects;
    if (attempts_ >= config_.max_attempts || counters_.requests >= config_.max_requests) {
        fail({"recovery_exhausted", expected_, 0, "request budget exhausted"}, true);
        return effects;
    }
    const auto count = static_cast<uint16_t>(std::min<uint64_t>(128, high_ - expected_));
    auto wire = encode_request(config_.session, expected_, count);
    if (auto error = std::get_if<Error>(&wire)) {
        error->sequence = expected_;
        fail(*error);
        return effects;
    }
    if (!record("request", count))
        return effects;
    ++attempts_;
    if (!add(counters_.requests, 1)) {
        fail({"counter_overflow", expected_, 0, "request counter"});
        return effects;
    }
    retry_due_ = *stall_start_ + config_.retry_ns * attempts_;
    effects.requests.push_back({expected_, count, std::get<std::array<std::byte, 20>>(wire)});
    return effects;
}
Effects Session::ingest(Bytes bytes, uint64_t now, bool truncated) {
    if (!time_check(now))
        return {};
    const auto first = packet_first(bytes);
    if (!add(counters_.datagrams, 1) || !add(counters_.bytes, bytes.size())) {
        fail({"counter_overflow", first, 0, "receive counter"});
        return {};
    }
    if (counters_.datagrams > 2000000 || counters_.bytes > config_.limits.max_bytes) {
        fail({"resource_limit", first, 0, "received data budget"});
        return {};
    }
    if (truncated) {
        fail({"truncated_datagram", first, 0, "recvmsg reported MSG_TRUNC"});
        return {};
    }
    auto parsed = decode_frame(bytes);
    if (auto error = std::get_if<Error>(&parsed)) {
        error->sequence = first;
        fail(*error);
        return {};
    }
    const auto &frame = std::get<Frame>(parsed);
    if (frame.session != config_.session) {
        fail({"session_mismatch", frame.first, 0, "fixed session differs"});
        return {};
    }
    const Sequence bound = frame.kind == FrameKind::data ? frame.first + frame.count : frame.first;
    if (end_ && bound > *end_) {
        fail({"terminal_conflict", frame.first, 0, "packet beyond terminal bound"});
        return {};
    }
    if (frame.kind == FrameKind::end) {
        if (frame.first < high_ || frame.first < expected_ || (end_ && frame.first != *end_)) {
            fail({"terminal_conflict", frame.first, 0, "terminal contradicts observed bound"});
            return {};
        }
    }
    if (frame.kind == FrameKind::data) {
        if (!add(counters_.messages, frame.count)) {
            fail({"counter_overflow", frame.first, 0, "message counter"});
            return {};
        }
        if (counters_.messages > config_.limits.max_messages) {
            fail({"resource_limit", frame.first, 0, "processed message budget"});
            return {};
        }
    }
    high_ = std::max(high_, bound);
    if (frame.kind == FrameKind::end)
        end_ = frame.first;
    if (frame.kind != FrameKind::data) {
        if (frame.first >= expected_)
            last_activity_ = now_;
        if (!record(frame.kind == FrameKind::end ? "end" : "heartbeat"))
            return {};
        return recover();
    }
    if (frame.first > expected_) {
        if (!add(counters_.future_packets, 1)) {
            fail({"counter_overflow", frame.first, 0, "future packet counter"});
            return {};
        }
        if (!record("future_discard", frame.count))
            return {};
        return recover();
    }
    const uint64_t old = std::min<uint64_t>(expected_ - frame.first, frame.count);
    if (!add(counters_.old_messages, old)) {
        fail({"counter_overflow", frame.first, 0, "old message counter"});
        return {};
    }
    const uint64_t before = counters_.accepted;
    for (size_t index = static_cast<size_t>(old); index < frame.messages.size(); ++index) {
        const auto span = frame.messages[index];
        auto decoded = decode_itch(bytes.subspan(span.offset, span.length));
        if (auto error = std::get_if<Error>(&decoded)) {
            error->sequence = expected_;
            error->offset += span.offset;
            fail(*error);
            return {};
        }
        if (auto error = book_.apply(std::get<Event>(decoded))) {
            error->sequence = expected_;
            error->offset = span.offset;
            fail(*error);
            return {};
        }
        if (!add(expected_, 1) || !add(counters_.accepted, 1)) {
            fail({"counter_overflow", expected_, span.offset, "accepted sequence counter"});
            return {};
        }
        last_activity_ = now_;
    }
    if (!record(counters_.accepted == before ? "duplicate" : "accepted",
                counters_.accepted - before))
        return {};
    return recover();
}
Effects Session::on_time(uint64_t now) {
    if (!time_check(now))
        return {};
    return recover();
}
void Session::stop(Error error) {
    fail(std::move(error));
}
void Session::cancel() {
    if (terminal_failure() || (end_ && expected_ == *end_))
        return;
    cancelled_ = true;
    error_ = Error{"cancelled", expected_, 0, "caller cancelled"};
    if (audit_.size() < config_.limits.max_timeline)
        audit_.push_back({now_, "cancelled", expected_, high_, 0});
}
std::string Session::status(uint64_t now) const {
    if (cancelled_)
        return "Cancelled";
    if (recovery_failed_)
        return "RecoveryFailed";
    if (error_)
        return "Invalid";
    if (end_ && expected_ == high_ && expected_ == *end_)
        return "Complete";
    if (expected_ < high_)
        return "Gap";
    if (!config_.live)
        return "ReplayPrefix";
    if (!last_activity_)
        return now >= config_.silence_ns ? "Stale" : "Awaiting";
    if (now >= *last_activity_ && now - *last_activity_ >= config_.silence_ns)
        return "Stale";
    return "CurrentObserved";
}
View Session::view(uint64_t now, size_t depth, bool include_orders) const {
    View out;
    out.expected = expected_;
    out.high_water_next = high_;
    out.end_next = end_;
    out.status = status(now);
    out.error = error_;
    out.live_fresh = config_.live && out.status == "CurrentObserved";
    out.quote_usable = out.live_fresh;
    out.book = book_.snapshot(depth, include_orders);
    return out;
}
} // namespace feed
