import { useState, useEffect } from 'react';
import { fetchAnalytics } from './api';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, 
  ResponsiveContainer, PieChart, Pie, Cell, AreaChart, Area
} from 'recharts';

export default function AnalyticsDashboard() {
  const [timeframe, setTimeframe] = useState('24h');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState({
    metrics: { total_requests: 0, total_alarms: 0, resolved: 0, dismissed: 0, pending: 0 },
    category_data: [],
    trend_data: []
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetchAnalytics(timeframe);
      if (res.status === 'success') {
        setData({
          metrics: res.metrics,
          category_data: res.category_data,
          trend_data: res.trend_data
        });
      } else {
        alert("Failed to load analytics: " + res.message);
      }
    } catch (e) {
      console.error(e);
      alert("Failed to connect to backend for analytics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [timeframe]);

  // Modern vibrant palette for dark theme
  const CAT_COLORS = ['#38bdf8', '#fbbf24', '#f87171', '#34d399', '#a78bfa'];
  
  const statusData = [
    { name: 'Pending', value: data.metrics.pending },
    { name: 'Resolved', value: data.metrics.resolved },
    { name: 'Dismissed', value: data.metrics.dismissed }
  ];
  
  // Glossy vibrant status colors
  const STATUS_COLORS = ['#f43f5e', '#10b981', '#64748b'];
  
  const healthScore = data.metrics.total_requests > 0 
    ? Math.max(0, 100 - (data.metrics.total_alarms / data.metrics.total_requests * 100)).toFixed(2)
    : 100.00;

  // Custom Tooltip for dark mode charts
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{ backgroundColor: 'rgba(15, 23, 42, 0.95)', border: '1px solid #334155', padding: '12px', borderRadius: '8px', color: '#fff', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)' }}>
          <p style={{ margin: '0 0 8px 0', fontWeight: 'bold', color: '#cbd5e1', borderBottom: '1px solid #334155', paddingBottom: '4px' }}>{label}</p>
          {payload.map((entry, index) => (
            <div key={index} style={{ color: entry.color, display: 'flex', justifyContent: 'space-between', gap: '20px', marginBottom: '4px' }}>
              <span style={{opacity: 0.9}}>{entry.name}:</span>
              <span style={{ fontWeight: 'bold' }}>{entry.value}</span>
            </div>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ backgroundColor: '#0f172a', color: '#f8fafc', padding: '1.5rem', borderRadius: '12px', fontFamily: '"Inter", -apple-system, sans-serif', minHeight: '80vh', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)' }}>
      
      {/* Top Header & Controls */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid #1e293b', paddingBottom: '1rem' }}>
        <h2 style={{ margin: 0, fontWeight: '700', letterSpacing: '-0.025em', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1.4rem' }}>
          <span style={{ color: '#38bdf8', filter: 'drop-shadow(0 0 8px rgba(56, 189, 248, 0.6))' }}>⚡</span> Pulse Analytics
        </h2>
        
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <select 
            value={timeframe} 
            onChange={(e) => setTimeframe(e.target.value)}
            style={{ padding: '0.6rem 1.2rem', borderRadius: '8px', border: '1px solid #334155', backgroundColor: '#1e293b', color: '#f8fafc', fontSize: '0.95rem', outline: 'none', cursor: 'pointer', fontWeight: '500' }}
          >
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="90d">Last 3 Months</option>
            <option value="all">All Time</option>
          </select>
          <button 
            onClick={loadData} 
            disabled={loading}
            style={{ padding: '0.6rem 1.5rem', borderRadius: '8px', border: 'none', background: 'linear-gradient(to right, #3b82f6, #2563eb)', color: '#fff', fontSize: '0.95rem', fontWeight: '600', cursor: 'pointer', boxShadow: '0 4px 14px 0 rgba(59, 130, 246, 0.39)', transition: 'all 0.2s', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
          >
            {loading ? '⏳ Syncing...' : '🔄 Sync Data'}
          </button>
        </div>
      </div>

      {/* Glossy KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.5rem', marginBottom: '1.5rem' }}>
        
        <div style={{ background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 10px 25px -5px rgba(59, 130, 246, 0.4)', color: '#fff', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', right: '-10%', top: '-20%', fontSize: '8rem', opacity: 0.1 }}>🌍</div>
          <div style={{ fontSize: '0.85rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.9, marginBottom: '0.5rem' }}>Total Processed</div>
          <div style={{ fontSize: '2.5rem', fontWeight: '800', lineHeight: 1 }}>{data.metrics.total_requests}</div>
        </div>

        <div style={{ background: 'linear-gradient(135deg, #f43f5e 0%, #be123c 100%)', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 10px 25px -5px rgba(244, 63, 94, 0.4)', color: '#fff', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', right: '-10%', top: '-20%', fontSize: '8rem', opacity: 0.1 }}>🚨</div>
          <div style={{ fontSize: '0.85rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.9, marginBottom: '0.5rem' }}>Alarms Triggered</div>
          <div style={{ fontSize: '2.5rem', fontWeight: '800', lineHeight: 1 }}>{data.metrics.total_alarms}</div>
        </div>

        <div style={{ background: 'linear-gradient(135deg, #10b981 0%, #047857 100%)', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 10px 25px -5px rgba(16, 185, 129, 0.4)', color: '#fff', position: 'relative', overflow: 'hidden' }}>
           <div style={{ position: 'absolute', right: '-10%', top: '-20%', fontSize: '8rem', opacity: 0.1 }}>🛡️</div>
          <div style={{ fontSize: '0.85rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.9, marginBottom: '0.5rem' }}>Alarms Resolved</div>
          <div style={{ fontSize: '2.5rem', fontWeight: '800', lineHeight: 1 }}>{data.metrics.resolved}</div>
        </div>

        <div style={{ background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)', border: '1px solid #334155', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5)', color: '#fff', position: 'relative', overflow: 'hidden' }}>
           <div style={{ position: 'absolute', right: '-10%', top: '-20%', fontSize: '8rem', opacity: 0.05 }}>❤️</div>
          <div style={{ fontSize: '0.85rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', marginBottom: '0.5rem' }}>System Health Score</div>
          <div style={{ fontSize: '2.5rem', fontWeight: '800', lineHeight: 1, color: healthScore < 95 ? '#f43f5e' : '#10b981' }}>
            {healthScore}%
          </div>
        </div>
        
      </div>

      {/* Charts Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        
        {/* Category Breakdown */}
        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.2)' }}>
          <h3 style={{ margin: '0 0 1rem 0', color: '#f8fafc', fontSize: '1rem', fontWeight: '600' }}>Leakage by Category</h3>
          <div style={{ height: '240px' }}>
            {data.category_data.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b', fontStyle: 'italic' }}>No threat data available.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.category_data} layout="vertical" margin={{ top: 5, right: 30, left: 40, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={false} />
                  <XAxis type="number" stroke="#64748b" tick={{fill: '#94a3b8'}} />
                  <YAxis dataKey="name" type="category" width={100} stroke="#64748b" tick={{fill: '#cbd5e1', fontSize: '0.85rem', fontWeight: '500'}} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{fill: 'rgba(255,255,255,0.05)'}} />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={24}>
                    {data.category_data.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={CAT_COLORS[index % CAT_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Status Breakdown */}
        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '16px', padding: '1.25rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.2)' }}>
          <h3 style={{ margin: '0 0 1rem 0', color: '#f8fafc', fontSize: '1rem', fontWeight: '600' }}>Resolution Pipeline</h3>
          <div style={{ height: '240px' }}>
             {data.metrics.total_alarms === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b', fontStyle: 'italic' }}>No threat data available.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={statusData}
                    innerRadius="60%"
                    outerRadius="80%"
                    paddingAngle={5}
                    dataKey="value"
                    stroke="none"
                  >
                    {statusData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={STATUS_COLORS[index % STATUS_COLORS.length]} />
                    ))}
                  </Pie>
                  <RechartsTooltip content={<CustomTooltip />} />
                  <Legend verticalAlign="bottom" height={36} wrapperStyle={{ color: '#cbd5e1', fontSize: '0.9rem', fontWeight: '500' }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
        
        {/* Trend Analysis - Full Width */}
        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '16px', padding: '1.25rem', gridColumn: '1 / -1', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.2)' }}>
          <h3 style={{ margin: '0 0 1rem 0', color: '#f8fafc', fontSize: '1rem', fontWeight: '600' }}>Security Efficacy over Time</h3>
          <div style={{ height: '260px' }}>
            {data.trend_data.length === 0 ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b', fontStyle: 'italic' }}>No traffic in this timeframe.</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.trend_data} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorRequests" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="colorAlarms" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.4}/>
                      <stop offset="95%" stopColor="#f43f5e" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                  <XAxis dataKey="date" stroke="#64748b" tick={{fill: '#94a3b8', fontSize: '0.85rem'}} tickMargin={10} />
                  <YAxis stroke="#64748b" tick={{fill: '#94a3b8', fontSize: '0.85rem'}} tickMargin={10} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{stroke: '#64748b', strokeWidth: 1, strokeDasharray: '5 5'}} />
                  <Legend verticalAlign="top" height={36} wrapperStyle={{ color: '#cbd5e1', fontWeight: '500' }} />
                  <Area type="monotone" dataKey="requests" name="Processed Traffic" stroke="#38bdf8" strokeWidth={3} fillOpacity={1} fill="url(#colorRequests)" activeDot={{ r: 6, strokeWidth: 0, fill: '#38bdf8', filter: 'drop-shadow(0 0 5px rgba(56,189,248,0.8))' }} />
                  <Area type="monotone" dataKey="alarms" name="Threats Intercepted" stroke="#f43f5e" strokeWidth={3} fillOpacity={1} fill="url(#colorAlarms)" activeDot={{ r: 6, strokeWidth: 0, fill: '#f43f5e', filter: 'drop-shadow(0 0 5px rgba(244,63,94,0.8))' }} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
