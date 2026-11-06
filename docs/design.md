# Feed Replay design

Status: approved and implemented contract, 2026-10-23. Root and the fresh protocol reviewer approved this design; root independently verified the reference freeze before authorizing production implementation. Final independent execution review remains pending. The user already authorized routine portfolio builds; this is an internal engineering gate, not a new user-permission request.

## Intent, sources and approach

Build a bounded C++20 displayed-order-book reconstructor for a declared Nasdaq ITCH 5.0 subset, transported over actual loopback UDP with MoldUDP64 message-gap detection and re-request recovery. This adds exchange protocol/domain correctness beyond eventstore-cpp and Strata. Synthetic evidence does not establish personal market-microstructure expertise.

The selected approach is a small stateful protocol receiver with independently checked book semantics. File-only parsing would omit the recovery/currentness behavior that adds value; a full-feed decoder, matching engine or order-entry gateway would broaden the project without supporting this particular claim. The parent explicitly selected C++20, real UDP and this subset; the concrete admission/timeout choices below are engineering defaults for review.

Primary basis, read from the downloaded official PDFs/text and checked against rendered tables:

- [Nasdaq TotalView-ITCH 5.0](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf), data types and §§1.1, 1.2.1, 1.3–1.5. Cached PDF SHA-256 `45e0531d1b4b3beb886e9618b2ab824a5aa9bda3a99c0dff03509306e68aacc3`.
- [MoldUDP64 v1.00](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/moldudp64.pdf), downstream/header/message-block/heartbeat/end/request sections. Cached PDF SHA-256 `96cdd02b8728a441cb970d1371a96e73c01e1edaffb2891d43667e2a0ad8add5`.

Originals remain in `~/.cache/job-apps-runtime/protocol-specs/`; do not vendor the PDFs. This implementation is not full ITCH conformance: trading actions, halt/eligibility information, auctions, statistics, match corrections, snapshots, multicast deployment and other message types are outside scope. Quotes describe reconstructed displayed orders, not tradability, best execution or a matching engine. Unknown types invalidate processing; they are never silently skipped.

## Wire and field contract

All offsets below are zero-based bytes from the ITCH message type; lengths include the type and exclude Mold's two-byte length prefix. Decode unsigned big-endian integers using bounds-checked byte reads, never packed-struct casts. Preserve all 64-bit IDs and 48-bit timestamps exactly.

The common 11-byte header is type `[0:1]`, stock locate `[1:3]`, tracking `[3:5]`, timestamp `[5:11]`. Tracking is parsed/retained but has no sequencing semantics. Require timestamp `< 86,400,000,000,000 ns`; timestamps may repeat or decrease. Message sequence comes only from Mold. No monotone timestamp/order-ID assumption is permitted.

`Price` is `uint32_t` in ten-thousandths, admitted **0 through 2,000,000,000 inclusive**. No floating-point book arithmetic. A symbol is exactly eight bytes, nonempty graphic ASCII followed only by right-padding spaces; normalized display removes trailing spaces, while comparisons retain fixed bytes. Attribution is four bytes under the same nonempty/padding rule. This simple character admission is a project restriction, not validation of Nasdaq's entire symbol/MPID grammar.

