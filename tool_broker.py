"""
Tool broker -- the authorization boundary between model output and the database.

Previously /chat regex-matched <FETCH_DB:(\\d+)> out of the model's own output and called
database.get_customer_profile with whatever ID appeared there. That made the model the
authorizer of its own reads: whoever could phrase a request could reach any record, and
/demo_chat reached the same data by synthesising tool calls from keyword matches without
the model's involvement at all.

A regex over model text is not an authorization boundary. This module makes the boundary
explicit:

    parse_tool_calls()  -- what did the model ask for?
    authorize()         -- is the *caller* entitled to that?
    execute()           -- only then, run it.

The <FETCH_DB:ID> wire syntax is unchanged, so system prompts and models need no edits.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import auth
import database
import diff_engine
from auth import Principal

# The model may only name tools declared here. An unknown tool name is a refusal, not a
# dispatch attempt.
TOOL_FETCH_DB = "FETCH_DB"

_CALL_PATTERN = re.compile(r"<(?P<tool>[A-Z_]+):(?P<argument>[^>\s]{1,64})>")

# Record IDs are either an integer customer/spender ID or one of the named misc_data
# rows. Anything else is rejected before it reaches the database layer.
_NAMED_RECORDS = ("swiggy", "iban")


@dataclass(frozen=True)
class ToolCall:
    tool: str
    argument: str

    def __str__(self) -> str:
        return f"<{self.tool}:{self.argument}>"


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    allowed: bool
    data: Optional[str] = None
    refusal: Optional[str] = None


def parse_tool_calls(model_text: str) -> list:
    """
    Extract declared tool calls from model output, in the order they appear.

    Unknown tool names are dropped here and reported by caller-side logging -- they are
    not passed through to authorization, because there is nothing to authorize against.
    """
    calls = []
    for match in _CALL_PATTERN.finditer(model_text or ""):
        tool = match.group("tool")
        if tool != TOOL_FETCH_DB:
            logging.warning(f"Tool broker: ignoring undeclared tool '{tool}'")
            continue
        calls.append(ToolCall(tool=tool, argument=match.group("argument")))
    return calls


def make_call(tool: str, argument) -> ToolCall:
    """
    Build a tool call directly, for paths that bypass the model.

    /demo_chat decides some tool calls from keyword matches rather than model output.
    Those reach the same data and so must pass through the same authorization -- this is
    how they enter the broker.
    """
    return ToolCall(tool=tool, argument=str(argument))


def _validate_argument(call: ToolCall) -> Optional[str]:
    """Return None when the argument is well-formed, else a reason string."""
    argument = call.argument.strip()

    if not argument:
        return "empty record identifier"

    if argument.lower() in _NAMED_RECORDS:
        return None

    if not argument.isdigit():
        return f"record identifier '{argument}' is neither a number nor a known record name"

    return None


def authorize(principal: Principal, call: ToolCall) -> ToolResult:
    """
    Decide whether this caller may run this call. No database access happens here.

    Refusals are alarmed as TOOL_ABUSE, because a request for a record the caller is not
    entitled to is a signal worth reviewing even when it was the model's idea.
    """
    if call.tool != TOOL_FETCH_DB:
        return ToolResult(
            call=call,
            allowed=False,
            refusal=f"Tool '{call.tool}' is not available.",
        )

    invalid_reason = _validate_argument(call)
    if invalid_reason:
        _alarm(principal, call, invalid_reason)
        return ToolResult(
            call=call,
            allowed=False,
            refusal="That record identifier is not valid.",
        )

    if not auth.may_read_record(principal, call.argument):
        _alarm(
            principal,
            call,
            f"principal '{principal.name}' is not entitled to record '{call.argument}'",
        )
        return ToolResult(
            call=call,
            allowed=False,
            refusal=(
                "You are not authorized to view that record. "
                "Tell the user their access does not cover it, and do not guess the contents."
            ),
        )

    return ToolResult(call=call, allowed=True)


def execute(principal: Principal, call: ToolCall) -> ToolResult:
    """
    Authorize, then run. The only path from model output to the database.

    database.get_customer_profile is used unchanged -- it is already parameterized, so
    the risk this closes is authorization, not injection.
    """
    decision = authorize(principal, call)
    if not decision.allowed:
        logging.warning(
            f"Tool broker: REFUSED {call} for principal '{principal.name}' ({principal.role})"
        )
        return decision

    data = database.get_customer_profile(call.argument)
    logging.info(f"Tool broker: allowed {call} for principal '{principal.name}'")
    return ToolResult(call=call, allowed=True, data=data)


def _alarm(principal: Principal, call: ToolCall, reason: str) -> None:
    try:
        diff_engine.generate_tool_abuse_alarm(
            principal_name=principal.name,
            principal_role=principal.role,
            tool_call=str(call),
            reason=reason,
        )
    except Exception as e:  # an alarm failure must not mask the refusal itself
        logging.error(f"Tool broker: failed to raise TOOL_ABUSE alarm: {e}")
