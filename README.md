# Feed Replay

A C++20 Nasdaq ITCH displayed-book reconstructor with actual loopback MoldUDP64 recovery. It preserves the last valid message prefix, detects missing tail data from heartbeats/end markers, requests missing sequences, and makes incomplete or invalid books explicit.

The project adds exchange wire-format, order lifecycle, loss recovery and measured data-structure tradeoffs to a general systems portfolio. It is an AI-assisted artifact with independent protocol fixtures/review; it does not establish the owner's personal mastery or a job prerequisite by itself.

## Executed evidence

- **140 product tests** pass normally and with ASan/UBSan on the core probe, receiver/CLI and benchmark binaries; **10 independently authored reference tests** pass separately.
- **28 actual UDP subprocess tests** cover loss/recovery, partial replies, duplicates/overlap, pinned invalid traffic, kernel truncation, failed recovery, cancellation, foreign/duplicate flood deadlines, hard bounds and competing capture creation. These are finite local drills, not a reliability estimate.
- The independently frozen corpus has 17 literal messages, 17 hand-checked lifecycle states, 48 packet scenarios, 533 ITCH truncation boundaries and 116 Mold truncation boundaries. C++ implementation started only after root verified that freeze.
- A frozen synthetic study applies 52,056 messages: eight directories, 2,048 initial orders, then 50,000 updates. Every update's selected quote and the complete final book match the independent Python map reference.

| Quote query interval | Indexed median, ms | Scan median, ms | Interpretation in this workload |
|---|---:|---:|---|
| Every update | 6.577 | 256.889 | Maintained levels reduce frequent query work. |
| Every 32 updates | 5.914 | 14.275 | Query savings still exceed level maintenance. |
| Every 256 updates | 5.817 | 4.545 | Scanning wins when quotes are sparse. |

Eight measured pairs per interval, alternating order, following one warmup pair. All samples are retained. The timed region includes update validation, mutations, identical queries and result storage, and excludes decoding, preload, allocation of result capacity, output checks and serialization. Both engines share admission/lifecycle code; only the indexed engine maintains price levels. This is a warm synthetic microbenchmark on one Apple M4 Pro host, not production latency. The sparse schedules query instrument 1 because the frozen locate formula is `index % 8 + 1`; the every-update schedule cycles all eight instruments. No outcome-driven retuning was done.

Read [the measured report](docs/results.md), [shareable HTML report](evidence/report.html), [all benchmark samples](evidence/benchmark.json), [frozen workload](evidence/workload/manifest.json), and [verification artifacts](evidence/verification-20261023T212630Z/manifest.json). [Evidence index](evidence/index.json) binds source, binaries and artifacts. The [final independent review](review/final-independent-review.md) and [acceptance addendum](docs/acceptance-addendum.md) accept the declared local/synthetic subset scope; historical measurements remain unchanged.

## Run it

Tested on macOS 27.0.1 arm64 with Apple Clang 21, C++20 and Python 3.12. Uses only standard C++/POSIX and Python/pytest. Create a local environment for pytest; the C++ runtime has no third-party runtime dependency.

```sh
cd feed-replay
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
make verify PYTHON=python
make sanitize PYTHON=python
```

`verify` executes the frozen reference and all product checks, retaining a new timestamped evidence directory with actual UDP captures, reports and observed request bytes. Build/runtime caches stay under `~/.cache/job-apps-runtime/feed-replay` (override `CACHE` and `FEED_CACHE` consistently). The guard checks allocated cache size below 200 MiB and host free space above 2 GiB before/during commands. The cache may need scoped cleanup after many repeated verification runs; the guard fails rather than deleting unrelated files.

Replay the included workload into a **new** output directory:

```sh
~/.cache/job-apps-runtime/feed-replay/build/feed_replay replay \
  --capture evidence/workload/workload.frcp --session BENCH00001 \
  --output /tmp/feed-replay-example --depth 5 --include-orders 1
```

For a receiver with separately bound local peers:

```sh
~/.cache/job-apps-runtime/feed-replay/build/feed_replay listen \
  --listen-port 41001 --source-port 41002 --recovery-port 41003 \
  --session REVIEW0001 --capture /tmp/feed-new.frcp \
  --output /tmp/feed-new-report --depth 5
```

All three ports must be distinct; the socket binds only `127.0.0.1`. A flushed `{"ready":true,"port":...}` line is the startup handshake. The tests orchestrate real publisher and re-request processes using [udp_fixture.py](scripts/udp_fixture.py), including exact request-wire checks. `SIGINT`/`SIGTERM` cancel the owned receiver and publish its last prefix. Runs terminate after at most ten seconds under the default policy. `--overall-ms`, `--receive-bytes` and `--receive-count` may only lower their hard caps; `--recv-buffer 20..65507` permits real kernel-truncation drills.