| Type | Bytes | Fields after common header | Consumed semantics / validation |
|---|---:|---|---|
| `S` | 12 | event `11/1` | locate must be 0; code one of `O,S,Q,M,E,C`; retain last code. No book clearing or market-eligibility inference. |
| `R` | 39 | symbol `11/8`; remainder `19/20` | nonzero locate; fixed mapping to unique symbol. Other directory metadata is opaque: no enum/business validation or redistribution claim for those fields. |
| `A` | 36 | ID `11/8`, side `19/1`, shares `20/4`, symbol `24/8`, price `32/4` | add unattributed displayed order; side `B/S`, known locate and matching directory symbol. |
| `F` | 40 | A fields plus attribution `36/4` | same add, retaining attribution. |
| `E` | 31 | ID `11/8`, executed shares `19/4`, match `23/8` | reduce displayed quantity at the stored display price; match retained diagnostically, no match ledger. |
| `C` | 36 | E fields, printable `31/1`, execution price `32/4` | printable `Y/N`; validate price; **both values reduce displayed quantity**. Execution price does not change the resting level. |
| `X` | 23 | ID `11/8`, cancelled shares `19/4` | reduce displayed quantity at stored price. |
| `D` | 19 | ID `11/8` | remove all remaining displayed quantity. |
| `U` | 35 | old ID `11/8`, new ID `19/8`, shares `27/4`, price `31/4` | replace with new day-unique ID, new remaining quantity/price, preserving locate, symbol, side and attribution. |
| `P` | 44 | order ID `11/8`, side `19/1`, shares `20/4`, symbol `24/8`, price `32/4`, match `36/8` | explicit displayed-book no-op. Current cached spec requires ID=0 and side=`B`; validate these, known locate/symbol and price. Shares/match may be zero; no volume calculation. |
| `Q` | 40 | shares `11/8`, symbol `19/8`, cross price `27/4`, match `31/8`, cross type `39/1` | explicit displayed-book no-op; known locate/symbol, price range, cross type `O/C/H` in this revision. Zero cross shares are allowed. |
| `B` | 19 | match `11/8` | explicit displayed-book no-op; known nonzero locate. Does **not** restore executed quantity. Match existence/uniqueness is not checked. |

For all stock-dependent messages require nonzero, previously registered locate. `E/C/X/D/U` locate must match the referenced live order. `R` can repeat the identical locate/symbol mapping as an idempotent observation; conflicting locate→symbol or symbol→locate mapping invalidates. Directory records never clear orders. Unsupported directory metadata changes are not compared.

Order IDs cover the full unsigned 64-bit range, including zero; absence is represented with `optional`, not a zero sentinel. IDs introduced by `A/F/U` are unique for the session/day, even after fill, cancel, delete or replacement. New `U` ID cannot equal old ID or any retired ID. Retain bounded seen-ID history; exhausting it fails rather than evicting IDs and silently weakening uniqueness.

**Quantity admission:** `A/F/U` shares must be positive; this is an explicit project restriction because the cited tables do not explicitly prohibit zero. `E/C/X` zero reduction is accepted as a no-op only after validating the reference, locate and remaining shares. Reduction greater than remaining shares fails. Reduction to zero removes the live order; its ID stays seen. No arbitrary positive-price restriction or crossed-book rejection is imposed.

`S` is administrative metadata, not a reset or transport end. `S:E` does not prevent subsequent deletes/broken trades. The first version validates recognized codes but does not enforce a complete daily phase sequence or require `S:O` as the first message. `S:C` sets `itch_end_seen`; a later newly accepted ITCH message is a semantic contradiction. A Mold terminal marker still controls transport completeness. Thus `transport_complete=true` is not a claim of full daily ITCH lifecycle conformance, and `itch_end_seen` is reported separately.

## Book and mutation semantics

Use a global order-ID map, a global bounded seen-ID set, a locate→instrument map plus inverse symbol map, and ordered bid/ask maps of integer price→`uint64_t` aggregate quantity. Bids sort descending, asks ascending. Best quotes are optional, so price zero is distinct from no level. Depth returns up to the requested number of nonzero levels per side; depth 0 returns empty depth arrays while preserving best quotes. Aggregated quantities use checked addition/subtraction; with 100,000 live orders of at most `UINT32_MAX` shares, the declared bound is below `UINT64_MAX`.

Each event validates all references, field domains, resource caps and arithmetic before its semantic mutation. An invalid event cannot partially remove an old order, consume a new seen ID, change levels or alter directory mappings. Replacement at the live-order cap succeeds because the net live count is unchanged. Allocation failure is a fatal operational failure, with no successful/current output publication; process recovery after OOM is not claimed.

