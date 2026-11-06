#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <variant>
#include <vector>
namespace feed {
using Bytes = std::span<const std::byte>;
using Sequence = uint64_t;
using OrderId = uint64_t;
using Quantity = uint64_t;
using Price = uint32_t;
using Locate = uint16_t;
using Symbol = std::array<char, 8>;
using Attribution = std::array<char, 4>;
using SessionId = std::array<std::byte, 10>;
struct Error {
    std::string code;
    std::optional<Sequence> sequence{};
    size_t offset = 0;
    std::string detail;
};
template <class T> using Result = std::variant<T, Error>;
enum class Side : char { buy = 'B', sell = 'S' };
struct Header {
    char type;
    Locate locate;
    uint16_t tracking;
    uint64_t timestamp_ns;
};
struct Directory {
    Symbol symbol;
};
struct System {
    char event;
};
struct Add {
    OrderId id;
    Side side;
    uint32_t shares;
    Symbol symbol;
    Price price;
    std::optional<Attribution> attribution;
};
struct Reduction {
    OrderId id;
    uint32_t shares;
    std::optional<uint64_t> match;
    std::optional<bool> printable;
    std::optional<Price> execution_price;
};
struct Delete {
    OrderId id;
};
struct Replace {
    OrderId old_id, new_id;
    uint32_t shares;
    Price price;
};
struct Trade {
    OrderId id;
    Side side;
    uint32_t shares;
    Symbol symbol;
    Price price;
    uint64_t match;
};
struct Cross {
    uint64_t shares;
    Symbol symbol;
    Price price;
    uint64_t match;
    char cross_type;
};
struct Broken {
    uint64_t match;
};
struct Event {
    Header header;
    std::variant<Directory, System, Add, Reduction, Delete, Replace, Trade, Cross, Broken> body;
};
struct Limits {
    size_t max_orders = 100000, max_ids = 1000000, max_instruments = 4096, max_messages = 2000000,
           max_timeline = 10000;
    uint64_t max_bytes = 64ULL * 1024 * 1024;
};
} // namespace feed
