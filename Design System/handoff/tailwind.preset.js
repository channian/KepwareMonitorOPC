/**
 * Tailwind preset for Kepware Monitor Design System.
 *
 * Usage:
 *   // tailwind.config.js
 *   module.exports = {
 *     presets: [require('./design-system/handoff/tailwind.preset.js')],
 *     content: ['./src/**\/*.{js,jsx,ts,tsx}'],
 *   };
 */
module.exports = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg:       { 0:'#05070d', 1:'#0a0f1a', 2:'#0f172a', 3:'#172033', 4:'#1e293b' },
        fg:       { 1:'#e6edf7', 2:'#94a3b8', 3:'#64748b', 4:'#3f4b63' },
        stroke:   { 1:'#1e293b', 2:'#293548', 3:'#3b4a66' },
        accent:   { DEFAULT:'#22d3ee', hover:'#06b6d4' },
        brand:    { DEFAULT:'#3b82f6', hover:'#2563eb' },
        ok:       { DEFAULT:'#22c55e', bg:'rgba(34,197,94,0.1)' },
        warn:     { DEFAULT:'#f59e0b', bg:'rgba(245,158,11,0.1)' },
        err:      { DEFAULT:'#ef4444', bg:'rgba(239,68,68,0.1)' },
        info:     { DEFAULT:'#60a5fa', bg:'rgba(96,165,250,0.1)' },
        muted:    { DEFAULT:'#475569', bg:'rgba(71,85,105,0.15)' },
      },
      fontFamily: {
        sans:    ['Inter','-apple-system','Segoe UI','Microsoft JhengHei','PingFang TC','Noto Sans TC','sans-serif'],
        mono:    ['JetBrains Mono','Cascadia Code','Fira Code','SF Mono','Consolas','monospace'],
        display: ['Inter','-apple-system','Microsoft JhengHei','sans-serif'],
      },
      fontSize: {
        display: ['32px', { lineHeight: '1.2', letterSpacing: '-0.01em' }],
        h1: ['24px', { lineHeight: '1.2' }],
        h2: ['20px', { lineHeight: '1.2' }],
        h3: ['16px', { lineHeight: '1.5' }],
        body: ['14px', { lineHeight: '1.5' }],
        micro: ['11px', { letterSpacing: '0.08em' }],
      },
      borderRadius: { xs:'4px', sm:'6px', md:'10px', lg:'14px', xl:'20px' },
      boxShadow: {
        1: '0 2px 6px rgba(0,0,0,0.45), 0 1px 2px rgba(0,0,0,0.3)',
        2: '0 8px 24px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.3)',
        3: '0 16px 40px rgba(0,0,0,0.6)',
        'glow-accent': '0 0 0 1px rgba(34,211,238,0.25), 0 0 20px rgba(34,211,238,0.15)',
        'glow-blue':   '0 0 0 1px rgba(59,130,246,0.3), 0 0 16px rgba(59,130,246,0.2)',
      },
      transitionTimingFunction: { ds: 'cubic-bezier(0.4, 0, 0.2, 1)' },
      keyframes: {
        'ds-pulse': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.55' } },
        'ds-stripe': { to: { backgroundPosition: '32px 0' } },
      },
      animation: {
        'ds-pulse':  'ds-pulse 1.5s ease-in-out infinite',
        'ds-stripe': 'ds-stripe 0.8s linear infinite',
      },
      backgroundImage: {
        'ds-grid': 'linear-gradient(rgba(96,165,250,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(96,165,250,0.05) 1px, transparent 1px)',
      },
      backgroundSize: { 'ds-grid': '32px 32px' },
    },
  },
};
