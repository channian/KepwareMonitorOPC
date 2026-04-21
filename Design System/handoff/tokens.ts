/**
 * Kepware Monitor — Design Tokens
 * Generated from colors_and_type.css — keep in sync.
 */

export const color = {
  bg: {
    0: '#05070d',  // app base
    1: '#0a0f1a',  // page surface
    2: '#0f172a',  // card
    3: '#172033',  // elevated / input
    4: '#1e293b',  // hover
    grid: 'rgba(96, 165, 250, 0.05)',
  },
  fg: {
    1: '#e6edf7',  // primary
    2: '#94a3b8',  // secondary / labels
    3: '#64748b',  // tertiary / placeholder
    4: '#3f4b63',  // disabled
  },
  border: {
    1: '#1e293b',
    2: '#293548',
    3: '#3b4a66',  // input
  },
  accent: {
    DEFAULT: '#22d3ee',
    hover:   '#06b6d4',
    soft:    'rgba(34, 211, 238, 0.12)',
    glow:    'rgba(34, 211, 238, 0.35)',
  },
  blue: {
    DEFAULT: '#3b82f6',
    hover:   '#2563eb',
    soft:    'rgba(59, 130, 246, 0.12)',
    glow:    'rgba(59, 130, 246, 0.4)',
  },
  ok:    { DEFAULT: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)',  glow: 'rgba(34, 197, 94, 0.35)' },
  warn:  { DEFAULT: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)', glow: 'rgba(245, 158, 11, 0.35)' },
  err:   { DEFAULT: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)',  glow: 'rgba(239, 68, 68, 0.45)' },
  info:  { DEFAULT: '#60a5fa', bg: 'rgba(96, 165, 250, 0.1)' },
  muted: { DEFAULT: '#475569', bg: 'rgba(71, 85, 105, 0.15)' },
} as const;

export const shadow = {
  sm: '0 1px 2px rgba(0,0,0,0.4)',
  1:  '0 2px 6px rgba(0,0,0,0.45), 0 1px 2px rgba(0,0,0,0.3)',
  2:  '0 8px 24px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.3)',
  3:  '0 16px 40px rgba(0,0,0,0.6)',
  glowAccent: '0 0 0 1px rgba(34,211,238,0.25), 0 0 20px rgba(34,211,238,0.15)',
  glowBlue:   '0 0 0 1px rgba(59,130,246,0.3), 0 0 16px rgba(59,130,246,0.2)',
} as const;

export const radius = {
  xs: '4px', sm: '6px', md: '10px', lg: '14px', xl: '20px', pill: '999px',
} as const;

export const spacing = {
  1: '4px', 2: '8px', 3: '12px', 4: '16px', 5: '20px',
  6: '24px', 7: '32px', 8: '48px', 9: '64px',
} as const;

export const font = {
  sans:    '"Inter", -apple-system, "Segoe UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
  mono:    '"JetBrains Mono", "Cascadia Code", "Fira Code", "SF Mono", Consolas, monospace',
  display: '"Inter", -apple-system, "Microsoft JhengHei", sans-serif',
} as const;

export const fontSize = {
  display: '32px', h1: '24px', h2: '20px', h3: '16px',
  body: '14px',    sm: '13px', xs: '12px', micro: '11px',
} as const;

export const lineHeight = { tight: 1.2, normal: 1.5, loose: 1.7 } as const;
export const letterSpacing = { caps: '0.08em', tight: '-0.01em' } as const;

export const motion = {
  ease:    'cubic-bezier(0.4, 0, 0.2, 1)',
  easeOut: 'cubic-bezier(0, 0, 0.2, 1)',
  fast:    '120ms',
  med:     '200ms',
  slow:    '320ms',
} as const;

export const tokens = { color, shadow, radius, spacing, font, fontSize, lineHeight, letterSpacing, motion };
export default tokens;