Exit codes: `0` complete transport prefix, `3` incomplete/deadline/cancel, `4` invalid stream/resource admission, and `2` CLI/publication or other operational failure. Some live capture/socket failures latch Invalid and return `4` after diagnostics; inspect status/error fields rather than treating the numeric exit code as an exhaustive operational taxonomy. Output contains `summary.json`, `book.json` and `timeline.jsonl`. 64-bit IDs/cursors/aggregate quantities are decimal JSON strings, prices are exact integer ten-thousandths. Depth zero omits depth arrays while retaining best quotes. Optional full order lists can exceed the separate output budget and cause an explicit refusal.

`make benchmark` runs the fixed study and exclusively creates `evidence/benchmark.json`; it refuses to overwrite the retained original. For a new study, preserve this evidence first and deliberately choose a distinct destination in a reviewed change. `feed_benchmark --check evidence/workload` reruns full output/reference comparisons without retaining new timing samples.

## Contract and limits

- Exact subset: `S,R,A,F,E,C,X,D,U,P,Q,B`. `P/Q/B` are explicit displayed-book no-ops, not skipped unknown types. `C` reduces at the stored display price regardless of printability; a broken trade does not restore displayed orders. Unknown types stop the stream.
- Prices admit **zero through 2,000,000,000**. Timestamps must be within one day and may decrease. All order IDs, including zero and the full unsigned 64-bit domain, are exact and day-unique; retired IDs cannot be reused, including by replacement.
- A fixed caller-supplied ten-byte ASCII-alphanumeric session begins at sequence 1 with an empty book. Directory mappings are required and stable. Positive A/F/U quantity and the simple right-padded graphic-ASCII symbol/attribution grammar are **project admission restrictions**, not claims that Nasdaq forbids every rejected representation. Zero reductions are valid for existing orders.
- Whole packet framing/type/length preflight precedes any packet mutation. Field/book failure in a well-framed later message preserves prior accepted messages and latches invalid. Old packet payload identity is not verified. Overlap applies only the unseen suffix; future payloads are discarded until recovered.
- Heartbeat/end high-water bounds expose tail gaps. End cannot contradict an observed or accepted bound; completion requires the entire observed prefix. ITCH `S:C` and Mold end are distinct. A live receiver exits on a completed terminal bound; it cannot observe contradictory packets arriving after it exits. Offline replay continues through its captured arrivals after end to detect contradictions.
- Live `CurrentObserved` means fresh relative to **observed** high water, not proof that entirely unobserved traffic never went missing. Silence becomes stale at 1,500 ms. Completed historical snapshots and every offline replay have `live_fresh=false` and `quote_usable=false`; EOF without end remains incomplete.
- Request batch≤128, retries at 50/100 ms after the initial send, stalled cursor fails at 150 ms;≤128 sends/run, continuous gap≤1 s, run≤10 s. Deadlines are checked under continuously readable foreign/duplicate traffic. Pinning address/ports is not authentication.
- Datagram≤65,507 bytes; all-peer received bytes and capture bytes each≤64 MiB; received datagrams/capture records/processed messages≤2 million; live orders≤100,000; historical IDs≤1 million; instruments≤4,096; timeline≤10,000 entries; published report files combined≤8 MiB. A received datagram that crosses a budget is not processed/captured. Truncated foreign datagrams are conservatively charged 65,507 bytes on macOS, where `recvmsg` reports only copied length.
- Capture input must be a bounded regular nonsymlink file. `FRCP0001` stores pinned-peer arrival bytes and truncation flags, not wall-clock timing or foreign traffic. Replay reproduces protocol arrival order, not live deadline/source behavior. It may therefore differ from a deadline-stopped live run.
- New captures use `O_EXCL`; staged reports use macOS `renamex_np(RENAME_EXCL)`. Competing runs cannot overwrite an existing capture/report. Atomic publication is tested on macOS only; other platforms fail explicitly. No `fsync`/power-loss durability promise is made. Allocation or I/O failures are fatal operational failures, not a recoverable transaction guarantee.

This is a declared subset and synthetic environment. Halt/tradability eligibility, full ITCH metadata, match correction ledgers, snapshots, multicast deployment, order entry and actual trading are outside scope. The reconstructed displayed quote is not a tradability or execution guarantee.

## Source and review map

- [Design and official Nasdaq citations](docs/design.md): exact fields, length/domain decisions and omitted semantics.
- [Implementation plan](docs/implementation-plan.md), [root approval](docs/root-design-review.md), [RED/GREEN ledger](docs/progress.md).
- [Independent fixture provenance/adapters](review/README.md), [design review](review/protocol-design-review.md), [freeze](review/freeze-v1.json). These files were authored before production code and were not edited to match it.
- [Codec](src/codec.cpp) → [indexed lifecycle/levels](src/indexed_book.cpp) / [scan query](src/scan_book.cpp) → [sequence/deadlines](src/session.cpp) → [UDP shell](src/udp.cpp).
- [Capture](src/capture.cpp), [publication](src/report.cpp), [CLI](src/main.cpp), [paired harness](src/benchmark.cpp).

## Public export

[PUBLICATION.md](PUBLICATION.md) documents preserved source identities, normalized historical evidence, privacy exclusions and the limited publication verification. This AI-assisted artifact does not establish sole human authorship or personal mastery. No project license grant is added by the export.
