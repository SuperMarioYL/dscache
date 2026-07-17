# Changelog

## v0.3.0

A correctness pass that closes three residual holes in v0.2.0's own
sampling, pricing, and attribution paths — the same honesty thesis, extended
to the cases v0.2.0 left half-fixed — plus one small feature that unblocks the
before/after-bill writeup the README promised.

### Fixes

- **The prefix sample is capped at segment boundaries, not sliced mid-segment.**
  `_prefix_sample` enforced the 2048-char budget only inside the messages
  loop and then did a final `sample[:2048]` slice that could cut a tool block
  in half. For a coding agent whose tool list dominates the budget (the common
  case) the sample ended mid-tool — corrupting segment-level attribution with
  a stub segment — and message text past the tool head was never captured, so
  two requests with identical tools but a diverged system message got the
  *same* fingerprint and a real system-message bust was invisible. The budget
  is now applied incrementally across all segments (tools, `tool_choice`,
  `response_format`, messages); a segment that would overflow the remaining
  budget is never appended, so no segment is ever truncated mid-way.

- **`cost_ideal` is based on the full `prompt_tokens`, not `cached + miss`.**
  The counterfactual `price_request` models is "the entire prompt had stayed
  cached", and the entire prompt is `prompt_tokens`. DeepSeek documents
  `prompt_tokens == cached + miss`, but providers surface inconsistent splits
  in practice; when `cached + miss < prompt_tokens` the old ideal was
  understated and the headline overstated wasted ¥ — fabricating phantom
  money on data the user couldn't reconcile against their bill. The ideal now
  uses `prompt_tokens`; behavior is unchanged when the split is consistent.

- **A bust is never attributed to a MISS or UNKNOWN reference.** A MISS never
  cached, so it shouldn't register as the owner of a "stable" prefix — yet it
  did, so a later request with the same sampled head (also a MISS) was busted
  against an unstable owner and `suggest` told you to pin to a prefix that
  itself didn't cache. Likewise the no-prior-HIT fallback advanced
  `last_request_id` on UNKNOWN-tier entries, so a bust could point at a
  request whose cache split DeepSeek never reported. Only HIT/PARTIAL entries
  now register as fingerprint owners, and `last_request_id` only advances on
  judged (non-UNKNOWN) entries.

### Features

- **`dscache report --compare <baseline.jsonl>`** prints the before/after
  cache-savings delta in one panel. Run your agent loop, apply the prefix-
  reorder suggestion from `dscache suggest`, re-run, then `dscache report
  --compare baseline.jsonl` to see the recovered cache-busts, recovered ¥,
  and the cost-ratio drop — the shareable before/after-bill writeup the
  README's go-to-market called for, now one command. Honesty-preserving: the
  panel says "recovered", not "saved" — dscache can't prove you pinned the
  prefix (you may have changed the prompt or run), so it reports only that the
  judged requests in the current ledger wasted less ¥ than the baseline.

## v0.2.0

An honesty-first pass over the profiler. v0.1.0 could call a cache "stable"
when it wasn't, and could invent wasted money out of data we never actually
had. This release fixes the four ways the report could lie, and adds segment-
level attribution so a bust tells you *which* part of the prompt broke.

### Fixes

- **A real MISS that shares a sampled prefix is no longer reported as stable.**
  The 2048-char prefix sample is only a lower bound on DeepSeek's real cache
  key, not the key itself. If two requests happen to share that sampled head
  but DeepSeek still reports a MISS/PARTIAL, that's a genuine bust — we now flag
  it against the prefix's owner instead of silently passing over it. Previously
  this undercounted busts and made `suggest` return nothing on a real failure.

- **UNKNOWN-tier requests no longer fabricate wasted money.** When DeepSeek
  omits the cache-split fields we can't judge hit vs miss, yet the priced
  fallback still produced a miss-vs-hit gap. Summed into the headline, a run
  with zero detected busts could print a large "¥Z wasted" and a 4.00× ratio on
  data we admit we can't judge. UNKNOWN entries now contribute zero waste, and
  the headline excludes them from the actual/ideal totals.

- **Busts are attributed to the most-recent HIT, not the immediate neighbor.**
  We previously pinned a bust to whatever request came right before it, which
  might itself be an unstable prefix — so `suggest` could tell you to match a
  bad reference. We now track the last request that actually HIT and attribute
  against that, falling back to the immediate neighbor only when no stable prior
  prefix exists.

- **The prefix sample now includes tools.** `_prefix_sample` only serialized
  message role+content and ignored `tools` / `tool_choice` / `response_format`.
  For coding agents the cache key is dominated by a large, frequently-reordered
  tool list, so a reordered-tools bust — the exact failure mode the README
  advertises — was invisible. Tools are now serialized ahead of the message
  text (still capped at 2048 chars), so a shuffled tool array changes the
  fingerprint.

### Features

- **Segment-level bust attribution** (`dscache/attribute.py`). When a bust is
  detected against its most-recent-HIT reference, we diff the two serialized
  request heads at segment granularity and name the first diverging segment —
  e.g. `PREFIX BUST: tools[3] diverged vs req r17; segments[0..2] still stable`.
  Surfaced through `dscache suggest` and the reorder suggestion. Detect-and-
  attribute only: it never mutates the request. The output carries an explicit
  honesty caveat — a client can reason only about its own prefix divergence and
  cannot observe or control DeepSeek's server-side global LRU eviction, so a
  clean client-side diff means "you didn't cause this bust", not "this call was
  guaranteed a hit".

## v0.1.0

- Initial release. `dscache.wrap()` transparently records per-request context-
  cache usage to a local ledger; `dscache report` prints the HIT/PARTIAL/MISS
  table with DeepSeek two-tier pricing; `dscache suggest` points at the worst
  bust; `dscache demo` writes a sample ledger so the report runs without an API
  key.
