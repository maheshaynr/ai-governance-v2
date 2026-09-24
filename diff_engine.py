import json
import os
import uuid
from datetime import datetime
import logging
from notifications import EmailNotifier

ALARMS_FILE = "alarms.json"
ARCHIVE_FILE = "alarms_archive.json"

def load_alarms():
    if not os.path.exists(ALARMS_FILE):
        return []
    try:
        with open(ALARMS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def load_archive():
    if not os.path.exists(ARCHIVE_FILE):
        return []
    try:
        with open(ARCHIVE_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_alarm(alarm):
    alarms = load_alarms()
    alarms.insert(0, alarm)  # Prepend new alarm
    with open(ALARMS_FILE, "w") as f:
        json.dump(alarms, f, indent=2)

    archive = load_archive()
    archive.insert(0, alarm)
    with open(ARCHIVE_FILE, "w") as f:
        json.dump(archive, f, indent=2)

def _new_alarm(severity: str, category: str, **fields):
    """Build an alarm with the identifier/timestamp shape the dashboard expects."""
    alarm = {
        "alarm_id": f"ALM-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}",
        "severity": severity,
        "category": category,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "PENDING_REVIEW",
    }
    alarm.update(fields)
    return alarm


def _dispatch_to_subscribers(alarm: dict):
    """
    Email the subscribers who asked for this alarm's category, or for everything.

    Shared by every alarm generator so a new alarm category is routed without copying
    the subscriber loop again.
    """
    category = alarm.get("category", "UNCATEGORIZED")
    try:
        with open("pii_rules.json", "r") as f:
            subscribers = json.load(f).get("notification_subscribers", [])

        for sub in subscribers:
            if sub.get("alert_type") not in ("ALL", category):
                continue
            if sub.get("email"):
                EmailNotifier.send_alarm_email(
                    sub.get("email"), alarm, f"{sub.get('role')} ({sub.get('alert_type')})"
                )
    except Exception as e:
        logging.error(f"Failed to route notifications for {category}: {str(e)}")


def generate_tool_abuse_alarm(principal_name: str, principal_role: str, tool_call: str, reason: str):
    """
    Raised when a tool call is refused -- an unentitled record, or a malformed identifier.

    Worth reviewing even when the model originated the request, because a model asking
    for records the caller cannot see is either a prompt-injection symptom or a broken
    system prompt.
    """
    alarm = _new_alarm(
        "CRITICAL",
        "TOOL_ABUSE",
        tool_detail={
            "principal": principal_name,
            "role": principal_role,
            "tool_call": tool_call,
            "reason": reason,
        },
        context_snippet=f"Refused {tool_call} for {principal_name} ({principal_role}): {reason}",
    )

    save_alarm(alarm)
    logging.warning(f"🚨 TOOL ABUSE ALARM: {tool_call} refused for {principal_name} — {reason}")
    _dispatch_to_subscribers(alarm)
    return alarm


def generate_consent_violation_alarm(principal_name: str, principal_role: str, customer_id,
                                     data_category: str, purpose: str, reason: str):
    """
    Raised when a data read is refused because the customer never consented to it for the
    declared purpose (or no purpose was declared at all).

    Distinct from TOOL_ABUSE: an entitlement refusal is about who is asking; this is about
    whether the customer's own data can be used this way regardless of who asks -- the
    two are independent axes, and conflating them into one alarm category would lose that
    distinction for anyone reviewing the dashboard.
    """
    alarm = _new_alarm(
        "CRITICAL",
        "CONSENT_VIOLATION",
        consent_detail={
            "principal": principal_name,
            "role": principal_role,
            "customer_id": str(customer_id),
            "data_category": data_category,
            "purpose": purpose,
            "reason": reason,
        },
        context_snippet=(
            f"Refused {data_category} read for customer {customer_id} "
            f"(purpose: {purpose or 'none declared'}): {reason}"
        ),
    )

    save_alarm(alarm)
    logging.warning(
        f"🚨 CONSENT VIOLATION ALARM: customer {customer_id} {data_category}/{purpose} — {reason}"
    )
    _dispatch_to_subscribers(alarm)
    return alarm


def generate_injection_alarm(raw_text: str, injection_result: dict, direction: str = "INGRESS",
                             detected_by: str = "layer1"):
    """
    Raised when prompt-injection or SQL-injection indicators are found in text.

    detected_by distinguishes the inline local model ("layer1") from the background LLM
    watchdog ("layer2"). A layer2 alarm means layer 1 let something through, which is the
    signal to widen the pattern set -- the same relationship the PII pipeline already has
    between Presidio and the watchdog.
    """
    # A pattern match is a deterministic, admin-authored rule firing -- CRITICAL, and it
    # already blocked the request. A classifier-only flag is one model's unconfirmed
    # opinion that did NOT block (see injection_guard's note on false positives on
    # ordinary phrasing); it is worth a human looking at, not a five-alarm fire.
    blocked = injection_result.get("blocking", True)
    severity = "CRITICAL" if blocked else "MEDIUM"

    alarm = _new_alarm(
        severity,
        "INJECTION",
        injection_detail={
            "direction": direction,
            "detected_by": detected_by,
            "blocked": blocked,
            "score": injection_result.get("score", 0.0),
            "label": injection_result.get("label", "unknown"),
            "triggered_patterns": injection_result.get("triggered_patterns", []),
        },
        context_snippet=raw_text[:200] + "..." if len(raw_text) > 200 else raw_text,
    )

    save_alarm(alarm)
    logging.warning(
        f"🚨 INJECTION ALARM ({detected_by}): {direction} — "
        f"{injection_result.get('triggered_patterns') or injection_result.get('label')}"
    )
    _dispatch_to_subscribers(alarm)
    return alarm


def generate_guard_failure_alarm(guard_name: str, error: str, direction: str = "INGRESS"):
    """
    Raised when a guard could not run at all.

    This exists because "the guard says the text is clean" and "the guard failed" used to
    be the same value. A guard that cannot run is an outage of a security control, and it
    needs to be visible rather than logged past.
    """
    alarm = _new_alarm(
        "CRITICAL",
        "GUARD_FAILURE",
        guard_detail={"guard": guard_name, "direction": direction, "error": error},
        context_snippet=f"{guard_name} failed during {direction} check: {error}",
    )

    save_alarm(alarm)
    logging.error(f"🚨 GUARD FAILURE: {guard_name} ({direction}) — {error}")
    _dispatch_to_subscribers(alarm)
    return alarm


def generate_alarm(raw_text: str, missing_finding: dict, l1_entities: list, l2_entities: list,
                    correlation_id: str = None):
    """
    Creates and saves an alarm object for the dashboard.

    correlation_id, when the caller has one, ties this alarm back to the same
    Activity Log row /guardrail_validate already wrote (governance_db.log_activity) --
    lets the dashboard show which agent/principal/device this specific alarm came from
    without duplicating that identity data onto the alarm itself.
    """
    
    # --- INTELLIGENT NOTIFICATION ROUTING CATEGORY ---
    entity_type = missing_finding.get("type", "UNKNOWN").upper()
    category = "UNCATEGORIZED"
    
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            mappings = data.get("category_mappings", {})
            for cat_name, keywords in mappings.items():
                if any(k in entity_type for k in keywords):
                    category = cat_name
                    break
    except Exception as e:
        logging.error(f"Failed to load category mappings: {e}")

    alarm = {
        "alarm_id": f"ALM-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}",
        "severity": "HIGH",
        "category": category,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "missed_entity": {
            "type": missing_finding.get("type", "UNKNOWN"),
            "value_preview": missing_finding.get("value", "")[:15] + "...",  # don't store full PII in plain text if possible, but for admin preview it's ok
            "reason": missing_finding.get("reason", "No reason provided"),
            "detected_by": "phi-4-mini"
        },
        "context_snippet": raw_text[:200] + "..." if len(raw_text) > 200 else raw_text,
        "layer1_findings": l1_entities,
        "layer2_findings": l2_entities,
        "status": "PENDING_REVIEW"
    }
    if correlation_id:
        alarm["correlation_id"] = correlation_id

    save_alarm(alarm)
    logging.warning(f"🚨 ALARM GENERATED: Phi-4 found unmasked {alarm['missed_entity']['type']} (Category: {category})")

    _dispatch_to_subscribers(alarm)
    return alarm

def run_diff(raw_text: str, layer1_results: list, layer2_results: dict, correlation_id: str = None):
    """
    Compares Presidio results with LLM results.
    layer1_results: list of presidio AnalyzerResult objects (or dicts with entity_type, start, end)
    layer2_results: dict from llm_watchdog
    correlation_id: forwarded to generate_alarm, see its docstring.
    """
    if not layer2_results.get("has_sensitive_data", False):
        return None # LLM found nothing, no alarm

    l2_findings = layer2_results.get("findings", [])
    if not l2_findings:
        return None

    # The LLM watchdog's system prompt asks for a list of {"type", "value", "reason"}
    # objects, but a small local model doesn't always follow that shape exactly --
    # confirmed directly: phi4-mini returned a findings list of plain strings for one
    # real input, which crashed the .get() calls below with no defense against it at
    # all. Malformed entries are dropped and logged rather than the whole background
    # task crashing on them.
    malformed = [f for f in l2_findings if not isinstance(f, dict)]
    if malformed:
        logging.warning(f"LLM watchdog returned non-dict findings, dropping: {malformed}")
    l2_findings = [f for f in l2_findings if isinstance(f, dict)]
    if not l2_findings:
        return None

    # Extract the exact text values that Presidio masked
    l1_values = []
    l1_entity_types = []
    for res in layer1_results:
        # Depending on if it's an object or dict
        if hasattr(res, 'start') and hasattr(res, 'end'):
            val = raw_text[res.start:res.end].lower()
            l1_values.append(val)
            l1_entity_types.append(res.entity_type)
        elif isinstance(res, dict):
            val = raw_text[res['start']:res['end']].lower()
            l1_values.append(val)
            l1_entity_types.append(res['entity_type'])

    l2_entity_types = [f.get("type") for f in l2_findings]
    
    alarms_triggered = 0
    
    # Check if Layer 2 found something Layer 1 missed
    for finding in l2_findings:
        l2_val = str(finding.get("value", "")).lower()
        if not l2_val:
            continue
            
        # Very simple diff: Is the string that the LLM found present anywhere in what Presidio masked?
        # Note: In a production system, this could be a more sophisticated fuzzy match or overlap check.
        is_masked = False
        for masked_val in l1_values:
            if l2_val in masked_val or masked_val in l2_val:
                is_masked = True
                break
                
        if not is_masked:
            # LLM found something Presidio didn't!
            generate_alarm(raw_text, finding, l1_entity_types, l2_entity_types, correlation_id=correlation_id)
            alarms_triggered += 1
            
    return alarms_triggered

def generate_toxicity_alarm(raw_text: str, toxicity_result: dict, direction: str = "EGRESS",
                             correlation_id: str = None):
    """
    Creates and saves an alarm for toxic content detected by the detoxify model.

    Args:
        raw_text: The original text that was analyzed
        toxicity_result: Result dict from toxicity_guard.analyze()
        direction: "INGRESS" (user input) or "EGRESS" (AI output)
        correlation_id: see generate_alarm's docstring -- same idea, same source.
    """
    # Toxicity alarms used to be suppressed whenever enable_llm_watchdog was off, and
    # suppressed entirely when the settings file could not be read. Those are independent
    # controls: the toxicity guard has its own enable_toxicity_guard flag, checked by the
    # caller before we get here. An unreadable settings file must not silently discard a
    # detection that already happened.
    alarm = {
        "alarm_id": f"ALM-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}",
        "severity": "CRITICAL",
        "category": "TOXICITY",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "toxicity_detail": {
            "direction": direction,
            "scores": toxicity_result.get("scores", {}),
            "triggered_categories": toxicity_result.get("triggered_categories", []),
            "max_category": toxicity_result.get("max_category", "unknown"),
            "max_score": toxicity_result.get("max_score", 0.0)
        },
        "context_snippet": raw_text[:200] + "..." if len(raw_text) > 200 else raw_text,
        "status": "PENDING_REVIEW"
    }
    if correlation_id:
        alarm["correlation_id"] = correlation_id

    save_alarm(alarm)
    logging.warning(f"🚨 TOXICITY ALARM: {direction} — {toxicity_result.get('triggered_categories')} (max: {toxicity_result.get('max_category')} @ {toxicity_result.get('max_score')})")

    _dispatch_to_subscribers(alarm)
    return alarm
