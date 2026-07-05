import os
import json
import requests
import re
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
import hashlib
from audit_logger import AuditLogger
from custom_recognizers import AadhaarRecognizer
import database
import llm_watchdog
import diff_engine

app = FastAPI(title="AI Governance API")

# Add CORS Middleware to allow React frontend (running on port 5173) to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. Load Dynamic Presidio Config ---
# Global dynamic entities list
ACTIVE_ENTITIES = []
analyzer = None
anonymizer = AnonymizerEngine()

def reload_presidio_engine():
    global analyzer, ACTIVE_ENTITIES
    print("Reloading Presidio NLP models...")
    new_analyzer = AnalyzerEngine()
    
    ACTIVE_ENTITIES = []
    
    # Load custom python recognizer (Verhoeff Math)
    new_analyzer.registry.add_recognizer(AadhaarRecognizer())
    
    # Load dynamic JSON rules
    try:
        with open("pii_rules.json", "r") as f:
            rules = json.load(f)["rules"]
            for rule in rules:
                if not rule.get("is_active", True):
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
print("Presidio & Database loaded successfully.")

# --- 2. API Models ---
class DbQueryRequest(BaseModel):
    customer_id: int

class GenerativeRequest(BaseModel):
    text: str

class GovernResponse(BaseModel):
    masked_output: str
    status: str

class RuleRequest(BaseModel):
    name: str
    entity: str
    regex: str
    score: float
    is_builtin: bool = False
    is_algorithmic: bool = False
    is_active: bool = True

class UpdateRuleRequest(BaseModel):
    original_name: str
    name: str
    entity: str
    regex: str
    score: float
    is_builtin: bool = False
    is_algorithmic: bool = False
    is_active: bool = True

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

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    raw_output: str
    masked_output: str
    status: str

class SandboxSuggestRequest(BaseModel):
    context_snippet: str
    missed_entity_type: str
    value_preview: str

class SandboxTestRequest(BaseModel):
    context_snippet: str
    regex_pattern: str
    entity_name: str

# --- 3. The Universal Guardrail Function ---
def apply_egress_guardrail(raw_text: str):
    # We explicitly define the entities we want to track using the global ACTIVE_ENTITIES.
    # This includes both our hardcoded defaults and dynamic JSON rules.
    results = analyzer.analyze(text=raw_text, language='en', entities=ACTIVE_ENTITIES, score_threshold=0.5)
    anonymized_result = anonymizer.anonymize(text=raw_text, analyzer_results=results)
    return anonymized_result.text, results

def run_watchdog_task(raw_text: str, layer1_results):
    try:
        with open("pii_rules.json", "r") as f:
            settings = json.load(f).get("settings", {})
            if not settings.get("enable_llm_watchdog", False):
                return
    except:
        return
        
    l2_res = llm_watchdog.analyze_text(raw_text)
    diff_engine.run_diff(raw_text, layer1_results, l2_res)

# --- 4. Endpoints ---
@app.post("/query_db", response_model=GovernResponse)
def query_database(request: DbQueryRequest, background_tasks: BackgroundTasks):
    # 1. Fetch raw data
    raw_data = database.get_customer_profile(request.customer_id)
    
    # 2. Universal Egress Guardrail
    masked_output, l1_results = apply_egress_guardrail(raw_data)
    background_tasks.add_task(run_watchdog_task, raw_data, l1_results)
    
    # 3. Secure Audit Logging
    raw_hash = hashlib.sha256(raw_data.encode()).hexdigest()
    AuditLogger.log_transaction(
        pii_masked_input=f"DB_HASH:{raw_hash[:8]}", # Secure Data Minimization
        final_rewrite=masked_output,
        fidelity_score=1.0,
        fallback_triggered=False
    )
    
    return GovernResponse(masked_output=masked_output, status="success")

@app.post("/govern_ai", response_model=GovernResponse)
def govern_ai_output(request: GenerativeRequest, background_tasks: BackgroundTasks):
    # This simulates receiving output FROM an AI model before sending to user.
    masked_output, l1_results = apply_egress_guardrail(request.text)
    background_tasks.add_task(run_watchdog_task, request.text, l1_results)
    
    raw_hash = hashlib.sha256(request.text.encode()).hexdigest()
    AuditLogger.log_transaction(
        pii_masked_input=f"AI_HASH:{raw_hash[:8]}",
        final_rewrite=masked_output,
        fidelity_score=1.0,
        fallback_triggered=False
    )
    return GovernResponse(masked_output=masked_output, status="success")

