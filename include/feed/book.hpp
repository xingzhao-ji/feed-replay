#pragma once
#include "types.hpp"
#include <functional>
#include <map>
#include <unordered_map>
#include <unordered_set>
namespace feed {
struct Order {
    OrderId id;
    Locate locate;
    Symbol symbol;
    Side side;
    uint32_t shares;
    Price price;
    std::optional<Attribution> attribution;
};
struct Level {
    Price price;
    Quantity quantity;
    bool operator==(const Level &) const = default;
};
struct Quote {
    std::optional<Level> bid, ask;
    bool operator==(const Quote &) const = default;
};
struct InstrumentSnapshot {
    Locate locate;
    Symbol symbol;
    std::vector<Order> orders;
    std::vector<Level> bids, asks;
    Quote quote;
};
struct BookSnapshot {
    size_t order_count = 0, seen_id_count = 0;
    std::vector<InstrumentSnapshot> instruments;
    bool itch_end_seen = false;
    std::optional<char> last_system_event;
};
class IBook {
  public:
    virtual ~IBook() = default;
    virtual std::optional<Error> apply(const Event &) = 0;
    virtual Result<Quote> quote(Locate) const = 0;
    virtual BookSnapshot snapshot(size_t depth, bool include_orders) const = 0;
};
// Both engines share order admission/lifecycle semantics. Only IndexedBook maintains levels.
class BookCore : public IBook {
  public:
    std::optional<Error> apply(const Event &) override;
    Result<Quote> quote(Locate) const override;
    BookSnapshot snapshot(size_t, bool) const override;

  protected:
    BookCore(bool indexed, Limits limits);

  private:
    struct Instrument {
        Symbol symbol;
        std::map<Price, Quantity, std::greater<Price>> bids;
        std::map<Price, Quantity> asks;
    };
    bool indexed_;
    Limits limits_;
    bool ended_ = false;
    std::optional<char> last_system_event_;
    std::map<Locate, Instrument> instruments_;
    std::map<Symbol, Locate> symbols_;
    std::unordered_map<OrderId, Order> orders_;
    std::unordered_set<OrderId> seen_;
    std::optional<Error> validate_level_change(const Order &, int64_t) const;
    void level_change(const Order &, int64_t);
};
class IndexedBook final : public BookCore {
  public:
    explicit IndexedBook(Limits limits = {}) : BookCore(true, limits) {}
};
class ScanBook final : public BookCore {
  public:
    explicit ScanBook(Limits limits = {}) : BookCore(false, limits) {}
};
Quote scan_quote(const std::unordered_map<OrderId, Order> &, Locate);
} // namespace feed
