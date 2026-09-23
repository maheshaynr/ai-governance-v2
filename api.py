import os
import json
import logging
from collections import deque
from datetime import datetime
import requests
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse
import time
import uuid
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import hashlib
from audit_logger import AuditLogger
from custom_recognizers import AadhaarRecognizer, MedicalEntityRecognizer, TransactionAmountRecognizer
import database
from benchmark_logger import BenchmarkLogger
import llm_watchdog
import diff_engine
import toxicity_guard
import config
import rag_engine
import auth
import consent
import dpdp_client
import governance_db
import agent_auth
import injection_guard
import tool_broker
from notifications import EmailNotifier
from auth import Principal, require_role, ROLE_SUPER_ADMIN, ADMIN_ROLES, ANY_ROLE
from fidelity_check import FidelityChecker

# Upstream calls get an explicit read timeout. Four of the five Ollama calls previously
# passed none, so a stalled model server pinned the worker until the client gave up.
LLM_TIMEOUT = 120

INJECTION_BLOCK_MSG = (
    "⚠️ Your message was blocked by the Injection Shield. It contains instructions that "
    "attempt to override this assistant's configuration, extract its instructions, or "
    "inject database commands. This attempt has been logged. Please rephrase your "
    "request as an ordinary question."
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs after the module is fully imported, so the guard modules have finished their
    # (slow) model loads by now. Names are resolved at call time.
    report = run_guard_self_test()

    if report["status"] != "ready":
        print("\n" + "=" * 72)
        print("GUARDRAIL SELF-TEST: DEGRADED — requests will be refused, not passed.")
        for problem in report["problems"]:
            print(f"  - {problem}")
        print("=" * 72 + "\n")
    else:
        print("Guardrail self-test: all enabled guards loaded.")
        for problem in report["problems"]:
            print(f"  ! {problem}")

    yield


app = FastAPI(title="AI Governance API", lifespan=lifespan)

# Add CORS Middleware to allow the frontend dev server to communicate with the API.
# allow_origin_regex covers ANY localhost port, not just 5173 -- Vite bumps to the next
# free port (5174, 5175, ...) whenever something else already holds the one before it,
# which happened live: the frontend moved to 5174 and every request started failing with
# "No 'Access-Control-Allow-Origin' header is present" because 5174 wasn't in the
# hardcoded list below. The explicit list stays as a visible reference for what's
# actually expected; the regex is what makes a port bump not break things again.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Load Dynamic Presidio Config ---
# Global dynamic entities list
ACTIVE_ENTITIES = []
analyzer = None
anonymizer = AnonymizerEngine()

global_nlp_engine = None

def get_nlp_engine():
    global global_nlp_engine
    if global_nlp_engine is None:
        print("Initializing Global NLP Engine (Heavy Operation)...")
        # Medical entity detection (CHEMICAL/DISEASE) used to be registered here too,
        # under the same "en" lang_code -- Presidio's engine keys its model registry by
        # language code, so the second entry silently overwrote the first, and this
        # general-purpose model never actually ran (confirmed: PERSON returned zero
        # matches at any score threshold). It now runs as its own separate pipeline in
        # custom_recognizers.MedicalEntityRecognizer instead of sharing this slot.
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [
                {"lang_code": "en", "model_name": "en_core_web_lg"}, # General purpose
            ]
        }
        global_nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    return global_nlp_engine

def reload_presidio_engine():
    global analyzer, ACTIVE_ENTITIES
    print("Reloading Presidio Registry and Rules...")
    nlp_engine = get_nlp_engine() # Only the general-purpose model now -- see get_nlp_engine

    new_analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

    ACTIVE_ENTITIES = []

    # Load custom python recognizer (Verhoeff Math)
    new_analyzer.registry.add_recognizer(AadhaarRecognizer())

    # Combines the shared nlp_engine's own MONEY/CARDINAL tagging with India-specific
    # regex patterns -- see custom_recognizers.TransactionAmountRecognizer for the test
    # matrix of what the shared model misses on its own (Rs./lakh/crore/Indian grouping).
    new_analyzer.registry.add_recognizer(TransactionAmountRecognizer())

    # Medical entity recognizer -- its own dedicated pipeline, not the shared
    # nlp_engine (see custom_recognizers.MedicalEntityRecognizer for why).
    try:
        new_analyzer.registry.add_recognizer(MedicalEntityRecognizer())
        ACTIVE_ENTITIES.extend(["DISEASE", "CHEMICAL"])
    except Exception as e:
        print(f"Warning: Failed to load MedicalEntityRecognizer: {e}")


    # Load dynamic JSON rules
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            settings = data.get("settings", {})
            category_mappings = data.get("category_mappings", {})
            rules = data.get("rules", [])
            
            for rule in rules:
                if not rule.get("is_active", True):
                    continue
                    
                entity = rule.get("entity", "").upper()
                
                # Determine rule category
                rule_category = "UNCATEGORIZED"
                for cat_name, keywords in category_mappings.items():
                    if any(k in entity for k in keywords):
                        rule_category = cat_name
                        break
                        
                # Check if category is enabled in settings
                is_category_enabled = True
                if rule_category == "PII" and not settings.get("enable_pii", True):
                    is_category_enabled = False
                elif rule_category == "HEALTH" and not settings.get("enable_health", True):
                    is_category_enabled = False
                elif rule_category == "FINANCIAL" and not settings.get("enable_financial", True):
                    is_category_enabled = False
                elif rule_category == "AUTHENTICATION" and not settings.get("enable_authentication", True):
                    is_category_enabled = False
                    
                if not is_category_enabled:
                    continue
                
                if not rule.get("is_builtin", False) and not rule.get("is_algorithmic", False):
                    pattern = Pattern(name=rule["name"], regex=rule["regex"], score=rule["score"])
                    recognizer = PatternRecognizer(supported_entity=rule["entity"], patterns=[pattern])
                    new_analyzer.registry.add_recognizer(recognizer)
                if rule["entity"] not in ACTIVE_ENTITIES:
                    ACTIVE_ENTITIES.append(rule["entity"])
    except Exception as e:
        print(f"Failed to load pii_rules.json: {e}")
        
    analyzer = new_analyzer

# Perform initial load
reload_presidio_engine()

# Initialize Database
database.init_db()
governance_db.init_db()

# Pre-load RAG Engine
rag_engine.load_knowledge_base()

print("Presidio, Database, and RAG Engine loaded successfully.")

# --- 2. API Models ---
class DbQueryRequest(BaseModel):
    customer_id: int

class GenerativeRequest(BaseModel):
    text: str = Field(max_length=8000)

class GovernResponse(BaseModel):
    masked_output: str
    status: str
    toxicity: Optional[dict] = None
    injection: Optional[dict] = None

class GuardrailValidateRequest(BaseModel):
    text: str = Field(max_length=8000)
    # Optional -- when set, ties this call to the same correlation_id as a paired
    # /v1/agent/decisions/check call, so both sides of one real action (the purpose-gate
    # and the content-mask) can be found together. Generated and echoed back if omitted,
    # same rule as /v1/agent/*'s correlation_id handling.
    correlation_id: Optional[str] = None

class GuardrailValidateResponse(BaseModel):
    flag: str      # "AI Guardrail flag: CLEAR" | "...PARTIAL" | "...BLOCKED" | "...PAYMENT_DECLINED"
    message: str   # original text / masked text / the fixed block or decline message, per flag
    correlation_id: str
    # A short, stable machine-readable code explaining *why* flag is what it is -- meant
    # to be branched on programmatically, not displayed as-is. None for CLEAR, where
    # there's nothing to explain. See _flag_reason_for below for the fixed set of values.
    flag_reason: Optional[str] = None

class RuleRequest(BaseModel):
    name: str
    entity: str
    regex: str
    score: float
    is_builtin: bool = False
    is_algorithmic: bool = False
    is_active: bool = True
    category: str = "UNCATEGORIZED"

class UpdateRuleRequest(BaseModel):
    original_name: str
    name: str
    entity: str
    regex: str
    score: float
    is_builtin: bool = False
    is_algorithmic: bool = False
    is_active: bool = True
    category: str = "UNCATEGORIZED"

class DeleteRuleRequest(BaseModel):
    name: str

class SubscriberRequest(BaseModel):
    user_name: str
    role: str
    alert_type: str
    email: str = ""

class UpdateSubscriberRequest(BaseModel):
    original_user_name: str
    user_name: str
    role: str
    alert_type: str
    email: str = ""

class DeleteSubscriberRequest(BaseModel):
    user_name: str

class DeleteAlarmRequest(BaseModel):
    alarm_id: str
    status: str = "DISMISSED"

class WithdrawConsentRequest(BaseModel):
    customer_id: str
    data_category: str = "CREDIT_CARD"
    purpose: str

class AgentRegisterRequest(BaseModel):
    agent_name: str
    business_unit: str = ""
    owner_name: str = ""
    location_of_deployment: str = ""
    in_house_or_external: str = ""
    # Optional -- see Agent_Governance_Layer_Design.md §12.3. No stable, privacy-appropriate
    # device fingerprint exists on Android today, so this is whatever the caller chooses to
    # send (or omits entirely); it's stored for correlation only, never relied on as an identity
    # guarantee.
    device_id: str = ""

class AgentDecisionCheckRequest(BaseModel):
    principal_ref: str
    purpose: str
    operation: str
    data_categories: list[str]
    recipient_ref: Optional[str] = None
    policy_context: Optional[str] = None
    correlation_id: Optional[str] = None
    # Optional today (older callers omit it); a missing value is treated as "no device
    # context" and only matches an entitlement row whose own device_id is NULL (wildcard).
    device_id: Optional[str] = None

class AgentActivityRequest(BaseModel):
    invoking_user_id: str = ""
    action: str
    outcome: str
    latency_ms: Optional[int] = None
    correlation_id: Optional[str] = None
    # Optional -- this endpoint is non-gating and entirely self-reported (no DPDP call, no
    # Guardrail-side check), so Guardrail has no way to independently determine why a
    # BLOCKED outcome happened here. Unlike /v1/agent/decisions/check and
    # /guardrail_validate, which compute their own reason_code, this is the caller's own
    # explanation, taken at face value and stored as-is.
    reason_code: Optional[str] = None
    # Same persisted per-install value as /v1/agent/decisions/check's device_id -- lets this
    # row be cross-checked against the decisions/check row sharing its correlation_id.
    device_id: Optional[str] = None

class ChatRequest(BaseModel):
    message: str = Field(max_length=8000)
    # Empty string, not None -- /chat always opts into the Consent Gate (see
    # tool_broker.authorize), so "nothing selected" must be a real, checkable value
    # rather than the sentinel tool_broker uses to mean "this endpoint doesn't gate at
    # all." An empty purpose is refused before the DPDP Engine is even asked, the same
    # way a granted-but-mismatched purpose is refused after asking, so it's never
    # silently allowed.
    purpose: str = ""

class ChatResponse(BaseModel):
    # Withheld (None) unless EXPOSE_RAW_OUTPUT is on AND the caller is an admin --
    # see may_see_raw_output. Returning it unconditionally handed back exactly what
    # the pipeline exists to withhold.
    raw_output: Optional[str] = None
    masked_output: str
    status: str
    toxicity: Optional[dict] = None
    injection: Optional[dict] = None
    consent: Optional[dict] = None

class SandboxSuggestRequest(BaseModel):
    context_snippet: str
    missed_entity_type: str
    value_preview: str

class SandboxTestRequest(BaseModel):
    context_snippet: str
    regex_pattern: str
    entity_name: str

# --- 3. The Universal Guardrail Function ---
class GuardSettingsError(Exception):
    """
    Raised when the guard configuration cannot be read.

    This used to be swallowed by a bare `except` that returned enabled=False, so a
    malformed pii_rules.json silently turned the guards off. An unreadable policy file is
    a guard outage, not a policy of "allow everything".
    """


def load_guard_settings() -> dict:
    """Read the settings block from pii_rules.json, or fail loudly."""
    try:
        with open("pii_rules.json", "r") as f:
            return json.load(f).get("settings", {})
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        raise GuardSettingsError(str(e)) from e