@app.post("/chat", response_model=ChatResponse)
def chat_agent(request: ChatRequest, background_tasks: BackgroundTasks):
    OLLAMA_URL = "http://localhost:11434/api/chat"
    SYSTEM_PROMPT = """You are an internal enterprise AI with access to a customer database. 
If the user asks for details about a specific customer, you MUST output ONLY the command <FETCH_DB:ID> where ID is the customer number (e.g. <FETCH_DB:101>). 
Do NOT output anything else if you need data. 
If you are provided with data, summarize it naturally and helpfully."""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request.message}
    ]
    
    try:
        # Step 1: Initial call to Ollama
        payload = {
            "model": "phi4-mini:3.8b",
            "messages": messages,
            "stream": False
        }
        resp = requests.post(OLLAMA_URL, json=payload)
        if resp.status_code != 200:
            return ChatResponse(raw_output="Error", masked_output="Failed to contact Ollama. Is it running?", status="error")
            
        ai_message = resp.json()["message"]["content"]
        
        # Step 2: Check for Tool Call
        match = re.search(r"<FETCH_DB:(\d+)>", ai_message)
        if match:
            customer_id = int(match.group(1))
            # Execute tool
            raw_data = database.get_customer_profile(customer_id)
            
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
            
            resp2 = requests.post(OLLAMA_URL, json=payload)
            ai_message = resp2.json()["message"]["content"]
            
        # Step 3: Apply Guardrail
        masked_message, l1_results = apply_egress_guardrail(ai_message)
        background_tasks.add_task(run_watchdog_task, ai_message, l1_results)
        
        # Secure Audit Logging
        raw_hash = hashlib.sha256(ai_message.encode()).hexdigest()
        AuditLogger.log_transaction(
            pii_masked_input=f"CHAT_HASH:{raw_hash[:8]}",
            final_rewrite=masked_message,
            fidelity_score=1.0,
            fallback_triggered=False
        )
        
        return ChatResponse(raw_output=ai_message, masked_output=masked_message, status="success")
        
    except Exception as e:
        return ChatResponse(raw_output="Error", masked_output=str(e), status="error")

