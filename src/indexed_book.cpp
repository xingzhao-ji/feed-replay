#include "feed/book.hpp"
#include <algorithm>
#include <limits>
#include <stdexcept>
namespace feed {
namespace {
Error bad(const char *code) {
    return {code, {}, 0, code};
}
} // namespace
BookCore::BookCore(bool indexed, Limits limits) : indexed_(indexed), limits_(limits) {
    if (limits.max_orders > 100000 || limits.max_ids > 1000000 || limits.max_instruments > 4096)
        throw std::invalid_argument("book limits exceed hard bounds");
    orders_.reserve(std::min<size_t>(limits.max_orders, 4096));
    seen_.reserve(std::min<size_t>(limits.max_ids, 4096));
}
std::optional<Error> BookCore::validate_level_change(const Order &order, int64_t delta) const {
    if (!indexed_)
        return {};
    const auto &instrument = instruments_.at(order.locate);
    auto check = [&](const auto &levels) -> std::optional<Error> {
        auto it = levels.find(order.price);
        const uint64_t before = it == levels.end() ? 0 : it->second;
        if (delta >= 0 &&
            static_cast<uint64_t>(delta) > std::numeric_limits<uint64_t>::max() - before)
            return bad("counter_overflow");
        if (delta < 0 && static_cast<uint64_t>(-delta) > before)
            return bad("over_reduction");
        return {};
    };
    return order.side == Side::buy ? check(instrument.bids) : check(instrument.asks);
}
void BookCore::level_change(const Order &order, int64_t delta) {
    if (!indexed_ || delta == 0)
        return;
    auto &instrument = instruments_.at(order.locate);
    auto change = [&](auto &levels) {
        if (delta > 0)
            levels[order.price] += static_cast<uint64_t>(delta);
        else {
            auto it = levels.find(order.price);
            it->second -= static_cast<uint64_t>(-delta);
            if (it->second == 0)
                levels.erase(it);
        }
    };
    if (order.side == Side::buy)
        change(instrument.bids);
    else
        change(instrument.asks);
}
std::optional<Error> BookCore::apply(const Event &event) {
    // Event is the typed result of successful decode_itch; book validates stateful semantics.
    if (ended_)
        return bad("after_itch_end");
    const auto locate = event.header.locate;
    if (auto s = std::get_if<System>(&event.body)) {
        last_system_event_ = s->event;
        ended_ = s->event == 'C';
        return {};
    }
    if (auto d = std::get_if<Directory>(&event.body)) {
        if (auto existing = instruments_.find(locate); existing != instruments_.end()) {
            if (existing->second.symbol != d->symbol)
                return bad("directory_conflict");
            return {};
        }
        if (symbols_.contains(d->symbol))
            return bad("directory_conflict");
        if (instruments_.size() >= limits_.max_instruments)
            return bad("resource_limit");
        instruments_.emplace(locate, Instrument{d->symbol, {}, {}});
        symbols_.emplace(d->symbol, locate);
        return {};
    }
    const auto instrument = instruments_.find(locate);
    if (instrument == instruments_.end())
        return bad("unknown_instrument");
    if (auto t = std::get_if<Trade>(&event.body)) {
        if (t->symbol != instrument->second.symbol)
            return bad("wrong_instrument");
        return {};
    }
    if (auto c = std::get_if<Cross>(&event.body)) {
        if (c->symbol != instrument->second.symbol)
            return bad("wrong_instrument");
        return {};
    }
    if (std::holds_alternative<Broken>(event.body))
        return {};
    if (auto a = std::get_if<Add>(&event.body)) {
        if (a->symbol != instrument->second.symbol)
            return bad("wrong_instrument");
        if (seen_.contains(a->id))
            return bad("duplicate_order_id");
        if (!a->shares)
            return bad("field_domain");
        if (orders_.size() >= limits_.max_orders || seen_.size() >= limits_.max_ids)
            return bad("resource_limit");
        const Order next{a->id, locate, a->symbol, a->side, a->shares, a->price, a->attribution};
        if (auto error = validate_level_change(next, next.shares))
            return error;
        orders_.emplace(next.id, next);
        seen_.insert(next.id);
        level_change(next, next.shares);
        return {};
    }
    OrderId id = 0;
    if (auto r = std::get_if<Reduction>(&event.body))
        id = r->id;
    else if (auto d = std::get_if<Delete>(&event.body))
        id = d->id;
    else
        id = std::get<Replace>(event.body).old_id;
    auto existing = orders_.find(id);
    if (existing == orders_.end())
        return bad("missing_order");
    const Order old = existing->second;
    if (old.locate != locate)
        return bad("wrong_instrument");
    if (std::holds_alternative<Delete>(event.body)) {
        level_change(old, -static_cast<int64_t>(old.shares));
        orders_.erase(existing);
        return {};
    }
    if (auto r = std::get_if<Reduction>(&event.body)) {
        if (r->shares > old.shares)
            return bad("over_reduction");
        if (auto error = validate_level_change(old, -static_cast<int64_t>(r->shares)))
            return error;
        level_change(old, -static_cast<int64_t>(r->shares));
        if (r->shares == old.shares)
            orders_.erase(existing);
        else
            existing->second.shares -= r->shares;
        return {};
    }
    const auto &r = std::get<Replace>(event.body);
    if (seen_.contains(r.new_id))
        return bad("duplicate_order_id");
    if (!r.shares)
        return bad("field_domain");
    if (seen_.size() >= limits_.max_ids)
        return bad("resource_limit");
    Order next = old;
    next.id = r.new_id;
    next.shares = r.shares;
    next.price = r.price;
    if (old.price == next.price) {
        if (auto error = validate_level_change(old, static_cast<int64_t>(next.shares) - old.shares))
            return error;
    } else {
        if (auto error = validate_level_change(old, -static_cast<int64_t>(old.shares)))
            return error;
        if (auto error = validate_level_change(next, next.shares))
            return error;
    }
    // All semantic rejection paths precede mutation. Allocation failure is fatal, not recoverable.
    orders_.erase(existing);
    orders_.emplace(next.id, next);
    seen_.insert(next.id);
    level_change(old, -static_cast<int64_t>(old.shares));
    level_change(next, next.shares);
    return {};
}
Result<Quote> BookCore::quote(Locate locate) const {
    auto it = instruments_.find(locate);
    if (it == instruments_.end())
        return bad("unknown_instrument");
    if (!indexed_)
        return scan_quote(orders_, locate);
    Quote q;
    if (!it->second.bids.empty()) {
        auto [p, n] = *it->second.bids.begin();
        q.bid = Level{p, n};
    }
    if (!it->second.asks.empty()) {
        auto [p, n] = *it->second.asks.begin();
        q.ask = Level{p, n};
    }
    return q;
}
BookSnapshot BookCore::snapshot(size_t depth, bool include_orders) const {
    if (depth > 20)
        throw std::invalid_argument("depth outside 0..20");
    BookSnapshot out;
    out.order_count = orders_.size();
    out.seen_id_count = seen_.size();
    out.itch_end_seen = ended_;
    out.last_system_event = last_system_event_;
    std::map<Locate, size_t> positions;
    for (const auto &[locate, instrument] : instruments_) {
        InstrumentSnapshot view{
            locate, instrument.symbol, {}, {}, {}, std::get<Quote>(quote(locate))};
        if (indexed_) {
            for (const auto &[p, n] : instrument.bids) {
                if (view.bids.size() == depth)
                    break;
                view.bids.push_back({p, n});
            }
            for (const auto &[p, n] : instrument.asks) {
                if (view.asks.size() == depth)
                    break;
                view.asks.push_back({p, n});
            }
        } else if (depth) {
            // Hard admission bounds prove totals <= 100000 * UINT32_MAX < UINT64_MAX.
            std::map<Price, Quantity> bids, asks;
            for (const auto &[id, order] : orders_) {
                (void)id;
                if (order.locate == locate)
                    (order.side == Side::buy ? bids : asks)[order.price] += order.shares;
            }
            for (auto it = bids.rbegin(); it != bids.rend() && view.bids.size() < depth; ++it)
                view.bids.push_back({it->first, it->second});
            for (auto it = asks.begin(); it != asks.end() && view.asks.size() < depth; ++it)
                view.asks.push_back({it->first, it->second});
        }
        positions.emplace(locate, out.instruments.size());
        out.instruments.push_back(std::move(view));
    }
    if (include_orders) {
        for (const auto &[id, order] : orders_) {
            (void)id;
            out.instruments[positions.at(order.locate)].orders.push_back(order);
        }
        for (auto &i : out.instruments)
            std::sort(i.orders.begin(), i.orders.end(),
                      [](const Order &a, const Order &b) { return a.id < b.id; });
    }
    return out;
}
} // namespace feed
