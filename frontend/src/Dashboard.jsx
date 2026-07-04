import { useState, useEffect } from 'react';
import { queryDb, governAi, fetchTestCases, chatAgent } from './api';

export default function Dashboard() {
  const [testCases, setTestCases] = useState([]);
  const [selectedTest, setSelectedTest] = useState(null);
  const [payload, setPayload] = useState('');
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  
  // Chat state
  const [chatMessages, setChatMessages] = useState([]);

  useEffect(() => {
    loadTestCases();
  }, []);

  const loadTestCases = async () => {
    try {
      const data = await fetchTestCases();
      if (data.tests) {
        setTestCases(data.tests);
        if (data.tests.length > 0) {
          handleSelectTest(data.tests[0]);
        }
      }
    } catch (e) {
      console.error("Failed to load test cases", e);
    }
  };

  const handleSelectTest = (test) => {
    setSelectedTest(test);
    setPayload(test.payload);
    setResult(null);
    setChatMessages([]); // Reset chat when switching
  };

  const handleRunGuardrail = async () => {
    if (!selectedTest) return;
    
    setIsLoading(true);
    setResult(null);

    try {
      let res;
      if (selectedTest.type === 'db_query') {
        res = await queryDb(parseInt(payload));
        setResult({ type: 'success', text: res.masked_output });
      } else if (selectedTest.type === 'ai_generative') {
        res = await governAi(payload);
        setResult({ type: 'success', text: res.masked_output });
      } else if (selectedTest.type === 'chatbot') {
        // Chatbot logic
        const newMsg = { role: 'user', content: payload };
        setChatMessages(prev => [...prev, newMsg]);
        
        res = await chatAgent(payload);
        
        const botMsg = { 
          role: 'assistant', 
          raw_content: res.raw_output,
          masked_content: res.masked_output,
          status: res.status
        };
        setChatMessages(prev => [...prev, botMsg]);
        setPayload(''); // clear input
      }
    } catch (e) {
      setResult({ type: 'error', text: 'Failed to connect to backend.' });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div>
      <h2>Egress Shield (Client)</h2>
      <p>Test the <strong>Universal Output Guardrail</strong> against Database Queries and AI Hallucinations.</p>

      <div className="admin-layout">
        
        {/* Left Pane: Master List */}
        <div className="rules-list">
          <h3>Test Suite</h3>
          {testCases.map((tc) => (
            <div 
              className={`rule-card ${selectedTest?.id === tc.id ? 'active-test' : ''}`} 
              key={tc.id}
              onClick={() => handleSelectTest(tc)}
              style={{ cursor: 'pointer', border: selectedTest?.id === tc.id ? '2px solid #0969da' : '1px solid #d0d7de' }}
            >
              <h4 style={{ color: selectedTest?.id === tc.id ? '#0969da' : 'inherit' }}>{tc.id}</h4>
              <div className="rule-meta">{tc.summary}</div>
            </div>
          ))}
        </div>

        {/* Right Pane: Execution Details */}
        <div className="rule-form">
          {selectedTest ? (
            <div className="card">
              <h3>{selectedTest.summary}</h3>
              
              <div className="form-group" style={{ backgroundColor: '#f6f8fa', padding: '1rem', borderRadius: '6px', marginBottom: '1.5rem' }}>
                <label>Expected Behavior:</label>
                <div style={{ fontStyle: 'italic', color: '#57606a' }}>{selectedTest.expected_behavior}</div>
              </div>

              {/* Chatbot Interface */}
              {selectedTest.type === 'chatbot' ? (
                <div>
                  <div style={{ border: '1px solid #d0d7de', borderRadius: '6px', height: '400px', overflowY: 'auto', padding: '1rem', marginBottom: '1rem', backgroundColor: '#fff' }}>
                    {chatMessages.length === 0 && <div style={{color: '#57606a', textAlign: 'center', marginTop: '2rem'}}>Send a message to start the agent.</div>}
                    
                    {chatMessages.map((msg, idx) => (
                      <div key={idx} style={{ marginBottom: '1rem', display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                        {msg.role === 'user' ? (
                          <div style={{ backgroundColor: '#0969da', color: '#fff', padding: '0.8rem 1rem', borderRadius: '18px 18px 0 18px', maxWidth: '70%' }}>
                            {msg.content}
                          </div>
                        ) : (
                          <div style={{ width: '100%', display: 'flex', gap: '1rem' }}>
                            {/* Raw Output Bubble (Leaky) */}
                            <div style={{ flex: 1, backgroundColor: '#ffebe9', border: '1px solid #ff8182', color: '#cf222e', padding: '1rem', borderRadius: '18px 18px 18px 0' }}>
                              <strong>🔴 Raw LLM Output (Leaking PII):</strong>
                              <pre style={{ margin: '0.5rem 0 0 0', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.9rem' }}>{msg.raw_content}</pre>
                            </div>
                            
                            {/* Shielded Output Bubble */}
                            <div style={{ flex: 1, backgroundColor: '#dafbe1', border: '1px solid #4ac26b', color: '#1a7f37', padding: '1rem', borderRadius: '18px 18px 18px 0' }}>
                              <strong>🟢 Shielded Output (Safe):</strong>
                              <pre style={{ margin: '0.5rem 0 0 0', whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.9rem' }}>{msg.masked_content}</pre>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                    {isLoading && <div style={{ color: '#57606a' }}>Agent is thinking...</div>}
                  </div>
                  
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <input 
                      type="text" 
                      value={payload} 
                      onChange={e => setPayload(e.target.value)} 
                      placeholder="Ask the agent for customer details..." 
                      style={{ margin: 0 }}
                      onKeyPress={e => e.key === 'Enter' && handleRunGuardrail()}
                    />
                    <button className="primary" onClick={handleRunGuardrail} disabled={isLoading}>Send</button>
                  </div>
                </div>
              ) : (
                /* Standard Database/AI Interface */
                <div>
                  <div className="form-group">
                    <label>{selectedTest.type === 'db_query' ? 'Enter Customer ID:' : 'Simulated AI Output / User Input:'}</label>
                    {selectedTest.type === 'db_query' ? (
                      <input type="number" value={payload} onChange={e => setPayload(e.target.value)} />
                    ) : (
                      <textarea rows="4" value={payload} onChange={e => setPayload(e.target.value)}></textarea>
                    )}
                  </div>

                  <button className="primary" onClick={handleRunGuardrail} disabled={isLoading}>
                    {isLoading ? 'Scanning...' : 'Run Guardrail'}
                  </button>

                  {result && (
                    <div style={{ marginTop: '2rem' }}>
                      <h4>Final Result:</h4>
                      <div className={`alert-${result.type}`}>{result.text}</div>
                    </div>
                  )}
                </div>
              )}

            </div>
          ) : (
            <div className="card">
              <p>Select a test case from the left menu to begin.</p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
