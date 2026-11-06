#!/usr/bin/env python3
"""Independent review oracle; standard library only, never imports product code.

Wire integers use explicit byte slices. The book is a plain order dictionary:
every snapshot rescans it and rebuilds all levels. This intentionally differs
from an incrementally maintained C++ price-level implementation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LENGTHS = {"S": 12, "R": 39, "A": 36, "F": 40, "E": 31,
           "C": 36, "X": 23, "D": 19, "U": 35, "P": 44,
           "Q": 40, "B": 19}
DAY = 86_400_000_000_000
MAX_PRICE = 2_000_000_000
MAX_SEQUENCE = (1 << 64) - 1


class Reject(ValueError):
    @property
    def code(self):
        message = str(self)
        categories = {
            "Mold datagram size": "mold_header", "sequence zero": "mold_header",
            "session mismatch": "session_mismatch", "control packet contains bytes": "mold_trailing",
            "sequence interval overflow": "counter_overflow", "truncated block length": "mold_block",
            "truncated block body": "mold_block", "empty ITCH message": "itch_length",
            "unsupported message type": "unsupported_type", "wrong ITCH message length": "itch_length",
            "trailing Mold bytes": "mold_trailing", "instrument not registered": "unknown_instrument",
            "directory locate remapped": "directory_conflict", "symbol has another locate": "directory_conflict",
            "symbol disagrees with locate": "wrong_instrument", "order locate mismatch": "wrong_instrument",
            "day-unique order ID reused": "duplicate_order_id", "day-unique replacement ID reused": "duplicate_order_id",
            "unknown order reference": "missing_order", "over-reduction": "over_reduction",
            "instrument capacity": "resource_limit", "live order capacity": "resource_limit",
            "day ID capacity": "resource_limit", "ITCH event after end of messages": "after_itch_end",
            "packet beyond terminal bound": "terminal_conflict", "terminal before observed high water": "terminal_conflict",
            "conflicting terminals": "terminal_conflict",
        }
        return categories.get(message, "field_domain")


ReferenceError = Reject


def require(condition, message):
    if not condition:
        raise Reject(message)


def uint(data, offset, length):
    return int.from_bytes(data[offset:offset + length], "big", signed=False)


def alpha(data):
    require(all(32 <= x <= 126 for x in data), "non-ASCII alpha field")
    return data.decode("ascii")


def symbol(data):
    value = alpha(data)
    require(value.strip(" ") != "", "empty symbol")
    require(" " not in value.rstrip(" "), "symbol is not right padded")
    return value


def decode_message(data):
    require(bool(data), "empty ITCH message")
    kind = chr(data[0])
    require(kind in LENGTHS, "unsupported message type")
    require(len(data) == LENGTHS[kind], "wrong ITCH message length")
    result = {"type": kind, "locate": uint(data, 1, 2),
              "tracking": uint(data, 3, 2), "time": uint(data, 5, 6)}
    require(result["time"] < DAY, "timestamp outside day")
    if kind == "S":
        result["code"] = alpha(data[11:12])
        require(result["locate"] == 0, "system locate is not zero")
        require(result["code"] in "OSQMEC", "invalid system event")
    elif kind == "R":
        require(result["locate"] != 0, "directory locate is zero")
        result["symbol"] = symbol(data[11:19])
    elif kind in "AFP":
        result.update(id=uint(data, 11, 8), side=alpha(data[19:20]),
                      quantity=uint(data, 20, 4), symbol=symbol(data[24:32]),
                      price=uint(data, 32, 4))
        require(result["side"] in "BS", "invalid order side")
        if kind == "F":
            result["attribution"] = symbol(data[36:40])
        if kind == "P":
            result["match"] = uint(data, 36, 8)
            require(result["id"] == 0 and result["side"] == "B", "invalid current P convention")
    elif kind in "ECXD":
        result["id"] = uint(data, 11, 8)
        if kind != "D":
            result["quantity"] = uint(data, 19, 4)
        if kind in "EC":
            result["match"] = uint(data, 23, 8)
        if kind == "C":
            result.update(printable=alpha(data[31:32]), price=uint(data, 32, 4))
            require(result["printable"] in "YN", "invalid printable flag")
    elif kind == "U":
        result.update(id=uint(data, 11, 8), new_id=uint(data, 19, 8),
                      quantity=uint(data, 27, 4), price=uint(data, 31, 4))
    elif kind == "Q":
        result.update(quantity=uint(data, 11, 8), symbol=symbol(data[19:27]),
                      price=uint(data, 27, 4), match=uint(data, 31, 8),
                      cross_type=alpha(data[39:40]))
        require(result["cross_type"] in "OCH", "invalid cross type")
    elif kind == "B":
        result["match"] = uint(data, 11, 8)
    if "price" in result:
        require(result["price"] <= MAX_PRICE, "price above ITCH maximum")
    return result


def unpack_packet(data, expected_session, maximum_bytes=65507):
    """Preflight the whole envelope/type/length table before semantic decoding."""
    require(20 <= len(data) <= maximum_bytes, "Mold datagram size")
    require(data[:10] == expected_session, "session mismatch")
    sequence, count = uint(data, 10, 8), uint(data, 18, 2)
    require(sequence != 0, "sequence zero")
    if count in (0, 65535):
        require(len(data) == 20, "control packet contains bytes")
        return sequence, count, []
    require(sequence <= MAX_SEQUENCE - count, "sequence interval overflow")
    position, bodies = 20, []
    for _ in range(count):
        require(position + 2 <= len(data), "truncated block length")
        length = uint(data, position, 2)
        position += 2
        require(position + length <= len(data), "truncated block body")
        body = data[position:position + length]
        position += length
        require(bool(body), "empty ITCH message")
        kind = chr(body[0])
        require(kind in LENGTHS, "unsupported message type")
        require(length == LENGTHS[kind], "wrong ITCH message length")
        bodies.append(body)
    require(position == len(data), "trailing Mold bytes")
    return sequence, count, bodies


class MapBook:
    def __init__(self, max_orders=100000, max_ids=1000000, max_instruments=4096):
        self.directory = {}
        self.orders = {}
        self.used_ids = set()
        self.max_orders = max_orders
        self.max_ids = max_ids
        self.max_instruments = max_instruments
        self.itch_ended = False

    def apply(self, event):
        kind, locate = event["type"], event["locate"]
        require(not self.itch_ended, "ITCH event after end of messages")
        if kind == "S":
            self.itch_ended = event["code"] == "C"
            return
        if kind == "R":
            name = event["symbol"]
            if locate in self.directory:
                require(self.directory[locate] == name, "directory locate remapped")
                return
            require(name not in self.directory.values(), "symbol has another locate")
            require(len(self.directory) < self.max_instruments, "instrument capacity")
            self.directory[locate] = name
            return
        require(locate in self.directory, "instrument not registered")
        if "symbol" in event:
            require(event["symbol"] == self.directory[locate], "symbol disagrees with locate")
        if kind in "PQB":
            return
        if kind in "AF":
            order_id = event["id"]
            require(order_id not in self.used_ids, "day-unique order ID reused")
            require(event["quantity"] > 0, "zero displayed add quantity")
            require(len(self.orders) < self.max_orders, "live order capacity")
            require(len(self.used_ids) < self.max_ids, "day ID capacity")
            self.orders[order_id] = {"id": order_id, "locate": locate,
                                     "symbol": event["symbol"], "side": event["side"],
                                     "quantity": event["quantity"], "price": event["price"],
                                     "attribution": event.get("attribution", "")}
            self.used_ids.add(order_id)
            return
        order_id = event["id"]
        require(order_id in self.orders, "unknown order reference")
        old = self.orders[order_id]
        require(locate == old["locate"], "order locate mismatch")
        if kind == "D":
            del self.orders[order_id]
        elif kind in "ECX":
            quantity = event["quantity"]
            require(quantity <= old["quantity"], "over-reduction")
            if quantity == old["quantity"]:
                del self.orders[order_id]
            else:
                self.orders[order_id] = dict(old, quantity=old["quantity"] - quantity)
        elif kind == "U":
            new_id = event["new_id"]
            require(new_id not in self.used_ids, "day-unique replacement ID reused")
            require(event["quantity"] > 0, "zero displayed replacement quantity")
            require(len(self.used_ids) < self.max_ids, "day ID capacity")
            replacement = dict(old, id=new_id, quantity=event["quantity"], price=event["price"])
            del self.orders[order_id]
            self.orders[new_id] = replacement
            self.used_ids.add(new_id)

    def snapshot(self):
        levels = {}
        for order in self.orders.values():
            key = (order["locate"], order["side"], order["price"])
            levels[key] = levels.get(key, 0) + order["quantity"]
        instruments = []
        for locate, name in sorted(self.directory.items()):
            bids = sorted([[p, q] for (l, s, p), q in levels.items() if l == locate and s == "B"], reverse=True)
            asks = sorted([[p, q] for (l, s, p), q in levels.items() if l == locate and s == "S"])
            instruments.append({"locate": locate, "symbol": name, "bids": bids, "asks": asks,
                                "best_bid": bids[0] if bids else None, "best_ask": asks[0] if asks else None})
        return {"orders": [dict(self.orders[k]) for k in sorted(self.orders)],
                "order_count": len(self.orders), "instruments": instruments,
                "used_id_count": len(self.used_ids), "itch_ended": self.itch_ended}


class PrefixOracle:
    """No reorder buffer: future packets advertise high water and are discarded."""
    def __init__(self, session=b"REVIEW0001", **limits):
        self.session = session
        self.book = MapBook(**limits)
        self.next_sequence = 1
        self.high_water = 1
        self.terminal = None
        self.error = None
        self.error_code = None
        self.error_sequence = None
        self.events = []

    def receive(self, data):
        if self.error:
            return self.snapshot()
        try:
            sequence, count, bodies = unpack_packet(data, self.session)
            end = sequence if count in (0, 65535) else sequence + count
            if self.terminal is not None:
                require(end <= self.terminal, "packet beyond terminal bound")
            if count == 65535:
                require(sequence >= self.high_water, "terminal before observed high water")
                require(self.terminal is None or sequence == self.terminal, "conflicting terminals")
                self.terminal = sequence
            self.high_water = max(self.high_water, end)
            if bodies and sequence <= self.next_sequence:
                for number, body in enumerate(bodies, sequence):
                    if number < self.next_sequence:
                        continue
                    self.error_sequence = number
                    event = decode_message(body)
                    self.book.apply(event)
                    self.next_sequence += 1
                    self.events.append({"sequence": number, "event": event,
                                        "book": self.book.snapshot()})
            self.error_sequence = None
        except Reject as error:
            self.error = str(error)
            self.error_code = error.code
            if self.error_sequence is None:
                self.error_sequence = uint(data, 10, 8) if len(data) >= 18 else None
        return self.snapshot()

    def snapshot(self):
        status = "invalid" if self.error else (
            "complete" if self.terminal == self.next_sequence else (
                "gap" if self.next_sequence < self.high_water else "current"))
        return {"next_sequence": self.next_sequence, "high_water": self.high_water,
                "terminal": self.terminal, "status": status,
                "error": self.error, "error_code": self.error_code, "error_sequence": self.error_sequence,
                "book": self.book.snapshot()}


def normalized_event(event):
    result = {"type": event["type"], "locate": event["locate"],
              "tracking": event["tracking"], "timestamp_ns": str(event["time"])}
    kind = event["type"]
    names = {"id": "old_order_id" if kind == "U" else "order_id",
             "new_id": "new_order_id", "quantity": "shares", "match": "match_id",
             "code": "event", "price": "execution_price" if kind == "C" else "price"}
    for key, value in event.items():
        if key in ("type", "locate", "tracking", "time"):
            continue
        output_key = names.get(key, key)
        if key in ("id", "new_id", "match") or (key == "quantity" and kind == "Q"):
            value = str(value)
        elif key in ("symbol", "attribution"):
            value = value.rstrip(" ")
        elif key == "printable":
            value = value == "Y"
        result[output_key] = value
    if kind == "A":
        result["attribution"] = None
    return result


def decode_itch(data: bytes) -> dict:
    return normalized_event(decode_message(data))


def decode_mold(data: bytes) -> dict:
    sequence, count, bodies = unpack_packet(data, data[:10])
    position, messages = 20, []
    for body in bodies:
        position += 2
        messages.append({"offset": position, "length": len(body), "hex": body.hex()})
        position += len(body)
    return {"session_hex": data[:10].hex(), "first_sequence": str(sequence),
            "kind": "heartbeat" if count == 0 else "end" if count == 65535 else "data",
            "messages": messages}


def normalized_snapshot(raw, depth=5):
    instruments = []
    for instrument in raw["instruments"]:
        item = {"locate": instrument["locate"], "symbol": instrument["symbol"].rstrip(" ")}
        item["orders"] = [{"order_id": str(order["id"]), "side": order["side"],
                           "shares": order["quantity"], "price": order["price"],
                           "attribution": order["attribution"].rstrip(" ") or None}
                          for order in raw["orders"] if order["locate"] == item["locate"]]
        for side in ("bids", "asks"):
            item[side] = [{"price": price, "quantity": str(quantity)}
                          for price, quantity in instrument[side][:depth]]
        for output, source in (("best_bid", "bids"), ("best_ask", "asks")):
            best = instrument[source][0] if instrument[source] else None
            item[output] = {"price": best[0], "quantity": str(best[1])} if best else None
        instruments.append(item)
    return {"order_count": raw["order_count"], "seen_id_count": raw["used_id_count"],
            "instruments": instruments}


class ReferenceBook:
    def __init__(self, **limits):
        self.model = MapBook(**limits)

    def apply(self, event: dict) -> None:
        kind = event["type"]
        require(kind in LENGTHS, "unsupported message type")
        internal = {"type": kind, "locate": event["locate"], "tracking": event["tracking"],
                    "time": int(event["timestamp_ns"])}
        names = {"order_id": "id", "old_order_id": "id", "new_order_id": "new_id",
                 "shares": "quantity", "match_id": "match", "event": "code", "execution_price": "price"}
        for key, value in event.items():
            if key in ("type", "locate", "tracking", "timestamp_ns") or value is None:
                continue
            name = names.get(key, key)
            if name in ("id", "new_id", "quantity", "match"):
                value = int(value)
            elif name == "symbol":
                value = value.ljust(8)
            elif name == "attribution":
                value = value.ljust(4)
            elif name == "printable":
                value = "Y" if value else "N"
            internal[name] = value
        require(0 <= internal["time"] < DAY, "timestamp outside day")
        require(0 <= internal["locate"] <= 65535, "locate outside domain")
        require(0 <= internal["tracking"] <= 65535, "tracking outside domain")
        if "price" in internal:
            require(0 <= internal["price"] <= MAX_PRICE, "price above ITCH maximum")
        if "side" in internal:
            require(internal["side"] in ("B", "S"), "invalid order side")
        for key in ("id", "new_id", "match"):
            if key in internal:
                require(0 <= internal[key] <= MAX_SEQUENCE, "ID outside domain")
        if "quantity" in internal:
            require(0 <= internal["quantity"] <= (MAX_SEQUENCE if kind == "Q" else (1 << 32) - 1), "shares outside domain")
        if kind == "S":
            require(internal["locate"] == 0 and internal["code"] in "OSQMEC", "invalid system event")
        if kind == "R":
            require(internal["locate"] != 0, "directory locate is zero")
        if kind == "P":
            require(internal["id"] == 0 and internal["side"] == "B", "invalid current P convention")
        if kind == "Q":
            require(internal["cross_type"] in "OCH", "invalid cross type")
        for key, length in (("symbol", 8), ("attribution", 4)):
            if key in internal:
                encoded = internal[key].encode("ascii")
                require(len(encoded) == length, "alpha field length")
                symbol(encoded)
        self.model.apply(internal)

    def snapshot(self, depth: int = 5) -> dict:
        return normalized_snapshot(self.model.snapshot(), depth)


def reference_sequence(datagrams: list[bytes], session=b"REVIEW0001", **limits) -> dict:
    oracle = PrefixOracle(session=session, **limits)
    states = []
    for datagram in datagrams:
        raw = oracle.receive(datagram)
        states.append({"expected": str(raw["next_sequence"]), "high_water_next": str(raw["high_water"]),
                       "end_next": str(raw["terminal"]) if raw["terminal"] is not None else None,
                       "status": {"current": "ReplayPrefix", "gap": "Gap", "invalid": "Invalid", "complete": "Complete"}[raw["status"]],
                       "live_fresh": False, "quote_usable": False,
                       "error": raw["error_code"],
                       "error_sequence": str(raw["error_sequence"]) if raw["error_sequence"] is not None else None,
                       "book": normalized_snapshot(raw["book"]), "itch_end_seen": raw["book"]["itch_ended"]})
    outcome = "Invalid" if oracle.error else "Complete" if oracle.terminal == oracle.next_sequence else "Incomplete"
    return {"outcome": {"status": outcome, "live_fresh": False, "quote_usable": False},
            "states": states, "events": [{"sequence": str(item["sequence"]),
             "event": normalized_event(item["event"]), "book": normalized_snapshot(item["book"])} for item in oracle.events]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--packets", type=Path)
    parser.add_argument("--events", type=Path, help="JSON array of decoded event dictionaries")
    args = parser.parse_args()
    if args.vectors:
        vectors = json.loads(args.vectors.read_text())["messages"]
        for name, expected in vectors.items():
            raw = bytes.fromhex(expected["hex"])
            assert len(raw) == expected["length"], name
            actual = decode_message(raw)
            for key, value in expected.items():
                if key not in ("hex", "length"):
                    assert actual.get(key) == value, (name, key, actual.get(key), value)
        print(json.dumps({"vectors_checked": len(vectors), "status": "passed"}))
    elif args.events:
        book = ReferenceBook()
        results = []
        for event in json.loads(args.events.read_text()):
            book.apply(event)
            results.append(book.snapshot())
        print(json.dumps(results, sort_keys=True))
    elif args.packets:
        cases = json.loads(args.packets.read_text())["cases"]
        results = []
        for case in cases:
            oracle = PrefixOracle(**case.get("limits", {}))
            states = [oracle.receive(bytes.fromhex(packet)) for packet in case["packets"]]
            results.append({"name": case["name"], "states": states, "events": oracle.events})
        print(json.dumps(results, sort_keys=True, indent=2))
    else:
        parser.error("choose --vectors, --packets, or --events")


if __name__ == "__main__":
    main()
