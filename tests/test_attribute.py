"""Tests for v0.2.0 tool-aware prefix sampling + segment-level attribution.

Covers:
- fix-prefix-sample-ignores-tools-and-full-system: a reordered ``tools`` array
  (identical leading messages) now changes the prefix fingerprint, so the
  advertised reordered-tools bust becomes visible.
- feat-segment-level-bust-attribution: attribute_bust names the FIRST diverging
  segment (the right tool block / message index / system text), states the
  honesty caveat, and never mutates the request.
"""

from __future__ import annotations

from dscache.attribute import HONESTY_CAVEAT, attribute_bust
from dscache.profiler import Tier, profile
from dscache.reorder import suggest_reorder
from dscache.wrapper import _prefix_sample


# --- fix-prefix-sample-ignores-tools-and-full-system ------------------------


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": f"call {name}", "parameters": {}},
    }


def test_prefix_sample_includes_tools():
    messages = [{"role": "system", "content": "You are an agent."}]
    sample = _prefix_sample({"messages": messages, "tools": [_tool("read"), _tool("write")]})
    assert sample is not None
    assert "tools[0]" in sample
    assert "tools[1]" in sample
    # Tools are serialized AHEAD of the message text. Message content is now
    # json-quoted (fix fix-multiline-content-breaks-segment-attribution), so the
    # system segment reads `system:"You are an agent."`.
    assert sample.index("tools[0]") < sample.index("system:")
    assert '"You are an agent."' in sample


def test_reordered_tools_change_the_sample():
    messages = [{"role": "system", "content": "You are an agent."}]
    a = _prefix_sample({"messages": messages, "tools": [_tool("read"), _tool("write")]})
    b = _prefix_sample({"messages": messages, "tools": [_tool("write"), _tool("read")]})
    # Identical leading messages, reordered tools -> DIFFERENT sample.
    assert a != b


def test_tool_choice_and_response_format_included():
    sample = _prefix_sample(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": "auto",
            "response_format": {"type": "json_object"},
        }
    )
    assert "tool_choice:" in sample
    assert "response_format:" in sample


def test_reordered_tools_bust_is_now_visible_end_to_end():
    # Two requests with identical messages but a reordered tool list. With the
    # tools now in the sample, the second call's fingerprint diverges, and when
    # DeepSeek reports a MISS the profiler flags the bust (previously invisible).
    messages = [{"role": "system", "content": "You are an agent."}]
    s1 = _prefix_sample({"messages": messages, "tools": [_tool("read"), _tool("write")]})
    s2 = _prefix_sample({"messages": messages, "tools": [_tool("write"), _tool("read")]})
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": s1},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": s2},
    ]
    entries = profile(records)
    assert entries[1].tier is Tier.MISS
    assert entries[1].busted_against == "r1"


# --- feat-segment-level-bust-attribution ------------------------------------


def test_attribute_names_the_diverging_tool_block():
    messages = [{"role": "system", "content": "You are an agent."}]
    ref = _prefix_sample(
        {"messages": messages, "tools": [_tool("read"), _tool("write"), _tool("grep")]}
    )
    busted = _prefix_sample(
        {"messages": messages, "tools": [_tool("read"), _tool("write"), _tool("DIFFERENT")]}
    )
    attribution = attribute_bust(busted, ref, "r17")
    assert attribution.diverged
    assert attribution.segment == "tools[2]"
    assert "tools[2]" in attribution.message
    assert "r17" in attribution.message


def test_attribute_first_divergence_is_reported_not_a_later_one():
    messages = [{"role": "system", "content": "You are an agent."}]
    ref = _prefix_sample({"messages": messages, "tools": [_tool("a"), _tool("b"), _tool("c")]})
    busted = _prefix_sample({"messages": messages, "tools": [_tool("a"), _tool("Z"), _tool("Q")]})
    attribution = attribute_bust(busted, ref, "r5")
    # First diverging tool is index 1, even though index 2 also differs.
    assert attribution.segment == "tools[1]"


def test_attribute_reports_diverging_message_when_tools_stable():
    ref = _prefix_sample(
        {"messages": [{"role": "system", "content": "stable system"}], "tools": [_tool("a")]}
    )
    busted = _prefix_sample(
        {"messages": [{"role": "system", "content": "CHANGED system"}], "tools": [_tool("a")]}
    )
    attribution = attribute_bust(busted, ref, "r9")
    assert attribution.diverged
    # The tool block is identical; the first divergence is the system message.
    assert "system" in attribution.segment


