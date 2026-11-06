# Feed Replay measured results

One fixed synthetic study; no success threshold, retuning or discarded timing samples. The primary finding is a crossover: maintaining price levels helps frequent quotes, while scanning is faster at the sparsest query interval.

| Query interval | Indexed median (range), ms | Scan median (range), ms | Median scan/indexed ratio |
| --- | --- | --- | --- |
| 1 | 6.577 (6.418–6.739) | 256.889 (248.761–321.836) | 39.060 |
| 32 | 5.914 (5.636–6.269) | 14.275 (13.990–14.905) | 2.414 |
| 256 | 5.817 (5.506–5.924) | 4.545 (4.433–4.604) | 0.781 |


Eight measured pairs per interval after one warmup pair. Table ranges retain the slowest samples, including the 321.836 ms scan observation. Both engines perform identical validated updates, queries and result writes; every query and full final state match the independent oracle. Shared lifecycle code is intentional; the separate Python reference supplies semantic independence.

The 50,000 updates start with 2,048 live orders over eight instruments. Query interval 1 cycles all instruments; frozen intervals 32/256 query instrument1. Thus cross-interval differences combine query frequency with instrument selection; do not treat this as a pure causal estimate of query frequency. Output is synthetic displayed depth only. No exchange traffic, cold-start, network or production latency is measured by this table.

Environment: Apple M4 Pro, macOS-27.0.1-arm64-arm-64bit, Apple clang version 21.0.0 (clang-2100.3.34.2); flags `-std=c++20 -O2 -Wall -Wextra -Werror`. 14 logical CPUs; start/end 1/5/15-minute load averages [3.91064453125, 4.3447265625, 5.1552734375] / [3.91064453125, 4.3447265625, 5.1552734375]. No CPU pinning or exclusive-host guarantee. The parent coordinated other portfolio benchmark work outside this short window. All paired observations, warmups, source hashes and timestamps are in [benchmark.json](../evidence/benchmark.json).

Separate parser-only phase: decode 52,056 messages from already resident raw packets, including frame/type/field checks and decoded-result construction; exclude file I/O. Eight measured passes after one warmup: median 0.704 ms, range 0.700–0.708 ms. These values cannot be added to the book table to predict end-to-end service latency.

## Every measured pair

| Interval | Pair | Order | Indexed ms | Scan ms |
| --- | --- | --- | --- | --- |
| 1 | 1 | indexed → scan | 6.487 | 290.231 |
| 1 | 2 | scan → indexed | 6.571 | 321.836 |
| 1 | 3 | indexed → scan | 6.418 | 295.112 |
| 1 | 4 | scan → indexed | 6.736 | 253.572 |
| 1 | 5 | indexed → scan | 6.739 | 251.422 |
| 1 | 6 | scan → indexed | 6.583 | 248.761 |
| 1 | 7 | indexed → scan | 6.453 | 257.787 |
| 1 | 8 | scan → indexed | 6.713 | 255.992 |
| 32 | 1 | indexed → scan | 6.055 | 14.545 |
| 32 | 2 | scan → indexed | 6.045 | 14.905 |
| 32 | 3 | indexed → scan | 5.684 | 13.990 |
| 32 | 4 | scan → indexed | 5.911 | 14.013 |
| 32 | 5 | indexed → scan | 5.663 | 14.410 |
| 32 | 6 | scan → indexed | 5.917 | 14.185 |
| 32 | 7 | indexed → scan | 5.636 | 14.210 |
| 32 | 8 | scan → indexed | 6.269 | 14.340 |
| 256 | 1 | indexed → scan | 5.724 | 4.509 |
| 256 | 2 | scan → indexed | 5.882 | 4.433 |
| 256 | 3 | indexed → scan | 5.751 | 4.535 |
| 256 | 4 | scan → indexed | 5.864 | 4.433 |
| 256 | 5 | indexed → scan | 5.924 | 4.604 |
| 256 | 6 | scan → indexed | 5.771 | 4.579 |
| 256 | 7 | indexed → scan | 5.506 | 4.556 |
| 256 | 8 | scan → indexed | 5.916 | 4.567 |


## Actual UDP drills

These rows come from separate receiver/publisher/recovery processes and retained `recvmsg` captures. Times are elapsed receiver steady-clock timestamps of the last recorded event, not packet latency distributions or throughput. Zero/no-input failures and retry deadlines remain in the report. Source-port pinning is unauthenticated. Captures omit foreign bytes and wall-clock timings; replay is a separate protocol-order check.

| Actual process drill | Status | Next sequence | Sent requests | Last recorded event, ms |
| --- | --- | --- | --- | --- |
| test_actual_gap_recovery_and_p0-out | Complete | 4 | 2 | 0.795 |
| test_actual_gap_recovery_and_p1-out | Complete | 4 | 2 | 0.723 |
| test_actual_gap_recovery_and_p2-out | Complete | 4 | 2 | 0.682 |
| test_actual_gap_recovery_and_p3-out | Complete | 4 | 1 | 0.553 |
| test_actual_gap_recovery_and_p4-out | Complete | 4 | 1 | 0.581 |
| test_actual_gap_recovery_and_p5-out | Complete | 4 | 1 | 0.599 |
| test_actual_overlap_and_old_du0-out | Complete | 4 | 0 | 0.453 |
| test_competing_capture_creator0-out0 | Complete | 1 | 0 | 1.997 |
| test_flood_does_not_extend_sta0-out | RecoveryFailed | 2 | 3 | 150.350 |
| test_flood_does_not_extend_sta1-out | RecoveryFailed | 2 | 3 | 150.309 |
| test_foreign_only_traffic_cann0-out | RecoveryFailed | 1 | 0 | 200.024 |
| test_foreign_traffic_charged_t0-out | Invalid | 1 | 0 | 0.269 |
| test_foreign_traffic_charged_t1-out | Invalid | 1 | 0 | 0.339 |
| test_kernel_recvmsg_truncation0-out | Invalid | 1 | 0 | 0.281 |
| test_pinned_invalid_traffic_pr0-out | Invalid | 2 | 0 | 0.366 |
| test_pinned_invalid_traffic_pr1-out | Invalid | 2 | 0 | 0.387 |
| test_pinned_invalid_traffic_pr2-out | Invalid | 2 | 0 | 0.466 |
| test_signal_cancellation_close0-out | Cancelled | 4 | 1 | 0.441 |
| test_terminated_recovery_peer_0-out | RecoveryFailed | 1 | 3 | 153.086 |


The complete 28 UDP test cases also include option rejection and competing capture creation. [Verification manifest](../evidence/verification-20261023T212630Z/manifest.json) hashes the actual artifacts and observed request bytes. Product suite 140 tests plus independent reference suite 10 tests passed. Full ASan/UBSan core/CLI/UDP/benchmark suite 140 tests passed; [sanitizer log](../evidence/logs/final-sanitized.log).

## Evidence boundaries

Whole packet structural admission and message-by-message semantic acceptance are different boundaries. The fixtures challenge both. Every offline report and completed historical snapshot sets freshness/usability false; observed high water cannot prove that unseen traffic was never lost. Hard caps intentionally fail a session/report rather than evict history, clip quantities or publish a successful partial result.

No full ITCH compatibility, authenticated feed, live exchange deployment, trading execution, operational reliability, personal mastery or employer endorsement is established. Final independent source/execution review remains pending.
