# Feed Replay implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans for the parent-selected implementation agent, or superpowers:subagent-driven-development if root explicitly delegates independent tasks. Steps use checkboxes. Root and fresh design approval plus a frozen independent reference are required before product code. Do not ask the user to reauthorize routine work already authorized.

**Goal:** execute a bounded ITCH displayed-book reconstruction and MoldUDP64 recovery experiment with independent protocol/book evidence and a fair measured baseline.

**Architecture:** separate checked byte decoding, book engines, a clock-injected sequence/recovery state machine, a loopback socket shell and bounded capture/report tooling. An independently authored Python reference/literal corpus precedes C++ implementation. The benchmark uses decoded events and identical quote observations for the indexed and scanning engines.

**Tech stack:** C++20/Clang standard library plus POSIX IPv4 UDP/poll/recvmsg; existing Python/pytest for reference and orchestration. No new service, cloud, production feed or dependency installation.

**Spec:** [design.md](design.md), [independent handoff](reference-handoff.md), and cached official PDFs identified there.

## Global constraints

- Own only `projects/feed-replay` and runtime `~/.cache/job-apps-runtime/feed-replay`; current workspace has no Git repository. Use directory isolation and source/evidence hash checkpoints; do not invent commit/worktree history.
- Fixed caller-supplied ten-byte session, empty book, `expected=1`; no mid-session snapshot/restart shortcut.
- Exactly `S,R,A,F,E,C,X,D,U,P,Q,B`, exact lengths and consumed/omitted fields in design. No unknown-type skip, float price, timestamp monotonicity or zero-price rejection.
- Packet structural preflight before any packet mutation; ordered field/book failure preserves prior accepted prefix and permanently invalidates the session.
- 65,507-byte datagrams; 64 MiB received/capture bytes; 2,000,000 capture records/processed messages; 100,000 live orders; 1,000,000 seen IDs; 4,096 instruments; 10,000 timeline entries; default depth 5/range 0–20; published output total≤8 MiB.
- Runtime allocated cache<200 MiB and free disk>2 GiB, checked before/during long commands. No heavy downloads or modifications to shared environments.
- Recovery: count≤128, 50 ms interval, three sends per stalled cursor, failure at 150 ms; run sends≤128, continuous gap≤1 s, overall live≤10 s. Silence threshold 1,500 ms. Exact-deadline failure precedes packet processing.
- No personal-mastery, universal-job-prerequisite, authenticated-feed, full-ITCH-conformance, production-latency or reliability claim.

## Review focus

1. A malformed/unknown trailing block must not partially apply an earlier block; a semantic error in a well-framed second message must preserve the first. Task 1 and Task 3 test both boundaries.
2. Replacement and retired-ID reuse must preserve directory/side/attribution and last-valid state; zero price must remain distinct from absence. Task 2 tests atomic rejection and zero-valued quotes.
3. Heartbeat/end can expose missing tail; stale/conflicting terminal bounds and arithmetic overflow must never certify completeness. Task 3 pins exact cursors/status/requests.
4. Duplicate/foreign traffic must not mask staleness or extend retry deadlines; actual kernel truncation and partial recovery responses must be exercised. Task 4 covers real socket behavior.
5. File EOF/output/cap failure and benchmark shortcuts must not become successful/current artifacts or incomparable timing samples. Task 5 tests publication; Task 6 compares every output/flag and retains every timing sample.

## Files and public types

