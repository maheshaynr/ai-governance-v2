const API_BASE = 'http://localhost:8000';
const STORAGE_KEY = 'gov_api_key';

// Every endpoint except /system_status now requires an X-API-Key header (see auth.py).
// The key is entered once at the login gate in App.jsx and kept here for every request
// this tab makes -- localStorage so a refresh doesn't force logging in again.
let currentApiKey = '';
try {
  currentApiKey = localStorage.getItem(STORAGE_KEY) || '';
} catch {
  // Private browsing / storage disabled -- fall back to in-memory only for this tab.
}

export function setApiKey(key) {
  currentApiKey = key || '';
  try {
    if (currentApiKey) localStorage.setItem(STORAGE_KEY, currentApiKey);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore -- the in-memory copy still works for this tab.
  }
}

export function getApiKey() {
  return currentApiKey;
}

export function clearApiKey() {
  setApiKey('');
}

/** Thrown when the server rejects the current key (missing, unknown, or wrong role). */
export class AuthError extends Error {
  constructor(status, detail) {
    super(detail || 'Authentication failed');
    this.name = 'AuthError';
    this.status = status;
  }
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (currentApiKey) headers['X-API-Key'] = currentApiKey;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401 || res.status === 403) {
    let detail = res.status === 401 ? 'Invalid or missing API key.' : 'Not permitted.';
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // Non-JSON error body -- keep the default message.
    }
    throw new AuthError(res.status, detail);
  }

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
  // Deliberately open (see auth.py) so health checks and the login screen itself work
  // without a key -- calls apiFetch anyway so a key present in localStorage still gets
  // sent, but a missing/invalid one here should not raise a screen-wide AuthError.
  try {
    return await apiFetch('/system_status');
  } catch (e) {
    return { status: 'loading' };
  }
}

export async function fetchWhoAmI() {
  return apiFetch('/whoami');
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
