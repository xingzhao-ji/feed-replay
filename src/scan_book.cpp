#include "feed/book.hpp"
#include <limits>
#include <stdexcept>
namespace feed {
Quote scan_quote(const std::unordered_map<OrderId, Order> &orders, Locate locate) {
    Quote out;
    for (const auto &[id, order] : orders) {
        (void)id;
        if (order.locate != locate)
            continue;
        auto &best = order.side == Side::buy ? out.bid : out.ask;
        if (!best ||
            (order.side == Side::buy ? order.price > best->price : order.price < best->price))
            best = Level{order.price, order.shares};
        else if (order.price == best->price) {
            if (order.shares > std::numeric_limits<Quantity>::max() - best->quantity)
                throw std::overflow_error("aggregate overflow");
            best->quantity += order.shares;
        }
    }
    return out;
}
} // namespace feed
