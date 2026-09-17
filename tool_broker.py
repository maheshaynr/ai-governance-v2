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
import dpdp_client
from auth import Principal

# The model may only name tools declared here. An unknown tool name is a refusal, not a
# dispatch attempt.
TOOL_FETCH_DB = "FETCH_DB"

_CALL_PATTERN = re.compile(r"<(?P<tool>[A-Z_]+):(?P<argument>[^>\s]{1,64})>")

# Record IDs are either an integer customer/spender ID or one of the named misc_data
# rows. Anything else is rejected before it reaches the database layer.
_NAMED_RECORDS = ("swiggy", "iban")

# Scoped to credit card data for this pass -- see dpdp_client.py. Every numeric-ID record
# in this dataset (customers and spenders) carries a card field, so gating on the record
# shape (numeric vs. named) is correct here without inspecting the formatted profile
# string get_customer_profile returns. This is the local alarm/consent_detail vocabulary
# (matches consent.py's own schema) -- distinct from _CONSENT_DPDP_DATA_CATEGORIES below,
# which is what actually goes out over the wire to the DPDP Engine.
_CONSENT_GATED_CATEGORY = "CREDIT_CARD"

# Per API_INTEGRATION.pdf: this is a customer reading their own card/payment reference
# data back, not a disclosure to a third party -- READ, not DISCLOSE_*, and the DPDP
# Engine's registered category for it is PAYMENT_TOKEN, not CREDIT_CARD.
_CONSENT_OPERATION = "READ"
_CONSENT_DPDP_DATA_CATEGORIES = ["PAYMENT_TOKEN"]

CONSENT_REFUSAL_MSG = (
    "This customer has not consented to their card data being used for that purpose. "
    "Tell the user their request cannot be completed, and do not guess the contents."
)


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
    # Populated only on a consent refusal, so api.py can pass it straight into
    # ChatResponse.consent without re-deriving what was checked.
    consent_detail: Optional[dict] = None
    # Populated only when a DPDP consent check ran and allowed the call, so api.py's
    # audit entry can cite the notice version it was granted under without a second
    # lookup call.
    notice_version: Optional[str] = None


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


