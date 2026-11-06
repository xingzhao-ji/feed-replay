#!/usr/bin/env python3
"""Review-owned literal corpus assembly. Does not import the reference/product.

Every message byte, length prefix, header sequence and count below is literal.
Assembly only removes whitespace/concatenates. Mutations are explicit byte
offset edits of those checked literals, not encode/decode round trips.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VECTORS = json.loads((HERE / "literal_vectors.json").read_text())["messages"]
RAW = {name: bytes.fromhex(value["hex"]).hex() for name, value in VECTORS.items()}
PREFIX = {"start": "000c", "alpha": "0027", "beta": "0027", "add_bid": "0024",
          "add_zero_id": "0024", "add_attributed_ask": "0028", "add_extremes": "0024",
          "nonprintable": "0024", "break": "0013", "replace": "0023", "execute": "001f",
          "cancel": "0017", "trade": "002c", "zero_cross": "0028", "delete": "0013",
          "zero_price": "0024", "end_messages": "000c"}
SESSION = "52455649455730303031"  # REVIEW0001, ten ASCII bytes


def header(sequence_hex, count_hex):
    assert len(sequence_hex) == 16 and len(count_hex) == 4
    return SESSION + sequence_hex + count_hex


def packet(sequence_hex, count_hex, *names):
    return header(sequence_hex, count_hex) + "".join(PREFIX[name] + RAW[name] for name in names)


def changed(name, offset, hex_bytes):
    raw = bytearray.fromhex(RAW[name])
    edit = bytes.fromhex(hex_bytes)
    raw[offset:offset + len(edit)] = edit
    return raw.hex()


def single(sequence_hex, name, body=None):
    return header(sequence_hex, "0001") + PREFIX[name] + (body or RAW[name])


def expect(next_sequence, high_water, status="current", terminal=None, count=None, error=None, error_sequence=None):
    result = {"next_sequence": next_sequence, "high_water": high_water, "status": status,
              "terminal": terminal, "error_code": error, "error_sequence": error_sequence}
    if count is not None:
        result["book"] = {"order_count": count}
    return result


P1 = packet("0000000000000001", "0003", "start", "alpha", "beta")
P2 = packet("0000000000000004", "0004", "add_bid", "add_zero_id", "add_attributed_ask", "add_extremes")
P3 = packet("0000000000000008", "0003", "nonprintable", "break", "replace")
P4 = packet("000000000000000b", "0004", "execute", "cancel", "trade", "zero_cross")
P5 = packet("000000000000000f", "0003", "delete", "zero_price", "end_messages")
END18 = header("0000000000000012", "ffff")
HEART18 = header("0000000000000012", "0000")

CASES = []


def case(name, packets, expected, **kwargs):
    CASES.append({"name": name, "packets": packets, "expected": expected, **kwargs})


case("complete_lifecycle", [P1, P2, P3, P4, P5, END18],
     [expect(4,4,count=0), expect(8,8,count=4), expect(11,11,count=4), expect(15,15,count=3),
      expect(18,18,count=3), expect(18,18,"complete",18,3)])
case("future_discard_pending_end_partial_recovery", [P1,P3,P1,P2,END18,P3,P4,P5,HEART18,END18],
     [expect(4,4),expect(4,11,"gap"),expect(4,11,"gap"),expect(8,11,"gap"),expect(8,18,"gap",18),
      expect(11,18,"gap",18),expect(15,18,"gap",18),expect(18,18,"complete",18),
      expect(18,18,"complete",18),expect(18,18,"complete",18)])
OVERLAP = packet("0000000000000002","0003","alpha","beta","add_bid")
case("overlap_unseen_suffix", [P1,OVERLAP], [expect(4,4,count=0),expect(5,5,count=1)])
case("trailing_heartbeat_gap", [P1,header("0000000000000005","0000"),single("0000000000000004","add_bid")],
     [expect(4,4),expect(4,5,"gap"),expect(5,5,count=1)])
case("stale_heartbeat_does_not_regress", [P1,header("0000000000000002","0000")], [expect(4,4),expect(4,4)])
case("terminal_before_highwater", [P1,P3,header("000000000000000a","ffff")],
     [expect(4,4),expect(4,11,"gap"),expect(4,11,"invalid",error="terminal_conflict",error_sequence=10)])
case("terminal_before_accepted", [P1,header("0000000000000003","ffff")],
     [expect(4,4),expect(4,4,"invalid",error="terminal_conflict",error_sequence=3)])
case("conflicting_terminal", [P1,END18,header("0000000000000011","ffff")],
     [expect(4,4),expect(4,18,"gap",18),expect(4,18,"invalid",18,error="terminal_conflict",error_sequence=17)])
case("data_beyond_pending_terminal", [P1,header("0000000000000005","ffff"),P2],
     [expect(4,4),expect(4,5,"gap",5),expect(4,5,"invalid",5,error="terminal_conflict",error_sequence=4)])
case("heartbeat_beyond_terminal", [P1,header("0000000000000004","ffff"),header("0000000000000005","0000")],
     [expect(4,4),expect(4,4,"complete",4),expect(4,4,"invalid",4,error="terminal_conflict",error_sequence=5)])
case("unrepresentable_exclusive_bound", [P1,single("ffffffffffffffff","start")],
     [expect(4,4),expect(4,4,"invalid",error="counter_overflow",error_sequence=18446744073709551615)])
case("largest_representable_marker", [header("ffffffffffffffff","0000")],
     [expect(1,18446744073709551615,"gap")])
case("sequence_zero", [header("0000000000000000","0000")],
     [expect(1,1,"invalid",error="mold_header",error_sequence=0)])
case("wrong_session", ["58455649455730303031"+P1[20:]],
     [expect(1,1,"invalid",error="session_mismatch",error_sequence=1)])
BAD_FINAL = header("0000000000000004","0002")+PREFIX["add_bid"]+RAW["add_bid"]+"0024"+RAW["add_zero_id"][:-2]
case("framing_failure_whole_packet_atomic", [P1,BAD_FINAL],
     [expect(4,4),expect(4,4,"invalid",count=0,error="mold_block",error_sequence=4)])
UNKNOWN_FINAL = header("0000000000000004","0002")+PREFIX["add_bid"]+RAW["add_bid"]+"0001 5a".replace(" ","")
case("unknown_final_type_whole_packet_atomic", [P1,UNKNOWN_FINAL],
     [expect(4,4),expect(4,4,"invalid",count=0,error="unsupported_type",error_sequence=4)])
WRONG_LENGTH = header("0000000000000004","0002")+PREFIX["add_bid"]+RAW["add_bid"]+"0001 41".replace(" ","")
case("wrong_final_type_length_whole_packet_atomic", [P1,WRONG_LENGTH],
     [expect(4,4),expect(4,4,"invalid",count=0,error="itch_length",error_sequence=4)])
OVER_REDUCE = header("0000000000000004","0002")+PREFIX["add_bid"]+RAW["add_bid"]+PREFIX["execute"]+changed("execute",19,"00000065")
case("semantic_failure_preserves_same_packet_prefix", [P1,OVER_REDUCE,P2],
     [expect(4,4),expect(5,6,"invalid",count=1,error="over_reduction",error_sequence=5),
      expect(5,6,"invalid",count=1,error="over_reduction",error_sequence=5)])
ALTERED_OLD = single("0000000000000001","start",changed("start",5,"ffffffffffff"))
case("old_semantically_invalid_payload_not_rechecked", [P1,ALTERED_OLD], [expect(4,4),expect(4,4)])
case("old_unknown_type_still_rejected", [P1,header("0000000000000001","0001")+"0001 5a".replace(" ","")],
     [expect(4,4),expect(4,4,"invalid",error="unsupported_type",error_sequence=1)])

for name, offset, value, error in [
    ("zero_add",20,"00000000","field_domain"),
    ("bad_side",19,"58","field_domain"),
    ("price_above_max",32,"77359401","field_domain"),
    ("timestamp_at_day_boundary",5,"4e94914f0000","field_domain"),
    ("unknown_locate",1,"0003","unknown_instrument"),
    ("symbol_mismatch",24,"4245544120202020","wrong_instrument"),
]:
    case(name,[P1,single("0000000000000004","add_bid",changed("add_bid",offset,value))],
         [expect(4,4),expect(4,5,"invalid",count=0,error=error,error_sequence=4)])
case("zero_price_best_bid",[P1,single("0000000000000004","zero_price")], [expect(4,4),expect(5,5,count=1)])
case("directory_idempotent",[P1,single("0000000000000004","alpha")], [expect(4,4),expect(5,5,count=0)])
case("directory_locate_conflict",[P1,single("0000000000000004","alpha",changed("alpha",11,"4245544120202020"))],
     [expect(4,4),expect(4,5,"invalid",error="directory_conflict",error_sequence=4)])
case("directory_symbol_conflict",[P1,single("0000000000000004","alpha",changed("alpha",1,"0003"))],
     [expect(4,4),expect(4,5,"invalid",error="directory_conflict",error_sequence=4)])
case("wrong_instrument_reduction",[P1,P2,single("0000000000000008","execute",changed("execute",1,"0002"))],
     [expect(4,4),expect(8,8),expect(8,9,"invalid",count=4,error="wrong_instrument",error_sequence=8)])
for kind in ("execute","nonprintable","cancel"):
    case("zero_reduction_"+kind,[P1,P2,single("0000000000000008",kind,changed(kind,19,"00000000"))],
         [expect(4,4),expect(8,8),expect(9,9,count=4)])
case("zero_reduction_missing_reference",[P1,single("0000000000000004","execute",changed("execute",19,"00000000"))],
     [expect(4,4),expect(4,5,"invalid",count=0,error="missing_order",error_sequence=4)])
FULL_FILL = single("0000000000000005","execute",changed("execute",19,"00000064"))
case("fill_then_retired_id_reuse",[P1,single("0000000000000004","add_bid"),FULL_FILL,single("0000000000000006","add_bid")],
     [expect(4,4),expect(5,5,count=1),expect(6,6,count=0),expect(6,7,"invalid",count=0,error="duplicate_order_id",error_sequence=6)])
for name, value in [("replace_self","fedcba9876543210"),("replace_live_collision","0102030405060708")]:
    case(name,[P1,P2,single("0000000000000008","replace",changed("replace",19,value))],
         [expect(4,4),expect(8,8),expect(8,9,"invalid",count=4,error="duplicate_order_id",error_sequence=8)])
case("zero_replace_preserves_old",[P1,P2,single("0000000000000008","replace",changed("replace",27,"00000000"))],
     [expect(4,4),expect(8,8),expect(8,9,"invalid",count=4,error="field_domain",error_sequence=8)])
case("itch_end_then_new_message",[P1,single("0000000000000004","end_messages"),single("0000000000000005","break")],
     [expect(4,4),expect(5,5),expect(5,6,"invalid",error="after_itch_end",error_sequence=5)])
case("live_order_cap",[P1,P2],[expect(4,4),expect(5,8,"invalid",count=1,error="resource_limit",error_sequence=5)],limits={"max_orders":1})
case("seen_id_cap_retains_history",[P1,single("0000000000000004","add_bid"),FULL_FILL,single("0000000000000006","add_zero_id")],
     [expect(4,4),expect(5,5),expect(6,6,count=0),expect(6,7,"invalid",count=0,error="resource_limit",error_sequence=6)],limits={"max_ids":1})
case("instrument_cap",[P1],[expect(3,4,"invalid",count=0,error="resource_limit",error_sequence=3)],limits={"max_instruments":1})
case("replacement_at_live_cap",[P1,single("0000000000000004","add_attributed_ask"),single("0000000000000005","replace")],
     [expect(4,4),expect(5,5,count=1),expect(6,6,count=1)],limits={"max_orders":1})
case("empty_message",[header("0000000000000001","0001")+"0000"],
     [expect(1,1,"invalid",error="itch_length",error_sequence=1)])
case("trailing_bytes",[P1+"00"],[expect(1,1,"invalid",error="mold_trailing",error_sequence=1)])
case("heartbeat_has_bytes",[header("0000000000000001","0000")+"00"],[expect(1,1,"invalid",error="mold_trailing",error_sequence=1)])
case("short_header",[SESSION],[expect(1,1,"invalid",error="mold_header")])

ORDER = ["start","alpha","beta","add_bid","add_zero_id","add_attributed_ask","add_extremes",
         "nonprintable","break","replace","execute","cancel","trade","zero_cross","delete","zero_price","end_messages"]
# Fully hand-checked order content at each accepted event. Aliases only expand
# immutable metadata from the literal add vectors; quantities/prices are literal.
SPECS = [[],[],[],[("bid",100,100000)],[("zero",40,100000),("bid",100,100000)],
         [("zero",40,100000),("bid",100,100000),("ask",80,100100)],
         [("zero",40,100000),("bid",100,100000),("ask",80,100100),("max",4294967295,2000000000)],
         [("zero",40,100000),("bid",100,100000),("ask",50,100100),("max",4294967295,2000000000)],
         [("zero",40,100000),("bid",100,100000),("ask",50,100100),("max",4294967295,2000000000)],
         [("zero",40,100000),("bid",100,100000),("replacement",60,100200),("max",4294967295,2000000000)],
         [("zero",40,100000),("bid",80,100000),("replacement",60,100200),("max",4294967295,2000000000)],
         [("bid",80,100000),("replacement",60,100200),("max",4294967295,2000000000)],
         [("bid",80,100000),("replacement",60,100200),("max",4294967295,2000000000)],
         [("bid",80,100000),("replacement",60,100200),("max",4294967295,2000000000)],
         [("bid",80,100000),("max",4294967295,2000000000)],
         [("pricezero",1,0),("bid",80,100000),("max",4294967295,2000000000)],
         [("pricezero",1,0),("bid",80,100000),("max",4294967295,2000000000)]]
IDS = {"zero":0,"bid":72623859790382856,"ask":18364758544493064720,
       "replacement":9223372036854775809,"max":18446744073709551615,"pricezero":66}
SEEN = [0,0,0,1,2,3,4,4,4,5,5,5,5,5,5,6,6]
LEVELS = [([],[]),([],[]),([],[]),([[100000,100]],[]),([[100000,140]],[]),
          ([[100000,140]],[[100100,80]]),([[100000,140]],[[100100,80]]),
          ([[100000,140]],[[100100,50]]),([[100000,140]],[[100100,50]]),
          ([[100000,140]],[[100200,60]]),([[100000,120]],[[100200,60]]),
          ([[100000,80]],[[100200,60]]),([[100000,80]],[[100200,60]]),
          ([[100000,80]],[[100200,60]]),([[100000,80]],[]),([[100000,80],[0,1]],[]),([[100000,80],[0,1]],[])]
ANCHORS = []
for index, (name, specs) in enumerate(zip(ORDER,SPECS)):
    orders = [{"id":IDS[alias],"locate":2 if alias=="max" else 1,
               "side":"S" if alias in ("ask","replacement") else "B",
               "quantity":quantity,"price":price,
               "attribution":"ABCD" if alias in ("ask","replacement") else ""}
              for alias,quantity,price in specs]
    ANCHORS.append({"sequence":index+1,"message":name,"orders":sorted(orders,key=lambda o:o["id"]),
                    "seen_id_count":SEEN[index],"alpha_bids":LEVELS[index][0],"alpha_asks":LEVELS[index][1],
                    "beta_bids":[[2000000000,4294967295]] if index>=6 else [],
                    "itch_end_seen":index==16})

(HERE/"literal_fixtures.json").write_text(json.dumps({"session":"REVIEW0001","cases":CASES},indent=2)+"\n")
(HERE/"lifecycle_anchors.json").write_text(json.dumps({"events":ORDER,"anchors":ANCHORS},indent=2)+"\n")
(HERE/"mold_anchors.json").write_text(json.dumps({
    "multi_message":{"hex":P1,"first_sequence":"1","kind":"data","spans":[[22,12],[36,39],[77,39]]},
    "request":{"hex":SESSION+"00000000000000040080","first_sequence":"4","count":128},
    "heartbeat":{"hex":HEART18,"first_sequence":"18","kind":"heartbeat"},
    "end":{"hex":END18,"first_sequence":"18","kind":"end"}},indent=2)+"\n")
print(json.dumps({"literal_vectors":len(VECTORS),"packet_cases":len(CASES),"lifecycle_anchors":len(ANCHORS)}))
