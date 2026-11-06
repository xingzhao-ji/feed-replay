#include "feed/io.hpp"
#include <cstdio>
#include <fstream>
#include <unistd.h>
namespace feed {
namespace {
struct Json {
    std::string data;
    uint64_t limit;
    explicit Json(uint64_t n) : limit(n) {}
    void raw(std::string_view s) {
        if (s.size() > limit - data.size())
            throw IoFailure({"output_limit", {}, 0, "JSON output byte cap"});
        data.append(s);
    }
    void text(std::string_view s) {
        raw("\"");
        for (unsigned char c : s) {
            if (c == '"' || c == '\\') {
                char b[2] = {'\\', static_cast<char>(c)};
                raw(std::string_view(b, 2));
            } else if (c < 32) {
                char b[7];
                std::snprintf(b, sizeof(b), "\\u%04x", c);
                raw(b);
            } else {
                const char b = static_cast<char>(c);
                raw(std::string_view(&b, 1));
            }
        }
        raw("\"");
    }
    void number(uint64_t n) {
        raw(std::to_string(n));
    }
    void id(uint64_t n) {
        text(std::to_string(n));
    }
    void boolean(bool b) {
        raw(b ? "true" : "false");
    }
};
template <size_t N> std::string trim(std::array<char, N> s) {
    std::string out(s.begin(), s.end());
    while (!out.empty() && out.back() == ' ')
        out.pop_back();
    return out;
}
void level(Json &j, const std::optional<Level> &l) {
    if (!l) {
        j.raw("null");
        return;
    }
    j.raw("{\"price\":");
    j.number(l->price);
    j.raw(",\"quantity\":");
    j.id(l->quantity);
    j.raw("}");
}
void write_file(const std::filesystem::path &p, const std::string &s) {
    std::ofstream f;
    f.exceptions(std::ios::badbit | std::ios::failbit);
    f.open(p, std::ios::binary);
    f.write(s.data(), static_cast<std::streamsize>(s.size()));
    f.close();
}
std::string summary(const RunOutcome &o, uint64_t cap) {
    Json j(cap);
    const auto &v = o.view;
    j.raw("{\"schema_version\":1,\"scope\":");
    j.text(o.offline ? "offline_replay" : "loopback_udp");
    j.raw(",\"engine\":");
    j.text(o.engine);
    j.raw(",\"status\":");
    j.text(v.status);
    j.raw(",\"expected\":");
    j.id(v.expected);
    j.raw(",\"last_accepted_sequence\":");
    j.id(v.expected - 1);
    j.raw(",\"high_water_next\":");
    j.id(v.high_water_next);
    j.raw(",\"end_next\":");
    if (v.end_next)
        j.id(*v.end_next);
    else
        j.raw("null");
    j.raw(",\"transport_complete\":");
    j.boolean(v.status == "Complete");
    j.raw(",\"live_fresh\":");
    j.boolean(v.live_fresh);
    j.raw(",\"quote_usable\":");
    j.boolean(v.quote_usable);
    j.raw(",\"itch_end_seen\":");
    j.boolean(v.book.itch_end_seen);
    j.raw(",\"last_system_event\":");
    if (v.book.last_system_event)
        j.text(std::string(1, *v.book.last_system_event));
    else
        j.raw("null");
    j.raw(",\"snapshot_depth\":");
    j.number(o.depth);
    j.raw(",\"orders_included\":");
    j.boolean(o.include_orders);
    j.raw(",\"price_scale\":10000,\"error\":");
    if (v.error) {
        j.raw("{\"code\":");
        j.text(v.error->code);
        j.raw(",\"sequence\":");
        if (v.error->sequence)
            j.id(*v.error->sequence);
        else
            j.raw("null");
        j.raw(",\"offset\":");
        j.number(v.error->offset);
        j.raw(",\"detail\":");
        j.text(v.error->detail);
        j.raw("}");
    } else
        j.raw("null");
    j.raw(",\"counters\":{");
    bool first = true;
    auto field = [&](const char *name, uint64_t n) {
        if (!first)
            j.raw(",");
        first = false;
        j.text(name);
        j.raw(":");
        j.id(n);
    };
    field("datagrams", o.counters.datagrams);
    field("bytes", o.counters.bytes);
    field("messages", o.counters.messages);
    field("accepted", o.counters.accepted);
    field("old_messages", o.counters.old_messages);
    field("future_packets", o.counters.future_packets);
    field("requests_generated", o.counters.requests);
    field("udp_received", o.transport.received);
    field("udp_received_bytes", o.transport.received_bytes);
    field("foreign", o.transport.foreign);
    field("requests_sent", o.transport.requests_sent);
    j.raw("}}\n");
    return j.data;
}
} // namespace
std::string book_json(const BookSnapshot &b, uint64_t cap) {
    Json j(cap);
    j.raw("{\"order_count\":");
    j.number(b.order_count);
    j.raw(",\"seen_id_count\":");
    j.number(b.seen_id_count);
    j.raw(",\"instruments\":[");
    bool first = true;
    for (const auto &i : b.instruments) {
        if (!first)
            j.raw(",");
        first = false;
        j.raw("{\"locate\":");
        j.number(i.locate);
        j.raw(",\"symbol\":");
        j.text(trim(i.symbol));
        j.raw(",\"orders\":[");
        bool first_order = true;
        for (const auto &o : i.orders) {
            if (!first_order)
                j.raw(",");
            first_order = false;
            j.raw("{\"order_id\":");
            j.id(o.id);
            j.raw(",\"side\":");
            j.text(std::string(1, static_cast<char>(o.side)));
            j.raw(",\"shares\":");
            j.number(o.shares);
            j.raw(",\"price\":");
            j.number(o.price);
            j.raw(",\"attribution\":");
            if (o.attribution)
                j.text(trim(*o.attribution));
            else
                j.raw("null");
            j.raw("}");
        }
        j.raw("],\"bids\":[");
        for (size_t k = 0; k < i.bids.size(); ++k) {
            if (k)
                j.raw(",");
            level(j, i.bids[k]);
        }
        j.raw("],\"asks\":[");
        for (size_t k = 0; k < i.asks.size(); ++k) {
            if (k)
                j.raw(",");
            level(j, i.asks[k]);
        }
        j.raw("],\"best_bid\":");
        level(j, i.quote.bid);
        j.raw(",\"best_ask\":");
        level(j, i.quote.ask);
        j.raw("}");
    }
    j.raw("]}\n");
    return j.data;
}
std::optional<Error> write_report(const std::filesystem::path &destination, const RunOutcome &out,
                                  uint64_t cap) {
    namespace fs = std::filesystem;
    fs::path temp;
    try {
        if (cap > 8 * 1024 * 1024 || destination.filename().empty())
            throw IoFailure({"publication", {}, 0, "invalid output path/cap"});
        const auto book = book_json(out.view.book, cap);
        const auto info = summary(out, cap - book.size());
        Json timeline(cap - book.size() - info.size());
        for (const auto &a : out.audit) {
            timeline.raw("{\"time_ns\":");
            timeline.id(a.time_ns);
            timeline.raw(",\"event\":");
            timeline.text(a.event);
            timeline.raw(",\"expected\":");
            timeline.id(a.expected);
            timeline.raw(",\"high_water_next\":");
            timeline.id(a.high_water_next);
            timeline.raw(",\"count\":");
            timeline.id(a.count);
            timeline.raw("}\n");
        }
        std::string pattern = destination.string() + ".tmp-XXXXXX";
        std::vector<char> name(pattern.begin(), pattern.end());
        name.push_back(0);
        char *created = ::mkdtemp(name.data());
        if (!created)
            throw IoFailure({"publication", {}, 0, "cannot stage output directory"});
        temp = created;
        write_file(temp / "book.json", book);
        write_file(temp / "summary.json", info);
        write_file(temp / "timeline.jsonl", timeline.data);
#if defined(__APPLE__)
        if (::renamex_np(temp.c_str(), destination.c_str(), RENAME_EXCL) != 0)
            throw IoFailure(
                {"publication", {}, 0, "destination exists or exclusive publish failed"});
#else
        throw IoFailure({"publication",
                         {},
                         0,
                         "atomic no-replace publication not implemented on this platform"});
#endif
        return {};
    } catch (const IoFailure &e) {
        if (!temp.empty()) {
            std::error_code ignored;
            fs::remove_all(temp, ignored);
        }
        return e.error;
    } catch (const std::exception &) {
        if (!temp.empty()) {
            std::error_code ignored;
            fs::remove_all(temp, ignored);
        }
        return Error{"publication", {}, 0, "output serialization/write failed"};
    }
}
} // namespace feed