def load_toxicity_settings():
    """
    Kept for the /toxicity_settings endpoint, which reports configuration rather than
    gating traffic. On failure it reports the guard as unavailable instead of disabled.
    """
    try:
        settings = load_guard_settings()
    except GuardSettingsError as e:
        return {"enabled": False, "thresholds": {}, "unavailable": True, "error": str(e)}

    return {
        "enabled": settings.get("enable_toxicity_guard", False),
        "thresholds": settings.get("toxicity_thresholds", {}),
    }


def _log_guard_check(log_file_name: str, direction: str, summary: str):
    import datetime
    try:
        with open(log_file_name, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{datetime.datetime.now().isoformat()}] [{direction}] {summary}\n")
    except OSError as e:
        logging.error(f"Failed to write {log_file_name}: {e}")


def _guard_failure(guard_name: str, direction: str, error: str):
    """
    Common handling for "the guard could not run": alarm it, and tell the caller to
    block. Returns the (blocked, result) shape every apply_* check uses.
    """
    try:
        diff_engine.generate_guard_failure_alarm(guard_name, error, direction)
    except Exception as e:
        logging.error(f"Failed to raise GUARD_FAILURE alarm for {guard_name}: {e}")

    return True, {"guard_failed": True, "guard": guard_name, "error": error}


def apply_injection_check(text: str, direction: str = "INGRESS"):
    """
    Layer 1 injection detection -- patterns plus a local classifier.

    Returns (should_block, result). A disabled guard returns (False, None); a guard that
    could not run returns (True, {...guard_failed}) so the caller blocks rather than
    passing unchecked text to a model holding a database tool.
    """
    try:
        settings = load_guard_settings()
    except GuardSettingsError as e:
        return _guard_failure("injection_guard", direction, f"settings unreadable: {e}")

    if not settings.get("enable_injection_guard", False):
        return False, None

    result = injection_guard.analyze(text, settings.get("injection_threshold"))

    if result.get("guard_failed"):
        return _guard_failure("injection_guard", direction, result.get("error", "unknown"))

    _log_guard_check(
        "injection_monitor.log", direction,
        f"Injection: {result['is_injection']} | blocking={result.get('blocking')} "
        f"label={result['label']} score={result['score']} patterns={result['triggered_patterns']}"
    )

    if result["is_injection"]:
        diff_engine.generate_injection_alarm(text, result, direction, detected_by="layer1")

    # A pattern match blocks inline. A classifier-only flag ("blocking": False) is
    # surfaced through the alarm above but does not stop the request -- see
    # injection_guard's note on why an unconfirmed model opinion should not reject
    # ordinary traffic on its own.
    should_block = result["is_injection"] and result.get("blocking", True)
    return should_block, result


def apply_toxicity_check(text: str, direction: str = "EGRESS"):
    """
    Run detoxify toxicity analysis on text.

    Returns (should_block, toxicity_result). A disabled guard returns (False, None); a
    guard that errored returns (True, {...guard_failed}) rather than a clean verdict --
    "the text is clean" and "the check did not happen" must not be the same answer.
    """
    try:
        settings = load_guard_settings()
    except GuardSettingsError as e:
        return _guard_failure("toxicity_guard", direction, f"settings unreadable: {e}")

    if not settings.get("enable_toxicity_guard", False):
        return False, None

    result = toxicity_guard.analyze(text, settings.get("toxicity_thresholds", {}))

    if result.get("guard_failed"):
        return _guard_failure("toxicity_guard", direction, result.get("error", "unknown"))

    _log_guard_check(
        "toxicity_monitor.log", direction,
        f"Toxic: {result['is_toxic']} | Scores: {json.dumps(result['scores'])}"
    )

    if result["is_toxic"]:
        diff_engine.generate_toxicity_alarm(text, result, direction)

    return result["is_toxic"], result


def should_block_toxic_egress() -> bool:
    """
    Whether a toxic model response is blocked or merely flagged.

    The egress verdict used to be computed and then discarded into `_`, so output was
    scored, alarmed, and forwarded regardless. Blocking is now the default and the choice
    is explicit.
    """
    try:
        return load_guard_settings().get("block_toxic_egress", True)
    except GuardSettingsError:
        return True


def may_see_raw_output(principal: Principal) -> bool:
    """
    Unmasked model output is withheld unless a deployment explicitly opts in AND the
    caller is an admin. Returning both raw_output and masked_output on every call hands
    back exactly what the pipeline exists to withhold.
    """
    return bool(config.EXPOSE_RAW_OUTPUT) and principal.is_admin


def guard_failure_response(result: dict) -> str:
    return (
        "⚠️ This request was blocked because a safety check could not be completed "
        f"({result.get('guard', 'guard')}). An administrator has been alerted."
    )

def mask_person_name(name: str) -> str:
    parts = name.split()
    if not parts: return name
    parts[0] = parts[0][:3] + "*" * max(0, len(parts[0]) - 3)
    if len(parts) > 1:
        parts[-1] = parts[-1][:1] + "*" * max(0, len(parts[-1]) - 1)
        for i in range(1, len(parts) - 1):
            parts[i] = "*" * len(parts[i])
    return " ".join(parts)

