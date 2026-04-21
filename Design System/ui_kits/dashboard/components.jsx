// Shared UI primitives for the Kepware dashboard
const { useState } = React;

function Pill({ kind = 'muted', children }) {
  return (
    <span className={`pill p-${kind}`}>
      <span className="dot"></span>
      {children}
    </span>
  );
}

function Dot({ kind = 'muted' }) {
  const colors = {
    ok: { bg: '#22c55e', glow: 'rgba(34,197,94,0.6)' },
    warn: { bg: '#f59e0b', glow: 'rgba(245,158,11,0.6)' },
    err: { bg: '#ef4444', glow: 'rgba(239,68,68,0.8)' },
    info: { bg: '#60a5fa', glow: 'rgba(96,165,250,0.6)' },
    muted: { bg: '#475569', glow: 'rgba(71,85,105,0.4)' },
  };
  const c = colors[kind];
  return <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: c.bg, boxShadow: `0 0 6px ${c.glow}`, verticalAlign: 'middle', marginRight: 8 }}></span>;
}

function Button({ variant = 'ghost', size = 'md', icon, children, onClick }) {
  const cls = `btn btn-${variant} ${size === 'sm' ? 'btn-sm' : ''}`;
  return (
    <button className={cls} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

function Card({ title, icon, actions, children, style }) {
  return (
    <div className="card-ui" style={style}>
      {title && (
        <div className="card-hd">
          {icon}
          <span className="t">{title}</span>
          <span className="spacer"></span>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

function Metric({ title, icon, value, unit, delta, deltaKind = 'ok', active }) {
  const deltaColor = { ok: '#22c55e', warn: '#f59e0b', err: '#ef4444', muted: '#94a3b8' }[deltaKind];
  return (
    <div className="card-ui" style={active ? { borderColor: 'rgba(34,211,238,0.35)', boxShadow: '0 0 0 1px rgba(34,211,238,0.2), 0 0 24px rgba(34,211,238,0.08)' } : {}}>
      <div className="card-hd">
        {icon}
        <span className="t" style={active ? { color: '#22d3ee' } : {}}>{title}</span>
      </div>
      <div className="metric-v">
        {value}
        {unit && <span style={{ fontSize: 14, color: '#94a3b8', marginLeft: 4, fontWeight: 500 }}>{unit}</span>}
      </div>
      {delta && <div className="metric-delta" style={{ color: deltaColor }}>{delta}</div>}
    </div>
  );
}

function BrandMark() {
  return (
    <div className="brand">
      <svg viewBox="0 0 64 64" className="brand-mark">
        <rect x="2" y="2" width="60" height="60" rx="14" fill="#0f172a" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="1.5"/>
        <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#kpmG)" opacity="0.4"/>
        <text x="32" y="40" textAnchor="middle" fontFamily="Inter, sans-serif" fontWeight="800" fontSize="20" fill="#e6edf7" letterSpacing="-0.02em">KPM</text>
        <circle className="logo-pulse" cx="50" cy="50" r="4" fill="#22d3ee"/>
        <defs>
          <radialGradient id="kpmG" cx="0.8" cy="0.2" r="0.9">
            <stop offset="0" stopColor="#22d3ee" stopOpacity="0.5"/>
            <stop offset="1" stopColor="#0f172a" stopOpacity="0"/>
          </radialGradient>
        </defs>
      </svg>
      <div>
        <div className="brand-title">Kepware</div>
        <div className="brand-sub">MONITOR</div>
      </div>
    </div>
  );
}

function Sidebar({ page, setPage, alertCount }) {
  const items = [
    { id: 'overview', label: '儀表板', en: 'Overview', icon: <Icon.dashboard /> },
    { id: 'channels', label: '頻道與設備', en: 'Channels', icon: <Icon.server /> },
    { id: 'tags', label: '監控點位', en: 'Tags', icon: <Icon.tag /> },
    { id: 'alerts', label: '告警紀錄', en: 'Alerts', icon: <Icon.bell />, badge: alertCount },
    { id: 'diag', label: '診斷時間軸', en: 'Diagnostics', icon: <Icon.shield /> },
    { id: 'history', label: '歷史紀錄', en: 'History', icon: <Icon.clock /> },
  ];
  return (
    <aside className="sidebar">
      <BrandMark />
      <div className="nav-section">MONITORING</div>
      {items.map(it => (
        <div key={it.id} className={`nav-item ${page === it.id ? 'active' : ''}`} onClick={() => setPage(it.id)}>
          {it.icon}
          <span>{it.label}</span>
          {it.badge ? <span className="badge">{it.badge}</span> : null}
        </div>
      ))}
      <div className="nav-section">SYSTEM</div>
      <div className="nav-item"><Icon.settings /><span>設定</span></div>
    </aside>
  );
}

function Topbar({ page }) {
  const titles = {
    overview: { h1: '設備監控儀表板', crumb: 'home / overview' },
    channels: { h1: '頻道與設備', crumb: 'home / channels' },
    tags: { h1: '監控點位 · Tags', crumb: 'home / tags' },
    alerts: { h1: '告警紀錄', crumb: 'home / alerts' },
    diag: { h1: '三層網路診斷', crumb: 'home / diagnostics' },
    history: { h1: '歷史資料查詢', crumb: 'home / history' },
  };
  const t = titles[page];
  return (
    <header className="topbar">
      <div className="title">
        <h1>{t.h1}</h1>
        <div className="crumbs">{t.crumb}</div>
      </div>
      <span className="top-spacer"></span>
      <div className="top-meta">
        <div className="poll"><span className="dot"></span>LIVE · next poll 04:12</div>
        <Button variant="ghost" size="sm" icon={<Icon.search />}>搜尋</Button>
        <div className="avatar">OP</div>
      </div>
    </header>
  );
}

Object.assign(window, { Pill, Dot, Button, Card, Metric, BrandMark, Sidebar, Topbar });