```text
include/feed/types.hpp       scalar aliases, Event alternatives, Error, Limits, snapshot types
include/feed/codec.hpp       Frame/MessageSpan and checked wire/request API
include/feed/book.hpp        IBook, IndexedBook, ScanBook
include/feed/session.hpp     SessionConfig, View, Effects, pure clock-injected session
include/feed/io.hpp          bounded capture/socket/report interfaces
src/codec.cpp               Mold/ITCH decoding, exact length/type preflight
src/indexed_book.cpp        order/history/directory plus maintained levels
src/scan_book.cpp           same semantics, quote/depth by scanning orders
src/session.cpp            accepted-prefix, terminal bounds, retries/currentness
src/udp.cpp                loopback binding, pinning, recvmsg, poll, cancellation
src/capture.cpp            FRCP0001 bounded reader/writer
src/report.cpp             bounded JSON serialization/publication
src/main.cpp               strict CLI
src/benchmark.cpp          frozen workload runner and fair paired measurements
tests/codec_tests.cpp       independent literal wire fixtures/adversarial bounds
tests/book_tests.cpp        exact lifecycle and rejection invariants
tests/session_tests.cpp     injected-clock sequence/recovery/currentness cases
tests/test_cli.py           real subprocess artifact contracts
tests/test_udp.py           separate actual sender/re-request/receiver processes
tests/test_parity.py        every-event normalized reference parity
review/*                   independent-author-owned literals/reference/provenance
scripts/udp_fixture.py      bounded synthetic sender/re-request server
scripts/workload.py         deterministic workload construction/reference validation
scripts/verify.py           reproducible verification/drill orchestration
scripts/benchmark_report.py all-sample tables/report, no unmeasured claims
scripts/guard.py            scoped resource guard
Makefile                   build/test/sanitize/verify/benchmark targets
docs/progress.md            observed RED/GREEN and execution ledger
evidence/*                 bounded logs/results/timelines/manifests/report
```

All interfaces are in namespace `feed`. `Bytes=std::span<const std::byte>`, `Sequence/OrderId/Quantity=uint64_t`, `Price=uint32_t`, `Locate=uint16_t`; `Symbol=array<char,8>`, `Attribution=array<char,4>`. `Result<T>` is a C++20 wrapper over `variant<T,Error>`; no C++23 `std::expected` requirement. Error stores stable category, optional sequence, byte offset and a bounded explanatory string. Categories/output fields match reference-handoff.md.

`Header {char type; Locate locate; uint16_t tracking; uint64_t timestamp_ns;}`. `Event {Header header; variant<Directory,System,Add,Reduction,Delete,Replace,Trade,Cross,Broken> body;}`. Alternative fields follow the exact normalized handoff; Reduction carries optional match/printable/execution-price fields for E/C versus X. Fixed arrays preserve wire padding; JSON displays trimmed strings. `Limits` defaults to hard values above; tests may lower caps, never raise production hard caps.

`Order {OrderId id; Locate locate; Symbol symbol; Side side; uint32_t shares; Price price; optional<Attribution> attribution;}`. `Level {Price price; Quantity quantity;}`; `Quote {optional<Level> bid,ask;}`; `BookSnapshot` includes count/history count, directory and sorted instrument/order/level data. Production serialization may omit full order lists; parity adapters must expose them for correctness tests.

### Task 0 — independent oracle freeze and design acceptance

**Owners/files:** fresh reviewer owns `review/`; implementation agent owns docs only until approval.

- [ ] Root and fresh reviewer resolve the decisions listed at the end of design.md; retain the verdict and any explicit amendment.
- [ ] Fresh author completes literal raw bytes, hand-checked lifecycle anchors, independent decoder/order-map/sequence model and their own tests under `review/`. Exact file layout may follow the reviewer's existing work; publish a single adapter/provenance index.
- [ ] Run the independent tests without any C++ product binary. Record command/count/source-spec hashes and freeze SHA-256 of all golden/reference files.
- [ ] Confirm no product encoder/decoder supplied golden bytes/expected results. Preserve the freeze manifest; reviewed corrections get a new explicit version, never silent expected-output edits.
- [ ] Root approves this contract and assigns implementation method. Only then begin Task 1. No user permission question is required.

### Task 1 — checked wire decoder and request codec

**Files:** types.hpp, codec.hpp, codec.cpp, codec_tests.cpp, Makefile, guard.py.

**Interfaces:**

```cpp
struct MessageSpan {size_t offset; uint16_t length;};
enum class FrameKind {data,heartbeat,end};
struct Frame {array<byte,10> session; Sequence first; FrameKind kind;
              uint16_t count; vector<MessageSpan> messages;};
Result<Frame> decode_frame(Bytes); // spans refer to caller-owned datagram
Result<Event> decode_itch(Bytes);
Result<array<byte,20>> encode_request(array<byte,10>, Sequence first, uint16_t count);
```