def test_attribute_clean_diff_when_identical_states_server_side_only():
    sample = _prefix_sample({"messages": [{"role": "user", "content": "hi"}]})
    attribution = attribute_bust(sample, sample, "r1")
    assert not attribution.diverged
    assert attribution.segment is None
    assert "server-side" in attribution.message.lower()


def test_attribution_always_states_honesty_caveat():
    messages = [{"role": "user", "content": "hi"}]
    ref = _prefix_sample({"messages": messages, "tools": [_tool("a")]})
    busted = _prefix_sample({"messages": messages, "tools": [_tool("b")]})
    attribution = attribute_bust(busted, ref, "r2")
    assert HONESTY_CAVEAT in attribution.message


def test_suggest_reorder_surfaces_segment_attribution():
    messages = [{"role": "system", "content": "You are an agent."}]
    s1 = _prefix_sample({"messages": messages, "tools": [_tool("read"), _tool("write")]})
    s2 = _prefix_sample({"messages": messages, "tools": [_tool("read"), _tool("MOVED")]})
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": s1},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": s2},
    ]
    suggestion = suggest_reorder(profile(records))
    assert suggestion is not None
    assert suggestion.attribution is not None
    assert suggestion.attribution.segment == "tools[1]"
    assert "tools[1]" in suggestion.message
    assert "server-side" in suggestion.message.lower()


def test_attribute_never_mutates_inputs():
    messages = [{"role": "system", "content": "s"}]
    tools = [_tool("a"), _tool("b")]
    before = _prefix_sample({"messages": messages, "tools": tools})
    attribute_bust(before, before, "r1")
    # The request structures are untouched (detect-only).
    assert messages == [{"role": "system", "content": "s"}]
    assert tools[0]["function"]["name"] == "a"


# --- fix-prefix-sample-truncates-mid-segment --------------------------------


def _big_tool(name: str, size: int) -> dict:
    """A tool whose serialized form is ~`size` chars (to exercise the budget)."""
    pad = "x" * max(0, size - 60)
    return {
        "type": "function",
        "function": {"name": name, "description": f"call {name} {pad}", "parameters": {}},
    }


def test_prefix_sample_never_truncates_a_segment_mid_way():
    # A 2000-char tool fits the 2048 budget; a following 100-char tool does NOT
    # fit the remaining ~48-char budget. The old code appended every tool and
    # then did `sample[:2048]`, cutting the second tool mid-segment. The fix
    # drops the overflow segment whole, so the sample ends at a clean segment
    # boundary and is <= _PREFIX_SAMPLE_CHARS.
    from dscache.wrapper import _PREFIX_SAMPLE_CHARS, _prefix_sample

    sample = _prefix_sample(
        {
            "messages": [{"role": "system", "content": "hi"}],
            "tools": [_big_tool("a", 2000), _big_tool("b", 100)],
        }
    )
    assert sample is not None
    assert len(sample) <= _PREFIX_SAMPLE_CHARS
    # The first tool is present whole; the second (overflow) is absent; the
    # message fits the remaining budget and is present whole.
    assert sample.startswith("tools[0]:")
    assert "tools[1]" not in sample  # overflow tool dropped, not truncated
    # Message content is json-quoted (fix
    # fix-multiline-content-breaks-segment-attribution) -> `system:"hi"`.
    assert sample.endswith('\nsystem:"hi"')  # message landed at a clean boundary
    # No segment is cut mid-way: every line is a complete segment.
    for line in sample.split("\n"):
        assert line.startswith(("tools[", "system:"))


def test_prefix_sample_oversized_single_tool_falls_back_to_messages():
    # A single tool too big for the whole budget is skipped entirely (it would
    # truncate mid-segment), and the message is sampled instead — a faithful
    # lower bound, never a corrupt stub.
    from dscache.wrapper import _PREFIX_SAMPLE_CHARS, _prefix_sample

    sample = _prefix_sample(
        {
            "messages": [{"role": "system", "content": "stable message"}],
            "tools": [_big_tool("huge", _PREFIX_SAMPLE_CHARS + 500)],
        }
    )
    assert sample is not None
    assert "tools[0]" not in sample  # oversized tool dropped whole
    assert 'system:"stable message"' in sample  # json-quoted content (fix-multiline)


