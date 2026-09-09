// Reads the backend port from frontend/.env (VITE_API_BASE), falling back to 8000 if
// that file is missing. The backend's own port lives in start_backend.bat's --port flag
// -- when you change one, change the other. A restart of `npm run dev` is required after
// editing .env (unlike a source file, Vite only reads env files at server startup).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// Authentication was removed from the backend by explicit request (see auth.py and
// api.py's run_guard_self_test) -- no endpoint checks a header any more, so nothing
// here needs to carry one. The shared apiFetch/postJson helpers are kept because they
// still centralize the fetch-and-parse boilerplate every one of these calls repeats.
async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  return res.json();
}

function postJson(path, body) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchSystemStatus() {
  try {
    return await apiFetch('/system_status');
  } catch (e) {
    return { status: 'loading' };
  }
}

export async function fetchRules() {
  return apiFetch('/rules');
}

export async function fetchTestCases() {
  return apiFetch('/test_cases');
}

export async function addRule(rule) {
  return postJson('/add_rule', rule);
}

export async function updateRule(ruleData) {
  return postJson('/update_rule', ruleData);
}

export async function deleteRule(name) {
  return postJson('/delete_rule', { name });
}

export async function fetchAlarms() {
  return apiFetch('/alarms');
}

export async function deleteAlarm(alarm_id, status = 'DISMISSED') {
  return postJson('/delete_alarm', { alarm_id, status });
}

export async function fetchAnalytics(timeframe = '24h') {
  return apiFetch(`/analytics?timeframe=${timeframe}`);
}

export async function toggleWatchdog(enable_llm_watchdog) {
  return postJson('/toggle_watchdog', { enable_llm_watchdog });
}

export async function toggleCategory(category, enabled) {
  return postJson('/toggle_category', { category, enabled });
}

export async function fetchSubscribers() {
  return apiFetch('/subscribers');
}

export async function addSubscriber(subscriber) {
  return postJson('/add_subscriber', subscriber);
}

export async function updateSubscriber(subscriber) {
  return postJson('/update_subscriber', subscriber);
}

export async function deleteSubscriber(user_name) {
  return postJson('/delete_subscriber', { user_name });
}

export async function queryDb(customerId) {
  return postJson('/query_db', { customer_id: customerId });
}

export async function governAi(text) {
  return postJson('/govern_ai', { text });
}

export async function chatAgent(message, purpose = '') {
  // purpose opts every /chat call into the Consent Gate (see tool_broker.py) -- an
  // empty string is a real, checkable value ("nothing declared"), not the same as
  // omitting the field.
  return postJson('/chat', { message, purpose });
}

export async function demoChat(message, mode, purpose = '') {
  return postJson('/demo_chat', { message, mode, purpose });
}

export async function sandboxSuggestRule(context_snippet, missed_entity_type, value_preview) {
  return postJson('/sandbox_suggest_rule', { context_snippet, missed_entity_type, value_preview });
}

export async function sandboxTestRule(context_snippet, regex_pattern, entity_name) {
  return postJson('/sandbox_test_rule', { context_snippet, regex_pattern, entity_name });
}

export async function toggleToxicity(enable_toxicity_guard) {
  return postJson('/toggle_toxicity', { enable_toxicity_guard });
}

export async function fetchToxicitySettings() {
  return apiFetch('/toxicity_settings');
}

export async function fetchBenchmarks() {
  return apiFetch('/get_benchmarks');
}

// Generic validation for external systems: send raw text, get back a CLEAR / PARTIAL /
// BLOCKED verdict plus the resulting message. Unlike demoChat/chatAgent, this never
// calls the LLM -- it only runs the toxicity and PII/financial/health checks directly.
export async function guardrailValidate(text) {
  return postJson('/guardrail_validate', { text });
}

export async function fetchConsents() {
  return apiFetch('/consents');
}

export async function withdrawConsent(customer_id, data_category, purpose) {
  return postJson('/withdraw_consent', { customer_id, data_category, purpose });
}

export async function updateToxicitySettings({ thresholds, enable_toxicity_guard }) {
  // Takes the request body shape directly -- the caller already builds
  // { thresholds, enable_toxicity_guard }, and wrapping it again here used to nest it
  // one level too deep (body: { thresholds: { thresholds, enable_toxicity_guard } }),
  // which the backend's UpdateToxicitySettingsRequest could not have matched.
  return postJson('/update_toxicity_settings', { thresholds, enable_toxicity_guard });
}
