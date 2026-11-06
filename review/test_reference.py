#!/usr/bin/env python3
"""Executable checks of the independent oracle against literal/manual anchors."""
import json
from pathlib import Path
import unittest

from reference import (DAY, MapBook, PrefixOracle, ReferenceBook, ReferenceError,
                       decode_itch, decode_message, decode_mold, reference_sequence,
                       unpack_packet)

HERE = Path(__file__).resolve().parent
VECTORS = json.loads((HERE/"literal_vectors.json").read_text())["messages"]
RAW = {name:bytes.fromhex(value["hex"]) for name,value in VECTORS.items()}
CASES = json.loads((HERE/"literal_fixtures.json").read_text())["cases"]


def subset(test, actual, expected, context):
    for key,value in expected.items():
        if isinstance(value,dict):
            subset(test,actual[key],value,context+"."+key)
        else:
            test.assertEqual(actual[key],value,(context,key,actual[key],value))


class IndependentReferenceTests(unittest.TestCase):
    def test_all_literal_field_expectations(self):
        for name,expected in VECTORS.items():
            with self.subTest(name=name):
                self.assertEqual(len(RAW[name]),expected["length"])
                actual=decode_message(RAW[name])
                subset(self,actual,{k:v for k,v in expected.items() if k not in ("hex","length")},name)
                self.assertEqual(actual["tracking"],4660)

    def test_every_message_truncation_boundary_and_trailing_octet(self):
        checked=0
        for name,raw in RAW.items():
            for size in range(len(raw)):
                with self.subTest(name=name,size=size),self.assertRaises(ReferenceError):
                    decode_itch(raw[:size])
                checked+=1
            with self.subTest(name=name,extra=True),self.assertRaises(ReferenceError):
                decode_itch(raw+b"\x00")
        self.assertEqual(checked,533)

    def test_literal_multi_message_offsets_and_request(self):
        anchors=json.loads((HERE/"mold_anchors.json").read_text())
        raw=bytes.fromhex(anchors["multi_message"]["hex"])
        actual=decode_mold(raw)
        self.assertEqual(actual["first_sequence"],"1")
        self.assertEqual([[m["offset"],m["length"]] for m in actual["messages"]],[[22,12],[36,39],[77,39]])
        self.assertEqual(len(raw),116)
        request=bytes.fromhex(anchors["request"]["hex"])
        self.assertEqual(len(request),20)
        self.assertEqual(request[:10],b"REVIEW0001")
        self.assertEqual(int.from_bytes(request[10:18],"big"),4)
        self.assertEqual(int.from_bytes(request[18:20],"big"),128)
        for name in ("heartbeat","end"):
            decoded=decode_mold(bytes.fromhex(anchors[name]["hex"]))
            self.assertEqual(decoded["kind"],name)
            self.assertEqual(decoded["first_sequence"],"18")
            self.assertEqual(decoded["messages"],[])

    def test_every_mold_truncation_boundary_is_packet_atomic(self):
        raw=bytes.fromhex(CASES[0]["packets"][0])
        for size in range(len(raw)):
            with self.subTest(size=size):
                oracle=PrefixOracle()
                result=oracle.receive(raw[:size])
                self.assertEqual(result["status"],"invalid")
                self.assertEqual(result["next_sequence"],1)
                self.assertEqual(result["high_water"],1)
                self.assertEqual(oracle.events,[])
                self.assertEqual(oracle.book.directory,{})

    def test_handchecked_sequence_cases(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                oracle=PrefixOracle(**case.get("limits",{}))
                self.assertEqual(len(case["packets"]),len(case["expected"]))
                for index,(packet,expected) in enumerate(zip(case["packets"],case["expected"])):
                    subset(self,oracle.receive(bytes.fromhex(packet)),expected,case["name"]+":"+str(index))

    def test_every_event_against_handchecked_lifecycle(self):
        anchors=json.loads((HERE/"lifecycle_anchors.json").read_text())["anchors"]
        book=MapBook()
        public=ReferenceBook()
        for anchor in anchors:
            event=decode_message(RAW[anchor["message"]])
            book.apply(event)
            public.apply(decode_itch(RAW[anchor["message"]]))
            actual=book.snapshot()
            with self.subTest(sequence=anchor["sequence"]):
                self.assertEqual(actual["order_count"],len(anchor["orders"]))
                self.assertEqual(actual["used_id_count"],anchor["seen_id_count"])
                self.assertEqual(actual["itch_ended"],anchor["itch_end_seen"])
                self.assertEqual([{k:o[k] for k in ("id","locate","side","quantity","price","attribution")} for o in actual["orders"]],anchor["orders"])
                by_locate={i["locate"]:i for i in actual["instruments"]}
                if 1 in by_locate:
                    self.assertEqual(by_locate[1]["bids"],anchor["alpha_bids"])
                    self.assertEqual(by_locate[1]["asks"],anchor["alpha_asks"])
                    self.assertEqual(by_locate[1]["best_bid"],anchor["alpha_bids"][0] if anchor["alpha_bids"] else None)
                    self.assertEqual(by_locate[1]["best_ask"],anchor["alpha_asks"][0] if anchor["alpha_asks"] else None)
                if 2 in by_locate:
                    self.assertEqual(by_locate[2]["bids"],anchor["beta_bids"])
                    self.assertEqual(by_locate[2]["asks"],[])
                self.assertEqual(public.snapshot()["order_count"],len(anchor["orders"]))

    def test_public_normalization_exact_integer_and_metadata(self):
        self.assertEqual(decode_itch(RAW["add_extremes"])["order_id"],"18446744073709551615")
        self.assertEqual(decode_itch(RAW["add_extremes"])["timestamp_ns"],"86399999999999")
        self.assertEqual(decode_itch(RAW["nonprintable"])["printable"],False)
        self.assertEqual(decode_itch(RAW["zero_cross"])["shares"],"0")
        result=reference_sequence([bytes.fromhex(p) for p in CASES[0]["packets"]])
        self.assertEqual(result["states"][-1]["status"],"Complete")
        self.assertEqual(result["states"][-1]["expected"],"18")
        self.assertEqual(result["outcome"],{"status":"Complete","live_fresh":False,"quote_usable":False})
        incomplete=reference_sequence([bytes.fromhex(CASES[0]["packets"][0])])
        self.assertEqual(incomplete["states"][-1]["status"],"ReplayPrefix")
        self.assertEqual(incomplete["outcome"],{"status":"Incomplete","live_fresh":False,"quote_usable":False})
        replaced=result["events"][9]["book"]["instruments"][0]["orders"]
        self.assertIn({"order_id":"9223372036854775809","side":"S","shares":60,"price":100200,"attribution":"ABCD"},replaced)
        final=result["states"][-1]["book"]
        self.assertEqual(final["instruments"][0]["bids"],[{"price":100000,"quantity":"80"},{"price":0,"quantity":"1"}])

    def test_quantity_aggregate_wider_than_uint32(self):
        book=ReferenceBook()
        book.apply(decode_itch(RAW["beta"]))
        book.apply(decode_itch(RAW["add_extremes"]))
        second=decode_itch(RAW["add_extremes"])
        second["order_id"]="9223372036854775808"
        book.apply(second)
        self.assertEqual(book.snapshot()["instruments"][0]["best_bid"],{"price":2000000000,"quantity":"8589934590"})

    def test_replace_consumes_old_id_forever_and_failure_is_atomic(self):
        book=ReferenceBook()
        for name in ("alpha","add_attributed_ask","replace"):
            book.apply(decode_itch(RAW[name]))
        before=book.snapshot()
        for event in (decode_itch(RAW["add_attributed_ask"]),
                      dict(decode_itch(RAW["replace"]),old_order_id="9223372036854775809",new_order_id="18364758544493064720")):
            with self.assertRaises(ReferenceError) as caught:
                book.apply(event)
            self.assertEqual(caught.exception.code,"duplicate_order_id")
            self.assertEqual(book.snapshot(),before)

    def test_zero_price_is_quote_not_absence_and_depth_is_nonmutating(self):
        book=ReferenceBook()
        for name in ("alpha","zero_price"):
            book.apply(decode_itch(RAW[name]))
        self.assertEqual(book.snapshot()["instruments"][0]["best_bid"],{"price":0,"quantity":"1"})
        before=book.snapshot()
        self.assertEqual(book.snapshot(0)["instruments"][0]["bids"],[])
        self.assertEqual(book.snapshot(0)["instruments"][0]["best_bid"],before["instruments"][0]["best_bid"])
        self.assertEqual(book.snapshot(),before)


if __name__=="__main__":
    unittest.main(verbosity=2)
