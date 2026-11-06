# Independent fixture/reference handoff

Status: contract for a fresh author; **do not use future C++ product code to produce expected behavior**. Read design.md plus the cached official ITCH/Mold tables. Report any mismatch before freezing files. The parent will approve design after fresh review; the independent fixture/reference must then be complete and hash-frozen before C++ implementation begins.

## Deliverables and interfaces

The independent author owns future `review/` (including `review/literal_fixtures.json`, `review/reference.py`, independent tests and provenance). The implementation author owns C++ and its tests. This planning task creates docs only; the parent assigns actual reference authorship.

1. `review/literal_fixtures.json`: list of `{name, layer, hex, expected}`. `layer` is `itch` or `mold`. Fixtures may declare any exact ten-byte session (the independent author uses `REVIEW0001`; `FRLAB00001` is only a demo example). Hex is literal, hand-authored bytes, with no runtime C++ encoder dependency. Expected includes either exact normalized fields/spans or the stable error category; explanatory notes cite table offsets. Include all 12 supported types. Hand-check at least one complete multi-message datagram and one request.
2. `review/lifecycle.json`: typed event array plus **literal hand-checked** states/quotes for a small two-instrument lifecycle; the independent reference can expand comparison coverage but cannot replace these hand-checked anchors.
3. `review/sequence-cases.json`: ordered datagram hex inputs, injected times and terminal assertions (`expected`, `high_water_next`, optional `end_next`, status, request sequence/count, accepted-prefix book). These pin boundary decisions before implementation.
4. `review/reference.py`: `decode_itch(data: bytes) -> dict`, `decode_mold(data: bytes) -> dict`, and `ReferenceBook.apply(event: dict) -> None`, `ReferenceBook.snapshot(depth: int=5) -> dict`. It uses Python integer/byte operations and a simple order dictionary, recomputing levels by scanning; no C++ subprocess/library calls or copied implementation helper. Semantic errors raise `ReferenceError(code: str)`. A pure `reference_sequence(datagrams: list[bytes]) -> dict` models offline prefix/high-water/end semantics independently; actual UDP timer/socket behavior is checked separately.
5. `review/test_reference.py`: literal anchors and independently derived invariants. Freeze a manifest of all reference/golden source bytes before implementation, and document authorship/spec hashes. Do not infer personal/employer endorsement.

## Normalized JSON contract

All event objects include `type`, `locate` (integer), `tracking` (integer), `timestamp_ns` (decimal string). Event-specific fields:

- R: `symbol` (trimmed string). S: `event` (one character).
- A/F: `order_id` string, `side` B/S, `shares` integer, `symbol` string, `price` integer, `attribution` string or null.
- E/C: `order_id`, `shares`, `match_id` string; C also `printable` boolean and `execution_price` integer.
- X: `order_id`, `shares`. D: `order_id`.
- U: `old_order_id`, `new_order_id`, `shares`, `price`.
- P: `order_id`, `side`, `shares`, `symbol`, `price`, `match_id` (zero ID/B validated).
- Q: `shares` decimal string, `symbol`, `price`, `match_id`, `cross_type`.
- B: `match_id`.

Snapshot is `{order_count, seen_id_count, instruments:[...]}`; instruments sorted by numeric locate, containing `locate`, `symbol`, `orders` sorted numerically by ID and `bids` descending / `asks` ascending. Each order has `order_id`, `side`, `shares`, `price`, `attribution`; levels are `{price, quantity}` with aggregate quantity string. `best_bid` and `best_ask` are a level object or null; depth truncates returned levels only, not state; depth 0 preserves best_bid/best_ask and returns empty bids/asks arrays. Full sorted orders are available for small correctness fixtures; production output can omit orders and still compares full state via test adapter. Do not sort numeric ID strings lexicographically.

Decoded Mold object: `{session_hex, first_sequence: str, kind: data|heartbeat|end, messages: [{offset:int,length:int,hex:str}]}`. Preserve framing order. A re-request is exactly ten session bytes + `u64 first` + `u16 requested_count`; fixtures use count 1–128.

Stable error categories: `mold_header`, `mold_block`, `mold_trailing`, `unsupported_type`, `itch_length`, `field_domain`, `unknown_instrument`, `directory_conflict`, `duplicate_order_id`, `missing_order`, `wrong_instrument`, `over_reduction`, `resource_limit`, `counter_overflow`, `session_mismatch`, `terminal_conflict`, `after_itch_end`, `truncated_datagram`. Error wording is not frozen; category/state preservation is.

## Mandatory adversarial anchors

- Nontrivial big-endian 48/64-bit values, IDs above 2^53, `UINT64_MAX` ID, zero ID, timestamp max-day−1 and day boundary, prices 0/2e9/2e9+1; decreasing timestamps accepted.
- A/F/U zero quantity rejected as project admission; E/C/X zero reduction accepted only with valid references. Same-price aggregation; exact-price-zero best quote; nonprintable C reduces stored-price liquidity; full fill removes order; B never restores; P/Q do not add displayed orders.
- Two instruments with overlapping price ranges; wrong-locate modification; repeated identical R versus conflicting mappings; retired-ID reuse; U ID collision/self-replacement; U preserves F attribution/side/symbol; rejection leaves all state/history unchanged.
- Broken final Mold length/unknown type after a valid first block: zero packet mutation. A well-framed second message with over-reduction: first message accepted, failing sequence remains expected, Invalid latches.
- Future packet discard followed by suffix recovery; overlap; old duplicates with different but structurally valid payload are ignored without an identity-equivalence claim.
- Heartbeat/end reveals missing tail; end precedes final recovery; stale end below accepted/observed high-water; conflicting ends; data beyond known end; identical repeated end; sequence/count overflow. End only completes when the entire prefix is present.
- Limits tested with lower configurable test caps (not million-entry fixtures), but production hard bounds remain those in design. No golden corpus should approach the runtime/storage budget.

The fresh author should challenge this contract rather than conform to a mistake. Root resolves source-backed disagreements before implementation; approved fixture changes retain an explicit provenance note.

The independent author may organize the proposed lifecycle/sequence records inside a single indexed fixture JSON instead of separate files; preserve the declared normalized adapter and publish exact paths in review provenance.

Live/capture/publication layers add operational categories (`recovery_exhausted`, `deadline`, `cancelled`, `capture_format`, `output_limit`, `publication`, `io_error`); the independent wire/book/sequence reference need not implement socket/filesystem behavior.
