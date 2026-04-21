# Kepware Monitor Design System

A **dark-themed, high-tech SCADA monitoring aesthetic** for the Kepware OPC UA device monitoring dashboard. Built to extend the functionality of `channian/KepwareMonitorOPC` (Python backend) with a visual language suitable for 24/7 NOC-style displays showing device channels, tag values, thresholds, and three-layer diagnostics.

## Product context

**What it is.** An operator-facing web dashboard for the Kepware OPC monitoring stack. The Python engine (`kepware_monitor.py` → `MonitorManager`) polls KEPServerEX V6 servers on an interval, reads device tags over OPC UA (`asyncua`), evaluates thresholds, runs 3-layer network diagnostics on failures (ping host → TCP OPC port → ping iFIX/IGS device → TCP IGS port), sends HTML email alerts, and writes everything to SQLite (WAL mode). The dashboard surfaces all of that in real time.

**Primary screens.**
- **Overview** — channel/device status grid, active alerts, recent events.
- **Channels** — drill-down per Kepware server → channels → devices → tags.
- **Tags & Thresholds** — manage monitoring points. Add via CSV upload (`name,nodeid,server,type,condition,threshold,countneeded,enable,device_ip,device_port,mail_to,mail_cc`) or manual web form.
- **Diagnostics** — timeline of 3-layer diagnostic results: `host_down`, `opc_service_down`, `device_down`, `igs_service_down`, `value_abnormal`.
- **Alerts** — alert log with routing (connection alerts → IT, device/value alerts → per-device recipients).
- **History** — query `monitor_history` table, filter by device/date, export CSV.

**Locale.** Traditional Chinese (繁體中文) is primary for all user-facing text, with English co-equal for technical tokens (tag NodeIds, IPs, log levels).

## Sources

- **Primary codebase** — `channian/KepwareMonitorOPC` @ branch `claude/improve-kepware-monitoring-JEe1D`
  - `monitor_manager.py` — core orchestrator, CSV loading, alert routing
  - `diagnostic_service.py` — 3-layer diagnostic levels (source of truth for status enums)
  - `db_service.py` — SQLite schema (`monitor_history`, `alert_log`, `kepware_event_log`)
  - `opc_connection.py` — asyncua client wrapper
  - `ase_email_service.py` — SMTP HTML email
  - `Config/settings.example.ini`, `Config/tags.example.csv` — real config shapes
- **Sister repo (visual reference)** — `channian/ThingsBoradAPIWebUI` @ `claude/kepware-web-interface-l3WXm`, a Vue 3 SPA that manages Kepware points through ThingsBoard. Used as the starting point for the dark theme palette (slate-900 surfaces, blue accent, JhengHei typography), then pushed further toward a high-tech industrial look.
- **Sister repo** — `channian/KepwareAPIWeb` @ `claude/kepware-api-security-jIlhR` — FastAPI + light-theme Jinja templates. Not used visually; confirmed tag terminology (`name`, `type`, `description`, `scaling_type`, channel/device/tag hierarchy).

---

## Content fundamentals

