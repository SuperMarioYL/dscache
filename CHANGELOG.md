# Changelog

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
