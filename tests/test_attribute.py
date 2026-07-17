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
    # Tools are serialized AHEAD of the message text.
    assert sample.index("tools[0]") < sample.index("system:You are an agent.")


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
    assert sample.endswith("\nsystem:hi")  # message landed at a clean boundary
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
    assert "system:stable message" in sample


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
