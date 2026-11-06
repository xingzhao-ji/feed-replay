# Root design review — 2026-10-23

The 124-line design was reviewed against the cached official ITCH data-type and A/F/E/C/X/D/U/P/Q/B tables, S/R metadata, and MoldUDP64 framing/marker/request rules. The selected scope adds protocol-aware book reconstruction and actual loss recovery beyond the existing storage/replay projects. It is not a matching engine, market-performance experiment, full-feed implementation or proof of applicant expertise.

The design is approved for planning. Product implementation remains gated on the fresh reviewer's literal/reference freeze and the implementation-plan check. No new user approval is required for this local work within the already authorized portfolio objective.

The exact-integer price/ID treatment, day-unique ID history, non-printable execution handling, replacement metadata, whole-packet framing preflight, per-message semantic prefix, latched invalidity, terminal contradictions and bounded re-request behavior are appropriate. The explicit zero-add-quantity admission restriction, opaque directory metadata and skipped-duplicate identity limitation keep the conformance claims honest.

The plan must preserve four operational details:

- Offline EOF without a complete terminal prefix produces incomplete, unusable quote output. Gap-free replay does not establish live freshness.
- Receive budgets and deadlines are checked during continuous duplicate/foreign traffic, not only when a socket poll times out.
- Every-event reference checks stream comparisons, and benchmark output buffers are reused. Do not retain 50,000 full order-book snapshots under a 200 MiB runtime budget.
- Benchmark runs retain all timings and equal query work; live-session message budgets and experiment resource limits have distinct documented scopes.

No speed or qualification-coverage claim follows from this design approval. Final source, failure drills, independent expected behavior and measured baseline comparisons still need execution and review.
