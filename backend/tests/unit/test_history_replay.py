"""`build_history` — the fold and the repair.

No database: `build_history` is pure, and detached EventRecord objects construct
fine without a session. That is the entire reason it was split out of
`load_history`, and it is why these run in milliseconds.

This is the most intricate logic in the codebase and the most expensive to get
wrong: every failure here is a 400 from the provider on a real conversation,
and two of them wedge that conversation permanently.
"""

from typing import Any

from app.llm.types import TextBlock, ToolResultBlock, ToolUseBlock
from app.models import EventRecord
from app.services.transcript_service import INTERRUPTED_TOOL_RESULT, build_history


def event(type_: str, **data: Any) -> EventRecord:
    return EventRecord(type=type_, data=data)


def user(text: str) -> EventRecord:
    return event("user_message", text=text)


def assistant(text: str) -> EventRecord:
    return event("assistant_message", text=text)


def tool_call(tool_use_id: str, name: str = "find_patients") -> EventRecord:
    return event("tool_call", tool_use_id=tool_use_id, name=name, input={"timezone": "UTC"})


def tool_result(tool_use_id: str, content: str = "noon") -> EventRecord:
    return event("tool_result", tool_use_id=tool_use_id, content=content, is_error=False)


def test_folds_consecutive_events_by_the_same_speaker_into_one_turn():
    """Text-then-tool-call is ONE assistant turn, and the results are one user turn.

    The provider requires this. Get it wrong and every conversation involving a
    tool fails — which a manual smoke test of a plain chat never reveals.
    """
    history = build_history(
        [
            user("what time is it"),
            assistant("let me check"),
            tool_call("toolu_1"),
            tool_result("toolu_1"),
            assistant("it is noon"),
        ]
    )

    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]
    assert [len(m.content) for m in history] == [1, 2, 1, 1]
    assert isinstance(history[1].content[0], TextBlock)
    assert isinstance(history[1].content[1], ToolUseBlock)


def test_orphaned_tool_call_gets_a_synthetic_error_result():
    """The closed-tab case, and not a hypothetical one.

    A tool call with no result is rejected outright by the provider, so without
    this repair the conversation can never be continued again.
    """
    history = build_history([user("what time is it"), assistant(""), tool_call("toolu_1")])

    assert [m.role for m in history] == ["user", "assistant", "user"]
    repair = history[-1].content[0]
    assert isinstance(repair, ToolResultBlock)
    assert repair.tool_use_id == "toolu_1"
    assert repair.is_error
    assert repair.content == INTERRUPTED_TOOL_RESULT


def test_repair_lands_before_the_next_user_message_and_merges_with_real_results():
    """Two calls, one answered, then the user speaks.

    The repaired result must join the *same* user turn as the real one and come
    before the user's text — two consecutive user turns is a protocol error, and
    a tool_result after a text block is rejected. This is the subtlest branch in
    the codebase and the one least likely to survive a well-meaning refactor.
    """
    history = build_history(
        [
            user("do two things"),
            tool_call("toolu_a"),
            tool_call("toolu_b"),
            tool_result("toolu_b"),
            user("actually never mind"),
        ]
    )

    assert [m.role for m in history] == ["user", "assistant", "user"]
    kinds = [type(block).__name__ for block in history[2].content]
    assert kinds == ["ToolResultBlock", "ToolResultBlock", "TextBlock"]

    repaired, real, _text = history[2].content
    assert isinstance(repaired, ToolResultBlock)
    assert repaired.tool_use_id == "toolu_a"
    assert repaired.is_error
    assert isinstance(real, ToolResultBlock)
    assert real.tool_use_id == "toolu_b"
    assert not real.is_error


def test_empty_assistant_message_is_dropped_but_its_tool_call_survives():
    """A response that was nothing but a tool call.

    The row exists — it carries that call's token counts — but an empty text
    block is a request validation error, so it must not be replayed.
    """
    history = build_history(
        [user("hi"), assistant(""), tool_call("toolu_1"), tool_result("toolu_1")]
    )

    assert [m.role for m in history] == ["user", "assistant", "user"]
    assert len(history[1].content) == 1
    assert isinstance(history[1].content[0], ToolUseBlock)


def test_empty_history_and_unknown_event_types_are_survivable():
    assert build_history([]) == []
    assert build_history([event("something_from_the_future", text="?")]) == []