Two book implementations share the same public contract: `IndexedBook` maintains levels, and `ScanBook` keeps orders and derives quotes/depth by scanning. The latter is a deliberately straightforward correct baseline, independently checked against the Python reference, not an optimized competing implementation. Both enforce identical admission rules and carry identical observation metadata.

## Datagram framing and accepted prefix

Mold's header is exactly 20 bytes: session `[0:10]`, first/next sequence `[10:18]`, count `[18:20]`. Session is fixed caller-supplied ten bytes (`FRLAB00001` in fixtures); start with an empty book and `expected=1`. CLI session input is exactly ten ASCII alphanumeric bytes, an explicitly narrower project input profile. Arbitrary mid-session starts/snapshots and day rollover are excluded; restart replays the entire capture.

For normal count 1–65534, each block has a big-endian 16-bit data length then exactly that many bytes. Preflight **the entire datagram** before changing book, cursor, high-water or liveness: all prefixes/bounds, exact exhaustion (no trailing bytes), supported type and exact type length. Empty Mold data blocks are permitted by Mold generally but invalid for this ITCH application. A malformed later block or unknown later type applies none of that packet. This preflight is separate from ordered field/domain/semantic validation.

Count 0 is heartbeat; 65535 is end of session; both must have header only. Their sequence denotes the next expected message. Require sequence≥1. Reject before mutation if `first + count` overflows `uint64_t`; accepting a message at `UINT64_MAX` would need an unrepresentable next cursor and is therefore rejected. Markers may carry `UINT64_MAX` as a representable exclusive bound. Every counter increment is checked; no wrapping statistics or resource counters.

State holds `expected` (next contiguous message), `high_water_next` (greatest observed exclusive bound, initially 1), optional `end_next`, validity, and bounded counters/timeline.

1. A fully framed normal packet contributes bound `first+count`; a marker contributes its next sequence. Bounds never regress.
2. If normal `first>expected`, expose the gap and discard its payload after preflight; no reorder buffer. Recover from `expected`, including the discarded future suffix.
3. If packet end≤expected, count old duplicate messages and apply none. Framing/type/length were checked; skipped payload fields/content are **not** authenticated or compared for identity.
4. For overlap `first<expected<end`, count/skip the old prefix and apply only the unseen suffix in order.
5. Decode fields and apply each unseen message; increment `expected` only on success. A field/domain/book failure preserves all earlier successfully accepted messages, including the same packet's prefix, and latches Invalid at that exact sequence. No later data restores validity.
6. A heartbeat can reveal a trailing gap. A heartbeat below `expected` is stale and never lowers a bound or refreshes liveness.
7. End records a terminal exclusive bound. Reject an end below `expected` **or** below previously observed high-water, and any conflicting repeated end. With a known end, reject data/heartbeat beyond it before application. End below the already observed prefix is not accepted as harmless stale termination. Complete only when valid and `expected==high_water_next==end_next`; an early end with missing prefix remains Gap and triggers recovery. Identical repeated end is idempotent.

Preflight structural errors invalidate at the packet's first sequence, without applying any packet message. Session mismatch is likewise invalid. Errors distinguish structural packet rejection from an ordered semantic failure and report the last accepted sequence. No current-book publication follows an invalid state.

## Live UDP, recovery and currentness

Bind IPv4 `127.0.0.1` only. CLI requires distinct listen/source/recovery ports (1–65535); sender and recovery processes bind their specified ports before receiver startup. Accept packets only from `127.0.0.1:source_port` or `127.0.0.1:recovery_port`. Other peers increment an ignored counter and cannot mutate session/liveness or cancel recovery. The same receive socket sends requests to the pinned recovery endpoint. This is peer filtering, not authenticated market data.