### Language & tone
- **Traditional Chinese first** for anything an operator reads: screen titles, button labels, toasts, error messages. English is used unchanged for technical identifiers (NodeId strings, IP addresses, ports, `DRY RUN`, `LIVE`).
- **Short, imperative, slightly formal** — the Vue reference uses things like `測試連線`, `開始新增`, `下載結果明細 CSV`, `尚無操作紀錄`. No "please", no exclamation marks in UI (they're reserved for email alert bodies).
- **First-person plural / implicit subject.** Operator is "you" implicitly; system actions are stated directly (`連線中...`, `讀取失敗或連線斷掉`).
- **No emoji in UI chrome.** The older `tools.html` has emoji (`🛠️ 🚀 📍`) but the production Vue SPA uses SVG icons exclusively — follow the Vue SPA. Emoji are acceptable *only* inside email alert bodies (`✅`, `❌`) where they match the existing `ase_email_service` logging style.
- **ALL CAPS micro-labels** in English for section markers (`CONNECTION`, `DIAGNOSTICS`, `THRESHOLD`). This is the system's visual rhythm.

### Specific vocabulary (use these exactly)
| Concept | Term | Notes |
|---|---|---|
| Kepware OPC UA server | `Kepware Server` / `Server` | not "broker", not "host" |
| Physical machine running Kepware | `主機` (host) | Layer 1 target |
| Device behind Kepware (iFIX/IGS) | `設備` / `機台` | Layer 3 target |
| Monitoring point | `點位` / `Tag` | interchangeable |
| Trigger condition | `條件` (`greater`, `less`, `equal`, `not_equal`) |  |
| Cumulative threshold trigger | `累積次數` / `CountNeeded` |  |
| Preview vs apply | `DRY RUN` / `LIVE` | English, literal |
| Alert dispatch | `派報` | custom term, preserve it |
| Recovery from alert | `復歸` | custom term |

### Copy samples (lifted from code, use verbatim when applicable)
- Subject: `[異常] Kepware 設備監控通知 - {device.name}`
- Subject: `[復歸] Kepware 設備恢復正常通知 - {device.name}`
- Subject: `[連線異常] Kepware 設備監控通知 - {server_name} OPC 服務異常`
- Diagnostic messages: `Kepware 主機 {host} 無法連線 (Ping 失敗)`, `iFIX/IGS 機台 {device_ip} 正常但 IGS 服務 (Port {device_port}) 無回應`

---

## Visual foundations

### Motif
**Mission-control dark.** Deep near-black surfaces (`#05070d` → `#0f172a`), subtle hairline borders in slate, cyan and blue as the only chromatic accents, semantic traffic-light colors for status, monospace for every number/ID. Think: a SCADA HMI reimagined by a product team that also uses Linear and Vercel. A faint grid overlay / scanline is optional but reserved for the dashboard background only — never inside cards.

### Colors
- **Surfaces stack** — `--bg-0` (#05070d, page) → `--bg-1` (#0a0f1a, container) → `--bg-2` (#0f172a, card) → `--bg-3` (#172033, input/elevated) → `--bg-4` (#1e293b, hover).
- **Primary accent** is `--accent` cyan `#22d3ee` for focus, active states, live-data indicators.
- **Primary action** is `--blue` `#3b82f6` for buttons.
- **Status**: OK `#22c55e`, WARN `#f59e0b`, ERR `#ef4444`, INFO `#60a5fa`, MUTED `#475569` (stale / disabled). Each has a matching `-bg` (10% alpha) and `-glow` (35-45% alpha).
- **No gradients** except: (a) button hover (accent→accent-hover, 135°), (b) progress bars, (c) the optional ambient glow behind the header. Never use the purple/violet gradient from the sister repos.

### Typography
- **Sans:** Inter (fallback to Segoe UI / Microsoft JhengHei / PingFang TC / Noto Sans TC). **Substitution flagged:** Inter is loaded from Google Fonts; if the user has a licensed display face they want, swap it here.
- **Mono:** JetBrains Mono (fallback Cascadia Code / Consolas). Mono is used **always** for: tag NodeIds, IPs, ports, timestamps, numeric values, log output.
- Display sizes cap at 32px; body is 14px; micro labels are 11px ALL CAPS with 0.08em tracking. Tabular numerals are mandatory on every metric.

### Spacing
4px base. Common steps `4 / 8 / 12 / 16 / 20 / 24 / 32 / 48 / 64`. Cards pad 24px. Inputs pad 10×14. Table cells pad 10×14.

### Borders, radii, shadows
- **Radii:** 4/6/10/14/20 + `999px` pill. Cards use 10-14; buttons 6; inputs 6; pills 999.
- **Borders:** 1px `--border-1` `#1e293b` (same as card bg +1 level) on cards; `--border-2` on elevated items; `--border-3` `#3b4a66` on inputs.
- **Shadows** are deep/dark (not soft grey), multi-layer. `--glow-accent` and `--glow-blue` are 1px ring + outer glow — used on focus and on active status pills to sell the "alive" feel.

### Background treatments
- **Dashboard background:** `--bg-1` with an optional faint grid (32px × 32px, `rgba(96,165,250,0.05)` lines) fixed to viewport. No photographic imagery. No illustrations.
- **Header:** flat `--bg-2` with a 1px bottom border; a single radial cyan glow in the top-right corner at ~6% opacity for subtle atmosphere.
- **Empty states:** single outlined icon in `--fg-3` + one line of `--fg-2` text. No illustrations.

### Animation
- All transitions **120–320ms** with `cubic-bezier(0.4, 0, 0.2, 1)`.
- **Pulses** on live data: status dot pulses `opacity 1→0.6` over 1.5s infinite. Connection indicator gets a `box-shadow` glow halo on the same pulse.
- **Progress bars** have an animated 45° stripe overlay (from the Vue reference) at 0.8s.
- **No spring, no bounce, no rotate-in/scale-in flourishes.** The vibe is steady instrumentation, not playful.
- Hover states: `translateY(-1px)` on buttons + shadow bump. Press state: `translateY(0)` + shadow removed. Rows: background shift only, no transform.
- Focus states: **always** the accent ring — `box-shadow: 0 0 0 3px var(--accent-soft)` — never remove outline without replacement.

### Transparency & blur
- Modals: overlay `rgba(0,0,0,0.65)` + `backdrop-filter: blur(8px)`.
- Toast region: solid card, no blur (keep legible against live data).
- Status pills use solid `-bg` tokens at 10% alpha of their status hue — never translucent over arbitrary backgrounds.

### Cards
1px border, 10-14px radius, `--shadow-1`, `--bg-2` fill. On hover (interactive cards only): border shifts to `--border-2`, shadow to `--shadow-2`, no transform. Card titles are micro-labels (11px UPPERCASE, 0.08em, `--fg-2`) with an optional accent icon and a 1px bottom divider when the card contains sub-sections.

### Layout rules
- Fixed header, 56-64px tall. Sidebar optional (240px, collapses to 64px icon rail).
- Content max-width 1440px on the dashboard; full-bleed on tables.
- 24px gutter, 24px gap between cards, 16px gap between sibling controls.

---

## Iconography

**Primary system: Lucide** (CDN: `https://unpkg.com/lucide@latest/dist/umd/lucide.min.js`). The Vue SPA hand-rolls its SVG icons, but every one of them is a near-exact Lucide glyph (dashboard → `layout-dashboard`, server → `server`, cpu → `cpu`, bell → `bell`, search → `search`, download → `download`, trash-2, plus-circle, settings, activity, alert-triangle, check, x, chevron-left/right, upload-cloud, clock). Lucide matches the stroke weight (1.75–2) and rounded line caps exactly. **Substitution flagged:** we're using Lucide from CDN rather than the repo's inline SVGs — swap in if exact parity is wanted.

- **Stroke weight:** 2, `stroke-linecap: round`, `stroke-linejoin: round`.
- **Sizes:** 14 (inline), 16 (button), 18 (card title), 22 (header), 32 (empty state), 48 (upload zone).
- **Color:** `currentColor` — inherit from the text or button context. Accent color only when the icon is the *subject* (status dots, card-title markers).

### Status dots (not icons — pure CSS)
A 7–10px `border-radius: 50%` dot with a matching `box-shadow: 0 0 6px var(--{status}-glow)`. Used everywhere — connection status, device state, alert severity. This is the most recognizable motif of the system.

### Logo
No external brand — this is an internal operator tool. The "brand mark" is a monogram: a rounded-square tile with a pulsing cyan dot in the lower-right and the letters **KPM** (Kepware Process Monitor) in Inter 700. See `assets/logo.svg`.

### Emoji / Unicode
- **Not in UI chrome.**
- In email alert bodies: `✅` / `❌` are preserved from `ase_email_service.py` logging, but any new email templates should prefer SVG inline.
- Avoid Unicode bullets / arrows in UI; use Lucide (`chevron-right`, `arrow-right`) instead.

---

## Index

Root files:
- `README.md` — this file
- `SKILL.md` — Agent-Skills-compatible manifest
- `colors_and_type.css` — all tokens + semantic classes
- `assets/` — logo, icon references
- `preview/` — one HTML card per design-system sub-concept (loaded by the Design System tab)
- `ui_kits/dashboard/` — high-fidelity React UI kit for the Kepware monitoring dashboard (components + click-through `index.html`)

UI kits:
- **dashboard** — operator dashboard: overview, channels/devices, tags, CSV upload, alerts, diagnostics timeline.

Preview cards (see `preview/`):
- **Type:** display scale, body scale, mono + metrics
- **Colors:** surfaces, accent + blue, semantic status, border tokens
- **Spacing:** spacing scale, radius scale, shadow + glow system
- **Components:** buttons, inputs, status pills & dots, tables, cards, progress & logs, tabs, modals & alerts
- **Brand:** logo & monogram, iconography examples