def test_prefix_sample_message_divergence_visible_when_tools_fit_budget():
    # Two requests with IDENTICAL small tools but a diverged system message
    # must produce DIFFERENT fingerprints — the message divergence is not
    # hidden behind the tool head (the fix keeps the cap at segment boundaries
    # so messages are sampled when they fit the remaining budget).
    from dscache.wrapper import _prefix_sample

    msgs_a = [{"role": "system", "content": "prefix A"}]
    msgs_b = [{"role": "system", "content": "prefix B"}]
    tools = [_tool("read"), _tool("write")]
    a = _prefix_sample({"messages": msgs_a, "tools": tools})
    b = _prefix_sample({"messages": msgs_b, "tools": tools})
    assert a is not None and b is not None
    assert a != b  # message divergence visible


# --- fix-multiline-content-breaks-segment-attribution ----------------------


def test_multiline_content_does_not_shatter_segment_attribution():
    # _prefix_sample joins segments with "\n" and attribute._split_segments
    # splits on "\n"; the wrapper used to embed message content RAW, so a
    # system/user prompt with a literal "\n" (the common coding-agent case)
    # was shattered into N spurious "segment[K]" labels and attribute_bust
    # reported a meaningless stable_through instead of naming the message that
    # diverged. Reproduced: "Rules:\n1. Do X" vs "...1. Do Y" yielded
    # segment="segment[1]", stable_through="segments[0..0]". The fix
    # serializes content via _serialize_value (json.dumps, which escapes "\n")
    # so "\n" is an unambiguous separator and the diverging segment labels the
    # system message, not "segment[K]" (fix
    # fix-multiline-content-breaks-segment-attribution).
    ref = _prefix_sample(
        {"messages": [{"role": "system", "content": "Rules:\n1. Do X\n2. Do Z"}]}
    )
    busted = _prefix_sample(
        {"messages": [{"role": "system", "content": "Rules:\n1. Do Y\n2. Do Z"}]}
    )
    assert ref is not None and busted is not None
    # The whole multi-line system message is ONE segment — no embedded "\n" to
    # shatter the split. (Under the old raw-content code both samples contained
    # literal "\n" and split into 3 spurious segments.)
    assert "\n" not in ref
    assert "\n" not in busted
    attribution = attribute_bust(busted, ref, "r17")
    assert attribution.diverged
    # The diverging segment names the system message, not an opaque
    # "segment[K]" label — the advertised "which message index" granularity is
    # preserved on every real multi-line coding-agent prompt.
    assert "system" in attribution.segment
    assert not attribution.segment.startswith("segment[")
    assert "r17" in attribution.message


def test_multiline_content_attribution_end_to_end_via_profile():
    # End-to-end: two profiled requests share the stable head but the second
    # busts the cache with a diverged multi-line system message. suggest_reorder
    # surfaces an attribution that names the system message (not "segment[K]"),
    # proving the fix holds through the wrapper -> profiler -> reorder path.
    from dscache.reorder import suggest_reorder

    s_stable = _prefix_sample(
        {"messages": [{"role": "system", "content": "Rules:\n1. Do X\n2. Do Z"}]}
    )
    s_busted = _prefix_sample(
        {"messages": [{"role": "system", "content": "Rules:\n1. Do Y\n2. Do Z"}]}
    )
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": s_stable},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": s_busted},
    ]
    suggestion = suggest_reorder(profile(records))
    assert suggestion is not None
    assert suggestion.attribution is not None
    assert "system" in suggestion.attribution.segment
    assert not suggestion.attribution.segment.startswith("segment[")


# --- feat-byte-level-prefix-divergence-attribution --------------------------
#
# v0.6.0 deepened attribute.py from segment-level to BYTE granularity: the
# attribution now names the first diverging SEGMENT AND the exact diverging
# BYTE offset within it (``byte_offset``), so a bust tells the user *where* in
# the segment the client prefix broke, not just *which* segment. This folds
# cacheguard's byte-level prefix-mutation linter into dscache's OWN attribute
# path as DETECTION-only deepening — strictly detect-and-attribute, never
# mutates (the cacheguard prefix-MUTATION capability is DROPPED).


