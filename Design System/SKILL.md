# SKILL: Kepware Monitor Design System

Dark-theme SCADA-style design system for the **channian/KepwareMonitorOPC** Python OPC UA monitoring stack. Use when designing any operator-facing UI (dashboards, alert pages, diagnostic views, threshold editors, CSV upload flows) that sits on top of `MonitorManager`, `DiagnosticService`, `DBService`, `OPCConnection`, and `ASEEmailService`.

## When to apply
Apply this system whenever the surface is:
- An operator-facing monitoring dashboard (24/7 NOC-style).
- A configuration screen for OPC UA tags, thresholds, or device routing.
- A diagnostic timeline / alert log / history query view.
- An admin tool for the Kepware Monitor Python engine or its sibling web services.

Do **not** apply it to email templates — those live inside `ase_email_service.py` and follow their own (emoji-rich) HTML style.

## Core tokens
Source of truth: `colors_and_type.css`. Key decisions:

- **Surfaces** stack `bg-0..bg-4`: `#05070d → #0a0f1a → #0f172a → #172033 → #1e293b`.
- **Accent:** cyan `#22d3ee` (focus, live, active, the subject of iconography). **Primary action:** blue `#3b82f6`. No purple/violet gradients.
- **Status:** ok `#22c55e` · warn `#f59e0b` · err `#ef4444` · info `#60a5fa` · muted `#475569`. Each pairs with a 10% `-bg` and 35-45% `-glow`.
- **Type:** Inter (sans, + CJK fallbacks), JetBrains Mono (numbers, IDs, logs). Body 14px. Micro-labels 11px UPPERCASE 0.08em. Numeric cells use `font-variant-numeric: tabular-nums`.
- **Radii:** 4/6/10/14/20/pill. Cards 10–14, inputs/buttons 6, pills 999.
- **Motion:** 120–320ms `cubic-bezier(0.4,0,0.2,1)`. Buttons lift 1px on hover. Live-data dots pulse `opacity 1↔0.55` at 1.5s. No spring/bounce.

## Vocabulary (use verbatim)
- Server / 主機 (L1 host) / 設備 / 機台 (L3 device) / 點位 (tag) / 條件 / 累積次數 / DRY RUN · LIVE / 派報 · 復歸.
- Diagnostic enums (exact): `host_down`, `opc_service_down`, `device_down`, `igs_service_down`, `value_abnormal`.
- Email subjects: `[異常] Kepware 設備監控通知 - {tag}`, `[復歸] Kepware 設備恢復正常通知 - {device}`, `[連線異常] Kepware 設備監控通知 - {server} OPC 服務異常`.

## Motifs
- **Status dot + glow halo** = the system's signature. Use it everywhere: nav, table rows, pills, device tree, diagnostic steps.
- **Tabular mono metrics** for every number. Never a proportional font on values.
- **Left accent bar** on active nav: 3×20px cyan, outer glow.
- **Subtle grid background** on page (32×32 `rgba(96,165,250,0.05)`), never inside cards.
- **Top-right radial cyan glow** on topbar for subtle atmosphere.

## Iconography
Lucide, stroke 2, rounded caps. Sizes 14 (inline) / 16 (button) / 18 (card title) / 22 (header) / 32 (empty state) / 48 (upload zone). Color = `currentColor`. Accent only when the icon is the subject. No emoji in UI chrome.

## Components covered by the kit
Buttons (primary/accent/outline/ghost/danger) · inputs (with focus ring + error state) · status pills & inline dots · data tables (zebra + hover) · metric cards (resting + active glow) · progress bars (animated stripe) · log panel · tabs (primary + pill subtabs) · alerts (inline banner) · modals · sidebar nav · topbar · device tree · diagnostic timeline · CSV upload zone · threshold editor · mini sparkline chart.

Complete reference: `ui_kits/dashboard/index.html`. Preview cards: `preview/*.html`.

## Do
- Lead with status + numeric value — operators need to triage in &lt;1 second.
- Keep alerts **live-looking**: pulse dots, glow halos, streaming log.
- Use Traditional Chinese for UI strings, mono English for identifiers, side by side.
- Pair every severity hue with its `-bg` and `-glow` tokens — never raw hex over arbitrary surfaces.

## Don't
- Don't invent new accent colors; use `--accent`, `--blue`, or semantic tokens.
- Don't use gradient backgrounds except on primary buttons (hover), progress fill, and the topbar ambient glow.
- Don't use emoji in screen chrome (they belong in email templates only).
- Don't use soft grey shadows — elevation is dark multi-layer.
- Don't use rotate/scale entry animations — the vibe is steady instrumentation.