Use `recvmsg`, with a default 65,507-byte buffer, inspect `MSG_TRUNC` before decoding, and reject truncated packets from pinned peers. A bounded test option permits a 20–65,507-byte receive buffer to exercise actual kernel truncation. Poll and steady-clock deadlines, not sleeps, drive progress. Evaluate clock deadlines and receive-byte/record budgets on every event-loop iteration and every received datagram, including foreign, duplicate and malformed traffic; do not depend on poll timeouts for enforcement. Signal handlers only set a cancellation flag; the event loop closes its own socket and records incomplete cancellation.

One outstanding recovery cursor at a time. On a gap, immediately request `start=expected`, `count=min(high_water_next-expected,128)` in an exact 20-byte Mold request. A response can contain fewer requested messages; advance to the new cursor and request the remaining range. Repeated/old/future traffic cannot postpone a stalled cursor's retry deadline.

Defaults: retry every 50 ms, at most three sends per stalled cursor (initial + two retries, failure at 150 ms without progress); at most 128 sends for the run; at most 1 s continuously in Gap even if tiny progress occurs; 10 s overall live deadline. Progress resets the stalled-cursor attempt count, not the gap-episode or overall budget. Protocol/application failure cancels further requests. Time is injected into the pure session core for deterministic tests; socket drills exercise real timers. At an exact deadline, deadline failure is evaluated before a newly received packet.

Silence threshold is 1,500 ms. Only newly accepted messages or a valid heartbeat/end whose sequence is at least the current `expected` refresh activity; wholly old data/stale markers/foreign peers do not. Status priority: Invalid/Cancelled/RecoveryFailed, Complete, Gap, Stale, CurrentObserved; before any accepted activity use Awaiting (Stale after the silence threshold). `CurrentObserved` means the accepted prefix reaches the observed high-water and recent eligible activity exists. It cannot prove that an entirely unseen later packet was never lost. A Gap never becomes CurrentObserved just because duplicates arrive. Complete is a terminal claim relative to the observed terminal bound, not a live freshness claim.

## Limits, capture and outputs

| Resource | Hard bound |
|---|---:|
| IPv4 UDP datagram | 65,507 bytes |
| Received/capture bytes per run | 64 MiB, counting malformed/foreign traffic for receive budget |
| Capture records / processed messages | 2,000,000 each |
| Live displayed orders | 100,000 |
| Seen day-unique IDs | 1,000,000 |
| Instruments | 4,096, with locate domain 1–65,535 |
| Stored audit timeline | 10,000 entries; overflow fails explicitly |
| Snapshot depth | default 5, range 0–20 per side/instrument |
| Published JSON/timeline/summary total | 8 MiB; fail, never silently truncate |
| Runtime cache / host free floor | <200 MiB allocated / >2 GiB |

Use resource guard before/during long builds/runs. Everything new is under `projects/feed-replay` or `~/.cache/job-apps-runtime/feed-replay`; reuse existing Clang/Python. No dependency installation is planned. No cloud, external feed, trading account/order, credential use or external submission occurs.

Private capture format `FRCP0001`: eight magic bytes, followed by records of flags `u8` (bit0=`MSG_TRUNC`, other bits zero), payload length `u32` big-endian, then payload bytes (0–65,507). Capture only pinned-peer datagrams, including malformed/truncated records; unrelated-peer evidence is in bounded audit counters. Reject truncated record/file, unknown flags, cap overflow or trailing partial record. Offline replay processes recorded arrival order and reconstructs prefix/gap/end semantics; it does not claim to reproduce wall-clock freshness/retry timing. EOF without terminal completion is explicitly incomplete with `quote_usable=false`, even if gap-free relative to observed high-water. Offline replay never emits `CurrentObserved` or `live_fresh=true`; use `ReplayPrefix`, `Incomplete` or `Complete` with explicit offline scope. Live socket drills are the timing/source-filtering evidence.