@app.post("/sandbox_suggest_rule")
def sandbox_suggest_rule(request: SandboxSuggestRequest):
    OLLAMA_URL = "http://localhost:11434/api/chat"
    
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            existing_rules = data.get("rules", [])
            existing_entities = [r.get("entity") for r in existing_rules if r.get("entity")]
            
            # PRE-CHECK: See if an inactive rule already catches this leak
            inactive_rules = [r for r in existing_rules if not r.get("is_active", True)]
            for r in inactive_rules:
                if "regex" in r:
                    import re
                    pattern = re.compile(r["regex"])
                    if pattern.search(request.context_snippet):
                        return {"status": "success", "suggestion": {"entity": r["entity"], "regex": r["regex"], "is_reactivation": True}}
    except:
        existing_entities = []
        
    SYSTEM_PROMPT = f"""You are an expert Data Loss Prevention (DLP) engineer writing for Microsoft Presidio. 
Your job is to provide a Python regular expression to catch sensitive data that was missed. 
You must output ONLY valid JSON matching this EXACT schema:
{{
  "entity": "STANDARD_ENTITY_NAME",
  "regex": "valid_regex_pattern"
}}
Ensure the regex uses word boundaries (\\b) instead of string anchors (^ or $) because the sensitive data will be found in the middle of sentences. 
The 'entity' field MUST be formatted in UPPER_CASE_WITH_UNDERSCORES (e.g. OPEN_AI_API_KEY, IBAN_NUMBER) and it MUST be a highly meaningful name specific to the data being extracted. Do NOT use generic names like AUTHENTICATION_DATA.

CRITICAL: The existing entities in our rule engine are: {existing_entities}. 
If your suggested meaningful name already exists in this list, you MUST append a number to make it unique (e.g. OPEN_AI_API_KEY_2).
Do NOT include any markdown formatting or explanation."""
    
    user_prompt = f"The primary engine missed a sensitive entity (currently broadly categorized as '{request.missed_entity_type}'). Specifically, it missed the value starting with '{request.value_preview}'. Here is the full context statement:\n\n{request.context_snippet}\n\nProvide the JSON with a regex to specifically catch that extracted value. You MUST deduce a highly specific, meaningful Entity Class from the context (e.g. if it mentions an API key, use OPENAI_API_KEY, NOT the broad category '{request.missed_entity_type}')."
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        payload = {
            "model": "phi4-mini:3.8b",
            "messages": messages,
            "stream": False,
            "format": "json"
        }
        resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
        if resp.status_code != 200:
            return {"status": "error", "message": "Failed to contact local AI"}
            
        ai_message = resp.json()["message"]["content"]
        return {"status": "success", "suggestion": json.loads(ai_message)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/sandbox_test_rule")
def sandbox_test_rule(request: SandboxTestRequest):
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
def get_rules():
    try:
        with open("pii_rules.json", "r") as f:
            return json.load(f)
    except Exception as e:
        return {"rules": [], "settings": {}}

@app.get("/alarms")
def get_alarms():
    import diff_engine
    return {"alarms": diff_engine.load_alarms()}

@app.post("/delete_alarm")
def delete_alarm(request: DeleteAlarmRequest):
    try:
        import diff_engine
        alarms = diff_engine.load_alarms()
        initial_length = len(alarms)
        alarms = [a for a in alarms if a.get("alarm_id") != request.alarm_id]
        
        if len(alarms) == initial_length:
            return {"status": "error", "message": "Alarm not found."}
            
        with open("alarms.json", "w") as f:
            json.dump(alarms, f, indent=2)
            
        # Update archive ledger
        archive = diff_engine.load_archive()
        for a in archive:
            if a.get("alarm_id") == request.alarm_id:
                a["status"] = request.status
                break
        with open(diff_engine.ARCHIVE_FILE, "w") as f:
            json.dump(archive, f, indent=2)
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class ToggleRequest(BaseModel):
    enable_llm_watchdog: bool

@app.post("/toggle_watchdog")
def toggle_watchdog(request: ToggleRequest):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
        
        if "settings" not in data:
            data["settings"] = {}
        data["settings"]["enable_llm_watchdog"] = request.enable_llm_watchdog
        
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/subscribers")
def get_subscribers():
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            return {"subscribers": data.get("notification_subscribers", [])}
    except Exception as e:
        return {"subscribers": []}

@app.post("/add_subscriber")
def add_subscriber(request: SubscriberRequest):
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
            
        return {"status": "success", "message": "Subscriber added successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/update_subscriber")
def update_subscriber(request: UpdateSubscriberRequest):
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
            
        return {"status": "success", "message": "Subscriber updated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/delete_subscriber")
def delete_subscriber(request: DeleteSubscriberRequest):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        initial_length = len(data.get("notification_subscribers", []))
        data["notification_subscribers"] = [s for s in data.get("notification_subscribers", []) if s["user_name"] != request.user_name]
        
        if len(data.get("notification_subscribers", [])) == initial_length:
            return {"status": "error", "message": "Subscriber not found."}
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)
            
        return {"status": "success", "message": "Subscriber deleted successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/test_cases")
def get_test_cases():
    try:
        with open("test_cases.json", "r") as f:
            return json.load(f)
    except Exception as e:
        return {"tests": []}

@app.post("/add_rule")
def add_rule(request: RuleRequest):
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
        
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)
            
        # 2. Hot-reload Presidio Engine
        reload_presidio_engine()
            
        return {"status": "success", "message": "Rule added and hot-reloaded successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/update_rule")
def update_rule(request: UpdateRuleRequest):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        # Find and update the rule
        rule_found = False
        for rule in data["rules"]:
            if rule["name"] == request.original_name:
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
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)
            
        reload_presidio_engine()
        return {"status": "success", "message": "Rule updated successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/delete_rule")
def delete_rule(request: DeleteRuleRequest):
    try:
        with open("pii_rules.json", "r") as f:
            data = json.load(f)
            
        initial_length = len(data["rules"])
        data["rules"] = [rule for rule in data["rules"] if rule["name"] != request.name]
        
        if len(data["rules"]) == initial_length:
            return {"status": "error", "message": "Rule not found."}
            
        with open("pii_rules.json", "w") as f:
            json.dump(data, f, indent=2)
            
        reload_presidio_engine()
        return {"status": "success", "message": "Rule deleted successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/analytics")
def get_analytics(timeframe: str = "24h"):
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
            try:
                with open("governance_audit.json", "r") as f:
                    audit_logs = json.load(f)
            except:
                audit_logs = []
                
            for log in audit_logs:
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
