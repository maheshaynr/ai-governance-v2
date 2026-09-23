import { useState, useEffect } from 'react';
import { fetchRules, addRule, updateRule, deleteRule, toggleWatchdog, fetchSubscribers, addSubscriber, updateSubscriber, deleteSubscriber, toggleToxicity, fetchToxicitySettings, updateToxicitySettings, toggleCategory } from './api';

// Authentication was removed from the backend by explicit request -- see auth.py and
// api.py's run_guard_self_test. There is no more login gate to supply a real principal
// (App.jsx no longer passes one), so this default stands in for it: every one of this
// component's `principal.role === 'admin_pii'` checks below now simply never restricts
// anything, since nothing ever sets the role to admin_pii any more. Left in place
// rather than stripped out at each of those ~24 call sites, so re-adding real identity
// later is a matter of passing a real principal again, not rewriting this file.
const DEFAULT_PRINCIPAL = { name: 'anonymous', role: 'super_admin', is_admin: true };

export default function AdminConfig({ principal = DEFAULT_PRINCIPAL, rulePrefill = null, onConsumeRulePrefill }) {
  const [activeTab, setActiveTab] = useState('rules'); // 'rules', 'routing', 'toxicity'

  const [rules, setRules] = useState([]);
  const [subscribers, setSubscribers] = useState([]);
  const [llmWatchdogEnabled, setLlmWatchdogEnabled] = useState(false);
  const [isTogglingWatchdog, setIsTogglingWatchdog] = useState(false);
  const [toxicityGuardEnabled, setToxicityGuardEnabled] = useState(false);
  const [isTogglingToxicity, setIsTogglingToxicity] = useState(false);
  const [toxicityThresholds, setToxicityThresholds] = useState({});
  const [isSavingToxicity, setIsSavingToxicity] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryMappings, setCategoryMappings] = useState({});
  const [categoryToggles, setCategoryToggles] = useState({
    pii: true,
    health: true,
    financial: true,
    authentication: true
  });
  const [isTogglingCategory, setIsTogglingCategory] = useState({});

  const [selectedCategory, setSelectedCategory] = useState('PII');
  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [editingSubscriber, setEditingSubscriber] = useState(null);
  
  const [formData, setFormData] = useState({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
  const [subFormData, setSubFormData] = useState({ user_name: '', role: '', alert_type: 'ALL', email: '' });
  
  const [formMessage, setFormMessage] = useState(null);
  const [subFormMessage, setSubFormMessage] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    loadRules();
    loadSubscribers();
  }, [activeTab]);

  useEffect(() => {
    if (rulePrefill) {
      setActiveTab('rules');
      setFormData({ name: `New_${rulePrefill.entity}`, entity: rulePrefill.entity, regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
      setFormMessage({ type: 'success', text: `Auto-filled form for ${rulePrefill.entity}. Please define Regex or select Built-in AI.`});
      if (onConsumeRulePrefill) onConsumeRulePrefill();
    }
  }, [rulePrefill]);

  const loadRules = async () => {
    try {
      const data = await fetchRules();
      if (data.rules) setRules(data.rules);
      if (data.category_mappings) setCategoryMappings(data.category_mappings);
      if (data.settings) {
        if (data.settings.enable_llm_watchdog !== undefined) setLlmWatchdogEnabled(data.settings.enable_llm_watchdog);
        if (data.settings.enable_toxicity_guard !== undefined) setToxicityGuardEnabled(data.settings.enable_toxicity_guard);
        if (data.settings.toxicity_thresholds) setToxicityThresholds(data.settings.toxicity_thresholds);
        
        setCategoryToggles({
          pii: data.settings.enable_pii !== false,
          health: data.settings.enable_health !== false,
          financial: data.settings.enable_financial !== false,
          authentication: data.settings.enable_authentication !== false
        });
      }
    } catch (e) {
      console.error("Failed to load rules", e);
    }
  };

  const handleToggleCategory = async (category, enabled) => {
    setIsTogglingCategory(prev => ({ ...prev, [category]: true }));
    try {
      await toggleCategory(category, enabled);
      setCategoryToggles(prev => ({ ...prev, [category]: enabled }));
      loadRules();
    } catch (e) {
      console.error(`Failed to toggle ${category}`, e);
    } finally {
      setIsTogglingCategory(prev => ({ ...prev, [category]: false }));
    }
  };

  const loadSubscribers = async () => {
    try {
      const data = await fetchSubscribers();
      if (data.subscribers) setSubscribers(data.subscribers);
    } catch (e) {
      console.error("Failed to load subscribers", e);
    }
  };

  const handleToggleWatchdog = async (enabled) => {
    setIsTogglingWatchdog(true);
    try {
      await toggleWatchdog(enabled);
      setLlmWatchdogEnabled(enabled);
    } catch (e) {
      console.error("Failed to toggle watchdog", e);
    } finally {
      setIsTogglingWatchdog(false);
    }
  };

  const handleToggleToxicity = async (enabled) => {
    setIsTogglingToxicity(true);
    try {
      await toggleToxicity(enabled);
      setToxicityGuardEnabled(enabled);
    } catch (e) {
      console.error("Failed to toggle toxicity guard", e);
    } finally {
      setIsTogglingToxicity(false);
    }
  };

  const handleSaveToxicitySettings = async () => {
    setIsSavingToxicity(true);
    try {
      await updateToxicitySettings({ thresholds: toxicityThresholds, enable_toxicity_guard: toxicityGuardEnabled });
      alert("Toxicity settings saved successfully!");
    } catch (e) {
      console.error("Failed to save toxicity settings", e);
      alert("Failed to save toxicity settings.");
    } finally {
      setIsSavingToxicity(false);
    }
  };

  const getRuleCategory = (entity) => {
    if (!entity) return 'UNCATEGORIZED';
    const e = entity.toUpperCase();
    for (const [cat, keywords] of Object.entries(categoryMappings || {})) {
      if (keywords && Array.isArray(keywords) && keywords.some(k => e.includes(k))) return cat;
    }
    return 'UNCATEGORIZED';
  };

  const handleEditClick = (rule) => {
    setEditingRule(rule);
    setFormData({ 
      name: rule.name, 
      entity: rule.entity, 
      regex: rule.regex || '', 
      score: rule.score || 0.85, 
      is_builtin: rule.is_builtin || false, 
      is_algorithmic: rule.is_algorithmic || false, 
      is_active: rule.is_active !== false,
      category: getRuleCategory(rule.entity)
    });
    setFormMessage(null);
    setIsRuleModalOpen(true);
  };

  const handleCancelEdit = () => {
    setEditingRule(null);
    setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
    setFormMessage(null);
    setIsRuleModalOpen(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.entity || (!formData.is_builtin && !formData.is_algorithmic && !formData.regex)) {
      setFormMessage({ type: 'error', text: 'All fields are required.' });
      return;
    }

    setIsSaving(true);
    setFormMessage(null);

    try {
      if (editingRule) {
        const payload = { ...formData, original_name: editingRule.name };
        const res = await updateRule(payload);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule updated and hot-reloaded!' });
          setEditingRule(null);
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
          setIsRuleModalOpen(false);
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addRule(formData);
        if (res.status === 'success') {
          setFormMessage({ type: 'success', text: 'Rule added and hot-reloaded!' });
          setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
          setIsRuleModalOpen(false);
        } else {
          setFormMessage({ type: 'error', text: res.message });
        }
      }
      loadRules();
    } catch (e) {
      setFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!editingRule) return;
    if (!window.confirm(`Are you sure you want to delete ${editingRule.name}?`)) return;

    setIsSaving(true);
    setFormMessage(null);

    try {
      const res = await deleteRule(editingRule.name);
      if (res.status === 'success') {
        setFormMessage({ type: 'success', text: 'Rule deleted!' });
        setEditingRule(null);
        setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: 'UNCATEGORIZED' });
        setIsRuleModalOpen(false);
        loadRules();
      } else {
        setFormMessage({ type: 'error', text: res.message });
      }
    } catch (e) {
      setFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteDirect = async (rule) => {
    if (!window.confirm(`Are you sure you want to delete ${rule.name}?`)) return;
    try {
      const res = await deleteRule(rule.name);
      if (res.status === 'success') {
        loadRules();
      } else {
        alert(res.message);
      }
    } catch (e) {
      alert('Failed to connect to backend.');
    }
  };

  const handleToggleRuleActive = async (rule) => {
    const payload = { ...rule, original_name: rule.name, is_active: rule.is_active === false ? true : false };
    try {
      await updateRule(payload);
      loadRules();
    } catch (e) {
      console.error("Failed to toggle rule", e);
    }
  };

  const handleEditSubscriberClick = (s) => {
    setEditingSubscriber(s);
    setSubFormData({ user_name: s.user_name, role: s.role, alert_type: s.alert_type, email: s.email || '' });
    setSubFormMessage(null);
  };

  const handleCancelEditSubscriber = () => {
    setEditingSubscriber(null);
    setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
    setSubFormMessage(null);
  };

  const handleAddSubscriber = async (e) => {
    e.preventDefault();
    if (!subFormData.user_name || !subFormData.role) {
      setSubFormMessage({ type: 'error', text: 'Name and Role are required.' });
      return;
    }
    if (!subFormData.email) {
      setSubFormMessage({ type: 'error', text: 'Email is required.' });
      return;
    }
    
    setIsSaving(true);
    try {
      if (editingSubscriber) {
        const payload = { ...subFormData, original_user_name: editingSubscriber.user_name };
        const res = await updateSubscriber(payload);
        if (res.status === 'success') {
          setSubFormMessage({ type: 'success', text: 'Subscriber updated!' });
          setEditingSubscriber(null);
          setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
          loadSubscribers();
        } else {
          setSubFormMessage({ type: 'error', text: res.message });
        }
      } else {
        const res = await addSubscriber(subFormData);
        if (res.status === 'success') {
          setSubFormMessage({ type: 'success', text: 'Subscriber added!' });
          setSubFormData({ user_name: '', role: '', alert_type: 'ALL', email: '' });
          loadSubscribers();
        } else {
          setSubFormMessage({ type: 'error', text: res.message });
        }
      }
    } catch (e) {
      setSubFormMessage({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteSubscriber = async (user_name) => {
    if (!window.confirm(`Remove subscriber ${user_name}?`)) return;
    try {
      await deleteSubscriber(user_name);
      loadSubscribers();
    } catch (e) {
      console.error(e);
    }
  };

  const filteredRules = rules.filter(r =>
    r.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    r.entity.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem'}}>
        <h2>⚙️ Enterprise Governance Command Center</h2>
        <div style={{display: 'flex', gap: '1rem', alignItems: 'center'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#f6f8fa', padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #d0d7de'}}>
            <label style={{margin: 0, fontWeight: '600', fontSize: '0.9rem', color: '#24292f'}}>Secondary Threat Engine:</label>
            {isTogglingWatchdog ? (
              <span style={{ fontSize: '0.8rem', color: '#57606a', fontStyle: 'italic', marginLeft: '0.5rem' }}>⏳ Updating...</span>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <label className="switch" style={{position: 'relative', display: 'inline-block', width: '40px', height: '20px', opacity: principal.role === 'admin_pii' ? 0.5 : 1}}>
                  <input type="checkbox" checked={llmWatchdogEnabled} disabled={principal.role === 'admin_pii'} onChange={(e) => handleToggleWatchdog(e.target.checked)} style={{opacity: 0, width: 0, height: 0}} />
                  <span className="slider" style={{position: 'absolute', cursor: principal.role === 'admin_pii' ? 'not-allowed' : 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: llmWatchdogEnabled ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '20px'}}>
                    <span style={{position: 'absolute', height: '14px', width: '14px', left: llmWatchdogEnabled ? '22px' : '3px', bottom: '3px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
                  </span>
                </label>
                {principal.role === 'admin_pii' && <span title="Requires Super Admin" style={{ cursor: 'help' }}>🔒</span>}
              </div>
            )}
          </div>
          <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem', background: '#f6f8fa', padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #d0d7de'}}>
            <label style={{margin: 0, fontWeight: '600', fontSize: '0.9rem', color: '#24292f'}}>Content Safety:</label>
            {isTogglingToxicity ? (
              <span style={{ fontSize: '0.8rem', color: '#57606a', fontStyle: 'italic', marginLeft: '0.5rem' }}>⏳ Updating...</span>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <label className="switch" style={{position: 'relative', display: 'inline-block', width: '40px', height: '20px', opacity: principal.role === 'admin_pii' ? 0.5 : 1}}>
                  <input type="checkbox" checked={toxicityGuardEnabled} disabled={principal.role === 'admin_pii'} onChange={(e) => handleToggleToxicity(e.target.checked)} style={{opacity: 0, width: 0, height: 0}} />
                  <span className="slider" style={{position: 'absolute', cursor: principal.role === 'admin_pii' ? 'not-allowed' : 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: toxicityGuardEnabled ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '20px'}}>
                    <span style={{position: 'absolute', height: '14px', width: '14px', left: toxicityGuardEnabled ? '22px' : '3px', bottom: '3px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
                  </span>
                </label>
                {principal.role === 'admin_pii' && <span title="Requires Super Admin" style={{ cursor: 'help' }}>🔒</span>}
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', borderBottom: '1px solid #d0d7de', paddingBottom: '0.5rem' }}>
        <button 
          onClick={() => setActiveTab('rules')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'rules' ? '#0969da' : '#57606a', borderBottom: activeTab === 'rules' ? '2px solid #0969da' : '2px solid transparent', cursor: 'pointer' }}>
          Rule Configuration
        </button>
        <button
          onClick={() => setActiveTab('routing')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'routing' ? '#9a6700' : '#57606a', borderBottom: activeTab === 'routing' ? '2px solid #d29922' : '2px solid transparent', cursor: 'pointer' }}>
          Alert Routing
        </button>
        <button
          onClick={() => setActiveTab('toxicity')}
          style={{ background: 'none', border: 'none', padding: '0.5rem 1rem', fontSize: '1rem', fontWeight: '600', color: activeTab === 'toxicity' ? '#8b5cf6' : '#57606a', borderBottom: activeTab === 'toxicity' ? '2px solid #8b5cf6' : '2px solid transparent', cursor: 'pointer' }}>
          Toxicity Guard
        </button>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', padding: '0.5rem 1rem', fontSize: '0.9rem', color: '#57606a', fontWeight: 'bold' }}>
          👤 {principal.role === 'super_admin' ? 'Super Admin' : 'PII Admin'}
        </div>
      </div>

      {activeTab === 'toxicity' && (
        <div className="card" style={{ maxWidth: '600px', margin: '0 auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3>🛡️ Content Toxicity Guard</h3>
            {principal.role === 'admin_pii' && <span style={{ backgroundColor: '#fff8c5', color: '#9a6700', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.8rem', border: '1px solid #d4a72c' }}>🔒 Super Admin Only</span>}
          </div>
          <p style={{ color: '#57606a', fontSize: '0.9rem', marginBottom: '1.5rem' }}>Adjust the sensitivity thresholds for the AI toxicity guard. A lower threshold makes the guard stricter, catching more subtle language but potentially causing false positives. Values range from 0.0 to 1.0.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', opacity: principal.role === 'admin_pii' ? 0.6 : 1, pointerEvents: principal.role === 'admin_pii' ? 'none' : 'auto' }}>
            {Object.keys(toxicityThresholds).map((category) => (
              <div key={category} className="form-group" style={{ marginBottom: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label style={{ margin: 0, textTransform: 'capitalize' }}>{category.replace(/_/g, ' ')}</label>
                  <span style={{ fontWeight: 'bold', color: toxicityThresholds[category] < 0.6 ? '#cf222e' : '#2da44e' }}>{toxicityThresholds[category]}</span>
                </div>
                <input 
                  type="range" 
                  min="0" max="1" step="0.05" 
                  value={toxicityThresholds[category]} 
                  onChange={(e) => setToxicityThresholds({...toxicityThresholds, [category]: parseFloat(e.target.value)})} 
                  style={{ width: '100%', marginTop: '0.5rem' }}
                />
              </div>
            ))}
          </div>
          <button className="primary" onClick={handleSaveToxicitySettings} disabled={isSavingToxicity || principal.role === 'admin_pii'} style={{ marginTop: '2rem', width: '100%' }}>
            {isSavingToxicity ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      )}

      {activeTab === 'rules' && (
        <div className="admin-layout" style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>
          
          {/* Left Panel: Category Sidebar */}
          <div className="category-sidebar" style={{ flex: '0 0 280px' }}>
            <h3 style={{ margin: '0 0 1rem 0' }}>Guardrail Modules</h3>
            {['PII', 'HEALTH', 'FINANCIAL', 'AUTHENTICATION', 'UNCATEGORIZED'].map(cat => {
              const catKey = cat.toLowerCase();
              const isEnabled = cat === 'UNCATEGORIZED' ? true : categoryToggles[catKey];
              const isToggling = isTogglingCategory[catKey];
              const isRestrictedCat = principal.role === 'admin_pii' && catKey !== 'pii' && catKey !== 'uncategorized';
              
              return (
                <div 
                  key={cat} 
                  className={`category-card ${selectedCategory === cat ? 'active' : ''}`}
                  onClick={() => !isRestrictedCat && setSelectedCategory(cat)}
                  style={{ 
                    opacity: isRestrictedCat ? 0.7 : 1,
                    cursor: isRestrictedCat ? 'not-allowed' : 'pointer'
                  }}
                >
                  <div className="category-card-content">
                    <h4 className="category-card-title">
                      {cat} {isRestrictedCat && <span title="Requires Super Admin" style={{ cursor: 'help', marginLeft: '0.25rem', fontSize: '1rem' }}>🔒</span>}
                    </h4>
                    <span style={{ fontSize: '0.75rem', fontWeight: 'bold', color: isEnabled ? '#1a7f37' : '#cf222e' }}>
                      {isEnabled ? 'ACTIVE' : 'DISABLED'}
                    </span>
                  </div>
                  
                  <div className="category-card-actions" onClick={e => e.stopPropagation()}>
                    {cat !== 'UNCATEGORIZED' && (
                      <label className="switch" style={{position: 'relative', display: 'inline-block', width: '30px', height: '16px', opacity: isRestrictedCat ? 0.5 : 1}}>
                        <input type="checkbox" checked={isEnabled} disabled={isRestrictedCat} onChange={(e) => handleToggleCategory(catKey, e.target.checked)} style={{opacity: 0, width: 0, height: 0}} />
                        <span className="slider" style={{position: 'absolute', cursor: isRestrictedCat ? 'not-allowed' : 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: isEnabled ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '16px'}}>
                          <span style={{position: 'absolute', height: '12px', width: '12px', left: isEnabled ? '16px' : '2px', bottom: '2px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
                        </span>
                      </label>
                    )}
                    
                    <button 
                      className="btn-add-rule" 
                      title="Add New Rule" 
                      disabled={isRestrictedCat}
                      style={{ cursor: isRestrictedCat ? 'not-allowed' : 'pointer', opacity: isRestrictedCat ? 0.5 : 1 }}
                      onClick={() => {
                        setEditingRule(null);
                        setFormData({ name: '', entity: '', regex: '', score: 0.85, is_builtin: false, is_algorithmic: false, is_active: true, category: cat });
                        setIsRuleModalOpen(true);
                      }}
                    >
                      +
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Right Panel: Rules Viewer */}
          <div className="rule-viewer" style={{ flex: '1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0 }}>{selectedCategory} Configurations</h3>
              <input 
                type="text" 
                placeholder="🔍 Search rules..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ padding: '0.4rem 0.8rem', borderRadius: '20px', border: '1px solid #d0d7de', fontSize: '0.85rem', width: '250px', margin: 0 }}
              />
            </div>

            <div style={{ border: '1px solid #d0d7de', borderRadius: '8px', background: '#fff', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                <thead style={{ background: '#f6f8fa' }}>
                  <tr>
                    <th style={{ padding: '1rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Rule Name</th>
                    <th style={{ padding: '1rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Entity Class</th>
                    <th style={{ padding: '1rem', borderBottom: '1px solid #d0d7de', whiteSpace: 'nowrap' }}>Type</th>
                    <th style={{ padding: '1rem', borderBottom: '1px solid #d0d7de', textAlign: 'center', whiteSpace: 'nowrap' }}>Status</th>
                    <th style={{ padding: '1rem', borderBottom: '1px solid #d0d7de', textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRules.filter(r => getRuleCategory(r.entity) === selectedCategory).length === 0 ? (
                    <tr>
                      <td colSpan="5" style={{ padding: '3rem', textAlign: 'center', color: '#57606a' }}>No configurations found for {selectedCategory}.</td>
                    </tr>
                  ) : filteredRules.filter(r => getRuleCategory(r.entity) === selectedCategory).map((r, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #d0d7de' }}>
                      <td style={{ padding: '1rem', fontWeight: '500' }}>{r.name}</td>
                      <td style={{ padding: '1rem', fontFamily: 'monospace', color: '#cf222e' }}>{r.entity}</td>
                      <td style={{ padding: '1rem', whiteSpace: 'nowrap' }}>
                        {r.is_algorithmic ? (
                          <span style={{ backgroundColor: '#f3e8ff', color: '#7e22ce', padding: '4px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '600' }}>🧬 Algorithmic</span>
                        ) : (
                          <span style={{ backgroundColor: r.is_builtin ? '#dafbe1' : '#ddf4ff', color: r.is_builtin ? '#1a7f37' : '#0969da', padding: '4px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '600' }}>
                            {r.is_builtin ? '✨ Built-In AI' : '⚙️ Custom Regex'}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '1rem', textAlign: 'center' }}>
                        <label className="switch" style={{position: 'relative', display: 'inline-block', width: '30px', height: '16px'}}>
                          <input type="checkbox" checked={r.is_active !== false} onChange={() => handleToggleRuleActive(r)} style={{opacity: 0, width: 0, height: 0}} />
                          <span className="slider" style={{position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: r.is_active !== false ? '#2da44e' : '#cf222e', transition: '.4s', borderRadius: '16px'}}>
                            <span style={{position: 'absolute', height: '12px', width: '12px', left: r.is_active !== false ? '16px' : '2px', bottom: '2px', backgroundColor: 'white', transition: '.4s', borderRadius: '50%'}}></span>
                          </span>
                        </label>
                      </td>
                      <td style={{ padding: '1rem', textAlign: 'right' }}>
                        <button className="secondary" title="Edit" style={{padding: '0.3rem 0.5rem', fontSize: '1.2rem', border: 'none', background: 'transparent'}} onClick={() => handleEditClick(r)}>✏️</button>
                        <button className="secondary" title="Delete" style={{padding: '0.3rem 0.5rem', fontSize: '1.2rem', border: 'none', background: 'transparent'}} onClick={() => handleDeleteDirect(r)}>🗑️</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          
          {/* Rule Modal Overlay */}
          {isRuleModalOpen && (
            <div className="modal-overlay">
              <div className="modal-content">
                <button className="modal-close" onClick={handleCancelEdit}>&times;</button>
                <h3 style={{ marginTop: 0 }}>{editingRule ? 'Edit Configuration' : 'Add New Configuration'}</h3>
                
                <form onSubmit={handleSubmit}>
                  <div className="form-group">
                    <label>Category</label>
                    <select 
                      value={formData.category} 
                      onChange={e => setFormData({...formData, category: e.target.value})}
                      style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #d0d7de' }}
                    >
                      {['PII', 'HEALTH', 'FINANCIAL', 'AUTHENTICATION', 'UNCATEGORIZED'].map(cat => (
                        <option key={cat} value={cat}>{cat}</option>
                      ))}
                    </select>
                  </div>
                  
                  <div className="form-group">
                    <label>Configuration Alias Name</label>
                    <input type="text" value={formData.name} onChange={e => setFormData({...formData, name: e.target.value})} required />
                  </div>

                  <div className="form-group">
                    <label>Entity Class Tag</label>
                    <input type="text" value={formData.entity} onChange={e => setFormData({...formData, entity: e.target.value})} required />
                    <small className="help-text">Output will be masked with &lt;ENTITY_CLASS&gt;</small>
                  </div>

                  <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <input type="checkbox" checked={formData.is_active} onChange={e => setFormData({...formData, is_active: e.target.checked})} style={{ width: 'auto', margin: 0 }} />
                      <label style={{ margin: 0, fontWeight: 'bold' }}>Active</label>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <input type="checkbox" checked={formData.is_builtin} onChange={e => setFormData({...formData, is_builtin: e.target.checked, is_algorithmic: false, regex: e.target.checked ? '' : formData.regex})} style={{ width: 'auto', margin: 0 }} />
                      <label style={{ margin: 0 }}>Built-in AI</label>
                    </div>
                  </div>

                  <div className="form-group">
                    <label style={{ color: (formData.is_builtin || formData.is_algorithmic) ? '#8c959f' : 'inherit' }}>Regex Pattern</label>
                    <input type="text" value={formData.regex} onChange={e => setFormData({...formData, regex: e.target.value})} disabled={formData.is_builtin || formData.is_algorithmic} style={{ backgroundColor: (formData.is_builtin || formData.is_algorithmic) ? '#f6f8fa' : '#fff' }} />
                  </div>

                  <div className="form-group">
                    <label>Confidence Score: {formData.score}</label>
                    <input type="range" min="0" max="1" step="0.05" value={formData.score} onChange={e => setFormData({...formData, score: parseFloat(e.target.value)})} />
                  </div>

                  <div style={{display: 'flex', gap: '1rem', alignItems: 'center', marginTop: '1.5rem'}}>
                    <button type="submit" className="primary" disabled={isSaving} style={{ flex: 1 }}>
                      {isSaving ? 'Processing...' : (editingRule ? 'Update Configuration' : 'Save Configuration')}
                    </button>
                    {editingRule && (
                      <button type="button" onClick={handleDelete} disabled={isSaving} style={{ backgroundColor: '#cf222e', color: 'white', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px', cursor: isSaving ? 'not-allowed' : 'pointer' }}>
                        Delete
                      </button>
                    )}
                  </div>
                  
                  {formMessage && (
                    <div className={`alert-${formMessage.type}`}>{formMessage.text}</div>
                  )}
                </form>
              </div>
            </div>
          )}

        </div>
      )}


      {activeTab === 'routing' && (
        <div className="admin-layout">
          <div className="rules-list">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 style={{ margin: 0 }}>Active Notification Subscribers</h3>
              <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                {principal.role === 'admin_pii' && <span style={{ backgroundColor: '#fff8c5', color: '#9a6700', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.8rem', border: '1px solid #d4a72c' }}>🔒 Super Admin Only</span>}
                <button onClick={loadSubscribers} className="secondary" style={{ padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>Refresh</button>
              </div>
            </div>
            
            <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', background: '#fff', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                <thead style={{ background: '#f6f8fa' }}>
                  <tr>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Name</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Role</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de' }}>Alert Type</th>
                    <th style={{ padding: '0.75rem', borderBottom: '1px solid #d0d7de', textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {subscribers.length === 0 ? (
                    <tr>
                      <td colSpan="4" style={{ padding: '2rem', textAlign: 'center', color: '#57606a' }}>No subscribers configured.</td>
                    </tr>
                  ) : subscribers.map((s, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid #d0d7de' }}>
                      <td style={{ padding: '0.75rem', fontWeight: '500' }}>{s.user_name}</td>
                      <td style={{ padding: '0.75rem' }}>{s.role}</td>
                      <td style={{ padding: '0.75rem' }}>
                        <span style={{ 
                          backgroundColor: s.alert_type === 'AUTHENTICATION' ? '#ede9fe' : s.alert_type === 'FINANCIAL' ? '#ddf4ff' : s.alert_type === 'HEALTH' ? '#dafbe1' : s.alert_type === 'PII' ? '#fff8c5' : '#f3e8ff', 
                          color: s.alert_type === 'AUTHENTICATION' ? '#8b5cf6' : s.alert_type === 'FINANCIAL' ? '#0969da' : s.alert_type === 'HEALTH' ? '#1a7f37' : s.alert_type === 'PII' ? '#9a6700' : '#7e22ce', 
                          padding: '2px 6px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '600' 
                        }}>
                          {s.alert_type}
                        </span>
                      </td>
                      <td style={{ padding: '0.75rem', textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <button className="secondary" title="Edit" disabled={principal.role === 'admin_pii'} style={{padding: '0.3rem 0.5rem', fontSize: '1rem', border: 'none', background: 'transparent', cursor: principal.role === 'admin_pii' ? 'not-allowed' : 'pointer', opacity: principal.role === 'admin_pii' ? 0.5 : 1}} onClick={() => handleEditSubscriberClick(s)}>✏️</button>
                        <button className="secondary" disabled={principal.role === 'admin_pii'} style={{padding: '0.2rem 0.5rem', fontSize: '0.8rem', color: principal.role === 'admin_pii' ? '#57606a' : '#cf222e', cursor: principal.role === 'admin_pii' ? 'not-allowed' : 'pointer'}} onClick={() => handleDeleteSubscriber(s.user_name)}>Remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rule-form" style={{ opacity: principal.role === 'admin_pii' ? 0.6 : 1, pointerEvents: principal.role === 'admin_pii' ? 'none' : 'auto' }}>
            <div className="card">
              <h3>{editingSubscriber ? 'Edit Subscriber' : 'Add Subscriber'}</h3>
              <form onSubmit={handleAddSubscriber}>
                <div className="form-group">
                  <label>Full Name</label>
                  <input type="text" value={subFormData.user_name} disabled={principal.role === 'admin_pii'} onChange={e => setSubFormData({...subFormData, user_name: e.target.value})} placeholder="Jane Doe" />
                </div>
                <div className="form-group">
                  <label>Role</label>
                  <input type="text" value={subFormData.role} disabled={principal.role === 'admin_pii'} onChange={e => setSubFormData({...subFormData, role: e.target.value})} placeholder="Compliance Officer" />
                </div>
                <div className="form-group">
                  <label>Alert Category</label>
                  <select 
                    value={subFormData.alert_type} 
                    disabled={principal.role === 'admin_pii'}
                    onChange={e => setSubFormData({...subFormData, alert_type: e.target.value})}
                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #d0d7de' }}
                  >
                    <option value="ALL">ALL (Global Admin / Uncategorized)</option>
                    <option value="FINANCIAL">FINANCIAL (PCI-DSS / Banking)</option>
                    <option value="AUTHENTICATION">AUTHENTICATION (API Keys / Credentials)</option>
                    <option value="HEALTH">HEALTH (Protected Health Info)</option>
                    <option value="PII">PII (General Privacy)</option>
                    <option value="TOXICITY">TOXICITY (Abusive / Hateful Content)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Email Address</label>
                  <input type="email" value={subFormData.email} disabled={principal.role === 'admin_pii'} onChange={e => setSubFormData({...subFormData, email: e.target.value})} placeholder="jane.doe@company.com" />
                </div>
                <div style={{marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center'}}>
                  <button type="submit" className="primary" disabled={isSaving || principal.role === 'admin_pii'}>
                    {isSaving ? 'Processing...' : (editingSubscriber ? 'Update Subscriber' : 'Add Subscriber')}
                  </button>
                  {editingSubscriber && (
                    <button type="button" className="secondary" onClick={handleCancelEditSubscriber} disabled={isSaving || principal.role === 'admin_pii'}>Cancel</button>
                  )}
                </div>
                {subFormMessage && (
                  <div className={`alert-${subFormMessage.type}`} style={{marginTop: '1rem'}}>{subFormMessage.text}</div>
                )}
              </form>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
