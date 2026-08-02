import requests
import json
import logging
import config

# Remove local OLLAMA_URL definition, using config.OLLAMA_URL instead

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
    {"type": "CATEGORY", "value": "the exact sensitive data value ONLY (e.g. the 16-digit number, NOT the words 'credit card')", "reason": "why it's sensitive"}
  ],
  "has_sensitive_data": true
}

CRITICAL INSTRUCTION: For the "value" field, extract ONLY the exact sensitive data values (e.g., the actual digits, the actual API key string). DO NOT extract the labels, field names, or surrounding context (e.g., DO NOT extract 'credit card number' or 'password is', ONLY extract the actual number or password itself).

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
        "model": config.DEFAULT_LLM_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "keep_alive": -1
    }
    
    try:
        logging.info(f"Sending request to Ollama ({config.OLLAMA_URL}) with model '{payload['model']}' | Input length: {len(raw_text)} chars")
        resp = requests.post(config.OLLAMA_URL, json=payload, timeout=120)
        logging.info(f"Ollama responded with status {resp.status_code}")
        if resp.status_code == 200:
            ai_message = resp.json()["message"]["content"]
            try:
                result = json.loads(ai_message)
                return result
            except json.JSONDecodeError:
                logging.error(f"LLM Watchdog failed to return valid JSON. Response: {ai_message}")
                return {"findings": [], "has_sensitive_data": False, "error": "Invalid JSON from LLM", "raw_response": ai_message}
        else:
            logging.error(f"Ollama Watchdog Error: {resp.status_code} - {resp.text}")
            return {"findings": [], "has_sensitive_data": False, "error": f"Ollama HTTP {resp.status_code}", "raw_response": resp.text}
    except Exception as e:
        logging.error(f"Watchdog Exception: {str(e)}")
        return {"findings": [], "has_sensitive_data": False, "error": str(e)}
