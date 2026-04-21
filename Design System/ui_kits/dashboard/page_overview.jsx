// Page: Overview
const { useState: useStateOv } = React;

function PageOverview() {
  const alerts = [
    { sev: 'err', who: 'kepware_a · iFIX3_SecondError', msg: 'VALUE_ABNORMAL · 124s since last error (threshold < 60s)', time: '14:32:09' },
    { sev: 'err', who: 'kepware_a · 主機 192.168.1.10', msg: 'L1 HOST_DOWN · Ping 失敗 · 派報 IT', time: '14:28:41' },
    { sev: 'warn', who: 'kepware_b · iFIX7_SecondError', msg: 'counter 2/3 · 累積次數將達標', time: '14:25:03' },
  ];
  const devices = [
    { name: 'kepware_a', host: '192.168.1.10', status: 'ok', tags: 42, alerts: 1 },
    { name: 'kepware_b', host: '192.168.1.11', status: 'warn', tags: 38, alerts: 0 },
    { name: 'kepware_c', host: '192.168.1.12', status: 'err', tags: 62, alerts: 2 },
    { name: 'kepware_d', host: '192.168.1.13', status: 'ok', tags: 24, alerts: 0 },
  ];
  return (
    <>
      <div className="banner err">
        <div className="banner-icon"><Icon.alert /></div>
        <div className="banner-body">
          <h4>[連線異常] kepware_a OPC 服務異常</h4>
          <p>L1 HOST_DOWN · 192.168.1.10 · 已派報至 IT 群組 · 持續 00:04:12</p>
        </div>
        <Button variant="outline" size="sm">查看診斷</Button>
        <Button variant="ghost" size="sm">暫時靜音</Button>
      </div>

      <div className="metrics">
        <Metric title="Active Servers" icon={<Icon.server />} value="4" delta="all reachable" deltaKind="ok" />
        <Metric title="Monitored Tags" icon={<Icon.tag />} value="166" unit="points" delta="▲ 3 loaded from CSV" deltaKind="muted" />
        <Metric title="Active Alerts" icon={<Icon.bell />} value="3" delta="1 new in last 5 min" deltaKind="err" active />
        <Metric title="Next Poll" icon={<Icon.clock />} value="04:12" delta="interval 600s" deltaKind="muted" />
      </div>

      <div className="two-col">
        <Card title="KEPWARE SERVERS" icon={<Icon.server />} actions={<Button variant="ghost" size="sm">全部檢視</Button>}>
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Server</th><th>Host</th><th className="td-num">Tags</th><th>Status</th><th>Alerts</th></tr></thead>
              <tbody>
                {devices.map(d => (
                  <tr key={d.name}>
                    <td style={{ fontWeight: 600 }}><Dot kind={d.status} />{d.name}</td>
                    <td className="td-mono">{d.host}:49320</td>
                    <td className="td-num">{d.tags}</td>
                    <td><Pill kind={d.status}>{d.status === 'ok' ? 'CONNECTED' : d.status === 'warn' ? 'DEGRADED' : 'HOST_DOWN'}</Pill></td>
                    <td className="td-mono" style={{ color: d.alerts ? '#ef4444' : '#64748b' }}>{d.alerts || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="ACTIVE ALERTS" icon={<Icon.bell />} actions={<Button variant="ghost" size="sm">Manage</Button>}>
          {alerts.map((a, i) => (
            <div key={i} className="diag">
              <div className={`diag-icon ${a.sev}`}><Icon.alert /></div>
              <div className="diag-body">
                <div className="who">{a.who}</div>
                <div className="msg">{a.msg}</div>
              </div>
              <div className="diag-time">{a.time}</div>
            </div>
          ))}
        </Card>
      </div>

      <Card title="POLLING LOG · kepware_a" icon={<Icon.activity />} actions={<Button variant="ghost" size="sm" icon={<Icon.download />}>Export</Button>}>
        <div className="log">
          <div><span className="t">14:32:07</span> <span className="i">[kepware_a]</span> 讀取 42 個點位…</div>
          <div><span className="t">14:32:08</span> <span className="o">[OK]</span> iFIX1_SecondError = 12</div>
          <div><span className="t">14:32:08</span> <span className="w">[WARN]</span> iFIX2_SecondError = 58 (counter 2/3)</div>
          <div><span className="t">14:32:09</span> <span className="e">[ALERT]</span> iFIX3_SecondError 觸發異常 &gt; 60s · 累積 3/3</div>
          <div><span className="t">14:32:09</span> <span className="i">[L3 DIAG]</span> iFIX/IGS 機台 10.0.1.20 無法連線 (Ping 失敗)</div>
          <div><span className="t">14:32:10</span> <span className="i">&gt;&gt;&gt; 寄送信件:</span> [異常] Kepware 設備監控通知 - iFIX3_SecondError</div>
          <div><span className="t">14:32:10</span> <span className="o">[SENT]</span> ops@factory.com, ops-lead@factory.com</div>
          <div><span className="t">14:32:11</span> <span className="o">[DB]</span> monitor_history ← 42 rows (alert_log ← 1 row)</div>
        </div>
      </Card>
    </>
  );
}

window.PageOverview = PageOverview;
