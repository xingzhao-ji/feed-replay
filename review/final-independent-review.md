# Independent final protocol, execution review

Reviewed 2026-10-23 by `/root/feed_protocol_review`. **Accept as a strong bounded exchange-feed reconstruction artifact. No material correctness or acceptance blocker was found within the documented ITCH subset, local UDP, fixed-session and synthetic-workload scope.** This closes the artifact review, not a hiring decision, personal-skill assessment, full market-data certification or broader professional qualifications.

The same reviewer independently read the official Nasdaq specifications and authored/froze the reference before production C++ existed. During implementation the reviewer did not write or repair product code. Final review read the complete C++ codec, book/scan implementations, session, UDP, capture, publication, CLI and benchmark, their interfaces, relevant orchestration/tests, design/plan, retained evidence, and the baseline reviews described below. The original nine frozen reference files remain unchanged.

## Independent execution and evidence binding

Fresh execution used the retained optimized and ASan/UBSan binaries, whose hashes were checked against the owner index. No new timing study was run. The reviewer did not rebuild or modify production source.

| Check | Observed result |
|---|---|
| Original reference freeze | All nine file hashes and original manifest hash `84ccec126a652758f05218775c27dee66ddf505e1890a315cf8b0519e90064c9` match; 10 reference tests passed. |
| Owner evidence binding | All 159 indexed files, 29 verification source inputs, 98 retained verification artifacts, six optimized/sanitized binaries, timed C++ source hashes and workload hashes matched at review. The reviewed owner index is preserved separately. |
| Product suite, optimized binaries | 140 tests passed in 10.75 seconds, including actual UDP subprocess tests and correctness-only benchmark checks. |
| Product suite, ASan/UBSan binaries | 140 tests passed in 15.58 seconds, including receiver/CLI and benchmark binaries. No sanitizer finding appeared. |
| New independent schedule corpus | 96 seeded schedules, 3,477 arrival states, compared in full with the pre-product Python oracle; passed optimized and sanitized. Reordering, overlapping ranges, old payloads, early end/heartbeat, discarded future suffixes and recovery splits vary. |
| New actual UDP lifecycle drill | Initial sequence 1–3 followed by end 18 caused seven observed 20-byte requests. The recovery endpoint returned two messages at a time. All 17 lifecycle events reconstructed the exact independent book; captured arrival replay matched. Passed both builds. |
| New adverse UDP/filesystem probes | Future malformed packet rejected without high-water/prefix mutation; five zero-byte foreign datagrams exhausted a four-datagram receive cap without capture writes; cancellation after one recovered order retained sequence 5; a report destination created after readiness remained untouched. Passed both builds. |
| New clock/request boundaries | Exactly 128 generated requests admitted; subsequent recovery need failed explicitly after retaining the accepted prefix. A packet presented at the stalled-cursor deadline could not revive the session. Passed both builds. |

The fresh probe sources were frozen before execution. [v1](final-review-v1/probe-freeze-v1.json) and its initial results are preserved. One reviewer-only assertion used exact floating-point equality to compare a median computed in nanoseconds and then scaled with a median of already scaled floats. For interval 256, indexed, those methods differ by `8.881784197001252e-16 ms`; this is not a product discrepancy. [v2](final-review-v1/probe-freeze-v2.json) changes only that comparison to a `1e-12 ms` tolerance, with [normal](final-review-v1/run-normal-v2/results.json) and [sanitized](final-review-v1/run-sanitized-v2/results.json) rechecks passing all eight probes. Erratum: the v2 freeze note says “frequency1”; the actual saved raw-row counterexample is frequency **256**. No protocol expectation or original frozen reference changed.

Retained execution logs: [product normal](final-review-v1/product-normal.log), [product sanitized](final-review-v1/product-sanitized.log), [reference](final-review-v1/reference.log). The fresh UDP evidence includes actual request hex, captures, returned book/summary/timeline files and process results. The final resource guard reported 80,494,592 allocated cache bytes and 151,517,650,944 free host bytes, below/above the stated limits respectively. Added reviewer artifacts are approximately 2–3 MiB.

## Source and protocol assessment

The [original protocol review](protocol-design-review.md) establishes the official table basis. The completed implementation follows those boundaries:

- Checked byte assembly preserves unsigned 64-bit IDs and 48-bit timestamps without packed-struct aliasing. Exact type lengths, price maximum, padded symbol admission, printable/cross/system codes and timestamp range are explicit. The declared restrictions and opaque R metadata remain disclosed.
- The order map and retained historical-ID set enforce session/day uniqueness after fill, cancellation, deletion and replacement. C:N reduces displayed quantity at the stored display price, B never restores it, P/Q/B do not add displayed interest, and U retains side/symbol/attribution. Reductions and replacement validate references, quantities and admitted resources before semantic mutation. Zero price remains a real quote, distinct from absence.
- Whole-datagram framing/type/length preflight precedes prefix/high-water mutation. Ordered field/book failure retains earlier valid messages and latches invalidity. Future messages are discarded but extend observed high water; overlap only applies the unseen suffix. Skipped old payload contents are explicitly not authenticated or compared for equivalence.
- Heartbeat/end markers expose trailing gaps. Stale or conflicting ends and data beyond a known terminal bound cannot certify completeness. Sequence exclusive-bound overflow rejects before application. S:C is independent from Mold completion, and later accepted ITCH events contradict it.
- The live loop uses actual nonblocking loopback UDP, pinned source/recovery endpoints, recvmsg truncation flags, one receive socket for requests and responses, and clock checks before each receive path. Foreign/duplicate traffic cannot postpone stalled or overall deadlines. Counts/bytes/history/timeline/output all have explicit bounds. Pinning remains unauthenticated and is not described as exchange access control.
- Capture creation uses exclusive creation; report files serialize within the combined cap before staging and exclusive directory publication. Existing destinations and the independently tested late-created destination are preserved. Capture input is a bounded regular nonsymlink file; replay continues past a completed end to detect captured contradictions. A live receiver exits at completion and necessarily cannot inspect subsequent packets, which the README discloses.

The C++ source is small enough to inspect and separates wire admission, stateful book behavior, sequencing/deadlines, socket mechanics and publication. The scan engine shares order admission/lifecycle code with the indexed engine and independently derives best levels from the order map. That is a fair data-structure baseline, **not** a second independent lifecycle implementation; the pre-product Python model supplies that independence. The plan's narrower baseline interpretation is documented.

Allocation and I/O failures are not claimed to be recoverable book transactions. No power-loss durability, authenticated feed, production multicast or complete ITCH compatibility is established. Public `BookCore::apply` assumes an Event produced by successful `decode_itch`; untrusted wire callers must retain that boundary.

## Measurement review

Raw rows reproduce the published medians and all samples are retained:

| Query interval | Indexed median, ms | Scan median, ms | Ratio of medians, scan/indexed |
|---|---:|---:|---:|
| 1 | 6.5767295 | 256.8894375 | 39.060362 |
| 32 | 5.9140830 | 14.2752295 | 2.413769 |
| 256 | 5.8173960 | 4.5453750 | 0.781342 |

There is one warmup pair and eight measured pairs per interval, alternating indexed/scan order. Each engine receives the same decoded events, validation, query schedule, quote storage and preallocated output capacity; exact query sequences and full final state are checked outside the timer. The separately measured parser median is 0.704042 ms for 52,056 already resident messages. These scopes are not summed into a fabricated end-to-end latency.

The retained sparse scan win is meaningful. It limits any blanket “indexed is faster” claim. The sparse schedules query instrument 1, whereas interval 1 cycles all eight instruments; cross-interval differences therefore mix query frequency and instrument selection. The documented warm single-host synthetic workload, lack of affinity/exclusive-host guarantee and shared lifecycle implementation limit generalization. No throughput capacity, production low-latency expertise or trading-performance inference is supported.

Two nonblocking workflow/documentation observations remain:

1. `scripts/benchmark_report.py` records the expected compiler flags as a literal rather than reading build metadata embedded in the binary. The reviewed retained source/binary hashes match and sanitizer binaries are separate, but a future build with overridden flags could mislabel a new study. Generate/validate build metadata before relying on this harness for a differently configured study.
2. README's broad “operational/capture error = exit 2” wording is narrower than the live source behavior: capture append errors and socket send/poll failures can latch an invalid session and return 4 after diagnostic publication. Such outputs remain unusable and non-successful. Clarify the exit-code prose or route the specific errors consistently before treating the numeric code alone as a detailed operational taxonomy. This is a source-observed classification issue, not a reproduced corruption/currentness failure.

Neither observation requires retiming the retained study or changes the accepted bounded correctness result. No requested product fix was implemented by this reviewer.

## Artifact scope

The distinct technical contribution is exchange-specific binary semantics and the correctness of a displayed-book prefix under packet loss. The finite independently reviewed artifact does not establish full ITCH compatibility, exchange certification, production low-latency operation, a calibrated exchange simulator, human employer endorsement or personal mastery. Private application and portfolio comparisons are omitted from this public export.