Emit `summary.json`, sorted `book.json` and bounded `timeline.jsonl` into a new output directory, publishing the set only after serialization succeeds. Existing capture/output paths must be preserved even under competing runs. Use exclusive capture creation/reservation and atomic no-replace publication (on the tested macOS target, `open` with `O_CREAT|O_EXCL`/no symlink following and `renamex_np(...,RENAME_EXCL)` or an equivalently reviewed primitive); an `exists()` check followed by ordinary open/rename is insufficient. Unsupported platforms must fail explicitly instead of falling back to a racy overwrite. Invalid/incomplete runs can publish explicitly failed diagnostic prefix snapshots (`quote_usable=false`); they are not current quotes. Operational serialization/publication failures return nonzero and publish no partial successful set. No power-loss durability claim.

IDs, nanoseconds, sequences and aggregate quantities are decimal strings in JSON to avoid downstream JavaScript precision loss. Prices and 32-bit shares remain integers; include the price scale 10,000. Snapshots include validity, gap, transport completion, live freshness, last accepted sequence and currentness scope. Quotes/depth and errors must not be interpreted without those flags.

## Verification and measurement

Before production code, a fresh agent reads the official tables and independently authors literal hex fixtures plus a Python order-map/scan reference under the handoff contract in `reference-handoff.md`. The C++ author must not generate those expected bytes/results from the implementation. Golden artifacts/hash ledger are frozen before it exists; later corrections need explicit source-backed review.

Evidence must include every-event reference comparison, adversarial semantic/packet boundaries, sanitizer runs and bounded seeded decoder mutations. Actual sender/receiver/re-request processes must cover middle/final loss, heartbeat-only exposed loss, reordering/overlap/duplicates, partial recovery responses, repeated/conflicting ends, wrong session/peer, kernel truncation, interrupted recovery and exhausted deadlines. Require either exact reference state with honest flags or explicit incomplete/invalid failure; retained timelines show requests and accepted cursors.

Benchmark uses one frozen decoded workload: eight instruments, 2,048 initially live orders, 50,000 following lifecycle events, deterministic seed 20261023, fixed best-quote queries (depth 0, preserving best quotes) after every 1/32/256 events. Generate/validate/freeze it before timings. Both engines get identical events, same query instrument/depth, same validation, exact query outputs and observation flags. The timed book phase excludes parsing/file I/O and includes updates plus the identical quote-query/storage work; preallocate identical result storage. Offline benchmark observations are valid-prefix/gap-free but `live_fresh=false`, never masquerading as live quotes. Compare full output sequences and final sorted books outside the timer, not only a checksum. Reuse bounded in-memory output buffers for each pair rather than retaining per-repetition query vectors. Every-event correctness comparisons use streams of at most 4,096 events/128 live orders, consuming one full snapshot at a time; never persist 50,000 full-book snapshots. The larger benchmark is reference-checked at every scheduled quote (every event for frequency 1) and at final full state. Benchmark budgets apply separately per experiment: at most 100,000 decoded updates, 64 MiB input, 64 MiB total query-result buffers; all timing samples are retained in a small report. These are separate from the live receive/message counters and remain under the same 200 MiB allocated disk-cache cap.

One untimed warmup pair, eight measured pairs per query frequency, alternating engine order AB/BA. Preserve every sample, median and distribution; no result-based resampling or minimum-only speedup. Measure decoder-only and loopback fault/recovery separately and label their scopes. No speed claim before execution, and no production latency/trading-performance extrapolation. Scientific plots/tables may use the already isolated plotting runtime if needed; no new plotting dependency is required for acceptance.

## Approval boundaries and open review calls

Root and fresh reviewer must review: the whole-packet type/length preflight versus ordered field/semantic failure distinction; opaque non-book R metadata; S lifecycle scope; zero-quantity project restriction; terminal-bound contradictions; request/silence clocks; and the fairness/bounds of the independent reference and benchmark. These are explicit decisions, not implementation blanks. After approval, implementation can proceed autonomously using the plan. No qualification is marked closed from this design alone.