- [ ] Write tests consuming independently frozen literal hex: every supported type and nontrivial 48/64-bit fields must equal exact normalized values; request bytes equal independently handwritten 20-byte vector.
- [ ] Add `trailing_bad_block_applies_nothing` preflight anchors, count/length/trailing/empty-block/unknown-type/type-length errors, exact price/timestamp boundaries, decreasing timestamps accepted, zero ID/large IDs and P/Q/C enum rules. Test all offsets immediately before/after required length.
- [ ] Build deliberate unimplemented function bodies and run `make test-codec`; record meaningful RED failures, not merely missing dependencies.
- [ ] Implement checked byte reads/preflight/field decoding and bounded typed results. Validate sequence addition before arithmetic. No book/session code in codec.
- [ ] Run `make test-codec` to GREEN. Add seeded byte truncation/mutation cases under ASan/UBSan: all inputs produce bounded error or a valid normalized object, no crash/out-of-bounds. Retain seed/count and any discovered regression.
- [ ] Record source checkpoint and observed commands in progress.md. Resource guard applies to builds from this first task.

### Task 2 — indexed book and independent scan baseline

**Files:** book.hpp, indexed_book.cpp, scan_book.cpp, book_tests.cpp, test_parity.py.

**Interfaces:** `IBook::apply(const Event&) -> optional<Error>`, `quote(Locate) const -> Result<Quote>`, `snapshot(size_t depth,bool include_orders) const -> BookSnapshot`; constructors consume `Limits`. Both implementations expose exactly these methods. Depth 0 preserves best quotes and emits empty depth arrays.

- [ ] Write literal lifecycle assertions from the frozen independent anchors: quantities/price levels after each event, two instruments, same-price aggregation, price-zero best bid/ask, F→U attribution/side/symbol preservation, nonprintable C reduction at stored price, P/Q/B no displayed mutation.
- [ ] Add atomic-rejection tests for missing/wrong-locate reference, over-reduction, duplicate live/retired ID, self/colliding U, conflicting R, add/seen-ID/instrument cap exhaustion. Snapshot before and after rejection must match exactly, including seen IDs. U at full live capacity must succeed.
- [ ] Add explicit zero policies: A/F/U zero shares rejected; E/C/X zero reduction accepted with valid reference and rejected for a missing reference. Validate uint64 aggregate arithmetic and prove the hard-cap bound; test checked-add helper at its overflow boundary.
- [ ] Run `make test-book` with stubs; record RED. Implement IndexedBook with semantic preflight before mutation and no fake state clipping or ID-history eviction.
- [ ] Implement ScanBook independently against the same tests/reference, deriving levels/quotes by scanning orders. Do not substitute IndexedBook's level map for the baseline.
- [ ] Run `make test-book test-parity` to GREEN. Compare every event's full sorted state and depth/quotes with the independent Python reference on deterministic valid and rejected correctness streams (at most 4,096 events/128 live orders), streaming and discarding each matched snapshot before the next. Include adverse events in parity; do not compare only final counts.

### Task 3 — sequence, terminal bounds and clock-driven recovery

**Files:** session.hpp, session.cpp, session_tests.cpp.

**Interfaces:** `Session(IBook&,const SessionConfig&)`; `ingest(Bytes,uint64_t now_ns,bool truncated=false) -> Effects`; `on_time(uint64_t now_ns) -> Effects`; `view(uint64_t now_ns,size_t depth) const -> View`; `cancel()`. Effects contains bounded recovery requests/audit records; View contains error, cursors, terminal bound, currentness/validity flags and snapshot. Config includes exact session, hard limits and default timers. Socket peer filtering stays outside Session; the session still rejects mismatched session bytes.

