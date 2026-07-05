import requests
import json
import logging

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """You are a data privacy auditor. Analyze the following text and identify 
ANY sensitive, private, or confidential information that should not be 
exposed publicly. This includes but is not limited to:

- Personal identifiers (names, IDs, passport numbers)
- Contact information (email, phone, address)
- Financial data (account numbers, salary, credit cards, API keys)
- Authentication data (passwords, tokens, secrets, keys)
- Medical / health information
- Internal identifiers (employee IDs, case numbers)
- Any other data that could identify an individual or compromise security

For each finding, respond ONLY in this strict JSON format. Do NOT add any extra text or markdown, just raw JSON:
{
  "findings": [
    {"type": "CATEGORY", "value": "the sensitive text", "reason": "why it's sensitive"}
  ],
  "has_sensitive_data": true
}

If the text is clean, return {"findings": [], "has_sensitive_data": false}"""

def analyze_text(raw_text: str) -> dict:
    """
    Asynchronously (or synchronously within a background thread) calls the LLM watchdog
    to perform semantic PII analysis.
    """
    if not raw_text or len(raw_text.strip()) == 0:
        return {"findings": [], "has_sensitive_data": False}
        
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"TEXT TO ANALYZE:\n{raw_text}"}
    ]
    
    payload = {
        "model": "phi4-mini:3.8b",
        "messages": messages,
        "stream": False,
        "format": "json"
    }
    
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=30)
        if resp.status_code == 200:
            ai_message = resp.json()["message"]["content"]
            try:
                result = json.loads(ai_message)
                return result
            except json.JSONDecodeError:
                logging.error(f"Failed to parse Watchdog JSON: {ai_message}")
                return {"findings": [], "has_sensitive_data": False, "error": "Invalid JSON from LLM"}
        else:
            logging.error(f"Ollama Watchdog Error: {resp.status_code}")
            return {"findings": [], "has_sensitive_data": False, "error": f"Ollama HTTP {resp.status_code}"}
    except Exception as e:
        logging.error(f"Watchdog Exception: {str(e)}")
        return {"findings": [], "has_sensitive_data": False, "error": str(e)}
