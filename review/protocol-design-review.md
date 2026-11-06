# Independent protocol and design review

Verdict: **approved for the declared bounded implementation after root acceptance and this directory's v1 freeze**. No unresolved blocking protocol ambiguity was found in the saved design and implementation plan reviewed on 2026-10-23. This is design approval, not implementation or employer acceptance.

Reviewer: independent `/root/feed_protocol_review` agent. The reviewer read the cached original Nasdaq tables and the design/plan; no product C++ implementation existed at reference authorship/freeze. The reference uses explicit byte slicing and a plain Python order dictionary that rescans all live orders for every snapshot. No production encoder, decoder, book implementation, or subprocess supplied the literal bytes or expected results.

## Source checks

- ITCH 5.0 Data Types (PDF p4): unsigned big-endian integers, six-byte nanoseconds, Price(4) maximum 2,000,000,000. Range validation is appropriate; monotonically increasing timestamps are not required by the cited text.
- ITCH pp12–16: A/F day-unique references, cumulative E/C/X reductions, deletion at zero, D removal, and U retaining side/symbol/attribution. Historical IDs must remain forbidden after deletion/fill/replacement. `C` non-printability affects time-and-sales/volume, not displayed reduction.
- ITCH pp16–18: P does not add displayed interest; the reviewed revision specifies zero P order reference and B side. Q explicitly permits zero cross shares. B has no impact on the current book and must not restore executed orders.
- ITCH pp4–7: recognized S codes, S:C as last ITCH message, directory mapping. The supported implementation consumes only R's locate/symbol mapping and declares other R metadata opaque; this is narrower than full-feed semantic validation.
- MoldUDP64 pp3–5: exact 20-byte header, per-message sequence increments, two-byte length excluded from message body length, zero-count heartbeat and 65535-count end carrying next sequence. A request may require multiple responses/requests when all messages do not fit one datagram.

Original source hashes: ITCH PDF `45e0531d1b4b3beb886e9618b2ab824a5aa9bda3a99c0dff03509306e68aacc3`; Mold PDF `96cdd02b8728a441cb970d1371a96e73c01e1edaffb2891d43667e2a0ad8add5`. Original PDFs remain private cache inputs, not repository copies.

## Explicit design decisions accepted

The design clearly labels positive A/F/U quantity, simple graphic-ASCII symbols/MPIDs, selected Q cross codes, and exact CLI session spelling as project admission restrictions. It permits zero prices, zero IDs, zero E/C/X reductions with valid references, crossed displayed books and decreasing timestamps. It validates full packet framing/type/length before any mutation, while ordered field/semantic failures preserve the earlier accepted prefix and permanently invalidate later publication.

Future packets advertise high water and are discarded; overlap contributes only its unseen suffix. Old structurally valid payloads are skipped without claiming identical bytes. Heartbeat/end can expose trailing gaps. An end below prior high water, conflicting end, or later data/heartbeat beyond the terminal bound invalidates. Exclusive sequence-bound overflow is rejected before mutation. Fixed session/sequence 1 avoids the unsolved snapshot problem.

Clock and peer boundaries are explicit: only pinned loopback endpoints, actual recvmsg truncation detection, retry and gap-episode limits, overall deadline, finite output/capture/history capacities, and no deadline reset by non-progress traffic. Final implementation review must still establish these with real socket traces and tests; the offline reference deliberately does not simulate OS sockets or wall-clock freshness.

The plan distinguishes offline EOF/incomplete diagnostics from completed transport, streams large correctness comparisons, and separates parser, book-update/query, and UDP timing. The planned full-output comparisons, alternating benchmark order and retained samples are sufficient design commitments; no performance claim is approved before execution.

One public-API clarification was sent to the builder: `snapshot(depth=0)` returns empty depth arrays but still reports the independent best quote. Depth limits the returned depth, not best-quote existence or state.

## Remaining implementation acceptance work

Production code must consume this corpus and pass every-event/reference comparisons, independently adverse semantics, real UDP loss/recovery/peer/truncation/deadline drills, capture/publication failure tests, bounded sanitizer mutation runs and the fair benchmark contract. This directory's success does not substitute for any of that work. Final review ownership stays with this reviewer so long as production implementation independence is preserved.
