// Pages: Channels, Tags, Alerts, Diagnostics, History
const { useState: useStateP } = React;

/* ---------------- CHANNELS ---------------- */
function PageChannels() {
  const [open, setOpen] = useStateP(['kepware_a']);
  const tree = [
    { name: 'kepware_a', host: '192.168.1.10', status: 'warn', channels: [
      { name: 'Channel1', devices: [
        { name: 'iFIX1', ip: '10.0.1.10', status: 'ok', tags: 8 },
        { name: 'iFIX2', ip: '10.0.1.11', status: 'warn', tags: 8 },
        { name: 'iFIX3', ip: '10.0.1.20', status: 'err', tags: 8 },
      ]},
      { name: 'Channel2', devices: [
        { name: 'Device1', ip: '10.0.1.30', status: 'ok', tags: 12 },
      ]},
    ]},
    { name: 'kepware_b', host: '192.168.1.11', status: 'ok', channels: [] },
    { name: 'kepware_c', host: '192.168.1.12', status: 'err', channels: [] },
  ];
  const tag = (o) => open.includes(o) ? open.filter(x => x !== o) : [...open, o];
  const [selected] = useStateP('Channel1.iFIX3');
  return (
    <div className="two-col" style={{ gridTemplateColumns: '360px 1fr' }}>
      <Card title="SERVER TREE" icon={<Icon.server />} actions={<Button variant="ghost" size="sm" icon={<Icon.search />} />}>
        {tree.map(s => (
          <div key={s.name}>
            <div className={`tree-row ${open.includes(s.name) ? 'open' : ''}`} onClick={() => setOpen(tag(s.name))}>
              <Icon.chevR className="chev" />
              <Icon.server style={{ width: 15, height: 15, color: '#22d3ee' }} />
              <span style={{ fontWeight: 600 }}>{s.name}</span>
              <Dot kind={s.status} />
              <span className="count">{s.channels.reduce((a, c) => a + c.devices.length, 0)}</span>
            </div>
            {open.includes(s.name) && s.channels.map(ch => (
              <div key={ch.name} className="tree-child">
                <div className="tree-row" style={{ padding: '7px 10px', fontSize: 12.5 }}>
                  <Icon.net style={{ width: 13, height: 13, color: '#94a3b8' }} />
                  <span style={{ color: '#94a3b8' }}>{ch.name}</span>
                  <span className="count">{ch.devices.length}</span>
                </div>
                {ch.devices.map(d => (
                  <div key={d.name} className={`tree-row ${selected.endsWith(d.name) ? 'active' : ''}`} style={{ padding: '7px 10px 7px 24px', fontSize: 12.5 }}>
                    <Icon.cpu style={{ width: 13, height: 13 }} />
                    <span className="td-mono" style={{ fontSize: 12 }}>{d.name}</span>
                    <Dot kind={d.status} />
                    <span className="count">{d.tags}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ))}
      </Card>

      <div>
        <Card title="DEVICE · Channel1.iFIX3" icon={<Icon.cpu />} actions={<>
          <Button variant="ghost" size="sm" icon={<Icon.activity />}>Test ping</Button>
          <Button variant="accent" size="sm" icon={<Icon.plus />}>新增點位</Button>
        </>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 20, marginBottom: 18 }}>
            <Field label="IP" value="10.0.1.20" />
            <Field label="IGS Port" value="49310" />
            <Field label="Connection" value={<Pill kind="err">L3 IGS_DOWN</Pill>} />
            <Field label="Last poll" value="14:32:09" />
            <Field label="Tags" value="8 monitored / 1 alert" />
            <Field label="Mail to" value="ops@factory.com" />
          </div>
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Tag</th><th>NodeId</th><th>Type</th><th>Condition</th><th className="td-num">Value</th><th>Status</th></tr></thead>
              <tbody>
                <TagRow name="iFIX3_SecondError" nid="ns=2;s=Channel1.iFIX3._System._Sec" cond="less < 60" v="124" s="err" badge="VALUE_ABNORMAL" />
                <TagRow name="iFIX3_Heartbeat" nid="ns=2;s=Channel1.iFIX3.Heartbeat" cond="equal = 1" v="1" s="ok" badge="OK" />
                <TagRow name="iFIX3_Temp1" nid="ns=2;s=Channel1.iFIX3.T1" cond="greater > 85" v="42.7" s="ok" badge="OK" />
                <TagRow name="iFIX3_Pressure" nid="ns=2;s=Channel1.iFIX3.P" cond="less < 0" v="3.1" s="ok" badge="OK" />
                <TagRow name="iFIX3_Counter" nid="ns=2;s=Channel1.iFIX3.CT" cond="log only" v="1,284" s="info" badge="LOG_ONLY" />
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
function Field({ label, value }) {
  return <div><div style={{ fontSize: 10.5, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: 4 }}>{label}</div><div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: '#e6edf7' }}>{value}</div></div>;
}
function TagRow({ name, nid, cond, v, s, badge }) {
  return <tr><td><Dot kind={s} />{name}</td><td className="td-mono">{nid}</td><td className="td-mono">FLOAT</td><td className="td-mono">{cond}</td><td className="td-num" style={{ color: s === 'err' ? '#ef4444' : '#e6edf7', fontWeight: 600 }}>{v}</td><td><Pill kind={s}>{badge}</Pill></td></tr>;
}

/* ---------------- TAGS (+CSV) ---------------- */
function PageTags() {
  const [tab, setTab] = useStateP('list');
  return (
    <>
      <div className="section-hd">
        <h2>監控點位</h2>
        <span className="count">166 tags</span>
        <div className="actions">
          <Button variant="ghost" icon={<Icon.download />}>下載範本</Button>
          <Button variant="outline" icon={<Icon.upload />} onClick={() => setTab('csv')}>CSV 匯入</Button>
          <Button variant="primary" icon={<Icon.plus />}>新增點位</Button>
        </div>
      </div>
      <div className="ctabs">
        <div className={`ctab ${tab === 'list' ? 'active' : ''}`} onClick={() => setTab('list')}><Icon.tag />全部點位</div>
        <div className={`ctab ${tab === 'csv' ? 'active' : ''}`} onClick={() => setTab('csv')}><Icon.upload />CSV 匯入</div>
        <div className={`ctab ${tab === 'thr' ? 'active' : ''}`} onClick={() => setTab('thr')}><Icon.shield />閾值設定</div>
      </div>
      {tab === 'list' && <TagsList />}
      {tab === 'csv' && <CsvImport />}
      {tab === 'thr' && <ThresholdMatrix />}
    </>
  );
}

function TagsList() {
  return (
    <Card>
      <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
        <div className="search" style={{ flex: 1 }}>
          <Icon.search />
          <input className="input" placeholder="搜尋 tag name、NodeId 或設備…" />
        </div>
        <select className="select"><option>全部 Server</option><option>kepware_a</option></select>
        <select className="select"><option>全部狀態</option><option>異常</option></select>
      </div>
      <div className="tbl-wrap">
        <table>
          <thead><tr><th style={{width:30}}><input type="checkbox" /></th><th>Tag</th><th>Server</th><th>NodeId</th><th>Condition</th><th className="td-num">Threshold</th><th className="td-num">CountNeeded</th><th>Mail</th><th>Status</th></tr></thead>
          <tbody>
            {[
              ['iFIX1_SecondError', 'kepware_a', 'ns=2;s=Channel1.iFIX1._Sys._Sec', 'less', 60, 3, 'ops@factory.com', 'ok', 'OK'],
              ['iFIX2_SecondError', 'kepware_a', 'ns=2;s=Channel1.iFIX2._Sys._Sec', 'less', 60, 3, 'ops@factory.com', 'warn', '2/3'],
              ['iFIX3_SecondError', 'kepware_a', 'ns=2;s=Channel1.iFIX3._Sys._Sec', 'less', 60, 3, 'ops@factory.com; lead@', 'err', 'FIRED'],
              ['iFIX3_Temp1', 'kepware_a', 'ns=2;s=Channel1.iFIX3.T1', 'greater', 85, 1, 'ops@factory.com', 'ok', 'OK'],
              ['LogOnly_Counter', 'kepware_a', 'ns=2;s=Channel1.iFIX3.CT', '—', '—', '—', '(log only)', 'info', 'LOG'],
              ['Boiler_Pressure', 'kepware_b', 'ns=2;s=Ch1.Dev1.Pressure', 'greater', '12.5', 2, 'boiler@factory.com', 'ok', 'OK'],
              ['Boiler_Temp', 'kepware_b', 'ns=2;s=Ch1.Dev1.Temp', 'greater', 200, 2, 'boiler@factory.com', 'ok', 'OK'],
              ['Line3_StopFlag', 'kepware_c', 'ns=2;s=Ch1.L3.Stop', 'equal', 1, 1, 'line3@factory.com', 'err', 'FIRED'],
              ['Line3_CycleCount', 'kepware_c', 'ns=2;s=Ch1.L3.CC', '—', '—', '—', '(log only)', 'muted', 'DISABLED'],
            ].map((r, i) => (
              <tr key={i}>
                <td><input type="checkbox" /></td>
                <td style={{ fontWeight: 600 }}><Dot kind={r[7]} />{r[0]}</td>
                <td className="td-mono">{r[1]}</td>
                <td className="td-mono" style={{ maxWidth: 240, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r[2]}</td>
                <td className="td-mono">{r[3]}</td>
                <td className="td-num">{r[4]}</td>
                <td className="td-num">{r[5]}</td>
                <td className="td-mono" style={{ maxWidth: 180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{r[6]}</td>
                <td><Pill kind={r[7]}>{r[8]}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function CsvImport() {
  return (
    <div className="two-col">
      <Card title="UPLOAD" icon={<Icon.upload />}>
        <div className="upload">
          <Icon.upload />
          <h4>拖曳 tags.csv 到此處</h4>
          <p style={{marginBottom:12}}>或點擊選擇檔案 · 欄位: name, nodeid, server, type, condition, threshold, countneeded, enable, device_ip, device_port, mail_to, mail_cc</p>
          <Button variant="outline" size="sm" icon={<Icon.download />}>下載範本</Button>
        </div>
        <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
          <input type="checkbox" defaultChecked style={{ accentColor: '#22d3ee' }} id="dry" />
          <label htmlFor="dry" style={{ color: '#fde68a', fontSize: 13 }}>DRY RUN · 預演，不會真的寫入</label>
        </div>
      </Card>
      <Card title="PREVIEW · 3 rows parsed" icon={<Icon.check />} actions={<>
        <Button variant="ghost" size="sm">取消</Button>
        <Button variant="primary" size="sm" icon={<Icon.check />}>DRY RUN</Button>
        <Button variant="danger" size="sm">執行 LIVE</Button>
      </>}>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>#</th><th>name</th><th>condition</th><th className="td-num">thr</th><th>result</th></tr></thead>
            <tbody>
              <tr><td className="td-mono">1</td><td>Line4_Temp</td><td className="td-mono">greater &gt; 75</td><td className="td-num">75</td><td><Pill kind="ok">新增</Pill></td></tr>
              <tr><td className="td-mono">2</td><td>Line4_Pres</td><td className="td-mono">less &lt; 1.0</td><td className="td-num">1.0</td><td><Pill kind="ok">新增</Pill></td></tr>
              <tr><td className="td-mono">3</td><td>iFIX3_Temp1</td><td className="td-mono">greater &gt; 85</td><td className="td-num">85</td><td><Pill kind="warn">覆蓋既有</Pill></td></tr>
            </tbody>
          </table>
        </div>
        <div className="log" style={{ marginTop: 14 }}>
          <div><span className="t">14:33:02</span> <span className="i">[CSV]</span> 讀取 3 列 · 0 errors</div>
          <div><span className="t">14:33:02</span> <span className="w">[DRY]</span> 若執行 LIVE 將新增 2，覆蓋 1</div>
        </div>
      </Card>
    </div>
  );
}

function ThresholdMatrix() {
  return (
    <Card title="THRESHOLD EDITOR · iFIX3_SecondError" icon={<Icon.shield />} actions={<Button variant="primary" size="sm" icon={<Icon.check />}>儲存</Button>}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16 }}>
        <div><label style={fLab}>Condition</label><select className="select" style={{ width: '100%' }}><option>less</option><option>greater</option><option>equal</option><option>not_equal</option></select></div>
        <div><label style={fLab}>Threshold</label><input className="input" defaultValue="60" style={{ width: '100%' }} /></div>
        <div><label style={fLab}>CountNeeded (累積)</label><input className="input" defaultValue="3" style={{ width: '100%' }} /></div>
        <div><label style={fLab}>Device IP (L3)</label><input className="input" defaultValue="10.0.1.20" style={{ width: '100%' }} /></div>
        <div><label style={fLab}>Device Port</label><input className="input" defaultValue="49310" style={{ width: '100%' }} /></div>
        <div><label style={fLab}>Enable</label><div style={{ marginTop: 10 }}><Pill kind="ok">ENABLED</Pill></div></div>
        <div style={{ gridColumn: '1 / -1' }}><label style={fLab}>Mail to / cc</label><input className="input" defaultValue="ops@factory.com; ops-lead@factory.com" style={{ width: '100%' }} /></div>
      </div>
    </Card>
  );
}
const fLab = { display: 'block', fontSize: 10.5, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600, marginBottom: 6 };

/* ---------------- ALERTS ---------------- */
function PageAlerts() {
  const [filter, setFilter] = useStateP('ALL');
  const filters = ['ALL', 'HOST_DOWN', 'OPC_SERVICE_DOWN', 'DEVICE_DOWN', 'IGS_SERVICE_DOWN', 'VALUE_ABNORMAL'];
  const rows = [
    ['14:32:09', 'err',  'iFIX3_SecondError',   'VALUE_ABNORMAL',  'kepware_a', 'ops@factory.com', '派報'],
    ['14:28:41', 'err',  'kepware_a',           'HOST_DOWN',       'kepware_a', 'it@factory.com', '派報'],
    ['14:25:03', 'warn', 'iFIX7_SecondError',   'threshold 2/3',   'kepware_b', '—',              '累積中'],
    ['13:52:18', 'err',  'Line3_StopFlag',      'VALUE_ABNORMAL',  'kepware_c', 'line3@factory.com', '派報'],
    ['13:20:04', 'ok',   'iFIX2_SecondError',   'RECOVERED',       'kepware_a', 'ops@factory.com', '復歸'],
    ['12:47:50', 'err',  'kepware_c',           'OPC_SERVICE_DOWN','kepware_c', 'it@factory.com', '派報'],
  ];
  return (
    <>
      <div className="section-hd">
        <h2>告警紀錄</h2>
        <span className="count">24h · 14 events</span>
        <div className="actions">
          <Button variant="ghost" icon={<Icon.download />}>匯出 CSV</Button>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
        {filters.map(f => (
          <div key={f} onClick={() => setFilter(f)} style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, color: f === filter ? '#03181c' : '#94a3b8', background: f === filter ? '#22d3ee' : 'transparent', border: `1px solid ${f === filter ? '#22d3ee' : '#293548'}`, borderRadius: 999, fontFamily: 'var(--font-mono)', letterSpacing: '0.04em', cursor: 'pointer' }}>{f}</div>
        ))}
      </div>
      <Card>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Time</th><th>Subject</th><th>Category</th><th>Server</th><th>Routed to</th><th>State</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="td-mono">{r[0]}</td>
                  <td style={{fontWeight:600}}><Dot kind={r[1]} />{r[2]}</td>
                  <td className="td-mono">{r[3]}</td>
                  <td className="td-mono">{r[4]}</td>
                  <td className="td-mono">{r[5]}</td>
                  <td><Pill kind={r[1]}>{r[6]}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

/* ---------------- DIAGNOSTICS TIMELINE ---------------- */
function PageDiag() {
  const steps = [
    { lvl: 'L1', ok: false, label: 'Ping Kepware Host', target: '192.168.1.10', msg: 'Ping 失敗 (timeout)', time: '14:32:09.120' },
    { lvl: 'L1', ok: true, label: 'TCP OPC Port', target: '192.168.1.10:49320', msg: '— skipped (L1 fail)', time: '—' },
    { lvl: 'L2', ok: null, label: 'OPC UA handshake', target: 'opc.tcp://192.168.1.10:49320', msg: '— skipped', time: '—' },
    { lvl: 'L3', ok: false, label: 'Ping Device', target: '10.0.1.20', msg: 'Ping 失敗 (機台無法連線)', time: '14:32:09.180' },
    { lvl: 'L3', ok: false, label: 'TCP IGS Port', target: '10.0.1.20:49310', msg: '— skipped (L3 ping fail)', time: '—' },
  ];
  return (
    <>
      <div className="banner err">
        <div className="banner-icon"><Icon.alert /></div>
        <div className="banner-body">
          <h4>三層診斷 · iFIX3_SecondError · 14:32:09</h4>
          <p>L1 HOST_DOWN + L3 DEVICE_DOWN · 上游主機與下游機台同時異常</p>
        </div>
        <Button variant="outline" size="sm">重跑診斷</Button>
      </div>
      <div className="two-col" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
        <Card title="DIAGNOSTIC STEPS" icon={<Icon.shield />}>
          {steps.map((s, i) => {
            const kind = s.ok === true ? 'ok' : s.ok === false ? 'err' : 'muted';
            return (
              <div key={i} className="diag">
                <div className={`diag-icon ${kind}`}>{s.ok === true ? <Icon.check /> : s.ok === false ? <Icon.x /> : <Icon.clock />}</div>
                <div className="diag-body">
                  <div className="who">[{s.lvl}] {s.label} · <span style={{ color: '#94a3b8', fontWeight: 400 }}>{s.target}</span></div>
                  <div className="msg">{s.msg}</div>
                </div>
                <div className="diag-time">{s.time}</div>
              </div>
            );
          })}
          <div style={{ marginTop: 14, padding: '12px 14px', background: 'var(--err-bg)', borderRadius: 8, border: '1px solid rgba(239,68,68,0.3)', fontSize: 13, color: '#fecaca' }}>
            <strong style={{ color: '#ef4444' }}>結論 · </strong>Kepware 主機 192.168.1.10 無法連線 (Ping 失敗) · 已通知 IT 群組 + ops@factory.com
          </div>
        </Card>
        <Card title="EMAIL PREVIEW" icon={<Icon.bell />} actions={<Button variant="ghost" size="sm">檢視原始 HTML</Button>}>
          <div style={{ background: 'var(--bg-0)', border: '1px solid var(--border-1)', borderRadius: 8, padding: 16, fontFamily: 'var(--font-mono)', fontSize: 12, color: '#cbd5e1', lineHeight: 1.8 }}>
            <div style={{ color: '#64748b' }}>Subject</div>
            <div style={{ color: '#e6edf7', marginBottom: 10 }}>[異常] Kepware 設備監控通知 - iFIX3_SecondError</div>
            <div style={{ color: '#64748b' }}>To</div>
            <div style={{ color: '#e6edf7', marginBottom: 10 }}>ops@factory.com; ops-lead@factory.com</div>
            <div style={{ color: '#64748b' }}>Body</div>
            <div style={{ color: '#fca5a5', marginTop: 4 }}>❌ 設備: iFIX3 (10.0.1.20)</div>
            <div>讀取失敗或連線斷掉</div>
            <div style={{ marginTop: 8 }}>診斷結果:</div>
            <div>· L1: 主機 192.168.1.10 無法連線 (Ping 失敗)</div>
            <div>· L3: iFIX/IGS 機台 10.0.1.20 無法連線</div>
            <div style={{ marginTop: 8, color: '#94a3b8' }}>時間: 2026-04-19 14:32:09</div>
          </div>
        </Card>
      </div>
    </>
  );
}

/* ---------------- HISTORY ---------------- */
function PageHistory() {
  return (
    <>
      <div className="section-hd">
        <h2>歷史資料查詢</h2>
        <span className="count">monitor_history · 2.4M rows</span>
        <div className="actions">
          <Button variant="outline" icon={<Icon.download />}>匯出 CSV</Button>
        </div>
      </div>
      <Card>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr auto', gap: 12, marginBottom: 16 }}>
          <div><label style={fLab}>Server</label><select className="select" style={{ width: '100%' }}><option>全部</option><option>kepware_a</option></select></div>
          <div><label style={fLab}>Tag</label><select className="select" style={{ width: '100%' }}><option>iFIX3_SecondError</option></select></div>
          <div><label style={fLab}>From</label><input className="input" defaultValue="2026-04-19 00:00" style={{ width: '100%' }} /></div>
          <div><label style={fLab}>To</label><input className="input" defaultValue="2026-04-19 23:59" style={{ width: '100%' }} /></div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}><Button variant="primary" icon={<Icon.search />}>查詢</Button></div>
        </div>

        <div style={{ height: 180, background: 'linear-gradient(180deg, rgba(34,211,238,0.04) 0%, transparent 100%)', border: '1px solid var(--border-1)', borderRadius: 8, padding: '14px 18px', position: 'relative', marginBottom: 16 }}>
          <div style={{ fontSize: 10.5, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>iFIX3_SecondError · last 24h</div>
          <svg viewBox="0 0 800 120" preserveAspectRatio="none" style={{ width: '100%', height: 140, marginTop: 4 }}>
            <defs>
              <linearGradient id="gArea" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="#22d3ee" stopOpacity="0.4"/>
                <stop offset="1" stopColor="#22d3ee" stopOpacity="0"/>
              </linearGradient>
            </defs>
            {[...Array(9)].map((_, i) => <line key={i} x1={i*100} y1="0" x2={i*100} y2="120" stroke="rgba(96,165,250,0.08)"/>)}
            <line x1="0" y1="40" x2="800" y2="40" stroke="#f59e0b" strokeDasharray="4 6" strokeOpacity="0.5" />
            <text x="6" y="36" fill="#f59e0b" fontSize="9" fontFamily="monospace">THR 60</text>
            <path d="M0,80 L50,75 L100,72 L150,78 L200,65 L250,50 L300,55 L350,48 L400,44 L420,30 L440,20 L460,15 L480,18 L520,22 L560,28 L600,35 L640,46 L680,54 L720,62 L760,70 L800,72 L800,120 L0,120 Z" fill="url(#gArea)" />
            <path d="M0,80 L50,75 L100,72 L150,78 L200,65 L250,50 L300,55 L350,48 L400,44 L420,30 L440,20 L460,15 L480,18 L520,22 L560,28 L600,35 L640,46 L680,54 L720,62 L760,70 L800,72" fill="none" stroke="#22d3ee" strokeWidth="1.5" />
            <circle cx="460" cy="15" r="4" fill="#ef4444" stroke="#0f172a" strokeWidth="2"/>
          </svg>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Timestamp</th><th>Tag</th><th className="td-num">Value</th><th>Condition met</th><th>Event</th></tr></thead>
            <tbody>
              {[
                ['2026-04-19 14:32:09', 'iFIX3_SecondError', '124', 'true', 'ALERT'],
                ['2026-04-19 14:31:09', 'iFIX3_SecondError', '78',  'true', '—'],
                ['2026-04-19 14:30:09', 'iFIX3_SecondError', '62',  'true', '—'],
                ['2026-04-19 14:29:09', 'iFIX3_SecondError', '45',  'false', 'RECOVER'],
                ['2026-04-19 14:28:09', 'iFIX3_SecondError', '12',  'false', '—'],
              ].map((r, i) => (
                <tr key={i}>
                  <td className="td-mono">{r[0]}</td>
                  <td style={{fontWeight:600}}>{r[1]}</td>
                  <td className="td-num" style={{ color: +r[2] > 60 ? '#ef4444' : '#e6edf7' }}>{r[2]}</td>
                  <td className="td-mono"><Pill kind={r[3] === 'true' ? 'err' : 'ok'}>{r[3]}</Pill></td>
                  <td className="td-mono">{r[4] === 'ALERT' ? <Pill kind="err">ALERT</Pill> : r[4] === 'RECOVER' ? <Pill kind="ok">RECOVER</Pill> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

Object.assign(window, { PageChannels, PageTags, PageAlerts, PageDiag, PageHistory });
