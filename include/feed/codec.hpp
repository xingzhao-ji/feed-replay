#pragma once
#include "types.hpp"
namespace feed {
struct MessageSpan {
    size_t offset;
    uint16_t length;
};
enum class FrameKind { data, heartbeat, end };
struct Frame {
    SessionId session;
    Sequence first;
    FrameKind kind;
    uint16_t count;
    std::vector<MessageSpan> messages;
};
Result<Frame> decode_frame(Bytes);
Result<Event> decode_itch(Bytes);
Result<std::array<std::byte, 20>> encode_request(SessionId, Sequence, uint16_t);
} // namespace feed
