// Test-only normalized adapter. Expected bytes/behavior live in frozen review/.
#include "feed/book.hpp"
#include "feed/codec.hpp"
#include "feed/session.hpp"
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
using namespace feed;
namespace {
std::string quote(std::string s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\')
            out += '\\';
        out += static_cast<char>(c);
    }
    return out + '"';
}
template <size_t N> std::string text(std::array<char, N> a) {
    std::string s(a.begin(), a.end());
    while (!s.empty() && s.back() == ' ')
        s.pop_back();
    return quote(s);
}
std::string id(uint64_t n) {
    return quote(std::to_string(n));
}
std::vector<std::byte> unhex(const std::string &line) {
    std::vector<std::byte> b;
    std::string s;
    for (unsigned char c : line)
        if (!std::isspace(c))
            s += static_cast<char>(c);
    if (s.size() % 2)
        throw std::runtime_error("odd hex");
    for (size_t j = 0; j < s.size(); j += 2)
        b.push_back(static_cast<std::byte>(std::stoul(s.substr(j, 2), nullptr, 16)));
    return b;
}
std::string hex(Bytes b) {
    std::ostringstream s;
    for (auto v : b)
        s << std::hex << std::setw(2) << std::setfill('0') << std::to_integer<unsigned>(v);
    return s.str();
}
void error(const Error &e) {
    std::cout << "{\"error\":" << quote(e.code) << "}\n";
}
void level(const std::optional<Level> &v) {
    if (!v)
        std::cout << "null";
    else
        std::cout << "{\"price\":" << v->price << ",\"quantity\":" << id(v->quantity) << '}';
}
void snapshot(const BookSnapshot &b) {
    std::cout << "{\"order_count\":" << b.order_count << ",\"seen_id_count\":" << b.seen_id_count
              << ",\"instruments\":[";
    for (size_t j = 0; j < b.instruments.size(); ++j) {
        const auto &i = b.instruments[j];
        if (j)
            std::cout << ',';
        std::cout << "{\"locate\":" << i.locate << ",\"symbol\":" << text(i.symbol)
                  << ",\"orders\":[";
        for (size_t k = 0; k < i.orders.size(); ++k) {
            const auto &o = i.orders[k];
            if (k)
                std::cout << ',';
            std::cout << "{\"order_id\":" << id(o.id)
                      << ",\"side\":" << quote(std::string(1, static_cast<char>(o.side)))
                      << ",\"shares\":" << o.shares << ",\"price\":" << o.price
                      << ",\"attribution\":" << (o.attribution ? text(*o.attribution) : "null")
                      << '}';
        }
        std::cout << "],\"bids\":[";
        for (size_t k = 0; k < i.bids.size(); ++k) {
            if (k)
                std::cout << ',';
            level(i.bids[k]);
        }
        std::cout << "],\"asks\":[";
        for (size_t k = 0; k < i.asks.size(); ++k) {
            if (k)
                std::cout << ',';
            level(i.asks[k]);
        }
        std::cout << "],\"best_bid\":";
        level(i.quote.bid);
        std::cout << ",\"best_ask\":";
        level(i.quote.ask);
        std::cout << '}';
    }
    std::cout << "]}";
}
void view(const View &v, const Effects &e) {
    std::cout << "{\"expected\":" << id(v.expected)
              << ",\"high_water_next\":" << id(v.high_water_next)
              << ",\"end_next\":" << (v.end_next ? id(*v.end_next) : "null")
              << ",\"status\":" << quote(v.status)
              << ",\"live_fresh\":" << (v.live_fresh ? "true" : "false")
              << ",\"quote_usable\":" << (v.quote_usable ? "true" : "false")
              << ",\"error\":" << (v.error ? quote(v.error->code) : "null")
              << ",\"error_sequence\":"
              << (v.error && v.error->sequence ? id(*v.error->sequence) : "null") << ",\"book\":";
    snapshot(v.book);
    std::cout << ",\"itch_end_seen\":" << (v.book.itch_end_seen ? "true" : "false")
              << ",\"requests\":[";
    for (size_t j = 0; j < e.requests.size(); ++j) {
        if (j)
            std::cout << ',';
        const auto &r = e.requests[j];
        std::cout << "{\"first\":" << id(r.first) << ",\"count\":" << r.count
                  << ",\"hex\":" << quote(hex(r.wire)) << '}';
    }
    std::cout << "]}\n";
}
void event(const Event &e) {
    const auto &h = e.header;
    std::cout << "{\"type\":" << quote(std::string(1, h.type)) << ",\"locate\":" << h.locate
              << ",\"tracking\":" << h.tracking << ",\"timestamp_ns\":" << id(h.timestamp_ns);
    std::visit(
        [&](const auto &v) {
            using T = std::decay_t<decltype(v)>;
            if constexpr (std::is_same_v<T, System>)
                std::cout << ",\"event\":" << quote(std::string(1, v.event));
            else if constexpr (std::is_same_v<T, Directory>)
                std::cout << ",\"symbol\":" << text(v.symbol);
            else if constexpr (std::is_same_v<T, Add>)
                std::cout << ",\"order_id\":" << id(v.id)
                          << ",\"side\":" << quote(std::string(1, static_cast<char>(v.side)))
                          << ",\"shares\":" << v.shares << ",\"symbol\":" << text(v.symbol)
                          << ",\"price\":" << v.price
                          << ",\"attribution\":" << (v.attribution ? text(*v.attribution) : "null");
            else if constexpr (std::is_same_v<T, Reduction>) {
                std::cout << ",\"order_id\":" << id(v.id) << ",\"shares\":" << v.shares;
                if (v.match)
                    std::cout << ",\"match_id\":" << id(*v.match);
                if (v.printable)
                    std::cout << ",\"printable\":" << (*v.printable ? "true" : "false");
                if (v.execution_price)
                    std::cout << ",\"execution_price\":" << *v.execution_price;
            } else if constexpr (std::is_same_v<T, Delete>)
                std::cout << ",\"order_id\":" << id(v.id);
            else if constexpr (std::is_same_v<T, Replace>)
                std::cout << ",\"old_order_id\":" << id(v.old_id)
                          << ",\"new_order_id\":" << id(v.new_id) << ",\"shares\":" << v.shares
                          << ",\"price\":" << v.price;
            else if constexpr (std::is_same_v<T, Trade>)
                std::cout << ",\"order_id\":" << id(v.id)
                          << ",\"side\":" << quote(std::string(1, static_cast<char>(v.side)))
                          << ",\"shares\":" << v.shares << ",\"symbol\":" << text(v.symbol)
                          << ",\"price\":" << v.price << ",\"match_id\":" << id(v.match);
            else if constexpr (std::is_same_v<T, Cross>)
                std::cout << ",\"shares\":" << id(v.shares) << ",\"symbol\":" << text(v.symbol)
                          << ",\"price\":" << v.price << ",\"match_id\":" << id(v.match)
                          << ",\"cross_type\":" << quote(std::string(1, v.cross_type));
            else if constexpr (std::is_same_v<T, Broken>)
                std::cout << ",\"match_id\":" << id(v.match);
        },
        e.body);
    std::cout << "}\n";
}
} // namespace
int main(int argc, char **argv) {
    try {
        if (argc < 2)
            return 2;
        const std::string mode = argv[1];
        if (mode == "request") {
            if (argc != 5)
                return 2;
            SessionId session{};
            std::string s = argv[2];
            if (s.size() != 10)
                return 2;
            for (size_t n = 0; n < 10; ++n)
                session[n] = static_cast<std::byte>(s[n]);
            auto r = encode_request(session, std::stoull(argv[3]),
                                    static_cast<uint16_t>(std::stoul(argv[4])));
            if (auto e = std::get_if<Error>(&r))
                error(*e);
            else
                std::cout << quote(hex(std::get<std::array<std::byte, 20>>(r))) << '\n';
            return 0;
        }
        std::unique_ptr<IBook> book;
        size_t depth = 5;
        if (mode == "book") {
            if (argc != 7)
                return 2;
            Limits limits;
            limits.max_orders = std::stoull(argv[3]);
            limits.max_ids = std::stoull(argv[4]);
            limits.max_instruments = std::stoull(argv[5]);
            depth = std::stoull(argv[6]);
            if (std::string(argv[2]) == "indexed")
                book = std::make_unique<IndexedBook>(limits);
            else
                book = std::make_unique<ScanBook>(limits);
        }
        std::unique_ptr<Session> session;
        uint64_t now = 0;
        if (mode == "session") {
            if (argc != 6)
                return 2;
            Limits limits;
            limits.max_orders = std::stoull(argv[3]);
            limits.max_ids = std::stoull(argv[4]);
            limits.max_instruments = std::stoull(argv[5]);
            book = std::make_unique<IndexedBook>(limits);
            SessionConfig config;
            config.limits = limits;
            config.live = std::string(argv[2]) == "live";
            const std::string name = "REVIEW0001";
            for (size_t j = 0; j < 10; ++j)
                config.session[j] = static_cast<std::byte>(name[j]);
            session = std::make_unique<Session>(*book, config);
        }
        std::string line;
        while (std::getline(std::cin, line)) {
            if (session && !line.empty() && line[0] == '@') {
                now = std::stoull(line.substr(1));
                auto e = session->on_time(now);
                view(session->view(now), e);
                continue;
            }
            if (session && line == "!cancel") {
                session->cancel();
                view(session->view(now), {});
                continue;
            }
            auto bytes = unhex(line);
            if (mode == "itch") {
                auto r = decode_itch(bytes);
                if (auto e = std::get_if<Error>(&r))
                    error(*e);
                else
                    event(std::get<Event>(r));
            } else if (mode == "mold") {
                auto r = decode_frame(bytes);
                if (auto e = std::get_if<Error>(&r))
                    error(*e);
                else {
                    auto &f = std::get<Frame>(r);
                    std::cout << "{\"session_hex\":" << quote(hex(f.session))
                              << ",\"first_sequence\":" << id(f.first) << ",\"kind\":"
                              << quote(f.kind == FrameKind::data        ? "data"
                                       : f.kind == FrameKind::heartbeat ? "heartbeat"
                                                                        : "end")
                              << ",\"messages\":[";
                    for (size_t j = 0; j < f.messages.size(); ++j) {
                        auto v = f.messages[j];
                        if (j)
                            std::cout << ',';
                        std::cout << "{\"offset\":" << v.offset << ",\"length\":" << v.length
                                  << ",\"hex\":"
                                  << quote(hex(Bytes(bytes).subspan(v.offset, v.length))) << '}';
                    }
                    std::cout << "]}\n";
                }
            } else if (mode == "book") {
                auto r = decode_itch(bytes);
                std::optional<Error> e;
                if (auto p = std::get_if<Error>(&r))
                    e = *p;
                else
                    e = book->apply(std::get<Event>(r));
                std::cout << "{\"error\":" << (e ? quote(e->code) : "null") << ",\"book\":";
                snapshot(book->snapshot(depth, true));
                std::cout << "}\n";
            } else if (session) {
                auto e = session->ingest(bytes, now);
                view(session->view(now), e);
            } else
                return 2;
        }
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 2;
    }
}
