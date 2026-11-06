#include "feed/codec.hpp"
#include <algorithm>
#include <limits>
namespace feed {
namespace {
Error fail(const char *code, size_t offset = 0) {
    return {code, {}, offset, code};
}
// Called only after the containing header or exact ITCH length has been checked.
// Byte assembly avoids packed-struct alignment and host-endianness assumptions.
uint64_t read_unsigned(Bytes bytes, size_t offset, size_t width) {
    uint64_t value = 0;
    for (size_t index = 0; index < width; ++index)
        value = (value << 8) | std::to_integer<unsigned>(bytes[offset + index]);
    return value;
}
char character(Bytes bytes, size_t offset) {
    return static_cast<char>(std::to_integer<unsigned char>(bytes[offset]));
}
size_t message_length(char type) {
    switch (type) {
    case 'S':
        return 12;
    case 'R':
        return 39;
    case 'A':
    case 'C':
        return 36;
    case 'F':
    case 'Q':
        return 40;
    case 'E':
        return 31;
    case 'X':
        return 23;
    case 'D':
    case 'B':
        return 19;
    case 'U':
        return 35;
    case 'P':
        return 44;
    default:
        return 0;
    }
}
template <size_t N> std::optional<std::array<char, N>> alpha(Bytes bytes, size_t offset) {
    std::array<char, N> out{};
    bool padding = false;
    for (size_t index = 0; index < N; ++index) {
        const auto code_point = std::to_integer<unsigned>(bytes[offset + index]);
        if (code_point < 32 || code_point > 126 || (padding && code_point != 32))
            return {};
        if (code_point == 32)
            padding = true;
        out[index] = static_cast<char>(code_point);
    }
    if (out[0] == ' ')
        return {};
    return out;
}
} // namespace
Result<Frame> decode_frame(Bytes bytes) {
    if (bytes.size() < 20 || bytes.size() > 65507)
        return fail("mold_header");
    Frame out{};
    std::copy_n(bytes.begin(), 10, out.session.begin());
    out.first = read_unsigned(bytes, 10, 8);
    out.count = static_cast<uint16_t>(read_unsigned(bytes, 18, 2));
    if (out.first == 0)
        return fail("mold_header", 10);
    if (out.count == 0 || out.count == 65535) {
        if (bytes.size() != 20)
            return fail("mold_trailing", 20);
        out.kind = out.count == 0 ? FrameKind::heartbeat : FrameKind::end;
        return out;
    }
    if (out.first > std::numeric_limits<uint64_t>::max() - out.count)
        return fail("counter_overflow", 10);
    out.kind = FrameKind::data;
    out.messages.reserve(std::min(static_cast<size_t>(out.count), bytes.size() / 14));
    size_t position = 20;
    for (unsigned index = 0; index < out.count; ++index) {
        if (bytes.size() - position < 2)
            return fail("mold_block", position);
        const auto width = static_cast<uint16_t>(read_unsigned(bytes, position, 2));
        position += 2;
        if (width > bytes.size() - position)
            return fail("mold_block", position);
        if (width == 0)
            return fail("itch_length", position);
        const size_t expected = message_length(character(bytes, position));
        if (!expected)
            return fail("unsupported_type", position);
        if (width != expected)
            return fail("itch_length", position);
        out.messages.push_back({position, width});
        position += width;
    }
    if (position != bytes.size())
        return fail("mold_trailing", position);
    return out;
}
Result<Event> decode_itch(Bytes bytes) {
    if (bytes.empty())
        return fail("itch_length");
    const char type = character(bytes, 0);
    const auto width = message_length(type);
    if (!width)
        return fail("unsupported_type");
    if (bytes.size() != width)
        return fail("itch_length");
    // ITCH common header: type 0/1, locate 1/2, tracking 3/2, nanoseconds 5/6.
    const Header header{type, static_cast<Locate>(read_unsigned(bytes, 1, 2)),
                        static_cast<uint16_t>(read_unsigned(bytes, 3, 2)),
                        read_unsigned(bytes, 5, 6)};
    if (header.timestamp_ns >= 86400000000000ULL)
        return fail("field_domain", 5);
    if (type == 'S') {
        const char code = character(bytes, 11);
        if (header.locate != 0 || std::string("OSQMEC").find(code) == std::string::npos)
            return fail("field_domain", 11);
        return Event{header, System{code}};
    }
    if (type == 'R') {
        auto symbol = alpha<8>(bytes, 11);
        if (!header.locate || !symbol)
            return fail("field_domain", 11);
        return Event{header, Directory{*symbol}};
    }
    // A/F/P share fields through byte 35; F adds attribution, P adds a match ID.
    if (type == 'A' || type == 'F' || type == 'P') {
        const auto id = read_unsigned(bytes, 11, 8);
        const char side = character(bytes, 19);
        const auto shares = static_cast<uint32_t>(read_unsigned(bytes, 20, 4));
        auto symbol = alpha<8>(bytes, 24);
        const auto price = static_cast<Price>(read_unsigned(bytes, 32, 4));
        if ((side != 'B' && side != 'S') || !symbol || price > 2000000000U)
            return fail("field_domain", 19);
        if (type == 'P') {
            if (id != 0 || side != 'B')
                return fail("field_domain", 11);
            return Event{header, Trade{id, static_cast<Side>(side), shares, *symbol, price,
                                       read_unsigned(bytes, 36, 8)}};
        }
        std::optional<Attribution> attribution;
        if (type == 'F') {
            attribution = alpha<4>(bytes, 36);
            if (!attribution)
                return fail("field_domain", 36);
        }
        return Event{header, Add{id, static_cast<Side>(side), shares, *symbol, price, attribution}};
    }
    if (type == 'D')
        return Event{header, Delete{read_unsigned(bytes, 11, 8)}};
    if (type == 'E' || type == 'C' || type == 'X') {
        Reduction reduction{read_unsigned(bytes, 11, 8),
                            static_cast<uint32_t>(read_unsigned(bytes, 19, 4)),
                            {},
                            {},
                            {}};
        if (type != 'X')
            reduction.match = read_unsigned(bytes, 23, 8);
        if (type == 'C') {
            const char flag = character(bytes, 31);
            const auto price = static_cast<Price>(read_unsigned(bytes, 32, 4));
            if ((flag != 'Y' && flag != 'N') || price > 2000000000U)
                return fail("field_domain", 31);
            reduction.printable = flag == 'Y';
            reduction.execution_price = price;
        }
        return Event{header, reduction};
    }
    if (type == 'U') {
        const auto price = static_cast<Price>(read_unsigned(bytes, 31, 4));
        if (price > 2000000000U)
            return fail("field_domain", 31);
        return Event{header, Replace{read_unsigned(bytes, 11, 8), read_unsigned(bytes, 19, 8),
                                     static_cast<uint32_t>(read_unsigned(bytes, 27, 4)), price}};
    }
    if (type == 'Q') {
        auto symbol = alpha<8>(bytes, 19);
        const auto price = static_cast<Price>(read_unsigned(bytes, 27, 4));
        const char cross = character(bytes, 39);
        if (!symbol || price > 2000000000U || std::string("OCH").find(cross) == std::string::npos)
            return fail("field_domain", 19);
        return Event{header, Cross{read_unsigned(bytes, 11, 8), *symbol, price,
                                   read_unsigned(bytes, 31, 8), cross}};
    }
    return Event{header, Broken{read_unsigned(bytes, 11, 8)}};
}
Result<std::array<std::byte, 20>> encode_request(SessionId session, Sequence first,
                                                 uint16_t count) {
    if (first == 0 || count == 0 || count > 128)
        return fail("field_domain");
    if (first > std::numeric_limits<uint64_t>::max() - count)
        return fail("counter_overflow");
    std::array<std::byte, 20> out{};
    std::copy(session.begin(), session.end(), out.begin());
    for (unsigned index = 0; index < 8; ++index)
        out[10 + index] = static_cast<std::byte>((first >> (56 - index * 8)) & 255);
    out[18] = static_cast<std::byte>(count >> 8);
    out[19] = static_cast<std::byte>(count & 255);
    return out;
}
} // namespace feed