- [ ] Pin independent sequence anchors: contiguous run, completely old packet, unseen overlap suffix, future discard/recovery, trailing heartbeat, early end recovery, identical/conflicting/stale terminal bounds, data/heartbeat beyond end, sequence overflow and S:C followed by new ITCH data.
- [ ] Assert precise failure boundaries: malformed second block leaves packet unapplied; well-framed over-reduction second message accepts first then latches Invalid at second. No future ingest can clear Invalid or emit new requests.
- [ ] With fake clock, assert immediate gap request, retries at 50/100 ms, failure at 150 ms, no timer extension by old/future/foreign activity, progress cursor reset with 1 s gap episode preserved, 128-send cap, 10 s global cap and cancellation. Test exact-deadline ordering.
- [ ] Test CurrentObserved/Gap/Stale/Complete/Awaiting distinctions. Whole old duplicates do not refresh; eligible heartbeat does; silence at 1,500 ms stales a complete observed prefix lacking end. Offline benchmark flags remain live_fresh=false.
- [ ] Run `make test-session` to RED, implement using codec/IBook, rerun to GREEN. Checked counters must reject overflow through low-level boundary tests without billions of actual packets.
- [ ] Compare offline accepted-prefix/cursors/status with independent `reference_sequence` on the frozen packet cases and seeded bounded reorder/drop/overlap schedules.

### Task 4 — actual loopback transport and recovery server drills

**Files:** udp.cpp, io.hpp, scripts/udp_fixture.py, test_udp.py.

**Interfaces:** `run_udp(const LiveConfig&,IBook&,CaptureSink&,AuditSink&) -> RunOutcome`; LiveConfig owns distinct loopback ports, fixed session, bounded receive buffer and timers. Synthetic fixture server accepts canonical sequence→message bytes and deterministic delivery/recovery fault schedule; it binds the pinned source/recovery sockets before emitting receiver-ready traffic.

- [ ] Write subprocess tests that initially fail without actual socket integration. Use separate receiver, publisher and recovery-server processes with bounded cleanup of only those owned processes; require readiness handshakes, not fixed startup sleeps.
- [ ] Cover middle loss, final loss exposed only by heartbeat/end, out-of-order future discard, duplicated/overlapping packets and recovery responses smaller than requested. Verify actual outgoing request bytes and cursor timeline, not only a mocked callback.
- [ ] Cover wrong sender address/port, wrong session, smaller receive buffer causing real MSG_TRUNC, silent retry exhaustion, recovery-server termination, conflicting end, cancellation and malformed pinned traffic. Foreign packets must not mutate sequence/liveness or provoke re-requests. Add a continuous foreign/duplicate flood drill: clock, overall deadline and receive-byte/record caps must still fire under constant socket readability.
- [ ] Implement bind/poll/recvmsg/sendto with explicit network byte order, peer pinning, truncation inspection, injected core clock and finite process deadlines checked on every receive path, not only on poll timeout. No external hosts, multicast joins or live exchange credentials.
- [ ] Run `make test-udp`; exact final state/flags must match the independent reference for recovered cases, and failure cases must retain honest invalid/incomplete prefix artifacts. Retain actual drill logs/timelines and source ports; do not claim authenticated delivery.

### Task 5 — capture, CLI and bounded publication

**Files:** capture.cpp, report.cpp, main.cpp, test_cli.py, scripts/verify.py.

**Interfaces:** bounded `CaptureReader::next() -> Result<optional<CapturedDatagram>>`, `CaptureWriter::append(Bytes,bool truncated) -> optional<Error>`; `write_report(new_directory,RunOutcome,BookSnapshot,Audit,max_bytes) -> optional<Error>`. Reader implements exact FRCP0001 framing. CLI `feed_replay replay --capture PATH --session TENBYTES --output NEWDIR [--depth N]` and `feed_replay listen --listen-port N --source-port N --recovery-port N --session TENBYTES --capture NEWFILE --output NEWDIR [--depth N --recv-buffer N]`.

