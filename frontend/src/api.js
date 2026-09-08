const API_BASE = 'http://localhost:8000';

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

export async function chatAgent(message) {
  return postJson('/chat', { message });
}

export async function demoChat(message, mode) {
  return postJson('/demo_chat', { message, mode });
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

export async function updateToxicitySettings({ thresholds, enable_toxicity_guard }) {
  // Takes the request body shape directly -- the caller already builds
  // { thresholds, enable_toxicity_guard }, and wrapping it again here used to nest it
  // one level too deep (body: { thresholds: { thresholds, enable_toxicity_guard } }),
  // which the backend's UpdateToxicitySettingsRequest could not have matched.
  return postJson('/update_toxicity_settings', { thresholds, enable_toxicity_guard });
}
