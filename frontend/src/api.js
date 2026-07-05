const API_BASE = 'http://localhost:8000';

export async function fetchRules() {
  const res = await fetch(`${API_BASE}/rules`);
  return res.json();
}

export async function fetchTestCases() {
  const res = await fetch(`${API_BASE}/test_cases`);
  return res.json();
}

export async function addRule(rule) {
  const res = await fetch(`${API_BASE}/add_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rule)
  });
  return res.json();
}

export async function updateRule(ruleData) {
  const res = await fetch(`${API_BASE}/update_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ruleData)
  });
  return res.json();
}

export async function deleteRule(name) {
  const res = await fetch(`${API_BASE}/delete_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  });
  return res.json();
}

export async function fetchAlarms() {
  const res = await fetch(`${API_BASE}/alarms`);
  return res.json();
}

export async function deleteAlarm(alarm_id, status = 'DISMISSED') {
  const res = await fetch(`${API_BASE}/delete_alarm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ alarm_id, status })
  });
  return res.json();
}

export async function fetchAnalytics(timeframe = '24h') {
  const res = await fetch(`${API_BASE}/analytics?timeframe=${timeframe}`);
  return res.json();
}

export async function toggleWatchdog(enable_llm_watchdog) {
  const res = await fetch(`${API_BASE}/toggle_watchdog`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enable_llm_watchdog })
  });
  return res.json();
}

export async function fetchSubscribers() {
  const res = await fetch(`${API_BASE}/subscribers`);
  return res.json();
}

export async function addSubscriber(subscriber) {
  const res = await fetch(`${API_BASE}/add_subscriber`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscriber)
  });
  return res.json();
}

export async function updateSubscriber(subscriber) {
  const res = await fetch(`${API_BASE}/update_subscriber`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscriber)
  });
  return res.json();
}

export async function deleteSubscriber(user_name) {
  const res = await fetch(`${API_BASE}/delete_subscriber`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_name })
  });
  return res.json();
}

export async function queryDb(customerId) {
  const res = await fetch(`${API_BASE}/query_db`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ customer_id: customerId })
  });
  return res.json();
}

export async function governAi(text) {
  const res = await fetch(`${API_BASE}/govern_ai`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
  });
  return res.json();
}

export async function chatAgent(message) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  return res.json();
}

export async function sandboxSuggestRule(context_snippet, missed_entity_type, value_preview) {
  const res = await fetch(`${API_BASE}/sandbox_suggest_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context_snippet, missed_entity_type, value_preview })
  });
  return res.json();
}

export async function sandboxTestRule(context_snippet, regex_pattern, entity_name) {
  const res = await fetch(`${API_BASE}/sandbox_test_rule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context_snippet, regex_pattern, entity_name })
  });
  return res.json();
}