def test_attribute_byte_offset_within_diverging_segment():
    # Two single-segment heads that share a leading stable span then diverge.
    # The diverging byte offset is the byte position where 'X' vs 'Y' starts.
    shared_prefix = "tools[0]:stableprefix"
    ref = f"{shared_prefix}X"
    busted = f"{shared_prefix}Y"
    attribution = attribute_bust(busted, ref, "r17")
    assert attribution.diverged
    assert attribution.segment == "tools[0]"
    # The byte offset is the length of the shared UTF-8 prefix.
    assert attribution.byte_offset == len(shared_prefix.encode("utf-8"))
    assert f"byte offset {attribution.byte_offset}" in attribution.message
    assert "tools[0]" in attribution.message
    assert "r17" in attribution.message


def test_attribute_byte_offset_none_when_clean_diff():
    # Byte-identical heads -> no client-side divergence; byte_offset stays None
    # and the stable message carries no "byte offset" clause.
    sample = "tools[0]:same"
    attribution = attribute_bust(sample, sample, "r1")
    assert not attribution.diverged
    assert attribution.segment is None
    assert attribution.byte_offset is None
    assert "byte offset" not in attribution.message
    assert "server-side" in attribution.message.lower()


def test_attribute_byte_offset_zero_when_segment_appended():
    # ref has 1 segment; busted appends a 2nd segment. The divergence is the
    # appended segment, whose first diverging byte is offset 0 (the whole
    # segment is new). Guards the length-divergence branch.
    ref = "system:stable"
    busted = "system:stable\nuser:new"
    attribution = attribute_bust(busted, ref, "r9")
    assert attribution.diverged
    assert "user" in attribution.segment
    assert attribution.byte_offset == 0
    assert "byte offset 0" in attribution.message


def test_attribute_byte_offset_zero_when_segment_removed():
    # Mirror: busted has 1 segment; ref had 2 (busted removed the 2nd). The
    # divergence is the removed segment; byte offset is 0 (the segment is gone
    # from byte 0).
    ref = "system:stable\nuser:gone"
    busted = "system:stable"
    attribution = attribute_bust(busted, ref, "r9")
    assert attribution.diverged
    assert attribution.byte_offset == 0
    assert "byte offset 0" in attribution.message


def test_attribute_byte_offset_counts_utf8_bytes_not_chars():
    # The byte offset counts UTF-8 BYTES, not characters — so a non-ASCII prompt
    # still reports a stable, byte-accurate span. The shared prefix
    # "system:语" is 7 ASCII bytes + one 3-byte CJK char (语) = 10 bytes, but
    # only 8 characters. The diverging chars (日 vs 中) differ at their FIRST
    # UTF-8 byte (日 = e6.., 中 = e4..), so the divergence lands exactly at
    # byte 10. Char-counting would put it at 8; byte-counting puts it at 10.
    shared = "system:语"  # 语 = U+8BED (3 UTF-8 bytes) -> 10 bytes / 8 chars
    ref = f"{shared}日"     # 日 = U+65E5 -> e6 97 a5
    busted = f"{shared}中"  # 中 = U+4E2D -> e4 b8 ad  (first byte != 日's)
    attribution = attribute_bust(busted, ref, "r1")
    assert attribution.diverged
    assert attribution.byte_offset == len(shared.encode("utf-8"))  # 10 bytes
    assert attribution.byte_offset == 10
    assert attribution.byte_offset != len(shared)  # 8 chars — not the char count


def test_attribute_byte_offset_locates_divergence_in_a_later_segment():
    # Segments 0 and 1 are byte-identical; the divergence is in segment 2. The
    # byte offset is WITHIN segment 2 (not an absolute head offset), starting
    # at the position where the two tools[2] serializations differ.
    stable_a = "tools[0]:A"
    stable_b = "tools[1]:B"
    ref = f"{stable_a}\n{stable_b}\ntools[2]:sameprefixX"
    busted = f"{stable_a}\n{stable_b}\ntools[2]:sameprefixY"
    attribution = attribute_bust(busted, ref, "r5")
    assert attribution.diverged
    assert attribution.segment == "tools[2]"
    # The byte offset is within tools[2]: len("tools[2]:sameprefix") bytes.
    within_seg_shared = "tools[2]:sameprefix"
    assert attribution.byte_offset == len(within_seg_shared.encode("utf-8"))
    # The stable span covers segments 0..1.
    assert attribution.stable_through == "segments[0..1]"


