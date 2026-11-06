# Independent reference corpus — v1

This directory is reviewer-owned. Its source and expectation files were authored and hash-frozen before C++ product implementation. Do not change expectations to accommodate product behavior; bring any suspected oracle defect back for source-backed review and a versioned correction.

Run without a product binary or third-party dependency:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 projects/feed-replay/review/test_reference.py
```

The suite checks 17 literal ITCH vectors spanning all 12 supported types, 17 hand-checked every-event lifecycle states, 48 explicit arrival-order/semantic/limit cases, 533 message truncation positions, 17 extra-octet message rejections, all 116 truncated prefixes of a full multi-message Mold datagram, and literal multi-message/request framing. It also checks 64-bit aggregation, retired replacement IDs, normalized JSON precision, zero-price best quotes, and depth independence. The normal runtime is a few milliseconds and the corpus is small; no external feed is used.

## Public adapter

Import `review/reference.py` via normal Python module loading (add `review/` to `sys.path`). The interfaces match `docs/reference-handoff.md`:

- `decode_itch(bytes) -> dict`: normalized event fields, decimal strings for IDs/time/Q shares, trimmed display symbols, boolean printable.
- `decode_mold(bytes) -> dict`: fixed header fields and exact message body offsets/lengths; preflights the entire datagram.
- `ReferenceBook(**limits).apply(event)` and `.snapshot(depth=5)`: simple map model and normalized sorted snapshot. Limit keywords are `max_orders`, `max_ids`, `max_instruments`; defaults match design. Semantic rejection raises `ReferenceError` whose `.code` is the stable error category.
- `reference_sequence(list[bytes], session=b'REVIEW0001', **limits)`: normalized per-arrival states plus every accepted event/snapshot. This is the **offline prefix oracle**, not a model of elapsed time, peer pinning, retry effects or socket behavior. `ReplayPrefix` means only that the prefix reaches observed high water. All records explicitly set `live_fresh=false` and `quote_usable=false`; the final `outcome` is `Incomplete` without transport end, `Complete` with recovered terminal prefix, or `Invalid` after rejection.

Use the API incrementally for large workload validation and stream comparison records. Do not retain 50,000 full order snapshots in memory or write them all to disk. The CLI's batch JSON output is intended for this small frozen corpus.

`PrefixOracle`, `MapBook`, and `decode_message` are internal reviewer representations. They use integer IDs, fixed-width symbols and a scan-rebuilt level map. Product code should consume the normalized public adapter or the literal fixture JSON, not copy these implementations.

## Fixture index and independent expectations

- `literal_vectors.json`: manually transcribed message bytes with manually calculated field values and exact lengths. Nontrivial common tracking/time are 0x1234 and 0x0123456789ab. Max ID, max-day timestamp, UINT32 shares, and zero/max prices are explicit literals.
- `mold_anchors.json`: a complete three-message datagram with body offsets 22/36/77 and length 116, heartbeat/end headers, and exact 20-byte re-request for sequence 4/count 128.
- `lifecycle_anchors.json`: hand-checked order content, history counts, both instruments' levels and ITCH-end state after every canonical event. These are literal anchors, not snapshots produced by the reference.
- `literal_fixtures.json`: 48 named packet-arrival cases with explicit hexadecimal datagrams, lower test caps where needed, and hand-authored expected cursor/high-water/end/error/count projections. Session is the ten ASCII bytes `REVIEW0001`.
- `author_fixtures.py`: reviewer-owned corpus assembly provenance. It concatenates manually supplied message hex, length prefixes and header hex, and applies explicit offset mutations. It imports neither reference nor product code and derives no expected result by replaying a model. Running it deterministically reproduces the three assembled JSON files.
- `test_reference.py`: verifies literals, manual lifecycle states, boundaries and invariants against the independent model. The accepted-prefix model cannot validate its own expectations merely by generating them.
- `protocol-design-review.md`: source audit and bounded design verdict. `freeze-v1.json` hashes all reviewed inputs and sources; it excludes itself and interpreter bytecode.

The canonical lifecycle proves C:N lowers an ask from 80 to 50 at its original price, B leaves it at 50, U changes it to 60 at a new price while keeping S/ALPHA/ABCD, E lowers the bid, full X removes ID 0, P and Q leave the displayed book unchanged, D removes the replacement, and an add at price zero remains visible. The 17-event final state is ALPHA bids 80 at 100000 and 1 at 0, and BETA bid 4294967295 at 2000000000; there are no asks, six historical IDs, and three live orders. Transport completes only after Mold end at sequence 18.

The model implements the admitted subset only. It has no match ledger, full directory metadata semantics, tradability model, timestamps monotonicity rule, historical snapshot, order matching, authenticated feed, or live market claim.