def authorize(principal: Principal, call: ToolCall, purpose: str = None) -> ToolResult:
    """
    Decide whether this caller may run this call. No database access happens here.

    Refusals are alarmed as TOOL_ABUSE, because a request for a record the caller is not
    entitled to is a signal worth reviewing even when it was the model's idea.

    purpose gates a second, independent question once entitlement passes: not "who may
    read this record" but "was this customer's data ever consented to being used this
    way." No purpose declared is not a bypass -- it means no processing basis was stated,
    which is refused, not defaulted to allowed. See dpdp_client.py.
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

    # Consent Gate. Scoped to numeric customer/spender IDs -- the named misc_data rows
    # (swiggy, iban) carry no card data, so they are untouched by this check.
    #
    # purpose=None (the parameter's default, unpassed) means this call site has not
    # opted into consent gating at all -- /query_db and /demo_chat's keyword paths don't
    # pass it, by design, and must behave exactly as before this feature existed.
    # purpose="" (passed, but nothing declared) DOES opt in and is refused, which is the
    # distinction that makes "no purpose stated" a refusal rather than a silent bypass
    # for /chat specifically, which always passes this parameter. Note "not purpose"
    # short-circuits before any DPDP call -- there is nothing to ask the DPDP Engine
    # when no processing basis was even stated.
    notice_version = None
    if call.argument.isdigit() and purpose is not None:
        if not purpose:
            reason = f"no purpose declared for record '{call.argument}'"
            _alarm_consent(principal, call, purpose, reason)
            return ToolResult(
                call=call,
                allowed=False,
                refusal=CONSENT_REFUSAL_MSG,
                consent_detail={
                    "customer_id": call.argument,
                    "data_category": _CONSENT_GATED_CATEGORY,
                    "purpose": purpose,
                    "granted": False,
                    "reason": reason,
                },
            )

        # Per API_INTEGRATION.pdf: subject_ref must be a stable pseudonym, not the bare
        # internal customer id -- prefix with "U" (customer 101 -> "U101"), the same
        # convention the payment gate's seeded test subjects already follow.
        dpdp_subject_ref = f"U{call.argument}"
        decision = dpdp_client.check_decision(
            subject_ref=dpdp_subject_ref,
            data_categories=_CONSENT_DPDP_DATA_CATEGORIES,
            purpose=purpose,
            operation=_CONSENT_OPERATION,
            policy_context="CHAT_TOOL_CALL",
        )
        if decision["decision"] != "ALLOW":
            reason = (
                f"DPDP decision check failed: {decision.get('error')}" if decision.get("guard_failed")
                else f"customer '{call.argument}' has no granted DPDP consent for "
                     f"{_CONSENT_GATED_CATEGORY}/{purpose} (decision={decision['decision']})"
            )
            _alarm_consent(principal, call, purpose, reason)
            _submit_consent_denied_event(dpdp_subject_ref, purpose, decision)
            return ToolResult(
                call=call,
                allowed=False,
                refusal=CONSENT_REFUSAL_MSG,
                consent_detail={
                    "customer_id": call.argument,
                    "data_category": _CONSENT_GATED_CATEGORY,
                    "purpose": purpose,
                    "granted": False,
                    "reason": reason,
                },
            )
        notice_version = decision.get("notice_version")

    return ToolResult(call=call, allowed=True, notice_version=notice_version)


def execute(principal: Principal, call: ToolCall, purpose: str = None) -> ToolResult:
    """
    Authorize, then run. The only path from model output to the database.

    database.get_customer_profile is used unchanged -- it is already parameterized, so
    the risk this closes is authorization, not injection.
    """
    decision = authorize(principal, call, purpose=purpose)
    if not decision.allowed:
        logging.warning(
            f"Tool broker: REFUSED {call} for principal '{principal.name}' ({principal.role})"
        )
        return decision

    data = database.get_customer_profile(call.argument)
    logging.info(f"Tool broker: allowed {call} for principal '{principal.name}'")
    return ToolResult(call=call, allowed=True, data=data, notice_version=decision.notice_version)


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


def _alarm_consent(principal: Principal, call: ToolCall, purpose: str, reason: str) -> None:
    try:
        diff_engine.generate_consent_violation_alarm(
            principal_name=principal.name,
            principal_role=principal.role,
            customer_id=call.argument,
            data_category=_CONSENT_GATED_CATEGORY,
            purpose=purpose,
            reason=reason,
        )
    except Exception as e:  # an alarm failure must not mask the refusal itself
        logging.error(f"Tool broker: failed to raise CONSENT_VIOLATION alarm: {e}")


def _submit_consent_denied_event(subject_ref: str, purpose: str, decision: dict) -> None:
    """
    Per API_INTEGRATION.pdf's event catalogue: a DPDP outage/timeout is a
    GUARDRAIL_DECISION_FAILURE (a failure of the decision infrastructure, no decision_id),
    not a CONSENT_DENIED (an actual data-processing denial) -- conflating the two would
    misreport infrastructure noise as a real consent violation.
    """
    try:
        if decision.get("guard_failed"):
            dpdp_client.submit_compliance_event(
                event_type="GUARDRAIL_DECISION_FAILURE",
                severity="MEDIUM",
                subject_ref=subject_ref,
                data_categories=_CONSENT_DPDP_DATA_CATEGORIES,
                purpose=purpose,
                operation=_CONSENT_OPERATION,
                decision_id=None,
                reason_code="DPDP_ENGINE_TIMEOUT",
            )
        else:
            dpdp_client.submit_compliance_event(
                event_type="CONSENT_DENIED",
                severity="HIGH",
                subject_ref=subject_ref,
                data_categories=_CONSENT_DPDP_DATA_CATEGORIES,
                purpose=purpose,
                operation=_CONSENT_OPERATION,
                decision_id=decision.get("decision_id"),
                reason_code=decision.get("reason_code") or "CONSENT_NOT_GRANTED",
            )
    except Exception as e:  # a compliance-event failure must not mask the refusal itself
        logging.error(f"Tool broker: failed to submit compliance event: {e}")
