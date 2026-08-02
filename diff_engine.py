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

def generate_alarm(raw_text: str, missing_finding: dict, l1_entities: list, l2_entities: list):
    """
    Creates and saves an alarm object for the dashboard.
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
    
    save_alarm(alarm)
    logging.warning(f"🚨 ALARM GENERATED: Phi-4 found unmasked {alarm['missed_entity']['type']} (Category: {category})")
    
    # 2. Dispatch to Subscribers
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            subscribers = data.get("notification_subscribers", [])
            for sub in subscribers:
                # If subscriber wants ALL alerts, or their type matches the category, or it's UNCATEGORIZED (send to ALL)
                if sub.get("alert_type") == "ALL" or sub.get("alert_type") == category or (category == "UNCATEGORIZED" and sub.get("alert_type") == "ALL"):
                    # Send Email Alert if configured
                    if sub.get("email"):
                        EmailNotifier.send_alarm_email(sub.get("email"), alarm, f"{sub.get('role')} ({sub.get('alert_type')})")
    except Exception as e:
        logging.error(f"Failed to route notifications: {str(e)}")

    return alarm

def run_diff(raw_text: str, layer1_results: list, layer2_results: dict):
    """
    Compares Presidio results with LLM results.
    layer1_results: list of presidio AnalyzerResult objects (or dicts with entity_type, start, end)
    layer2_results: dict from llm_watchdog
    """
    if not layer2_results.get("has_sensitive_data", False):
        return None # LLM found nothing, no alarm

    l2_findings = layer2_results.get("findings", [])
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
            generate_alarm(raw_text, finding, l1_entity_types, l2_entity_types)
            alarms_triggered += 1
            
    return alarms_triggered

def generate_toxicity_alarm(raw_text: str, toxicity_result: dict, direction: str = "EGRESS"):
    """
    Creates and saves an alarm for toxic content detected by the detoxify model.
    
    Args:
        raw_text: The original text that was analyzed
        toxicity_result: Result dict from toxicity_guard.analyze()
        direction: "INGRESS" (user input) or "EGRESS" (AI output)
    """
    # Load settings to check if LLM Watchdog (secondary threat engine) is enabled.
    # The user's request implies that if the secondary threat engine is off,
    # then toxicity alerts should also not be generated.
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            settings = data.get("settings", {})
            if not settings.get("enable_llm_watchdog", False):
                logging.info("Skipping toxicity alarm generation because LLM Watchdog (secondary threat engine) is disabled.")
                return None
    except Exception as e:
        logging.error(f"Failed to load PII settings for toxicity alarm check: {e}. Assuming LLM Watchdog is disabled, skipping toxicity alarm.")
        return None # If settings can't be read, assume watchdog is off and skip alarm.

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
    
    save_alarm(alarm)
    logging.warning(f"🚨 TOXICITY ALARM: {direction} — {toxicity_result.get('triggered_categories')} (max: {toxicity_result.get('max_category')} @ {toxicity_result.get('max_score')})")
    
    # Dispatch to subscribers who want TOXICITY or ALL alerts
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            subscribers = data.get("notification_subscribers", [])
            for sub in subscribers:
                if sub.get("alert_type") in ("ALL", "TOXICITY"):
                    if sub.get("email"):
                        EmailNotifier.send_alarm_email(sub.get("email"), alarm, f"{sub.get('role')} ({sub.get('alert_type')})")
    except Exception as e:
        logging.error(f"Failed to route toxicity notifications: {str(e)}")
    
    return alarm