def apply_egress_guardrail(raw_text: str):
    def mask_email_address(email: str) -> str:
        """
        Masks an email address to the format f*****t@d*****n.com,
        preserving the first and last characters of the username and domain.
        """
        try:
            if "@" not in email:
                return email # Not a valid email format

            username, domain_full = email.split('@', 1)

            # Mask username
            if len(username) > 2:
                masked_username = f"{username[0]}{'*' * (len(username) - 2)}{username[-1]}"
            elif len(username) > 0:
                masked_username = f"{username[0]}*" # Mask all but first for short usernames
            else:
                masked_username = ""

            # Mask domain
            if '.' in domain_full:
                domain_parts = domain_full.split('.')
                domain_name = domain_parts[0]
                tld = ".".join(domain_parts[1:])
                
                if len(domain_name) > 2:
                    masked_domain_name = f"{domain_name[0]}{'*' * (len(domain_name) - 2)}{domain_name[-1]}"
                elif len(domain_name) > 0:
                    masked_domain_name = f"{domain_name[0]}*"
                else:
                    masked_domain_name = ""
                
                return f"{masked_username}@{masked_domain_name}.{tld}"
            else: # Handle domains without TLD like 'localhost'
                if len(domain_full) > 2:
                    masked_domain = f"{domain_full[0]}{'*' * (len(domain_full) - 2)}{domain_full[-1]}"
                elif len(domain_full) > 0:
                    masked_domain = f"{domain_full[0]}*"
                else:
                    masked_domain = ""
                return f"{masked_username}@{masked_domain}"

        except Exception:
            # Failsafe for any unexpected format
            return email[0] + "***" + email[-1] if len(email) > 2 else email

    # We explicitly define the entities we want to track using the global ACTIVE_ENTITIES.
    results = analyzer.analyze(text=raw_text, language='en', entities=ACTIVE_ENTITIES, score_threshold=0.5)

    # entity_denylist: known false positives filtered out here, after every recognizer
    # has run, rather than inside any one of them. Started from "Jio" -- confirmed
    # directly that it gets misread as CHEMICAL by the medical model *and*, once PERSON
    # detection started working, as a person's name by the general model too. Two
    # different models, two different false positives on the same word -- a filter
    # scoped to one recognizer would only have caught one of them. This is the single
    # point every recognizer's output passes through, so one denylist entry covers
    # whichever entity type a given false positive happens to surface as.
    try:
        with open("pii_rules.json", "r") as f:
            denylist = {t.lower() for t in json.load(f).get("settings", {}).get("entity_denylist", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        denylist = set()
    if denylist:
        results = [r for r in results if raw_text[r.start:r.end].lower() not in denylist]

    operators = {
        "PERSON": OperatorConfig("custom", {"lambda": mask_person_name}),
        "CREDIT_CARD": OperatorConfig("custom", {"lambda": lambda x: "**** **** **** " + x[-4:] if len(x) >= 4 else x}),
        "EMAIL_ADDRESS": OperatorConfig("custom", {"lambda": mask_email_address}),
        "IN_AADHAAR": OperatorConfig("custom", {"lambda": lambda x: "".join("*" if c.isalnum() else c for c in x[:-4]) + x[-4:] if len(x) >= 4 else x}),
        # The CUSTOMER_ID rule's regex matches the label phrase plus the digits
        # together (e.g. "customer id is 123111"), so it can require a nearby label
        # word without matching every bare number in a message. Without this operator,
        # Presidio's default would replace that whole matched span with a generic
        # placeholder, destroying the label text along with the number -- this masks
        # only the trailing digit run and leaves "customer id is" readable.
        "CUSTOMER_ID": OperatorConfig("custom", {"lambda": lambda x: re.sub(r"\d{4,10}$", lambda m: "*" * len(m.group()), x)}),
        # Without this, VERIFICATION_CODE has no custom operator, so Presidio falls back to its
        # default behavior: replacing the whole matched span with the literal placeholder
        # "<VERIFICATION_CODE>" instead of a readable mask. This mirrors CUSTOMER_ID's approach --
        # mask only the digit run, leave the label text (e.g. "passcode is") readable.
        "VERIFICATION_CODE": OperatorConfig("custom", {"lambda": lambda x: re.sub(r"\d{4,12}", lambda m: "*" * len(m.group()), x)}),
    }
    
    anonymized_result = anonymizer.anonymize(text=raw_text, analyzer_results=results, operators=operators)
    return anonymized_result.text, results

def run_watchdog_task(request_id: str, raw_text: str, layer1_results):
    try:
        with open("pii_rules.json", "r") as f:
            settings = json.load(f).get("settings", {})
            if not settings.get("enable_llm_watchdog", False):
                return
    except Exception:
        return
    
    start_time = time.perf_counter()
    l2_res = llm_watchdog.analyze_text(raw_text)
    end_time = time.perf_counter()
    BenchmarkLogger.log_metric(request_id, "LLM_WATCHDOG", (end_time - start_time) * 1000)
    
    diff_engine.run_diff(raw_text, layer1_results, l2_res)

# --- 4. Endpoints ---
@app.post("/query_db", response_model=GovernResponse)
def query_database(request: DbQueryRequest, background_tasks: BackgroundTasks,
                   principal: Principal = Depends(require_role(*ANY_ROLE))):
    # 1. Authorize the read before performing it. This endpoint reads a record by ID
    #    directly, so it needs the same entitlement check as a brokered tool call --
    #    otherwise it is a way around the broker.
    decision = tool_broker.execute(principal, tool_broker.make_call(tool_broker.TOOL_FETCH_DB, request.customer_id))
    if not decision.allowed:
        return GovernResponse(masked_output=decision.refusal, status="forbidden")

    raw_data = decision.data

    # 2. Universal Egress Guardrail (No request_id for this endpoint yet, as it's not part of the demo_chat flow)
    masked_output, l1_results = apply_egress_guardrail(raw_data) # TODO: Add request_id and benchmarking here too if needed
    background_tasks.add_task(run_watchdog_task, "N/A", raw_data, l1_results) # Using N/A for request_id for now

    # 3. Toxicity Check (Egress)
    is_toxic, tox_result = apply_toxicity_check(raw_data, "EGRESS")

    # 4. Secure Audit Logging
    raw_hash = hashlib.sha256(raw_data.encode()).hexdigest()
    fidelity_ok, fidelity_score = FidelityChecker.check_fidelity(raw_data, masked_output)
    AuditLogger.log_transaction(
        pii_masked_input=f"DB_HASH:{raw_hash[:8]}", # Secure Data Minimization
        final_rewrite=masked_output,
        fidelity_score=fidelity_score,
        fallback_triggered=not fidelity_ok
    )

    if is_toxic and tox_result.get("guard_failed"):
        return GovernResponse(
            masked_output=guard_failure_response(tox_result),
            status="blocked_guard_failure",
            toxicity=tox_result,
        )

    return GovernResponse(
        masked_output=masked_output,
        status="toxic_flagged" if is_toxic else "success",
        toxicity=tox_result,
    )

@app.post("/govern_ai", response_model=GovernResponse)
def govern_ai_output(request: GenerativeRequest, background_tasks: BackgroundTasks,
                     principal: Principal = Depends(require_role(*ANY_ROLE))):
    # 1. Injection check. This endpoint governs arbitrary submitted text, so injected
    #    instructions arriving here matter for the same reason they do in /chat.
    is_injection, inj_result = apply_injection_check(request.text, "INGRESS")
    if is_injection:
        message = (
            guard_failure_response(inj_result)
            if inj_result.get("guard_failed") else INJECTION_BLOCK_MSG
        )
        status = "blocked_guard_failure" if inj_result.get("guard_failed") else "blocked_injection"
        return GovernResponse(masked_output=message, status=status, injection=inj_result)

    # 2. Toxicity Check (Egress — flag toxic AI output but still return it masked)
    is_toxic, tox_result = apply_toxicity_check(request.text, "EGRESS")
    if is_toxic and tox_result.get("guard_failed"):
        return GovernResponse(
            masked_output=guard_failure_response(tox_result),
            status="blocked_guard_failure",
            toxicity=tox_result,
        )

    # 3. PII Guardrail (No request_id for this endpoint yet, as it's not part of the demo_chat flow)
    masked_output, l1_results = apply_egress_guardrail(request.text) # TODO: Add request_id and benchmarking here too if needed
    background_tasks.add_task(run_watchdog_task, "N/A", request.text, l1_results) # Using N/A for request_id for now

    # 4. Secure Audit Logging
    raw_hash = hashlib.sha256(request.text.encode()).hexdigest()
    fidelity_ok, fidelity_score = FidelityChecker.check_fidelity(request.text, masked_output)
    AuditLogger.log_transaction(
        pii_masked_input=f"AI_HASH:{raw_hash[:8]}",
        final_rewrite=masked_output,
        fidelity_score=fidelity_score,
        fallback_triggered=not fidelity_ok
    )
    return GovernResponse(
        masked_output=masked_output,
        status="toxic_flagged" if is_toxic else "success",
        toxicity=tox_result,
        injection=inj_result
    )

_GUARDRAIL_BLOCK_MSG = (
    "⚠️ This message was blocked by the Content Safety Shield. It contains language "
    "that violates content policy. Please rephrase your request."
)

_PAYMENT_DECLINED_MSG = (
    "Transaction cannot be initiated as customer has not opted for auto payments."
)

# Cheap recall pass before the (comparatively expensive, synchronous, Ollama-dependent)
# LLM classification call -- most traffic through this endpoint has nothing to do with
# payments, and this keeps that traffic exactly as fast and Ollama-independent as
# before this feature existed. The LLM call's job is precision (is this actually an
# instruction to pay, not just a mention of payment); this list's job is recall.
_PAYMENT_KEYWORDS = (
    "pay", "payment", "bill", "billing", "charge", "invoice", "auto-pay", "autopay", "auto pay",
)


def _looks_payment_related(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _PAYMENT_KEYWORDS)


# The fixed, stable vocabulary for GuardrailValidateResponse.flag_reason -- an external
# caller branches on these, so they're deliberately short machine-readable codes, not
# the free-text `reason` string built below for the CONSENT_VIOLATION alarm (that one's
# for a human reading the alarms dashboard, this one's for code).
_FLAG_REASON_TOXIC_CONTENT = "TOXIC_CONTENT"
_FLAG_REASON_GUARD_FAILURE = "GUARD_FAILURE"
_FLAG_REASON_PAYMENT_CONSENT_NOT_GIVEN = "PAYMENT_CONSENT_NOT_GIVEN"
_FLAG_REASON_SENSITIVE_CONTENT_MASKED = "SENSITIVE_CONTENT_MASKED"


# In-memory only, deliberately -- the whole point of AuditLogger.log_transaction's
# "never write raw text to disk" policy (see audit_logger.py) is that nothing recovers
# the original message from what's persisted. This buffer exists purely so the ChatBot
# screen can show "yes, a call just arrived" while integrating an external system
# against this endpoint; it holds only a flag and a hash, the same two things already
# written to the audit log, and it's gone on restart.
_GUARDRAIL_ACTIVITY = deque(maxlen=50)


def _record_guardrail_activity(flag: str, raw_hash: str, x_user_id: Optional[str] = None,
                               flag_reason: Optional[str] = None):
    _GUARDRAIL_ACTIVITY.appendleft({
        "timestamp": datetime.now().isoformat(),
        "flag": flag,
        "flag_reason": flag_reason,
        "hash": raw_hash[:8],
        "user_id": x_user_id,
    })


@app.post("/guardrail_validate", response_model=GuardrailValidateResponse)
def guardrail_validate(request: GuardrailValidateRequest, background_tasks: BackgroundTasks,
                       x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
                       x_message_category: Optional[str] = Header(default=None, alias="X-Message-Category"),
                       x_agent_id: Optional[str] = Header(default=None, alias="X-Agent-Id"),
                       authorization: Optional[str] = Header(default=None)):
    """
    Generic validation endpoint for external systems: send arbitrary text, get back a
    verdict -- CLEAR (nothing found), PARTIAL (PII/financial/health content masked),
    BLOCKED (toxic content, the original text withheld entirely), or PAYMENT_DECLINED
    (a payment confirmation/initiation instruction from a customer who has not opted
    into auto-pay) -- plus the resulting text and flag_reason, a short machine-readable
    code for *why* (TOXIC_CONTENT / GUARD_FAILURE / SENSITIVE_CONTENT_MASKED /
    PAYMENT_CONSENT_NOT_GIVEN / null for CLEAR) meant to be branched on programmatically.

    Unlike /govern_ai, toxicity here actually blocks rather than merely flagging: this
    endpoint exists specifically so a caller doesn't have to separately decide whether a
    "toxic_flagged" status means "safe to relay" or not.

    X-Message-Category: "bill_payment" is an optional, explicit signal from the caller
    that this particular call IS a payment confirmation/initiation instruction -- when
    present, it goes straight to the consent check, skipping both the keyword pre-filter
    and the LLM classifier below. Added after confirming those two guesses have a real
    recall gap: phrasings like "yes, please proceed", "confirm the transaction", "please
    debit my account now" contain none of the pre-filter's keywords, so the LLM
    classifier -- which only runs when the pre-filter matches -- was never even reached
    for them, and a non-consented customer's payment went through unchecked. A caller
    that already knows a given request is a payment confirmation (e.g. because it's
    wired to a "Pay Now" button in its own UI) should always send this header; the
    keyword/LLM path remains as a fallback for callers that don't.

    X-Agent-Id + Authorization: Bearer <secret> are optional -- this endpoint stays reachable
    without them (JioCare Helper and the Chat Bot page call it with neither). When both are
    present and verify, the outcome is also written to the Agent Governance Layer's Activity
    Log (governance_db), keyed by the same correlation_id as any paired
    /v1/agent/decisions/check call -- closing the gap where a content-mask and its matching
    purpose-gate were two separately-logged, uncorrelated events (see the design doc's §9.6).
    A failed/absent identity check here never rejects the request -- it just means no
    Activity Log entry gets written, same as any caller that never sent the headers at all.
    """
    correlation_id = request.correlation_id or str(uuid.uuid4())
    secret = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
    agent = agent_auth.verify_agent(x_agent_id, secret) if x_agent_id else None
    if x_agent_id and not agent:
        # X-Agent-Id was sent but didn't verify (unknown id, wrong/missing secret, or
        # revoked) -- distinct from simply not sending identity at all, which is a normal,
        # unlogged case for callers like JioCare Helper or the Chat Bot page. Without this,
        # a dropped/failed identity here is silent and unrecoverable after the fact -- see
        # the design doc's §9.6, added after exactly that ambiguity came up in practice.
        logging.warning(
            f"/guardrail_validate: agent identity failed to verify (X-Agent-Id={x_agent_id}, "
            f"correlation_id={correlation_id}) -- content_check will not be logged for this call."
        )

    def _log_agent_activity(flag: str, flag_reason: str = None):
        if not agent:
            return
        blocked = flag in ("BLOCKED", "PAYMENT_DECLINED")
        try:
            governance_db.log_activity(
                agent_id=agent["agent_id"],
                invoking_user_id=x_user_id,
                action=f"content_check:{flag}",
                outcome="BLOCKED" if blocked else "SERVED",
                correlation_id=correlation_id,
                reason_code=flag_reason,
            )
            # Mirrors /v1/agent/decisions/check's AGENT_UNAUTHORIZED_ACTION event -- a content
            # block from this endpoint is a policy violation the same way a DPDP DENY is, and
            # should show up in Compliance Events/Stats the same way, not just the Activity Log.
            if blocked:
                governance_db.log_governance_event(
                    event_id=f"gov-{uuid.uuid4().hex[:12]}",
                    event_type="AGENT_POLICY_VIOLATION",
                    severity="HIGH",
                    agent_id=agent["agent_id"],
                    reason_code=flag_reason,
                    correlation_id=correlation_id,
                )
        except Exception as e:
            logging.error(f"Agent governance: failed to log guardrail_validate activity: {e}")

    # 1. Toxicity -- checked first, and blocking, unlike /govern_ai's flag-only egress
    # check. should_block_toxic_egress() is the same admin-configurable policy /chat's
    # egress path already respects, not a second toxicity policy invented for this
    # endpoint alone.
    is_toxic, tox_result = apply_toxicity_check(request.text, "EGRESS")
    if is_toxic and should_block_toxic_egress():
        guard_failed = tox_result.get("guard_failed")
        message = guard_failure_response(tox_result) if guard_failed else _GUARDRAIL_BLOCK_MSG
        # A guard failure blocks fail-closed -- the text was never actually confirmed
        # toxic, the check just couldn't run -- so it gets its own code rather than
        # being reported as TOXIC_CONTENT, which would overstate what's actually known.
        flag_reason = _FLAG_REASON_GUARD_FAILURE if guard_failed else _FLAG_REASON_TOXIC_CONTENT

        raw_hash = hashlib.sha256(request.text.encode()).hexdigest()
        AuditLogger.log_transaction(
            pii_masked_input=f"VALIDATE_HASH:{raw_hash[:8]}",
            final_rewrite="[BLOCKED]",
            fidelity_score=None,
            fallback_triggered=True,
        )
        _record_guardrail_activity("BLOCKED", raw_hash, x_user_id, flag_reason)
        _log_agent_activity("BLOCKED", flag_reason)
        return GuardrailValidateResponse(
            flag="AI Guardrail flag: BLOCKED", message=message, flag_reason=flag_reason,
            correlation_id=correlation_id,
        )

    # 2. Payment intent -- either the caller has explicitly told us via
    # X-Message-Category (see the docstring above -- the reliable path, no keyword or
    # LLM guessing involved), or we fall back to the keyword pre-filter + LLM
    # classifier so callers that don't send the header still get some coverage. See
    # llm_watchdog.analyze_payment_intent for the fail-closed behavior on a classifier
    # failure.
    declared_bill_payment = (x_message_category or "").strip().lower() == "bill_payment"
    if declared_bill_payment or _looks_payment_related(request.text):
        if declared_bill_payment:
            intent = {"is_payment_related": True, "is_payment_confirmation": True, "guard_failed": False}
        else:
            intent = llm_watchdog.analyze_payment_intent(request.text)
        if intent.get("is_payment_confirmation"):
            # The payment-consent question is answered by the DPDP Engine -- see
            # dpdp_client.py. Skipped entirely (fail closed, no call made) when there's no
            # X-User-Id to check, same "nothing to ask" short-circuit tool_broker.py uses
            # for an undeclared purpose.
            decision = None
            if x_user_id:
                decision = dpdp_client.check_decision(
                    principal_ref=x_user_id,
                    data_categories=["PAYMENT_TOKEN"],
                    purpose="AUTO_PAY",
                    operation="INITIATE_PAYMENT",
                    recipient_ref="payment-gateway",
                    policy_context="BILL_PAYMENT_CONFIRMATION",
                )
            consented = decision is not None and decision["decision"] == "ALLOW"
            if not consented:
                reason = (
                    "no X-User-Id header provided" if not x_user_id
                    else f"guard failed: {intent.get('error')}" if intent.get("guard_failed")
                    else f"DPDP guard failed: {decision.get('error')}" if decision.get("guard_failed")
                    else f"DPDP decision={decision['decision']} for user '{x_user_id}'"
                )
                try:
                    diff_engine.generate_consent_violation_alarm(
                        principal_name=x_user_id or "unknown",
                        principal_role="external_caller",
                        customer_id=x_user_id or "unknown",
                        data_category="BILL_PAYMENT",
                        purpose="AUTO_PAY",
                        reason=reason,
                    )
                except Exception as e:
                    logging.error(f"Failed to raise CONSENT_VIOLATION alarm for payment decline: {e}")

                # A DPDP outage/timeout is a GUARDRAIL_DECISION_FAILURE (infrastructure),
                # not a CONSENT_DENIED (an actual data-processing denial) -- see
                # API_INTEGRATION.pdf's event catalogue. Missing X-User-Id never reached
                # the DPDP Engine at all, so it's reported the same way as a guard
                # failure: there was no decision to make.
                if x_user_id and not (decision or {}).get("guard_failed"):
                    dpdp_client.submit_compliance_event(
                        event_type="CONSENT_DENIED",
                        severity="HIGH",
                        principal_ref=x_user_id,
                        data_categories=["PAYMENT_TOKEN"],
                        purpose="AUTO_PAY",
                        operation="INITIATE_PAYMENT",
                        decision_id=(decision or {}).get("decision_id"),
                        reason_code=(decision or {}).get("reason_code") or "CONSENT_NOT_GRANTED",
                    )
                else:
                    dpdp_client.submit_compliance_event(
                        event_type="GUARDRAIL_DECISION_FAILURE",
                        severity="MEDIUM",
                        principal_ref=x_user_id or "unknown",
                        data_categories=["PAYMENT_TOKEN"],
                        purpose="AUTO_PAY",
                        operation="INITIATE_PAYMENT",
                        decision_id=None,
                        reason_code="DPDP_ENGINE_TIMEOUT",
                    )

                raw_hash = hashlib.sha256(request.text.encode()).hexdigest()
                AuditLogger.log_transaction(
                    pii_masked_input=f"VALIDATE_HASH:{raw_hash[:8]}",
                    final_rewrite="[PAYMENT_DECLINED]",
                    fidelity_score=None,
                    fallback_triggered=True,
                    purpose="AUTO_PAY",
                )
                _record_guardrail_activity(
                    "PAYMENT_DECLINED", raw_hash, x_user_id, _FLAG_REASON_PAYMENT_CONSENT_NOT_GIVEN,
                )
                _log_agent_activity("PAYMENT_DECLINED", _FLAG_REASON_PAYMENT_CONSENT_NOT_GIVEN)
                return GuardrailValidateResponse(
                    flag="AI Guardrail flag: PAYMENT_DECLINED",
                    message=_PAYMENT_DECLINED_MSG,
                    flag_reason=_FLAG_REASON_PAYMENT_CONSENT_NOT_GIVEN,
                    correlation_id=correlation_id,
                )
            # consented is True -- falls through to the ordinary PII-masking path below,
            # same as any other non-toxic message.

    # 3. Not toxic, and not a declined payment confirmation -- mask PII/financial/health.
    masked_output, l1_results = apply_egress_guardrail(request.text)
    background_tasks.add_task(run_watchdog_task, "N/A", request.text, l1_results)

    flag = "PARTIAL" if masked_output != request.text else "CLEAR"
    flag_reason = _FLAG_REASON_SENSITIVE_CONTENT_MASKED if flag == "PARTIAL" else None

    raw_hash = hashlib.sha256(request.text.encode()).hexdigest()
    fidelity_ok, fidelity_score = FidelityChecker.check_fidelity(request.text, masked_output)
    AuditLogger.log_transaction(
        pii_masked_input=f"VALIDATE_HASH:{raw_hash[:8]}",
        final_rewrite=masked_output,
        fidelity_score=fidelity_score,
        fallback_triggered=not fidelity_ok,
    )

    _record_guardrail_activity(flag, raw_hash, x_user_id, flag_reason)
    _log_agent_activity(flag, flag_reason)
    return GuardrailValidateResponse(
        flag=f"AI Guardrail flag: {flag}", message=masked_output, flag_reason=flag_reason,
        correlation_id=correlation_id,
    )


@app.get("/guardrail_activity")
def get_guardrail_activity(principal: Principal = Depends(require_role(*ANY_ROLE))):
    """
    Recent /guardrail_validate calls -- newest first, in-memory only (see
    _GUARDRAIL_ACTIVITY). Backs the ChatBot screen's live confirmation panel so an
    integrator can see a call actually arrived while wiring up an external system,
    without the raw message ever being retrievable through this or any other endpoint.
    """
    return {"activity": list(_GUARDRAIL_ACTIVITY)}

@app.post("/chat", response_model=ChatResponse)
def chat_agent(request: ChatRequest, background_tasks: BackgroundTasks,
               principal: Principal = Depends(require_role(*ANY_ROLE))):
    common_error_msg = "⚠️ Your message was blocked by the Content Safety Shield. I cannot provide you with insults or derogatory language targeting any specific group of people, including those identified by nationality, nor can I write content that insults someone's intelligence and includes extreme profanity. My guidelines prohibit generating hateful content or slurs. Is there anything else I can help you with?"
    request_id = f"R-{uuid.uuid4().hex[:8]}"

    # Step 0a: INGRESS Injection Check — runs first because the pattern pass is the
    # cheapest check we have, and because injection is what reaches the database tool.
    start_time = time.perf_counter()
    is_injection, inj_result = apply_injection_check(request.message, "INGRESS")
    end_time = time.perf_counter()
    BenchmarkLogger.log_metric(request_id, "INGRESS_INJECTION_CHECK", (end_time - start_time) * 1000)
    if is_injection:
        if inj_result.get("guard_failed"):
            return ChatResponse(
                masked_output=guard_failure_response(inj_result),
                status="blocked_guard_failure",
                injection=inj_result,
            )
        return ChatResponse(
            masked_output=INJECTION_BLOCK_MSG,
            status="blocked_injection",
            injection=inj_result,
        )

    # Step 0b: INGRESS Toxicity Check — Block abusive user input before it reaches the LLM
    start_time = time.perf_counter()
    is_toxic_input, tox_input_result = apply_toxicity_check(request.message, "INGRESS")
    end_time = time.perf_counter()
    BenchmarkLogger.log_metric(request_id, "INGRESS_TOXICITY_CHECK", (end_time - start_time) * 1000)
    if is_toxic_input:
        if tox_input_result.get("guard_failed"):
            return ChatResponse(
                masked_output=guard_failure_response(tox_input_result),
                status="blocked_guard_failure",
                toxicity=tox_input_result,
            )
        return ChatResponse(
            masked_output=common_error_msg,
            status="blocked_toxic",
            toxicity=tox_input_result
        )

    OLLAMA_URL = config.OLLAMA_URL
    SYSTEM_PROMPT = """You are an internal enterprise AI with access to a customer database. 
If the user asks for details about a specific customer, you MUST output ONLY the command <FETCH_DB:ID> where ID is the customer number (e.g. <FETCH_DB:101>). 
Do NOT output anything else if you need data. 
If you are provided with data, summarize it naturally and helpfully."""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message}
    ]
    
    try:
        start_time = time.perf_counter()
        # Step 1: Initial call to Ollama
        payload = {
            "model": config.DEFAULT_LLM_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": 0.0, "num_predict": 300}
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
        if resp.status_code != 200:
            return ChatResponse(masked_output="Failed to contact Ollama. Is it running?", status="error")
        end_time = time.perf_counter()
        BenchmarkLogger.log_metric(request_id, "LLM_INITIAL_CALL", (end_time - start_time) * 1000)

        ai_message = resp.json()["message"]["content"]

        # Populated only when this turn's tool call succeeded under a declared purpose --
        # carried through to the audit entry below so a transaction backed by consent is
        # traceable to the exact notice version it was granted under.
        notice_version = None

        # Step 2: Tool call — brokered, not regex-dispatched.
        # The model names what it wants; tool_broker decides whether this caller may have
        # it. Previously the ID the model emitted went straight to the database.
        #
        # A refusal short-circuits with a fixed message rather than being fed back to the
        # model to paraphrase: this is a security boundary, and a small model asked to
        # relay a refusal is not a dependable way to guarantee the caller never sees the
        # data anyway (it could ignore the instruction, or invent something instead).
        tool_calls = tool_broker.parse_tool_calls(ai_message)
        if tool_calls:
            result = tool_broker.execute(principal, tool_calls[0], purpose=request.purpose)
            if not result.allowed:
                if result.consent_detail is not None:
                    return ChatResponse(
                        masked_output=result.refusal,
                        status="consent_required",
                        consent=result.consent_detail,
                    )
                return ChatResponse(masked_output=result.refusal, status="forbidden")
            raw_data = result.data

            if request.purpose:
                notice_version = result.notice_version

            # Feed back to LLM
            json_schema = '''{
  "customer_id": 101,
  "customer_name": "...",
  "sensitive_data": {
    "phone": "...",
    "payment_card": "...",
    "aadhaar": "...",
    "pan": "..."
  }
}'''
            messages.append({"role": "assistant", "content": ai_message})
            messages.append({
                "role": "user", 
                "content": f"Here is the database result: {raw_data}. Respond ONLY with a valid JSON object matching this exact schema, filling in the sensitive data fields. Schema:\n{json_schema}"
            })
            
            payload["messages"] = messages
            payload["format"] = "json"

            start_time = time.perf_counter()
            resp2 = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
            end_time = time.perf_counter()
            BenchmarkLogger.log_metric(request_id, "LLM_TOOL_FEEDBACK_CALL", (end_time - start_time) * 1000)

            ai_message = resp2.json()["message"]["content"]

        # Step 3: Apply PII Guardrail
        start_time = time.perf_counter()
        masked_message, l1_results = apply_egress_guardrail(ai_message)
        end_time = time.perf_counter()
        BenchmarkLogger.log_metric(request_id, "EGRESS_PII_GUARDRAIL", (end_time - start_time) * 1000)
        background_tasks.add_task(run_watchdog_task, request_id, ai_message, l1_results)

        # Step 4: EGRESS Toxicity Check on AI output. The verdict used to be discarded
        # into `_`, so output was scored, alarmed and forwarded regardless; whether it
        # blocks is now an explicit setting.
        is_toxic_output, tox_output_result = apply_toxicity_check(ai_message, "EGRESS")

        # Secure Audit Logging
        raw_hash = hashlib.sha256(ai_message.encode()).hexdigest()
        fidelity_ok, fidelity_score = FidelityChecker.check_fidelity(ai_message, masked_message)
        AuditLogger.log_transaction(
            pii_masked_input=f"CHAT_HASH:{raw_hash[:8]}",
            final_rewrite=masked_message,
            fidelity_score=fidelity_score,
            fallback_triggered=not fidelity_ok,
            purpose=request.purpose or None,
            notice_version=notice_version,
        )

        if is_toxic_output and should_block_toxic_egress():
            status = "blocked_guard_failure" if tox_output_result.get("guard_failed") else "blocked_toxic_egress"
            message = (
                guard_failure_response(tox_output_result)
                if tox_output_result.get("guard_failed") else common_error_msg
            )
            return ChatResponse(masked_output=message, status=status, toxicity=tox_output_result)

        return ChatResponse(
            raw_output=ai_message if may_see_raw_output(principal) else None,
            masked_output=masked_message,
            status="toxic_flagged" if is_toxic_output else "success",
            toxicity=tox_output_result
        )

    except requests.Timeout:
        logging.error(f"{request_id}: Ollama timed out after {LLM_TIMEOUT}s")
        return ChatResponse(
            masked_output="The AI service did not respond in time. Please try again.",
            status="error",
        )
    except Exception as e:
        # The exception text can carry model output or internal paths, so it goes to the
        # log rather than to the caller.
        logging.exception(f"{request_id}: /chat failed")
        return ChatResponse(
            masked_output="An internal error occurred while processing this request.",
            status="error",
        )

@app.post("/sandbox_suggest_rule")
def sandbox_suggest_rule(request: SandboxSuggestRequest, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    OLLAMA_URL = config.OLLAMA_URL
    
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            existing_rules = data.get("rules", [])
            existing_entities = [r.get("entity") for r in existing_rules if r.get("entity")]
            
            # PRE-CHECK: See if an inactive rule already catches this leak
            inactive_rules = [r for r in existing_rules if not r.get("is_active", True)]
            for r in inactive_rules:
                if r.get("regex"): # Check for a non-empty regex
                    import re
                    pattern = re.compile(r["regex"])
                    if pattern.search(request.context_snippet):
                        return {"status": "success", "suggestion": {"entity": r["entity"], "regex": r["regex"], "is_reactivation": True}}
    except:
        existing_entities = []
        
    try:
        combined_query = f"{request.missed_entity_type} {request.value_preview} {request.context_snippet}"
        policy_context = rag_engine.retrieve_relevant_policy(combined_query)
    except Exception as e:
        policy_context = ""
        print(f"RAG Error: {e}")
        
    rag_instruction = ""
    if policy_context:
        rag_instruction = f"\n\nCRITICAL POLICY ENFORCEMENT: You MUST strictly adhere to the following enterprise data standard when writing the regex:\n{policy_context}"
        
    SYSTEM_PROMPT = f"""You are an expert Data Loss Prevention (DLP) engineer writing for Microsoft Presidio. 
Your job is to provide a Python regular expression to catch sensitive data that was missed. 
You must output ONLY valid JSON matching this EXACT schema:
{{
  "entity": "STANDARD_ENTITY_NAME",
  "abstract_format": "Briefly explain the general mathematical or structural format of this data type (e.g. '2 letters followed by 2 digits then alphanumeric')",
  "regex": "valid_regex_pattern"
}}
Ensure the regex uses word boundaries (\\b) instead of string anchors (^ or $) because the sensitive data will be found in the middle of sentences. 
The 'entity' field MUST be formatted in UPPER_CASE_WITH_UNDERSCORES (e.g. OPEN_AI_API_KEY, IBAN_NUMBER).

CRITICAL: The existing entities in our rule engine are: {existing_entities}. 
If your suggested meaningful name already exists in this list, you MUST append a number to make it unique (e.g. OPEN_AI_API_KEY_2).
Do NOT include any markdown formatting or explanation.{rag_instruction}"""
    
    user_prompt = f"""The primary engine missed a sensitive entity (currently broadly categorized as '{request.missed_entity_type}'). Specifically, it missed the value starting with '{request.value_preview}'. Here is the full context statement:

{request.context_snippet}

Provide the JSON with a regex to specifically catch that extracted value. 
CRITICAL INSTRUCTION: You MUST generalize the regex pattern to catch ALL similar formats, not just this exact string.
For example, if the leaked value is 'ABCD123', the regex should be \\b[A-Z]{{4}}\\d{{3}}\\b.
DO NOT output the exact characters of the leaked value in the regex.

You MUST deduce a highly specific, meaningful Entity Class from the context (e.g. if it mentions an API key, use OPENAI_API_KEY, NOT the broad category '{request.missed_entity_type}')."""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        payload = {
            "model": getattr(config, "CODING_LLM_MODEL", config.DEFAULT_LLM_MODEL),
            "messages": messages,
            "stream": False,
            "format": "json",
            "keep_alive": -1,
            "options": {
                "temperature": 0.0,
                "num_predict": 150
            }
        }
        
        print(f"==================================================")
        print(f"SANDBOX AI: Sending request to Ollama with model '{payload['model']}'")
        print(f"==================================================")
        
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        
        print(f"==================================================")
        print(f"SANDBOX AI: Ollama responded with status {resp.status_code}")
        print(f"==================================================")
        
        if resp.status_code != 200:
            return {"status": "error", "message": "Failed to contact local AI"}
            
        ai_message = resp.json()["message"]["content"]
        return {"status": "success", "suggestion": json.loads(ai_message)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/sandbox_test_rule")
def sandbox_test_rule(request: SandboxTestRequest, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        # Spin up a temporary, isolated Presidio Engine
        sandbox_analyzer = AnalyzerEngine()
        
        # Add ONLY the proposed Regex
        pattern = Pattern(name="sandbox_test", regex=request.regex_pattern, score=0.85)
        recognizer = PatternRecognizer(supported_entity=request.entity_name, patterns=[pattern])
        sandbox_analyzer.registry.add_recognizer(recognizer)
        
        # Test the snippet against the isolated engine
        results = sandbox_analyzer.analyze(text=request.context_snippet, language='en', entities=[request.entity_name], score_threshold=0.5)
        
        if not results:
            return {"status": "success", "caught": False, "matched_text": None}
            
        # Extract the highest scoring match
        best_match = max(results, key=lambda x: x.score)
        matched_text = request.context_snippet[best_match.start:best_match.end]
        
        return {"status": "success", "caught": True, "matched_text": matched_text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/rules")
def get_rules(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        with open("pii_rules.json", "r") as f:
            return json.load(f)
    except Exception as e:
        return {"rules": [], "settings": {}}

def run_guard_self_test() -> dict:
    """
    Check that every guard the settings claim to enable actually loaded.

    Without this, a guard whose model failed to download looks identical to a healthy
    one until the first request -- and with fail-closed semantics that means refusing all
    traffic with no explanation. Reported through /system_status so the failure is visible
    before anyone sends a request.
    """
    report = {"status": "ready", "guards": {}, "problems": []}

    try:
        settings = load_guard_settings()
    except GuardSettingsError as e:
        report["status"] = "degraded"
        report["problems"].append(f"pii_rules.json unreadable: {e}")
        return report

    if analyzer is None:
        report["status"] = "degraded"
        report["problems"].append("Presidio analyzer failed to initialize")
    report["guards"]["pii_analyzer"] = analyzer is not None

    checks = [
        ("toxicity_guard", "enable_toxicity_guard", toxicity_guard.is_available, toxicity_guard.load_error),
        ("injection_guard", "enable_injection_guard", injection_guard.is_available, injection_guard.load_error),
    ]

    for name, flag, available, error in checks:
        enabled = settings.get(flag, False)
        ok = available()
        report["guards"][name] = {"enabled": enabled, "loaded": ok}
        if enabled and not ok:
            report["status"] = "degraded"
            report["problems"].append(f"{name} is enabled but failed to load: {error()}")

    # Roles are self-declared (X-Role header, see auth.py) with no credential behind
    # them -- require_role() still enforces which role may do what, but nothing stops a
    # caller from declaring a different role than they'd be issued. Surfaced here so
    # this is a known, visible trade-off rather than an assumed-secure setup.
    report["problems"].append(
        "Roles are self-declared, not authenticated -- any caller can declare "
        "super_admin via the X-Role header. See auth.py."
    )

    return report


@app.get("/system_status")
def system_status():
    """
    Open (unauthenticated) so health checks work, and deliberately reports only whether
    the guards loaded -- never the rules or traffic.
    """
    return run_guard_self_test()


@app.get("/whoami")
def whoami(principal: Principal = Depends(require_role(*ANY_ROLE))):
    """
    Echoes back the role the caller declared via X-Role (see auth.py) -- lets the
    frontend's role picker confirm what the server will enforce without guessing.
    """
    return {"name": principal.name, "role": principal.role, "is_admin": principal.is_admin}


@app.get("/alarms")
def get_alarms(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    import diff_engine
    return {"alarms": diff_engine.load_alarms()}

@app.get("/consents")
def get_consents(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    """Backs the admin Consents ledger tab -- every consent record, newest first."""
    return {"consents": consent.list_consents()}

@app.post("/withdraw_consent")
def withdraw_consent(request: WithdrawConsentRequest,
                      principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    """
    Marks a consent WITHDRAWN. Takes effect on the very next request that checks it --
    tool_broker.authorize reads live status, not a cached grant, so this is the live
    demo moment: withdraw here, and the same chat question that worked a second ago
    now gets refused.
    """
    withdrawn = consent.withdraw_consent(
        request.customer_id, request.data_category, request.purpose
    )
    if not withdrawn:
        return {"status": "error", "message": "No granted consent found to withdraw."}

    AuditLogger.log_config_change(
        actor=principal.name, actor_role=principal.role,
        action=f"withdraw_consent:{request.customer_id}:{request.data_category}:{request.purpose}",
        before="GRANTED", after="WITHDRAWN",
    )
    return {"status": "success"}


# --- Agent Governance Layer ---------------------------------------------------
#
# Distinct from the DPDP consent integration above: this is agent identity/registration,
# an activity log, and agent-scoped compliance events -- not a DPDP Act concept, and not
# a second consent engine. /v1/agent/decisions/check is a thin, identity-verified wrapper
# around the existing, unmodified dpdp_client.check_decision -- the DPDP Engine remains the
# sole authority on consent. See Implementation_Plan/Agent_Governance_Layer_Design.md.

# Mocked IAM -- a purpose string maps to the "app" it belongs to, checked against
# iam_entitlements before DPDP is ever asked. This is deliberately a separate, prior
# question from consent: "is this agent even scoped to attempt this at all" vs. "has the
# principal consented to this purpose." An unrecognized purpose maps to None, which
# governance_db.is_entitled() always treats as not-entitled -- fail closed on anything
# this table doesn't know about, rather than silently allowing an unmapped app through.
_PURPOSE_APP_SUBSTRINGS = (
    ("swiggy", "swiggy"),
    ("teams", "teams"),
    ("kite", "kite"),
    ("yahoo", "yahoo_finance"),
)


def _purpose_to_app(purpose: str) -> Optional[str]:
    lowered = (purpose or "").lower()
    for substring, app in _PURPOSE_APP_SUBSTRINGS:
        if substring in lowered:
            return app
    return None


def notify_incident(incident_id: str, agent: dict, request: "AgentDecisionCheckRequest", reason_code: str):
    """Fire-and-log, same discipline as diff_engine.py's alarm emails -- a notification
    failure must never affect the DENY already decided. Reuses the same
    notification_subscribers list every other alarm email already reads from, rather than
    inventing a separate recipient config just for incidents."""
    try:
        with open("pii_rules.json", "r") as f:
            subscribers = json.load(f).get("notification_subscribers", [])
        for sub in subscribers:
            if sub.get("alert_type") not in ("ALL", "AGENT_SCOPE_EXCEEDED"):
                continue
            if sub.get("email"):
                EmailNotifier.send_incident_email(
                    sub.get("email"), incident_id, agent, request, reason_code,
                    f"{sub.get('role')} ({sub.get('alert_type')})",
                )
    except Exception as e:
        logging.error(f"Failed to notify incident {incident_id}: {e}")


# Reason-code -> plain-language explainer content, shown at GET /awareness/{reason_code}
# and linked from the Data Principal's own awareness email. Distinct from any back-office
# runbook -- written for the end user, not for whoever investigates the incident.
AWARENESS_CONTENT = {
    "IAM_SCOPE_EXCEEDED": {
        "title": "An AI agent tried to do something outside its permissions",
        "body": [
            "One of the AI agents acting on your behalf tried to use a capability it was never "
            "granted, for example, an agent that's only allowed to check information tried to "
            "place an order or take an action instead. We blocked it automatically, before "
            "anything happened.",
            "Every AI agent connected to your account is only allowed to do the specific things "
            "it was explicitly set up for. This is deliberate: even if an agent is compromised, "
            "buggy, or simply misconfigured, it can never do more than it was scoped to do.",
            "You don't need to take any action. If you don't recognize the agent involved, or you "
            "didn't expect it to attempt this, let us know so we can review it.",
        ],
    },
}
DEFAULT_AWARENESS = {
    "title": "We blocked an AI agent action on your behalf",
    "body": [
        "One of the AI agents acting on your behalf attempted an action that didn't meet our "
        "governance rules, so it was blocked automatically before anything happened.",
        "You don't need to take any action. If you don't recognize the agent involved, let us "
        "know so we can review it.",
    ],
}


@app.get("/awareness/{reason_code}", response_class=HTMLResponse)
def awareness_page(reason_code: str):
    """Public, unauthenticated explainer page -- the link opened straight from the Data
    Principal's own email, same purpose as an investor-education article linked from a
    brokerage's trade-block SMS. No incident IDs, agent secrets, or other internal detail."""
    content = AWARENESS_CONTENT.get(reason_code, DEFAULT_AWARENESS)
    paragraphs = "".join(f"<p>{p}</p>" for p in content["body"])
    return f"""
    <html>
      <head><title>{content['title']}</title></head>
      <body style="font-family: Arial, sans-serif; color: #1c2128; max-width: 640px; margin: 40px auto; padding: 0 20px;">
        <h1 style="font-size: 1.4rem;">🛡️ {content['title']}</h1>
        {paragraphs}
      </body>
    </html>
    """


def notify_principal_awareness(incident_id: str, agent: dict, request: "AgentDecisionCheckRequest", reason_code: str):
    """Separate audience from notify_incident: the Data Principal themselves, not the
    back-office security council. Looks up a mocked principal->email mapping (PoC-scope,
    same pattern as notification_subscribers -- a real deployment would resolve this via
    the identity provider, not a JSON file). Fire-and-log; never affects the DENY."""
    try:
        with open("pii_rules.json", "r") as f:
            contacts = json.load(f).get("principal_contacts", {})
        to_email = contacts.get(request.principal_ref)
        if not to_email:
            return
        base_url = os.environ.get("GUARDRAIL_BASE_URL", "http://localhost:8000")
        awareness_url = f"{base_url}/awareness/{reason_code}"
        EmailNotifier.send_user_awareness_email(to_email, agent, reason_code, awareness_url)
    except Exception as e:
        logging.error(f"Failed to notify principal awareness for incident {incident_id}: {e}")


def _verify_agent_or_401(x_agent_id: Optional[str], authorization: Optional[str]):
    """
    Inline identity verification for every /v1/agent/* route that isn't registration itself.
    Fails closed: any problem (missing header, unknown agent, wrong secret, revoked agent)
    raises 401 immediately, logging an AGENT_IDENTITY_UNVERIFIED event, before the caller's
    request ever reaches a decision-check or activity-log write.
    """
    secret = None
    if authorization and authorization.lower().startswith("bearer "):
        secret = authorization[7:]

    agent = agent_auth.verify_agent(x_agent_id, secret)
    if agent is None:
        try:
            governance_db.log_governance_event(
                event_id=f"gov-{uuid.uuid4().hex[:12]}",
                event_type="AGENT_IDENTITY_UNVERIFIED",
                severity="HIGH",
                agent_id=x_agent_id or "unknown",
                reason_code="INVALID_OR_MISSING_CREDENTIALS",
                correlation_id=None,
            )
        except Exception as e:
            logging.error(f"Agent governance: failed to log AGENT_IDENTITY_UNVERIFIED event: {e}")
        raise HTTPException(status_code=401, detail="Agent identity could not be verified.")
    return agent


@app.post("/v1/agent/register")
def agent_register(request: AgentRegisterRequest):
    """Self-registration -- an agent calls this once, on install/first activation, and
    persists the returned secret itself. The secret is shown exactly once, here."""
    agent_id, secret, timestamp = agent_auth.register_agent(
        agent_name=request.agent_name,
        business_unit=request.business_unit,
        owner_name=request.owner_name,
        location_of_deployment=request.location_of_deployment,
        in_house_or_external=request.in_house_or_external,
        device_id=request.device_id or None,
    )
    return {
        "agent_id": agent_id,
        "agent_secret": secret,
        "identity_assignment_timestamp": timestamp,
    }


@app.post("/v1/agent/decisions/check")
def agent_decision_check(request: AgentDecisionCheckRequest,
                          x_agent_id: Optional[str] = Header(default=None, alias="X-Agent-Id"),
                          authorization: Optional[str] = Header(default=None)):
    agent = _verify_agent_or_401(x_agent_id, authorization)
    # Generated here, not left to dpdp_client's own internal fallback, so the same value
    # ties together the DPDP Engine call, our activity/event rows, and the response --
    # a caller that omits it must still get one back to correlate against.
    correlation_id = request.correlation_id or str(uuid.uuid4())

    # IAM scope check -- a prior, separate question from consent. DPDP is never even asked
    # when this fails: "is this agent scoped to attempt this at all" is answered first, and
    # a scope violation is an incident (§ design doc), not an ordinary consent denial.
    # Only enforced for purposes recognized as belonging to a known (VOXA) app -- this is a
    # scoped addition for the multi-skill-agent scenario, not a blanket policy over every
    # possible purpose. A purpose this repo's own original chatbot uses (e.g.
    # BILLING_SUPPORT, AUTO_PAY) maps to app=None and skips this gate entirely, proceeding
    # straight to DPDP exactly as before IAM existed.
    app = _purpose_to_app(request.purpose)
    if app and not governance_db.is_entitled(request.principal_ref, agent["agent_id"], request.device_id, app):
        reason_code = "IAM_SCOPE_EXCEEDED"
        try:
            governance_db.log_activity(
                agent_id=agent["agent_id"],
                invoking_user_id=request.principal_ref,
                action=f"decision_check:{request.operation}",
                outcome="BLOCKED",
                correlation_id=correlation_id,
                reason_code=reason_code,
                device_id=request.device_id,
            )
            incident_id = governance_db.create_incident(
                event_type="AGENT_SCOPE_EXCEEDED",
                severity="HIGH",
                agent_id=agent["agent_id"],
                principal_ref=request.principal_ref,
                reason_code=reason_code,
                correlation_id=correlation_id,
            )
            notify_incident(incident_id, agent, request, reason_code)
            notify_principal_awareness(incident_id, agent, request, reason_code)
        except Exception as e:
            logging.error(f"Agent governance: failed to log/incident IAM scope violation: {e}")
        return {
            "decision": "DENY", "guard_failed": False, "error": None,
            "decision_id": None, "notice_version": None, "reason_code": reason_code,
            "correlation_id": correlation_id,
        }

    decision = dpdp_client.check_decision(
        principal_ref=request.principal_ref,
        data_categories=request.data_categories,
        purpose=request.purpose,
        operation=request.operation,
        recipient_ref=request.recipient_ref,
        policy_context=request.policy_context,
        correlation_id=correlation_id,
    )

    allowed = decision.get("decision") == "ALLOW"
    reason_code = None if allowed else (decision.get("reason_code") or decision.get("error") or decision.get("decision"))
    try:
        governance_db.log_activity(
            agent_id=agent["agent_id"],
            invoking_user_id=request.principal_ref,
            action=f"decision_check:{request.operation}",
            outcome="SERVED" if allowed else "BLOCKED",
            correlation_id=correlation_id,
            reason_code=reason_code,
            device_id=request.device_id,
        )
        if not allowed:
            governance_db.log_governance_event(
                event_id=f"gov-{uuid.uuid4().hex[:12]}",
                event_type="AGENT_UNAUTHORIZED_ACTION",
                severity="HIGH",
                agent_id=agent["agent_id"],
                reason_code=reason_code,
                correlation_id=correlation_id,
            )
    except Exception as e:
        logging.error(f"Agent governance: failed to log decision-check activity/event: {e}")

    return {**decision, "correlation_id": correlation_id}


@app.post("/v1/agent/activity")
def agent_activity(request: AgentActivityRequest,
                    x_agent_id: Optional[str] = Header(default=None, alias="X-Agent-Id"),
                    authorization: Optional[str] = Header(default=None)):
    """Non-gating activity entry for calls that need no consent decision (e.g. a read)."""
    agent = _verify_agent_or_401(x_agent_id, authorization)
    correlation_id = request.correlation_id or str(uuid.uuid4())
    governance_db.log_activity(
        agent_id=agent["agent_id"],
        invoking_user_id=request.invoking_user_id,
        action=request.action,
        outcome=request.outcome,
        latency_ms=request.latency_ms,
        correlation_id=correlation_id,
        reason_code=request.reason_code,
        device_id=request.device_id,
    )
    return {"status": "logged", "correlation_id": correlation_id}


@app.get("/v1/agent/agents")
def agent_list_agents(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    """Backs the Admin 'Registered Agents' tab. Never returns the secret hash."""
    return {"agents": governance_db.list_agents()}


@app.post("/v1/agent/agents/{agent_id}/revoke")
def agent_revoke(agent_id: str, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    revoked = governance_db.revoke_agent(agent_id)
    if not revoked:
        return {"status": "error", "message": "Agent not found."}
    return {"status": "success"}


@app.get("/v1/agent/activity")
def agent_list_activity(limit: int = 100, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    return {"activity": governance_db.list_activity(limit)}


@app.get("/v1/agent/events")
def agent_list_events(limit: int = 100, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    return {"events": governance_db.list_governance_events(limit)}


@app.get("/v1/agent/stats")
def agent_stats(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    return governance_db.get_stats()


@app.get("/v1/agent/entitlements")
def agent_list_entitlements(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    """Read-only for now -- entitlements are seeded/managed by whoever owns the (mocked)
    IAM sync process, not editable from this admin UI yet."""
    return {"entitlements": governance_db.list_entitlements()}


@app.get("/v1/agent/incidents")
def agent_list_incidents(limit: int = 100, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    return {"incidents": governance_db.list_incidents(limit)}


@app.get("/v1/agent/reports")
def agent_reports(record_types: Optional[str] = None, start_ts: Optional[str] = None,
                   end_ts: Optional[str] = None, agent_id: Optional[str] = None,
                   principal_ref: Optional[str] = None, outcome: Optional[str] = None,
                   reason_code: Optional[str] = None, severity: Optional[str] = None,
                   correlation_id: Optional[str] = None,
                   principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    """Backs the Reports tab -- a single filtered, normalized view across Activity Log,
    Compliance Events and Incidents. record_types is a comma-separated subset of
    activity,event,incident (all three when omitted)."""
    types = [t.strip() for t in record_types.split(",")] if record_types else None
    return governance_db.query_report(
        record_types=types, start_ts=start_ts, end_ts=end_ts, agent_id=agent_id,
        principal_ref=principal_ref, outcome=outcome, reason_code=reason_code,
        severity=severity, correlation_id=correlation_id,
    )


@app.post("/delete_alarm")
def delete_alarm(request: DeleteAlarmRequest, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        import diff_engine
        alarms = diff_engine.load_alarms()
        initial_length = len(alarms)
        alarms = [a for a in alarms if a.get("alarm_id") != request.alarm_id]
        
        if len(alarms) == initial_length:
            return {"status": "error", "message": "Alarm not found."}
            
        with open("alarms.json", "w") as f:
            json.dump(alarms, f, indent=2)
            
        # Update archive ledger. The archive keeps who dismissed the alarm and when, so
        # the record of the decision survives alongside the record of the detection.
        archive = diff_engine.load_archive()
        before_status = None
        for a in archive:
            if a.get("alarm_id") == request.alarm_id:
                before_status = a.get("status")
                a["status"] = request.status
                a["resolved_by"] = principal.name
                a["resolved_at"] = datetime.utcnow().isoformat() + "Z"
                break
        with open(diff_engine.ARCHIVE_FILE, "w") as f:
            json.dump(archive, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"delete_alarm:{request.alarm_id}",
            before=before_status, after=request.status,
        )

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class ToggleRequest(BaseModel):
    enable_llm_watchdog: bool

class ToggleToxicityRequest(BaseModel):
    enable_toxicity_guard: bool

class ToggleCategoryRequest(BaseModel):
    category: str
    enabled: bool

class UpdateToxicitySettingsRequest(BaseModel):
    thresholds: dict
    enable_toxicity_guard: bool
    
@app.post("/toggle_category")
def toggle_category(request: ToggleCategoryRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
        
        setting_key = f"enable_{request.category.lower()}"
        if "settings" not in data:
            data["settings"] = {}

        before = data["settings"].get(setting_key)
        data["settings"][setting_key] = request.enabled

        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"toggle_category:{setting_key}", before=before, after=request.enabled,
        )

        reload_presidio_engine()
        return {"status": "success", "settings": data["settings"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/toggle_watchdog")
def toggle_watchdog(request: ToggleRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
        
        if "settings" not in data:
            data["settings"] = {}
        before = data["settings"].get("enable_llm_watchdog")
        data["settings"]["enable_llm_watchdog"] = request.enable_llm_watchdog

        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action="toggle_watchdog", before=before, after=request.enable_llm_watchdog,
        )

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/toggle_toxicity")
def toggle_toxicity(request: ToggleToxicityRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
        
        if "settings" not in data:
            data["settings"] = {}
        before = data["settings"].get("enable_toxicity_guard")
        data["settings"]["enable_toxicity_guard"] = request.enable_toxicity_guard

        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action="toggle_toxicity", before=before, after=request.enable_toxicity_guard,
        )

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/update_toxicity_settings")
def update_toxicity_settings(request: UpdateToxicitySettingsRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        if "settings" not in data:
            data["settings"] = {}
        # Persist both the toggle state and the thresholds
        before = {
            "enable_toxicity_guard": data["settings"].get("enable_toxicity_guard"),
            "toxicity_thresholds": data["settings"].get("toxicity_thresholds"),
        }
        data["settings"]["enable_toxicity_guard"] = request.enable_toxicity_guard
        data["settings"]["toxicity_thresholds"] = request.thresholds

        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action="update_toxicity_settings", before=before,
            after={"enable_toxicity_guard": request.enable_toxicity_guard,
                   "toxicity_thresholds": request.thresholds},
        )
            
        # If toxicity guard is being enabled, make a dummy call to warm up the model
        if request.enable_toxicity_guard:
            print("Warming up toxicity model...")
            # Use a non-toxic dummy text to avoid false alarms during warm-up
            toxicity_guard.analyze("Hello, how are you today?", data["settings"].get("toxicity_thresholds", {}))
            print("Toxicity model warmed up.")
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/toxicity_settings")
def get_toxicity_settings(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    return load_toxicity_settings()

@app.get("/subscribers")
def get_subscribers(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            return {"subscribers": data.get("notification_subscribers", [])}
    except Exception as e:
        return {"subscribers": []}

@app.post("/add_subscriber")
def add_subscriber(request: SubscriberRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        if "notification_subscribers" not in data:
            data["notification_subscribers"] = []
            
        new_sub = {
            "user_name": request.user_name,
            "role": request.role,
            "alert_type": request.alert_type,
            "email": request.email
        }
        data["notification_subscribers"].append(new_sub)
        
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"add_subscriber:{request.user_name}", before=None,
            after={"user_name": request.user_name, "role": request.role,
                   "alert_type": request.alert_type},
        )

        return {"status": "success", "message": "Subscriber added successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/update_subscriber")
def update_subscriber(request: UpdateSubscriberRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        sub_found = False
        if "notification_subscribers" in data:
            for sub in data["notification_subscribers"]:
                if sub["user_name"] == request.original_user_name:
                    sub["user_name"] = request.user_name
                    sub["role"] = request.role
                    sub["alert_type"] = request.alert_type
                    sub["email"] = request.email
                    sub_found = True
                    break
                    
        if not sub_found:
            return {"status": "error", "message": "Subscriber not found."}
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"update_subscriber:{request.original_user_name}", before=None,
            after={"user_name": request.user_name, "role": request.role,
                   "alert_type": request.alert_type},
        )

        return {"status": "success", "message": "Subscriber updated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/delete_subscriber")
def delete_subscriber(request: DeleteSubscriberRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        initial_length = len(data.get("notification_subscribers", []))
        data["notification_subscribers"] = [s for s in data.get("notification_subscribers", []) if s["user_name"] != request.user_name]
        
        if len(data.get("notification_subscribers", [])) == initial_length:
            return {"status": "error", "message": "Subscriber not found."}
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"delete_subscriber:{request.user_name}", before=None, after=None,
        )

        return {"status": "success", "message": "Subscriber deleted successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/test_cases")
def get_test_cases(principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        with open("test_cases.json", "r") as f:
            return json.load(f)
    except Exception as e:
        return {"tests": []}

@app.post("/add_rule")
def add_rule(request: RuleRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        # 1. Update JSON
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
        
        rule_found = False
        for rule in data.get("rules", []):
            if rule.get("entity") == request.entity:
                # Upsert: Rule exists, just update and reactivate it
                rule["regex"] = request.regex
                rule["score"] = request.score
                rule["is_active"] = request.is_active
                rule_found = True
                break
                
        if not rule_found:
            new_rule = {
                "name": request.name,
                "entity": request.entity,
                "regex": request.regex,
                "score": request.score,
                "is_builtin": request.is_builtin,
                "is_algorithmic": request.is_algorithmic,
                "is_active": request.is_active
            }
            if "rules" not in data:
                data["rules"] = []
            data["rules"].append(new_rule)
            
        if request.category and request.category != "UNCATEGORIZED":
            if "category_mappings" not in data:
                data["category_mappings"] = {}
            if request.category not in data["category_mappings"]:
                data["category_mappings"][request.category] = []
            if request.entity not in data["category_mappings"][request.category]:
                data["category_mappings"][request.category].append(request.entity)
        
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"add_rule:{request.entity}",
            before=None,
            after={"name": request.name, "entity": request.entity, "regex": request.regex,
                   "score": request.score, "is_active": request.is_active},
        )

        # 2. Hot-reload Presidio Engine
        reload_presidio_engine()

        return {"status": "success", "message": "Rule added and hot-reloaded successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/update_rule")
def update_rule(request: UpdateRuleRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        # Find and update the rule
        rule_found = False
        before_rule = None
        for rule in data["rules"]:
            if rule["name"] == request.original_name:
                before_rule = dict(rule)
                rule["name"] = request.name
                rule["entity"] = request.entity
                rule["regex"] = request.regex
                rule["score"] = request.score
                rule["is_builtin"] = request.is_builtin
                rule["is_algorithmic"] = request.is_algorithmic
                rule["is_active"] = request.is_active
                rule_found = True
                break
                
        if not rule_found:
            return {"status": "error", "message": "Rule not found."}
            
        if request.category and request.category != "UNCATEGORIZED":
            if "category_mappings" not in data:
                data["category_mappings"] = {}
            if request.category not in data["category_mappings"]:
                data["category_mappings"][request.category] = []
            if request.entity not in data["category_mappings"][request.category]:
                data["category_mappings"][request.category].append(request.entity)
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"update_rule:{request.original_name}",
            before=before_rule,
            after={"name": request.name, "entity": request.entity, "regex": request.regex,
                   "score": request.score, "is_active": request.is_active},
        )

        reload_presidio_engine()
        return {"status": "success", "message": "Rule updated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/delete_rule")
def delete_rule(request: DeleteRuleRequest, principal: Principal = Depends(require_role(ROLE_SUPER_ADMIN))):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        initial_length = len(data["rules"])
        deleted_rule = next((dict(r) for r in data["rules"] if r["name"] == request.name), None)
        data["rules"] = [rule for rule in data["rules"] if rule["name"] != request.name]

        if len(data["rules"]) == initial_length:
            return {"status": "error", "message": "Rule not found."}
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)

        AuditLogger.log_config_change(
            actor=principal.name, actor_role=principal.role,
            action=f"delete_rule:{request.name}", before=deleted_rule, after=None,
        )

        reload_presidio_engine()
        return {"status": "success", "message": "Rule deleted successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/analytics")
def get_analytics(timeframe: str = "24h", *, principal: Principal = Depends(require_role(*ADMIN_ROLES))):
    try:
        import diff_engine
        from datetime import datetime, timedelta
        
        # Determine cutoff time
        now = datetime.utcnow()
        if timeframe == "24h":
            cutoff = now - timedelta(hours=24)
        elif timeframe == "7d":
            cutoff = now - timedelta(days=7)
        elif timeframe == "30d":
            cutoff = now - timedelta(days=30)
        elif timeframe == "90d":
            cutoff = now - timedelta(days=90)
        else:
            cutoff = now - timedelta(days=3650) # All time basically
            
        # Parse audit logs for traffic trend
        total_requests = 0
        traffic_trend = {}
        
        if os.path.exists("governance_audit.json"):
            audit_logs = []
            with open("governance_audit.json", "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        audit_logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            for log in audit_logs:
                # Configuration changes share the audit file with traffic, but they are
                # not requests -- counting them would inflate the traffic figures. Entries
                # written before the event field existed are transactions.
                if log.get("event", AuditLogger.EVENT_TRANSACTION) != AuditLogger.EVENT_TRANSACTION:
                    continue
                try:
                    log_time = datetime.fromisoformat(log["timestamp"].replace("Z", ""))
                    if log_time >= cutoff:
                        total_requests += 1
                        if timeframe == "24h":
                            day_key = log_time.strftime("%H:00")
                        else:
                            day_key = log_time.strftime("%b %d")
                        traffic_trend[day_key] = traffic_trend.get(day_key, 0) + 1
                except:
                    pass
                    
        # Parse alarm archive for alarm metrics
        archive = diff_engine.load_archive()
        
        total_alarms = 0
        resolved_alarms = 0
        dismissed_alarms = 0
        pending_alarms = 0
        category_distribution = {}
        alarm_trend = {}
        
        for alarm in archive:
            try:
                alarm_time = datetime.fromisoformat(alarm["timestamp"].replace("Z", ""))
                if alarm_time >= cutoff:
                    total_alarms += 1
                    
                    # Status breakdown
                    status = alarm.get("status", "PENDING_REVIEW")
                    if status == "RESOLVED":
                        resolved_alarms += 1
                    elif status == "DISMISSED":
                        dismissed_alarms += 1
                    else:
                        pending_alarms += 1
                        
                    # Category breakdown
                    cat = alarm.get("category", "UNCATEGORIZED")
                    category_distribution[cat] = category_distribution.get(cat, 0) + 1
                    
                    # Trend breakdown
                    if timeframe == "24h":
                        day_key = alarm_time.strftime("%H:00")
                    else:
                        day_key = alarm_time.strftime("%b %d")
                    alarm_trend[day_key] = alarm_trend.get(day_key, 0) + 1
            except:
                pass
                
        # Format trends for recharts
        all_days = sorted(list(set(list(traffic_trend.keys()) + list(alarm_trend.keys()))))
        trend_data = []
        for day in all_days:
            trend_data.append({
                "date": day,
                "requests": traffic_trend.get(day, 0),
                "alarms": alarm_trend.get(day, 0)
            })
            
        # Format category data
        cat_data = []
        for cat, count in category_distribution.items():
            cat_data.append({"name": cat, "value": count})
            
        return {
            "status": "success",
            "metrics": {
                "total_requests": total_requests,
                "total_alarms": total_alarms,
                "resolved": resolved_alarms,
                "dismissed": dismissed_alarms,
                "pending": pending_alarms
            },
            "category_data": cat_data,
            "trend_data": trend_data
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/get_benchmarks")
async def get_benchmarks(principal: Principal = Depends(require_role(*ANY_ROLE))):
    # Per-stage latency numbers only -- no PII, no configuration -- and the "View
    # Benchmarks" button that calls this sits on the Chat Bot tab, usable by any
    # authenticated caller. Gating it to admins would just break that button for them.
    """
    Reads the benchmark.log file and returns its content.
    """
    BENCHMARK_LOG_FILE = "benchmark.log"
    if not os.path.exists(BENCHMARK_LOG_FILE):
        return {"message": "Benchmark log file not found.", "logs": []}
    
    try:
        with open(BENCHMARK_LOG_FILE, "r") as f:
            logs = f.readlines()
        return {"message": "Success", "logs": logs}
    except Exception as e:
        return {"message": f"Error reading benchmark log: {str(e)}", "logs": []}

class DemoChatRequest(BaseModel):
    message: str
    mode: str = "others"  # 'toxic' or 'others'
    # See ChatRequest.purpose -- empty string, not None, so /demo_chat's pinned
    # scenarios opt into the Consent Gate the same way /chat does.
    purpose: str = ""

@app.post("/demo_chat", response_model=ChatResponse)
def demo_chat_agent(request: DemoChatRequest, background_tasks: BackgroundTasks,
                    principal: Principal = Depends(require_role(*ANY_ROLE))):
    common_error_msg = "⚠️ Your message was blocked by the Content Safety Shield. I cannot provide you with insults or derogatory language targeting any specific group of people, including those identified by nationality, nor can I write content that insults someone's intelligence and includes extreme profanity. My guidelines prohibit generating hateful content or slurs. Is there anything else I can help you with?"
    
    request_id = f"R-{uuid.uuid4().hex[:8]}"

    # Step 0a: INGRESS Injection Check
    start_time = time.perf_counter()
    is_injection, inj_result = apply_injection_check(request.message, "INGRESS")
    end_time = time.perf_counter()
    BenchmarkLogger.log_metric(request_id, "INGRESS_INJECTION_CHECK", (end_time - start_time) * 1000)
    if is_injection:
        if inj_result.get("guard_failed"):
            return ChatResponse(
                masked_output=guard_failure_response(inj_result),
                status="blocked_guard_failure",
                injection=inj_result,
            )
        return ChatResponse(
            masked_output=INJECTION_BLOCK_MSG,
            status="blocked_injection",
            injection=inj_result,
        )

    # Step 0b: INGRESS Toxicity Check — Block abusive user input before it reaches the LLM
    start_time = time.perf_counter()
    is_toxic_input, tox_input_result = apply_toxicity_check(request.message, "INGRESS")
    end_time = time.perf_counter()
    BenchmarkLogger.log_metric(request_id, "INGRESS_TOXICITY_CHECK", (end_time - start_time) * 1000)
    if is_toxic_input:
        if tox_input_result.get("guard_failed"):
            return ChatResponse(
                masked_output=guard_failure_response(tox_input_result),
                status="blocked_guard_failure",
                toxicity=tox_input_result,
            )
        return ChatResponse(
            masked_output=common_error_msg,
            status="blocked_toxic",
            toxicity=tox_input_result
        )

    OLLAMA_URL = config.OLLAMA_URL
    model_to_use = config.TOXIC_LLM_MODEL if request.mode == "toxic" else config.DEFAULT_LLM_MODEL
    
    # Plain ASCII -- a raw emoji here crashes on a Windows console using the default
    # cp1252 codepage (surfaced while testing the Consent Gate against /demo_chat),
    # rather than something that only shows up under an unusual encoding.
    print("=" * 50)
    print("DEMO CHAT REQUEST RECEIVED")
    print(f"Mode toggled to: '{request.mode}'")
    print(f"Routing request to Ollama Model: '{model_to_use}'")
    print("=" * 50)
    
    if request.mode == "toxic":
        SYSTEM_PROMPT = "You are a helpful AI assistant. Please fulfill the user's request directly."
    else:
        # We use the DB-fetching system prompt for the standard model
        SYSTEM_PROMPT = """You are an internal enterprise AI with access to a customer database. 
If the user asks for details about a specific customer or partner, you MUST output ONLY the command <FETCH_DB:ID> where ID is the exact name or number requested.
For example:
- If asked about customer 101, output exactly: <FETCH_DB:101>
- If asked about swiggy, output exactly: <FETCH_DB:swiggy>
- If asked about an IBAN or transaction amount, output exactly: <FETCH_DB:iban>

Do NOT output anything else if you need data. 
If you are provided with data, summarize it naturally and helpfully."""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message}
    ]
    
    try:
        start_time_llm_call = time.perf_counter()
        # Step 1: Initial routing
        # Small models (like phi4-mini) struggle with complex routing instructions. 
        # For the sake of the demo, we explicitly intercept the known demo keywords.
        payload = {
            "model": model_to_use,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {"temperature": 0.0, "num_predict": 300}
        }

        msg_lower = request.message.lower()

        # These keyword branches decide tool calls and bulk reads WITHOUT the model, so
        # they reach the same data by a different route. Each one is authorized here --
        # otherwise the broker on the <FETCH_DB:...> path below would just be a detour
        # around an open door.
        bulk_read_requested = "all customer details" in msg_lower or "top 3 spenders" in msg_lower
        if bulk_read_requested and not auth.may_read_all_records(principal):
            diff_engine.generate_tool_abuse_alarm(
                principal_name=principal.name,
                principal_role=principal.role,
                tool_call="BULK_READ",
                reason=f"principal '{principal.name}' is not entitled to read all records",
            )
            return ChatResponse(
                masked_output="You are not authorized to view all customer records.",
                status="forbidden",
            )

        if "swiggy" in msg_lower:
            ai_message = "<FETCH_DB:swiggy>"
        elif "all customer details" in msg_lower:
            cust_rows, spend_rows = database.get_all_customers_and_spenders()
            lines = ["Here are all the customer details:\n"]
            count = 1
            for r in cust_rows:
                lines.append(f"{count}. {r[1]} (Customer).\n   - ID: {r[0]}.\n   - Phone: {r[2]}.\n   - Card: {r[3]}.\n   - Aadhaar: {r[4]}.\n   - PAN: {r[5]}.\n")
                count += 1
            for r in spend_rows:
                lines.append(f"{count}. {r[1]} (Spender).\n   - ID: {r[0]}.\n   - Email: {r[2]}.\n   - Card: {r[5]}.\n   - Aadhaar: {r[7]}.\n")
                count += 1
            ai_message = "\n".join(lines).strip()
        elif "top 3 spenders" in msg_lower:
            top_3 = database.get_top_spenders()
            if "aadhar" in msg_lower or "aadhaar" in msg_lower:
                lines = ["The Aadhaar numbers for the top 3 spenders are:\n"]
                for idx, r in enumerate(top_3, 1):
                    lines.append(f"{idx}. Name: {r[1]}.\n   - Aadhaar: {r[7]}.")
                ai_message = "\n".join(lines)
            else:
                lines = ["The top 3 spenders of today are:\n"]
                for idx, r in enumerate(top_3, 1):
                    lines.append(f"{idx}. Name: {r[1]}.\n   - Email: {r[2]}.\n   - Orders: {r[4]}.\n   - Spend: {r[3]}.\n   - Card: {r[5]}.\n")
                ai_message = "\n".join(lines).strip()
        elif "iban" in msg_lower or "transaction" in msg_lower:
            ai_message = "<FETCH_DB:iban>"
        else:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
            if resp.status_code != 200:
                return ChatResponse(masked_output="Failed to contact Ollama.", status="error")
            ai_message = resp.json()["message"]["content"]
        end_time_llm_call = time.perf_counter()
        BenchmarkLogger.log_metric(request_id, "LLM_INITIAL_CALL", (end_time_llm_call - start_time_llm_call) * 1000)

        # Populated only when this turn's tool call succeeded under a declared purpose --
        # carried through to the audit entry below, matching /chat's wiring.
        notice_version = None

        # Step 2: Tool call — brokered, so the caller's entitlement decides, not the model
        start_time_tool_call = time.perf_counter()
        tool_calls = tool_broker.parse_tool_calls(ai_message)
        if tool_calls:
            customer_id_str = tool_calls[0].argument
            decision = tool_broker.execute(principal, tool_calls[0], purpose=request.purpose)
            if not decision.allowed:
                if decision.consent_detail is not None:
                    return ChatResponse(
                        masked_output=decision.refusal,
                        status="consent_required",
                        consent=decision.consent_detail,
                    )
                return ChatResponse(masked_output=decision.refusal, status="forbidden")
            raw_data = decision.data

            if request.purpose:
                notice_version = decision.notice_version

            # Feed back to LLM
            messages.append({"role": "assistant", "content": ai_message})
            # To prevent the SLM from getting confused and re-outputting the FETCH_DB command due to the strict system prompt,
            # we overwrite the system prompt for the second request.
            messages[0]["content"] = "You are a helpful enterprise assistant. Convey the provided database result naturally to the user."
            
            if customer_id_str.lower() == "swiggy":
                messages.append({
                    "role": "user", 
                    "content": f"Here is the database result: {raw_data}. Output EXACTLY this sentence and nothing else: 'The GPS coordinates for the delivery driver are 48.8584 N, 2.2945 E.'"
                })
                if "format" in payload:
                    del payload["format"]
            elif customer_id_str.lower() == "iban":
                messages.append({
                    "role": "user", 
                    "content": f"Here is the database result: {raw_data}. Output EXACTLY this sentence and nothing else: '{raw_data}'"
                })
                if "format" in payload:
                    del payload["format"]
            else:
                json_schema = '''{
  "customer_id": 101,
  "customer_name": "...",
  "sensitive_data": {
    "phone": "...",
    "payment_card": "...",
    "aadhaar": "...",
    "pan": "..."
  }
}'''
                messages.append({
                    "role": "user", 
                    "content": f"Here is the database result: {raw_data}. Respond ONLY with a valid JSON object matching this exact schema, filling in the sensitive data fields. Schema:\n{json_schema}"
                })
                payload["format"] = "json"
            
            payload["messages"] = messages
            
            start_time_llm_tool_feedback = time.perf_counter()
            resp2 = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
            end_time_llm_tool_feedback = time.perf_counter()
            BenchmarkLogger.log_metric(request_id, "LLM_TOOL_FEEDBACK_CALL", (end_time_llm_tool_feedback - start_time_llm_tool_feedback) * 1000)

            ai_message = resp2.json()["message"]["content"]
            
        # Step 3: Conditionally Apply PII Guardrail
        # Check if any PII-related categories are enabled before masking.
        l1_results = []
        start_time_egress_pii = time.perf_counter()
        masked_message = ai_message
        try:
            with open("pii_rules.json", "r") as f:
                settings = json.load(f).get("settings", {})
                # Check if any of the main PII categories are enabled
                if settings.get("enable_pii") or settings.get("enable_health") or settings.get("enable_financial") or settings.get("enable_authentication"):
                    print("Applying Egress Guardrail: PII categories are enabled.")
                    masked_message, l1_results = apply_egress_guardrail(ai_message)
                else:
                    print("Skipping Egress Guardrail: All PII categories are disabled.")
        except Exception as e:
            print(f"Could not read PII settings, applying guardrail as failsafe. Error: {e}")
            masked_message, l1_results = apply_egress_guardrail(ai_message)
        end_time_egress_pii = time.perf_counter()
        BenchmarkLogger.log_metric(request_id, "EGRESS_PII_GUARDRAIL", (end_time_egress_pii - start_time_egress_pii) * 1000)
        background_tasks.add_task(run_watchdog_task, request_id, ai_message, l1_results)
        
        # Step 4: EGRESS Toxicity Check on AI output
        start_time_egress_toxicity = time.perf_counter()
        is_toxic_output, tox_output_result = apply_toxicity_check(ai_message, "EGRESS")
        end_time_egress_toxicity = time.perf_counter()
        BenchmarkLogger.log_metric(request_id, "EGRESS_TOXICITY_CHECK", (end_time_egress_toxicity - start_time_egress_toxicity) * 1000)
        
        # Initialize status to success
        status = "success"
        blocked = False

        if is_toxic_output:
            if tox_output_result.get("guard_failed"):
                masked_message = guard_failure_response(tox_output_result)
                status = "blocked_guard_failure"
                blocked = True
            elif should_block_toxic_egress():
                # If toxic, overwrite the masked_message with the common error and update status
                masked_message = common_error_msg
                status = "blocked_toxic"
                blocked = True
            else:
                status = "toxic_flagged"

        # Step 5: Secure Audit Logging
        raw_hash = hashlib.sha256(request.message.encode()).hexdigest()
        fidelity_ok, fidelity_score = FidelityChecker.check_fidelity(ai_message, masked_message)
        AuditLogger.log_transaction(
            pii_masked_input=f"CHAT_HASH:{raw_hash[:8]}",
            final_rewrite=masked_message,
            fidelity_score=fidelity_score,
            fallback_triggered=not fidelity_ok,
            purpose=request.purpose or None,
            notice_version=notice_version,
        )

        return ChatResponse(
            # Never leak the raw text on a block, whatever the policy says.
            raw_output=ai_message if (may_see_raw_output(principal) and not blocked) else None,
            masked_output=masked_message,
            status=status,
            toxicity=tox_output_result
        )
    except requests.Timeout:
        logging.error(f"{request_id}: Ollama timed out after {LLM_TIMEOUT}s")
        return ChatResponse(
            masked_output="The AI service did not respond in time. Please try again.",
            status="error",
        )
    except Exception as e:
        logging.exception(f"{request_id}: /demo_chat failed")
        return ChatResponse(
            masked_output="An internal error occurred while processing this request.",
            status="error",
        )