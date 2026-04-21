# HANDOFF — Kepware Monitor Design System

此資料夾是給 **Claude Code** 或前端工程師接手用的完整交接包。放進你的 repo（建議 `design-system/`）之後，整個團隊（人 + AI）都能照表施工。

---

## 1 · 資料夾結構

```
design-system/
├── SKILL.md                      ← Claude Code 會自動讀這個；決定何時套用此系統
├── README.md                     ← 完整系統文件（tokens、motifs、vocabulary）
├── colors_and_type.css           ← 所有 design tokens（唯一真相）
├── assets/
│   ├── logo.svg                  ← KPM 方型 monogram
│   └── logo-lockup.svg           ← 水平 lockup（header 用）
├── preview/                      ← 20 張 component spec 卡片，可在瀏覽器打開
├── ui_kits/dashboard/            ← 可運作的 React 範例（6 頁）
│   ├── index.html
│   ├── dashboard.css
│   ├── components.jsx            ← Pill / Dot / Button / Card / Metric / Sidebar / Topbar
│   ├── pages.jsx                 ← Channels / Tags / Alerts / Diag / History
│   └── page_overview.jsx
└── handoff/
    ├── HANDOFF.md                ← 你現在在看的這份
    ├── tokens.ts                 ← TypeScript 版 tokens（import 即用）
    └── tailwind.preset.js        ← Tailwind 專案的 preset
```

---

## 2 · 給 Claude Code 的提示詞（複製貼上即可）

> 請讀 `design-system/SKILL.md` 和 `design-system/README.md` 了解此專案的 design system。
> 所有 design tokens 在 `design-system/colors_and_type.css`（或 TypeScript 版 `design-system/handoff/tokens.ts`）。
> 可複用元件範例在 `design-system/ui_kits/dashboard/components.jsx` 和 `pages.jsx`。
> 接下來請幫我做 **XXX**（例：登入頁 / 設定頁 / 行動版 Alert 清單 / 把 dashboard 接到 FastAPI）。
> 產出時請：
> 1. 只用 tokens.ts 裡定義的顏色、間距、圓角、陰影。
> 2. 照 `components.jsx` 的命名與 pattern 寫新元件。
> 3. UI 字串用繁體中文，識別字（tag name / NodeId）用等寬英文。
> 4. 詞彙照 `SKILL.md` 的「Vocabulary」區塊，email 主旨必須跟 `ase_email_service.py` 一致。

---

## 3 · 三種整合方式

### A. 純 HTML / Vanilla（最簡單）
直接 `<link rel="stylesheet" href="design-system/colors_and_type.css">` — CSS 變數即可用：`background: var(--bg-2); color: var(--fg-1);`。

### B. React + CSS Modules / plain CSS
1. 把 `colors_and_type.css` import 到全域（`main.tsx` 最上面）。
2. Component 用 `var(--accent)` 這類 CSS 變數。
3. 複製 `ui_kits/dashboard/components.jsx` 的 `Pill` / `Button` / `Card` / `Metric` 當起手式。

### C. React + Tailwind（推薦給新專案）
```js
// tailwind.config.js
module.exports = {
  presets: [require('./design-system/handoff/tailwind.preset.js')],
  content: ['./src/**/*.{ts,tsx}'],
};
```
然後就能寫：
```tsx
<button className="bg-brand hover:bg-brand-hover text-white px-4 py-2 rounded-sm shadow-glow-blue transition">
  測試連線
</button>
<span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-err-bg text-err font-mono text-xs">
  <span className="w-1.5 h-1.5 rounded-full bg-err animate-ds-pulse" />HOST_DOWN
</span>
```

---

## 4 · 核心規則速查（5 條 Do / 5 條 Don't）

**Do**
1. 狀態資訊一律 **dot + glow halo**（警示資料的視覺簽名）。
2. 數值欄位一律等寬字 + `font-variant-numeric: tabular-nums`。
3. 告警顏色**必成對**使用：`#ef4444` 文字 + `rgba(239,68,68,0.1)` 背景 + glow。
4. 主要操作用藍（`#3b82f6`），強調/活動用青（`#22d3ee`）。
5. UI 繁中 + 識別字英文 mono 並列。

**Don't**
1. 不要新增新的藍/青以外的 accent。
2. 不要做柔和灰色陰影 — 暗色系陰影要多層深黑。
3. 不要在 UI chrome 放 emoji（emoji 只在 `ase_email_service.py` email HTML 裡用）。
4. 不要用 scale/rotate 進場動畫 — 儀表風格要穩。
5. 不要硬寫 hex，一定走 token。

---

## 5 · 詞彙表（Claude Code 會遵照 SKILL.md 但再重申一次）

| 概念 | 用詞 |
|---|---|
| L1 主機 | Server · 主機 |
| L3 機台 | 設備 · 機台 · IGS Device |
| 監控點位 | 點位 · Tag |
| 條件閾值 | condition · threshold · CountNeeded (累積次數) |
| 匯入模式 | DRY RUN · LIVE |
| 告警動作 | 派報（發出） · 復歸（恢復正常） |
| 診斷 enum | `host_down` · `opc_service_down` · `device_down` · `igs_service_down` · `value_abnormal` |
| Email 主旨 | `[異常] Kepware 設備監控通知 - {tag}` · `[復歸] Kepware 設備恢復正常通知 - {device}` · `[連線異常] Kepware 設備監控通知 - {server} OPC 服務異常` |

---

## 6 · 常見延伸工作（告訴 Claude Code 這樣講即可）

- **新增一個頁面** — 「照 `pages.jsx` 裡 `PageAlerts` 的 pattern，新增 `PageSettings`，包含 SMTP / OPC poll interval / CSV 排程 三個區塊」。
- **接真實 API** — 「把 `PageOverview` 裡的假資料換成 `fetch('/api/servers')` 和 `fetch('/api/alerts')`，loading 時用 skeleton（沿用 `bg-3` 做 shimmer 動畫）」。
- **做行動版** — 「幫我做 `PageAlerts` 的 mobile 版，sidebar 變 bottom sheet，表格變 card list」。
- **出深淺模式** — 系統目前只有暗色版；需要亮色版時，在 `colors_and_type.css` 新增 `[data-theme="light"]` 覆蓋區塊即可。