def test_byte_level_attribution_surfaces_through_suggest_reorder():
    # End-to-end: a reordered tool list busts the cache; suggest_reorder's
    # attribution names the diverging segment AND surfaces a byte offset
    # within it (the byte granularity flows wrapper -> profiler -> reorder).
    messages = [{"role": "system", "content": "You are an agent."}]
    s_ref = _prefix_sample(
        {"messages": messages, "tools": [_tool("read"), _tool("write"), _tool("grep")]}
    )
    s_busted = _prefix_sample(
        {"messages": messages, "tools": [_tool("read"), _tool("write"), _tool("DIFFERENT")]}
    )
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": s_ref},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": s_busted},
    ]
    suggestion = suggest_reorder(profile(records))
    assert suggestion is not None
    assert suggestion.attribution is not None
    assert suggestion.attribution.segment == "tools[2]"
    # The diverging byte sits inside the tools[2] serialization (after the
    # shared "tools[2]:" + json preamble), so it is a positive offset.
    assert suggestion.attribution.byte_offset is not None
    assert suggestion.attribution.byte_offset > 0
    assert "byte offset" in suggestion.message


def test_byte_level_attribution_never_mutates_inputs():
    # The byte-level deepening stays detect-only — it must never rewrite the
    # request (the cacheguard prefix-MUTATION capability is DROPPED, consistent
    # with dscache's "suggest only, never mutate" thesis).
    messages = [{"role": "system", "content": "s"}]
    tools = [_tool("a"), _tool("b")]
    before = _prefix_sample({"messages": messages, "tools": tools})
    ref = _prefix_sample({"messages": messages, "tools": [_tool("a"), _tool("c")]})
    attribution = attribute_bust(before, ref, "r1")
    assert attribution.diverged
    assert attribution.byte_offset is not None
    # Nothing mutated: the request structures and samples are untouched.
    assert messages == [{"role": "system", "content": "s"}]
    assert tools[0]["function"]["name"] == "a"
    assert tools[1]["function"]["name"] == "b"


# --- fix-suggest-reorder-names-diverging-segment ----------------------------
#
# v0.8.0 tightens suggest_reorder's actionable "Pin X" clause to name the
# actual diverging segment the attribution already computed, instead of a
# generic "Pin the system prompt and tool list" that misleads when the bust is
# in a user message or a specific tool (the v0.7.0 changelog flagged this gap
# as an open question but did not implement it).


def test_suggest_reorder_pins_actual_diverging_user_segment_not_generic():
    # fix-suggest-reorder-names-diverging-segment: the actionable "Pin X" clause
    # names the actual diverging segment the attribution computed, not a generic
    # "Pin the system prompt and tool list". Here the tools AND system message
    # are identical and the divergence is in the USER message, so the suggestion
    # must tell the user to pin the user message, not the system prompt.
    messages_ref = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": "do X"}]
    messages_busted = [{"role": "system", "content": "sys"},
                       {"role": "user", "content": "do Y"}]
    tools = [_tool("read")]
    s_ref = _prefix_sample({"messages": messages_ref, "tools": tools})
    s_busted = _prefix_sample({"messages": messages_busted, "tools": tools})
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": s_ref},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": s_busted},
    ]
    suggestion = suggest_reorder(profile(records))
    assert suggestion is not None
    assert suggestion.attribution is not None
    assert suggestion.attribution.segment is not None
    assert "user" in suggestion.attribution.segment  # divergence is the user msg
    # The actionable Pin clause names the user segment, not the generic line.
    assert "Pin user" in suggestion.message
    assert "system prompt and tool list" not in suggestion.message


def test_suggest_reorder_keeps_generic_pin_when_no_client_divergence():
    # When the attribution found NO client-side divergence (segment is None —
    # the sampled heads are byte-identical, a server-side eviction that still
    # registered as a lower-bound bust because the real cache key diverged past
    # the 2048-char sample), the generic "Pin the system prompt and tool list"
    # fallback is the honest answer (no specific segment to name).
    sample = "system:stable\nuser:a"
    records = [
        {"request_id": "r1", "prompt_tokens": 1000, "cached_tokens": 980,
         "miss_tokens": 20, "prefix_sample": sample},
        {"request_id": "r2", "prompt_tokens": 1000, "cached_tokens": 20,
         "miss_tokens": 980, "prefix_sample": sample},  # SAME sampled head
    ]
    suggestion = suggest_reorder(profile(records))
    assert suggestion is not None
    assert suggestion.attribution is not None
    assert suggestion.attribution.segment is None  # clean diff / server-side
    # Generic fallback: no specific segment to name.
    assert "system prompt and tool list" in suggestion.message
    assert "Pin user" not in suggestion.message
