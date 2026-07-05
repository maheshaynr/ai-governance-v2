import { useState, useEffect } from 'react';
import Dashboard from './Dashboard';
import AdminConfig from './AdminConfig';
import { fetchAlarms } from './api';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [alarms, setAlarms] = useState([]);

  useEffect(() => {
    // Poll for background alarms every 3 seconds
    const interval = setInterval(() => {
      fetchAlarms().then(data => {
        if (data.alarms) {
          setAlarms(data.alarms);
        }
      }).catch(e => console.error(e));
    }, 3000);
    
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <div className="header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>🛡️ Enterprise AI Governance v1.0</h1>
          <div className="nav-tabs">
            <button 
              className={activeTab === 'dashboard' ? 'active' : ''} 
              onClick={() => setActiveTab('dashboard')}
            >
              Testing Dashboard
            </button>
            <button 
              className={activeTab === 'admin' ? 'active' : ''} 
              onClick={() => setActiveTab('admin')}
            >
              Admin Configuration
            </button>
          </div>
        </div>
        
        {alarms.length > 0 && (
          <div style={{ backgroundColor: '#cf222e', color: 'white', padding: '0.75rem 1.25rem', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '0.75rem', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
            <span style={{ fontSize: '1.25rem' }}>🚨</span>
            <div>
              <strong>Security Alert:</strong> You have {alarms.length} pending alarm{alarms.length > 1 ? 's' : ''} triggered by the LLM Watchdog.
            </div>
          </div>
        )}
      </div>

      <main>
        {activeTab === 'dashboard' ? <Dashboard /> : <AdminConfig />}
      </main>
    </div>
  );
}

export default App;