- [ ] Write real subprocess RED tests for duplicate/unknown/missing args, noninteger/out-of-range ports/depth, non-ASCII/wrong-length session, nonexistent/corrupt/oversized captures, partial records, existing output/capture, publication failure and size cap. Ensure failures never publish a successful partial artifact.
- [ ] Test EOF without Mold end stays incomplete with quote_usable=false even when expected reaches observed high-water; replay never labels CurrentObserved/live_fresh=true. Failed prefix snapshots have quote_usable=false; JSON preserves >2^53 IDs as strings and escapes accepted graphic characters correctly.
- [ ] Implement bounded capture and report serialization. Capture creation/reservation must be exclusive; publish the staged output set with an atomic no-replace primitive in the supported/tested platform scope (macOS `renamex_np` with `RENAME_EXCL`, or an independently reviewed equivalent). Never rely on `exists()` followed by ordinary open/rename. Stage final output set before publication; distinguish successful transport completion, invalid protocol, incomplete/deadline/cancel and operational failures in exit/status fields. Offline replay does not claim real retry timing or freshness.
- [ ] Add a real competing-process publication test: both workers target the same new capture/output name across a barrier; exactly one can publish, the other fails, and the winning coherent artifact/previous sentinel bytes remain unchanged. Also test a destination appearing after staging and dangling-symlink refusal; unsupported no-replace platforms fail explicitly.
- [ ] Run `make test-cli` and the full smaller suite. Verify replay of actual pinned-peer captures reproduces protocol/book outcomes; live-only timing/source assertions remain separately reported.
- [ ] Record all limits, scopes and exact reproduction commands in README; source hash/toolchain/capture/golden provenance must be linked from evidence.

### Task 6 — frozen workload, fair measurements and final review package

**Files:** benchmark.cpp, scripts/workload.py, scripts/benchmark_report.py, evidence/*, README.md.

**Interfaces:** `run_book_benchmark(span<const Event> preload,span<const Event> updates,span<const QuerySpec> queries,EngineKind) -> BenchmarkSample`; sample includes elapsed ns, complete quote-observation outputs and final snapshot. QuerySpec fixes post-event index, locate and depth. Canonical workload generation freezes raw capture, decoded/reference summary, query schedule and SHA before any timings.

- [ ] Generate eight instruments / 2,048 initial live orders / 50,000 subsequent valid lifecycle events using seed20261023; reference-check the entire stream and freeze it. Query schedules are every 1/32/256 events, with identical instrument, depth 0 best-quote semantics and identical offline currentness flags for both engines. No tuning after measured outcomes. Reference-check every scheduled quote (all events at frequency 1) and final full state; do not persist a full book after every one of the 50,000 events.
- [ ] Write a benchmark-contract test that deliberately changes one engine's query schedule or one returned quantity/flag and is rejected. Assert equal query counts, exact output sequences and final sorted state, not merely equal hash values.
- [ ] Implement setup/predecode/preload outside the timed book phase; time updates and identical queries/result storage for each engine. One untimed warmup pair, eight measured pairs per schedule, alternating AB/BA; retain every timing sample and failure. Reuse exact-result buffers across pairs instead of retaining 16 output vectors. Per-experiment benchmark caps: 100,000 decoded updates, 64 MiB input, 64 MiB combined result buffers; these are distinct from live message counters and the 200 MiB allocated cache guard remains active.
- [ ] Measure parser-only and real UDP drill timings separately. Report them as distinct workloads, with hardware/compiler/build mode and medians/distributions. No promised speedup threshold, no minimum-only reporting and no production network extrapolation.
- [ ] Run `make verify PYTHON=python3`, then the fixed benchmark. Inspect report tables/figures and verify all retained links/source/golden/input/output hashes and size budgets. Preserve all negative cases.
- [ ] Request the planned independent final protocol/code/execution review. Reproduce findings with a regression before correcting them; never edit independent expected data simply to satisfy the implementation.
- [ ] Mark complete only after actual UDP recovery/failure drills, oracle parity, sanitizer/bounds checks, fair measurements and reviewer acceptance have executed. Keep final technical acceptance and implementation limitations explicit in this project's documentation.

## Self-review and handoff

Spec sections map to Tasks 1–6; public types/methods above match later task uses. Semantic errors versus structural packet errors, zero-valued data, terminal contradictions, resource limits, silence and measurement fairness each have an explicit test owner. Exact task commands will be Makefile targets created with the relevant deliverable. A task is not marked done from a plan or a passing stub rejection test; preserve behavior-level RED/GREEN evidence.

Planning checkpoint: this document originally preceded production code. Root and fresh protocol/reference approval subsequently authorized execution; docs/progress.md records actual RED/GREEN and measured outcomes. Final independent execution review is still pending.
