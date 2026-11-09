# ui_theme.py - Design system "Autopilot Normativo" (CSS + animações + componentes HTML reutilizáveis).
#
# Direção visual (gerada com a skill ui-ux-pro-max):  "Accessible & Ethical" para governo/jurídico.
#   Tipografia: EB Garamond (títulos, evoca texto legal) + Atkinson Hyperlegible (interface, máxima legibilidade).
#   Cores: tinta/azul-marinho institucional + verde-esmeralda de acento (herdado da marca original) + vermelho
#          jurídico exclusivo para "taxado/revogado".
#   Movimento: entrada escalonada, aurora lenta no hero, contadores animados, linha do fluxo, taxação animada no login.
#   Acessibilidade: contraste >= 4.5:1, foco visível, alvos >= 44px, prefers-reduced-motion respeitado, sem emoji
#          como ícone (SVG inline).
from html import escape

import streamlit as st

FONTES = ("@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400"
          "&family=EB+Garamond:wght@500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');")

# --------------------------------------------------------------------------- ícones (Lucide, traçado 24x24)
_ICONES = {
    "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "upload": '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "merge": '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/>',
    "news": '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "eye": '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
}


def icone(nome, tam=18, cls="", espessura=1.9):
    corpo = _ICONES.get(nome, _ICONES["info"])
    return (f'<svg class="cn-ico {cls}" width="{tam}" height="{tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{espessura}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{corpo}</svg>')


# --------------------------------------------------------------------------- CSS global
CSS = FONTES + """
@property --cn-n { syntax: '<integer>'; inherits: false; initial-value: 0; }

:root {
  --cn-ink: #0B1530;       --cn-ink-2: #14244F;   --cn-brand: #1E3C72;   --cn-brand-2: #2A5298;
  --cn-accent: #00A86B;    --cn-accent-2: #00D084; --cn-accent-ink: #006B45;
  --cn-info: #0369A1;      --cn-warn: #B45309;     --cn-danger: #C81E3A; --cn-ok: #0F8F5F;
  --cn-bg: #F3F6FB;        --cn-card: #FFFFFF;     --cn-line: #E2E8F0;   --cn-line-2: #CBD5E1;
  --cn-text: #0F172A;      --cn-muted: #475569;    --cn-soft: #EEF3FB;
  --cn-r: 16px;            --cn-r-sm: 10px;
  --cn-sh-1: 0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.05);
  --cn-sh-2: 0 8px 24px -8px rgba(15,23,42,.14), 0 2px 6px rgba(15,23,42,.05);
  --cn-sh-3: 0 24px 48px -16px rgba(11,21,48,.32);
  --cn-ease: cubic-bezier(.22,.8,.24,1);
  --cn-font: 'Atkinson Hyperlegible', 'Segoe UI', system-ui, -apple-system, sans-serif;
  --cn-serif: 'EB Garamond', 'Georgia', 'Times New Roman', serif;
  --cn-mono: 'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace;
}

/* ---------- base ---------- */
html, body, .stApp, [data-testid="stAppViewContainer"] { font-family: var(--cn-font); color: var(--cn-text); }
.stApp { background: var(--cn-bg); isolation: isolate; }
[data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer, [data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"] { background: transparent !important; height: 0 !important; min-height: 0 !important; }
[data-testid="stMainBlockContainer"], .block-container { max-width: 1240px !important; padding: .9rem 1.6rem 4rem !important; }
h1, h2, h3, h4 { font-family: var(--cn-serif); letter-spacing: -.01em; color: var(--cn-ink); font-weight: 600; }
h3 { font-size: 1.55rem !important; } h4 { font-size: 1.2rem !important; }
p, li, label, span { font-family: inherit; }
a { color: var(--cn-info); }
::selection { background: rgba(0,168,107,.22); }
:focus-visible { outline: 3px solid rgba(3,105,161,.55) !important; outline-offset: 2px !important; border-radius: 8px; }

/* aurora de fundo, lenta e sutil */
.stApp::before {
  content: ""; position: fixed; inset: -20vmax; z-index: -1; pointer-events: none; opacity: .75;
  background:
    radial-gradient(38vmax 30vmax at 12% 8%,  rgba(42,82,152,.16), transparent 60%),
    radial-gradient(34vmax 28vmax at 88% 4%,  rgba(0,208,132,.13), transparent 60%),
    radial-gradient(40vmax 34vmax at 70% 96%, rgba(3,105,161,.10), transparent 62%);
  animation: cn-aurora 38s ease-in-out infinite alternate;
}
@keyframes cn-aurora { from { transform: translate3d(0,0,0) rotate(0deg); } to { transform: translate3d(-3vmax,2vmax,0) rotate(6deg); } }

/* ---------- entrada escalonada (1 vez por elemento novo) ---------- */
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
[data-testid="stMainBlockContainer"] .element-container { animation: cn-up .5s var(--cn-ease) both; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:nth-child(2) { animation-delay: .04s; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:nth-child(3) { animation-delay: .08s; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:nth-child(4) { animation-delay: .12s; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:nth-child(5) { animation-delay: .16s; }
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:nth-child(n+6) { animation-delay: .2s; }
@keyframes cn-up { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@keyframes cn-pop { from { opacity: 0; transform: scale(.94); } to { opacity: 1; transform: none; } }
@keyframes cn-spin { to { transform: rotate(360deg); } }
@keyframes cn-pulse { 0% { box-shadow: 0 0 0 0 rgba(0,168,107,.55); } 70% { box-shadow: 0 0 0 9px rgba(0,168,107,0); } 100% { box-shadow: 0 0 0 0 rgba(0,168,107,0); } }
@keyframes cn-shimmer { from { background-position: -200% 0; } to { background-position: 200% 0; } }
@keyframes cn-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
@keyframes cn-sweep { from { transform: translateX(-120%) skewX(-20deg); } to { transform: translateX(260%) skewX(-20deg); } }
@keyframes cn-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes cn-count { from { --cn-n: 0; } to { --cn-n: var(--cn-alvo); } }

/* ---------- barra superior (navegação) ---------- */
.st-key-topbar {
  position: sticky; top: .5rem; z-index: 999; padding: .5rem .7rem; margin-bottom: 1.1rem;
  background: rgba(255,255,255,.82); backdrop-filter: saturate(160%) blur(14px); -webkit-backdrop-filter: saturate(160%) blur(14px);
  border: 1px solid rgba(203,213,225,.7); border-radius: 20px; box-shadow: var(--cn-sh-2);
  animation: cn-pop .5s var(--cn-ease) both;
}
.st-key-topbar [data-testid="stHorizontalBlock"] { align-items: center; gap: .35rem; }
.cn-brand { display: flex; align-items: center; gap: .65rem; padding: .15rem .35rem; white-space: nowrap; }
.cn-logo { position: relative; width: 42px; height: 42px; border-radius: 13px; display: grid; place-items: center; color: #fff; overflow: hidden;
  background: linear-gradient(135deg, var(--cn-brand), var(--cn-ink-2)); box-shadow: 0 6px 16px -4px rgba(30,60,114,.55); }
.cn-logo::after { content: ""; position: absolute; inset: 0; background: linear-gradient(115deg, transparent 30%, rgba(255,255,255,.35) 50%, transparent 70%); animation: cn-sweep 5s ease-in-out infinite; }
.cn-brand b { font-family: var(--cn-serif); font-size: 1.28rem; line-height: 1; color: var(--cn-ink); letter-spacing: -.01em; display: block; }
.cn-brand small { display: block; color: var(--cn-muted); font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; margin-top: 2px; }
.st-key-topbar [data-testid="stPageLink-NavLink"] {
  min-height: 44px; border-radius: 12px; padding: .35rem .7rem; justify-content: center; font-weight: 700; font-size: .86rem; color: var(--cn-muted) !important;
  transition: background .2s var(--cn-ease), color .2s, transform .2s var(--cn-ease); text-decoration: none;
}
.st-key-topbar [data-testid="stPageLink-NavLink"]:hover { background: var(--cn-soft); color: var(--cn-brand) !important; transform: translateY(-1px); }
.cn-nav-ativo {
  display: flex; align-items: center; justify-content: center; gap: .4rem; min-height: 44px; border-radius: 12px; padding: .35rem .7rem; font-weight: 700; font-size: .86rem; white-space: nowrap;
  color: #fff; background: linear-gradient(135deg, var(--cn-brand), var(--cn-brand-2)); box-shadow: 0 8px 18px -8px rgba(30,60,114,.7); position: relative; overflow: hidden;
}
.cn-nav-ativo::after { content: ""; position: absolute; left: 14%; right: 14%; bottom: 4px; height: 2px; border-radius: 2px; background: var(--cn-accent-2); transform-origin: left; animation: cn-grow .6s var(--cn-ease) .15s both; }
.st-key-topbar button { min-height: 44px; }

/* ---------- hero ---------- */
.cn-hero {
  position: relative; overflow: hidden; border-radius: 24px; padding: 2rem 2.2rem 1.9rem; margin: 0 0 1.4rem; color: #fff; isolation: isolate;
  background: linear-gradient(135deg, #0B1530 0%, #14306B 55%, #1E3C72 100%); box-shadow: var(--cn-sh-3); animation: cn-up .6s var(--cn-ease) both;
}
.cn-hero::before, .cn-hero::after { content: ""; position: absolute; z-index: -1; border-radius: 50%; filter: blur(46px); }
.cn-hero::before { width: 360px; height: 360px; right: -80px; top: -140px; background: radial-gradient(circle, rgba(0,208,132,.55), transparent 65%); animation: cn-float 11s ease-in-out infinite; }
.cn-hero::after { width: 320px; height: 320px; left: 28%; bottom: -200px; background: radial-gradient(circle, rgba(56,132,255,.55), transparent 65%); animation: cn-float 14s ease-in-out infinite reverse; }
.cn-hero .cn-grade { position: absolute; inset: 0; z-index: -1; opacity: .12; background-image: linear-gradient(rgba(255,255,255,.7) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.7) 1px, transparent 1px); background-size: 34px 34px; mask-image: linear-gradient(120deg, #000, transparent 70%); -webkit-mask-image: linear-gradient(120deg, #000, transparent 70%); }
.cn-hero-eyebrow { display: inline-flex; align-items: center; gap: .45rem; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--cn-accent-2); background: rgba(0,208,132,.12); border: 1px solid rgba(0,208,132,.3); padding: .28rem .7rem; border-radius: 999px; }
.cn-hero h1 { font-family: var(--cn-serif) !important; color: #fff !important; font-size: clamp(1.8rem, 3.4vw, 2.6rem) !important; line-height: 1.08 !important; margin: .75rem 0 .35rem !important; padding: 0 !important; font-weight: 600 !important; }
.cn-hero p { color: rgba(226,232,240,.92); max-width: 62ch; margin: 0; font-size: 1.02rem; line-height: 1.5; }

/* ---------- linha do fluxo (stepper) ---------- */
.cn-fluxo { display: flex; align-items: flex-start; gap: 0; margin: 0 0 1.3rem; padding: 1rem 1.2rem; background: var(--cn-card); border: 1px solid var(--cn-line); border-radius: var(--cn-r); box-shadow: var(--cn-sh-1); }
.cn-passo { flex: 1; position: relative; text-align: center; font-size: .82rem; color: var(--cn-muted); font-weight: 700; }
.cn-passo i { position: relative; z-index: 1; display: grid; place-items: center; width: 34px; height: 34px; margin: 0 auto .35rem; border-radius: 50%; font-style: normal; background: var(--cn-soft); color: var(--cn-brand); border: 2px solid var(--cn-line-2); transition: all .3s var(--cn-ease); }
.cn-passo::before { content: ""; position: absolute; top: 16px; left: -50%; width: 100%; height: 3px; background: var(--cn-line); z-index: 0; }
.cn-passo:first-child::before { display: none; }
.cn-passo.feito::before, .cn-passo.atual::before { background: linear-gradient(90deg, var(--cn-accent), var(--cn-accent-2)); transform-origin: left; animation: cn-grow .7s var(--cn-ease) both; }
.cn-passo.feito i { background: var(--cn-accent); border-color: var(--cn-accent); color: #fff; }
.cn-passo.atual i { background: #fff; border-color: var(--cn-accent); color: var(--cn-accent-ink); animation: cn-pulse 2s infinite; }
.cn-passo.atual, .cn-passo.feito { color: var(--cn-ink); }
@media (max-width: 640px) { .cn-passo span { display: none; } }

/* ---------- cartões e KPIs ---------- */
.cn-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .9rem; margin: 0 0 1.3rem; }
.cn-kpi { position: relative; overflow: hidden; background: var(--cn-card); border: 1px solid var(--cn-line); border-radius: var(--cn-r); padding: 1.05rem 1.15rem; box-shadow: var(--cn-sh-1); transition: transform .3s var(--cn-ease), box-shadow .3s var(--cn-ease), border-color .3s; animation: cn-up .55s var(--cn-ease) both; }
.cn-kpi:nth-child(2) { animation-delay: .06s; } .cn-kpi:nth-child(3) { animation-delay: .12s; } .cn-kpi:nth-child(4) { animation-delay: .18s; } .cn-kpi:nth-child(5) { animation-delay: .24s; }
.cn-kpi:hover { transform: translateY(-4px); box-shadow: var(--cn-sh-2); border-color: var(--cn-line-2); }
.cn-kpi::after { content: ""; position: absolute; right: -26px; top: -26px; width: 90px; height: 90px; border-radius: 50%; background: var(--cn-tom, rgba(42,82,152,.10)); transition: transform .4s var(--cn-ease); }
.cn-kpi:hover::after { transform: scale(1.5); }
.cn-kpi .cn-kpi-ico { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px; background: var(--cn-tom, rgba(42,82,152,.10)); color: var(--cn-cor, var(--cn-brand)); position: relative; z-index: 1; }
.cn-kpi .cn-num { display: block; font-family: var(--cn-serif); font-size: 2.35rem; font-weight: 600; line-height: 1; margin-top: .7rem; color: var(--cn-ink); counter-reset: cnn var(--cn-n); animation: cn-count 1.1s var(--cn-ease) .1s both; position: relative; z-index: 1; }
.cn-kpi .cn-num::after { content: counter(cnn); }
.cn-kpi .cn-rot { font-size: .8rem; color: var(--cn-muted); font-weight: 700; margin-top: .25rem; position: relative; z-index: 1; }
.cn-kpi.ok { --cn-cor: var(--cn-ok); --cn-tom: rgba(15,143,95,.12); } .cn-kpi.warn { --cn-cor: var(--cn-warn); --cn-tom: rgba(180,83,9,.12); }
.cn-kpi.info { --cn-cor: var(--cn-info); --cn-tom: rgba(3,105,161,.12); } .cn-kpi.rosa { --cn-cor: #6D28D9; --cn-tom: rgba(109,40,217,.10); }

.cn-card { background: var(--cn-card); border: 1px solid var(--cn-line); border-radius: var(--cn-r); padding: 1.1rem 1.25rem; margin-bottom: .8rem; box-shadow: var(--cn-sh-1); position: relative; transition: transform .25s var(--cn-ease), box-shadow .25s var(--cn-ease); animation: cn-up .5s var(--cn-ease) both; }
.cn-card:hover { transform: translateY(-2px); box-shadow: var(--cn-sh-2); }
.cn-card.ok { border-left: 5px solid var(--cn-ok); background: linear-gradient(90deg, rgba(15,143,95,.06), #fff 40%); }
.cn-card.warn { border-left: 5px solid var(--cn-warn); background: linear-gradient(90deg, rgba(180,83,9,.07), #fff 40%); }
.cn-card.info { border-left: 5px solid var(--cn-info); background: linear-gradient(90deg, rgba(3,105,161,.06), #fff 40%); }
.cn-card h5 { margin: 0 0 .3rem; font-family: var(--cn-font); font-size: .98rem; color: var(--cn-ink); display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.cn-card p { margin: .2rem 0; color: var(--cn-muted); font-size: .93rem; line-height: 1.5; }
.cn-card .cn-dica { margin-top: .5rem; padding-top: .5rem; border-top: 1px dashed var(--cn-line-2); font-style: italic; color: var(--cn-ink-2); font-size: .88rem; }

.cn-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .18rem .62rem; border-radius: 999px; font-size: .74rem; font-weight: 700; letter-spacing: .02em; background: var(--cn-soft); color: var(--cn-brand); border: 1px solid var(--cn-line-2); white-space: nowrap; }
.cn-badge.ok { background: rgba(15,143,95,.12); color: #0A6B47; border-color: rgba(15,143,95,.35); }
.cn-badge.warn { background: rgba(180,83,9,.12); color: #8A3F06; border-color: rgba(180,83,9,.35); }
.cn-badge.danger { background: rgba(200,30,58,.10); color: #A3162E; border-color: rgba(200,30,58,.35); }
.cn-badge.info { background: rgba(3,105,161,.10); color: #035985; border-color: rgba(3,105,161,.3); }
.cn-badge .cn-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: cn-pulse 2s infinite; }

.cn-vazio { text-align: center; padding: 2.4rem 1rem; color: var(--cn-muted); background: var(--cn-card); border: 1.5px dashed var(--cn-line-2); border-radius: var(--cn-r); }
.cn-vazio .cn-ico { color: var(--cn-line-2); animation: cn-float 4s ease-in-out infinite; } .cn-vazio b { display: block; color: var(--cn-ink); margin-top: .4rem; font-size: 1.02rem; }

.cn-presenca { display: flex; align-items: center; flex-wrap: wrap; gap: .45rem; margin: -.35rem 0 1rem; font-size: .82rem; color: var(--cn-muted); }
.cn-avatar { display: inline-grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; font-size: .72rem; font-weight: 700; color: #fff; background: linear-gradient(135deg, var(--cn-brand-2), var(--cn-accent)); border: 2px solid #fff; box-shadow: var(--cn-sh-1); }
.cn-chip { display: inline-flex; align-items: center; gap: .4rem; padding: .18rem .6rem .18rem .2rem; border-radius: 999px; background: #fff; border: 1px solid var(--cn-line); box-shadow: var(--cn-sh-1); animation: cn-pop .4s var(--cn-ease) both; }
.cn-chip .cn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--cn-accent-2); animation: cn-pulse 2s infinite; }
.cn-aviso-trava { display: flex; align-items: center; gap: .6rem; padding: .7rem 1rem; margin: 0 0 .8rem; border-radius: 12px; background: rgba(180,83,9,.09); border: 1px solid rgba(180,83,9,.35); color: #7A3606; font-weight: 700; font-size: .9rem; animation: cn-pop .4s var(--cn-ease) both; }

/* ---------- widgets nativos ---------- */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primaryFormSubmit"], [data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stDownloadButton"] button, [data-testid="stBaseButton-tertiary"] {
  border-radius: 12px !important; min-height: 46px; font-weight: 700 !important; font-family: var(--cn-font) !important; letter-spacing: .01em;
  transition: transform .2s var(--cn-ease), box-shadow .25s var(--cn-ease), background .25s, border-color .25s, color .25s !important; position: relative; overflow: hidden; cursor: pointer;
}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, var(--cn-brand) 0%, var(--cn-brand-2) 100%) !important; border: 0 !important; color: #fff !important; box-shadow: 0 10px 20px -10px rgba(30,60,114,.85);
}
[data-testid="stBaseButton-primary"]::after, [data-testid="stBaseButton-primaryFormSubmit"]::after { content: ""; position: absolute; top: 0; bottom: 0; width: 40%; left: 0; background: linear-gradient(100deg, transparent, rgba(255,255,255,.3), transparent); transform: translateX(-120%) skewX(-20deg); }
[data-testid="stBaseButton-primary"]:hover::after, [data-testid="stBaseButton-primaryFormSubmit"]:hover::after { animation: cn-sweep .9s var(--cn-ease); }
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover { transform: translateY(-2px); box-shadow: 0 16px 26px -12px rgba(30,60,114,.9); }
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stDownloadButton"] button { background: #fff !important; border: 1.5px solid var(--cn-line-2) !important; color: var(--cn-ink) !important; }
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-secondaryFormSubmit"]:hover, [data-testid="stDownloadButton"] button:hover { border-color: var(--cn-brand-2) !important; color: var(--cn-brand) !important; background: var(--cn-soft) !important; transform: translateY(-2px); box-shadow: var(--cn-sh-2); }
[data-testid="stBaseButton-primary"]:disabled, [data-testid="stBaseButton-secondary"]:disabled { opacity: .45; cursor: not-allowed; transform: none !important; box-shadow: none !important; }
[data-testid="stBaseButton-primary"]:active, [data-testid="stBaseButton-secondary"]:active, [data-testid="stDownloadButton"] button:active { transform: scale(.97); }

[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"], [data-testid="stTextInputRootElement"] { border-radius: 12px !important; }
[data-testid="stTextInputRootElement"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { border: 1.5px solid var(--cn-line-2) !important; background: #fff !important; transition: border-color .2s, box-shadow .25s !important; }
[data-testid="stTextInputRootElement"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within { border-color: var(--cn-brand-2) !important; box-shadow: 0 0 0 4px rgba(42,82,152,.16) !important; }
[data-testid="stWidgetLabel"] p, label p { font-weight: 700 !important; color: var(--cn-ink) !important; font-size: .9rem !important; }

[data-testid="stTabs"] [role="tablist"] { gap: .35rem; border-bottom: 0 !important; padding: .3rem; background: #fff; border: 1px solid var(--cn-line); border-radius: 16px; box-shadow: var(--cn-sh-1); width: fit-content; max-width: 100%; overflow-x: auto; position: relative; }
[data-testid="stTabs"] [data-testid="stTab"], [data-testid="stTabs"] button[role="tab"] { position: relative; border-radius: 12px !important; min-height: 42px; padding: 0 1rem !important; font-weight: 700 !important; color: var(--cn-muted) !important; cursor: pointer; display: flex; align-items: center; transition: background .2s, color .2s, box-shadow .25s var(--cn-ease) !important; }
[data-testid="stTabs"] [data-testid="stTab"] p { font-weight: 700 !important; color: inherit !important; margin: 0; }
[data-testid="stTabs"] [data-testid="stTab"]:hover { background: var(--cn-soft) !important; color: var(--cn-brand) !important; }
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"], [data-testid="stTabs"] button[role="tab"][aria-selected="true"] { background: linear-gradient(135deg, var(--cn-brand), var(--cn-brand-2)) !important; color: #fff !important; box-shadow: 0 8px 16px -8px rgba(30,60,114,.8); }
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] p { color: #fff !important; }
[data-testid="stTabs"] .react-aria-SelectionIndicator, [data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] { display: none !important; }
[data-testid="stTabPanel"] { padding-top: 1rem !important; animation: cn-up .4s var(--cn-ease) both; }

[data-testid="stExpander"] { border: 1px solid var(--cn-line) !important; border-radius: var(--cn-r) !important; background: var(--cn-card); box-shadow: var(--cn-sh-1); overflow: hidden; transition: box-shadow .25s var(--cn-ease), border-color .25s; }
[data-testid="stExpander"]:hover { box-shadow: var(--cn-sh-2); border-color: var(--cn-line-2) !important; }
[data-testid="stExpander"] summary { min-height: 52px; font-weight: 700; padding: .4rem 1rem !important; }
[data-testid="stExpander"] summary:hover { background: var(--cn-soft); }
[data-testid="stExpanderDetails"] { animation: cn-up .35s var(--cn-ease) both; }

[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) { border-radius: var(--cn-r); }
[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed var(--cn-line-2) !important; border-radius: 20px !important; background: linear-gradient(180deg, #fff, var(--cn-soft)) !important; padding: 1.8rem 1.4rem !important;
  transition: border-color .25s, background .25s, transform .25s var(--cn-ease), box-shadow .25s;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--cn-accent) !important; transform: translateY(-2px); box-shadow: 0 16px 30px -18px rgba(0,168,107,.6); background: linear-gradient(180deg, #fff, rgba(0,208,132,.07)) !important; }
[data-testid="stFileUploaderFile"] { animation: cn-pop .35s var(--cn-ease) both; border-radius: 12px; }

[data-testid="stAlert"] { border-radius: 14px !important; border: 1px solid var(--cn-line) !important; box-shadow: var(--cn-sh-1); animation: cn-pop .4s var(--cn-ease) both; }
[data-testid="stProgress"] [data-testid="stProgressBarTrack"], [data-testid="stProgress"] > div > div { border-radius: 999px !important; height: 10px !important; }
[data-testid="stProgress"] [role="progressbar"] > div, [data-testid="stProgress"] div[data-baseweb="progress-bar"] > div > div { background: repeating-linear-gradient(45deg, var(--cn-accent) 0 12px, var(--cn-accent-2) 12px 24px) !important; background-size: 34px 34px; animation: cn-shimmer 1s linear infinite; }
[data-testid="stStatus"], [data-testid="stStatusWidget"] ~ div details { border-radius: var(--cn-r) !important; }
[data-testid="stSpinner"] i, [data-testid="stSpinner"] svg { animation: cn-spin .9s linear infinite; }
[data-testid="stMetric"] { background: #fff; border: 1px solid var(--cn-line); border-radius: var(--cn-r); padding: .8rem 1rem; box-shadow: var(--cn-sh-1); }
[data-testid="stPopover"] button { min-height: 44px; border-radius: 14px !important; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--cn-muted) !important; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 14px; overflow: hidden; border: 1px solid var(--cn-line); }
hr { border: 0 !important; height: 1px !important; background: linear-gradient(90deg, transparent, var(--cn-line-2), transparent) !important; margin: 1.4rem 0 !important; }
[data-testid="stRadioGroup"] label { cursor: pointer; }
.cn-ico { vertical-align: -0.18em; flex-shrink: 0; }

/* ---------- prévia de documento (papel) ---------- */
.cn-papel { background: #fff; color: #111827; padding: 2.2rem 2.6rem; border: 1px solid var(--cn-line); border-top: 0; border-radius: 0 0 14px 14px; box-shadow: var(--cn-sh-2);
  font-family: 'Times New Roman', Georgia, serif; font-size: 1.02rem; line-height: 1.6; text-align: justify; max-height: 640px; overflow: auto; }
.cn-papel p, .cn-papel div { margin: 0 0 .55rem; } .cn-papel table { width: 100%; border-collapse: collapse; margin: .8rem 0; font-size: .9rem; } .cn-papel td, .cn-papel th { border: 1px solid #111; padding: 5px 7px; }
.cn-papel strike, .cn-papel s { text-decoration: line-through; } .cn-papel .capitulo, .cn-papel .titulo, .cn-papel .orgaos, .cn-papel .assinatura, .cn-papel .topo, .cn-assinatura { text-align: center; font-weight: 700; }
.cn-papel .ementa { margin-left: 45%; } .cn-papel .dispositivo { text-indent: 2.2rem; } .cn-papel .brasao img { width: 42px; display: block; margin: 0 auto; } .cn-papel .topo { font-size: .8rem; text-transform: uppercase; color: #475569; }
.cn-assinatura { margin-top: 2rem; }
.cn-papel-barra { display: flex; align-items: center; gap: .6rem; padding: .5rem .8rem; background: var(--cn-ink); color: #fff; border-radius: 14px 14px 0 0; font-size: .82rem; font-weight: 700; }
.cn-papel-barra i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; } .cn-papel-barra i:nth-child(1){background:#ff5f56} .cn-papel-barra i:nth-child(2){background:#ffbd2e} .cn-papel-barra i:nth-child(3){background:#27c93f}

/* ---------- login ---------- */
.st-key-login_shell { position: relative; border-radius: 28px; overflow: hidden; box-shadow: var(--cn-sh-3); background: #fff; margin-top: 2.2vh; animation: cn-pop .7s var(--cn-ease) both; border: 1px solid rgba(203,213,225,.7); }
.st-key-login_shell [data-testid="stHorizontalBlock"] { gap: 0 !important; }
.st-key-login_left { height: 100%; min-height: 600px; padding: 2.2rem 2.2rem 3rem; color: #fff; position: relative; overflow: hidden; isolation: isolate; background: linear-gradient(150deg, #0B1530 0%, #14306B 60%, #1E3C72 100%); }
.st-key-login_left::before { content: ""; position: absolute; z-index: -1; width: 420px; height: 420px; right: -140px; top: -160px; border-radius: 50%; background: radial-gradient(circle, rgba(0,208,132,.6), transparent 65%); filter: blur(40px); animation: cn-float 10s ease-in-out infinite; }
.st-key-login_left::after { content: ""; position: absolute; z-index: -1; width: 380px; height: 380px; left: -120px; bottom: -150px; border-radius: 50%; background: radial-gradient(circle, rgba(56,132,255,.6), transparent 65%); filter: blur(44px); animation: cn-float 13s ease-in-out infinite reverse; }
.st-key-login_left .cn-brand b { color: #fff; } .st-key-login_left .cn-brand small { color: rgba(226,232,240,.8); }
.cn-lg-titulo { font-family: var(--cn-serif); font-size: clamp(1.9rem, 3vw, 2.6rem); line-height: 1.06; font-weight: 600; margin: 2rem 0 .6rem; color: #fff; }
.cn-lg-titulo em { font-style: italic; color: var(--cn-accent-2); }
.cn-lg-sub { color: rgba(226,232,240,.9); max-width: 44ch; line-height: 1.5; }
.cn-lg-lista { list-style: none; padding: 0; margin: 1.4rem 0 0; display: grid; gap: .7rem; }
.cn-lg-lista li { display: flex; align-items: center; gap: .7rem; font-weight: 700; font-size: .92rem; opacity: 0; animation: cn-up .6s var(--cn-ease) forwards; }
.cn-lg-lista li:nth-child(1){animation-delay:.5s} .cn-lg-lista li:nth-child(2){animation-delay:.7s} .cn-lg-lista li:nth-child(3){animation-delay:.9s}
.cn-lg-lista .cn-ico-box { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.2); color: var(--cn-accent-2); }
/* demonstração viva: texto antigo é taxado e a nova redação surge */
.cn-demo { margin-top: 1.7rem; background: #fff; color: #1f2937; border-radius: 14px; padding: 1rem 1.1rem; font-family: 'Times New Roman', Georgia, serif; font-size: .92rem; line-height: 1.55; box-shadow: 0 24px 40px -20px rgba(0,0,0,.6); transform: rotate(-1.2deg); animation: cn-float 7s ease-in-out infinite; max-width: 430px; }
.cn-demo .t { font-family: var(--cn-font); font-size: .68rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #64748b; margin-bottom: .35rem; }
.cn-demo .velho { position: relative; display: inline; color: #1f2937; animation: cn-velho 7s infinite; }
.cn-demo .velho::after { content: ""; position: absolute; left: 0; right: 0; top: 52%; height: 2px; background: #dc2626; transform-origin: left; transform: scaleX(0); animation: cn-taxa 7s infinite; }
.cn-demo .novo { display: block; margin-top: .35rem; color: #1f2937; opacity: 0; animation: cn-novo 7s infinite; }
.cn-demo .nota { color: #dc2626; font-size: .8rem; }
@keyframes cn-taxa { 0%,12% { transform: scaleX(0); } 28%,88% { transform: scaleX(1); } 100% { transform: scaleX(0); } }
@keyframes cn-velho { 0%,12% { color: #1f2937; } 28%,88% { color: #dc2626; } 100% { color: #1f2937; } }
@keyframes cn-novo { 0%,32% { opacity: 0; transform: translateY(6px); } 44%,88% { opacity: 1; transform: none; } 100% { opacity: 0; } }
.st-key-login_right { padding: 2.4rem 2.2rem 2rem; }
.cn-lg-saud { font-family: var(--cn-serif); font-size: 2rem; font-weight: 600; color: var(--cn-ink); margin: 0 0 .2rem; line-height: 1.1; }
.cn-lg-saud + p { color: var(--cn-muted); margin: 0 0 1.2rem; }
.cn-seguro { display: flex; align-items: center; gap: .5rem; font-size: .78rem; color: var(--cn-muted); margin-top: .9rem; }

/* ---------- usuários ---------- */
.cn-usr { display: flex; align-items: center; gap: .85rem; }
.cn-usr .cn-avatar { width: 46px; height: 46px; font-size: 1rem; }
.cn-forca { height: 8px; border-radius: 99px; background: var(--cn-line); overflow: hidden; margin: .1rem 0 .3rem; }
.cn-forca > span { display: block; height: 100%; border-radius: 99px; transform-origin: left; animation: cn-grow .5s var(--cn-ease) both; }

.st-key-cn_cookie { position: absolute; width: 0; height: 0; overflow: hidden; margin: 0; padding: 0; }
.cn-rodape { text-align: center; color: var(--cn-muted); font-size: .78rem; margin-top: 2.4rem; opacity: .85; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; animation-delay: 0s !important; transition-duration: .001ms !important; scroll-behavior: auto !important; }
  .cn-demo .velho::after { transform: scaleX(1); } .cn-demo .novo { opacity: 1; }
}
@media (max-width: 900px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: .6rem .8rem 3rem !important; }
  .cn-hero { padding: 1.4rem 1.2rem; border-radius: 18px; } .st-key-login_left { min-height: 0; } .cn-demo { display: none; }
  .st-key-topbar { position: static; }
}
"""


def aplicar_tema():
    """Injeta o design system. Chamar uma vez por execução de página (idempotente)."""
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- componentes
def logo(tam=42):
    return f'<span class="cn-logo" style="width:{tam}px;height:{tam}px">{icone("scale", int(tam*0.55), espessura=1.8)}</span>'


def marca(subtitulo="Normas e Atos"):
    return f'<div class="cn-brand">{logo()}<div><b>Autopilot Normativo</b><small>{escape(subtitulo)}</small></div></div>'


def hero(titulo, descricao="", etiqueta="", icone_nome="sparkles"):
    eti = f'<span class="cn-hero-eyebrow">{icone(icone_nome, 14)} {escape(etiqueta)}</span>' if etiqueta else ""
    st.markdown(
        f'<section class="cn-hero"><div class="cn-grade"></div>{eti}<h1>{escape(titulo)}</h1>'
        f'{f"<p>{escape(descricao)}</p>" if descricao else ""}</section>', unsafe_allow_html=True)


def fluxo(passos, atual):
    """passos: lista de rótulos; atual: índice (0-based) do passo em andamento (len(passos) = tudo concluído)."""
    itens = []
    for i, p in enumerate(passos):
        cls = "feito" if i < atual else ("atual" if i == atual else "")
        conteudo = icone("check", 16, espessura=2.6) if i < atual else str(i + 1)
        itens.append(f'<div class="cn-passo {cls}"><i>{conteudo}</i><span>{escape(p)}</span></div>')
    st.markdown(f'<nav class="cn-fluxo" aria-label="Etapas do fluxo">{"".join(itens)}</nav>', unsafe_allow_html=True)


def kpis(itens):
    """itens: lista de (rotulo, valor|None, icone, tom) com tom em {'', 'ok', 'warn', 'info', 'rosa'}."""
    blocos = []
    for rot, val, ic, tom in itens:
        if val is None:
            num = '<span class="cn-num" style="--cn-alvo:0">&mdash;</span>'
            sr = ""
        else:
            num = f'<span class="cn-num" aria-hidden="true" style="--cn-alvo:{int(val)}"></span><span style="position:absolute;left:-9999px">{int(val)}</span>'
        blocos.append(f'<div class="cn-kpi {tom}"><span class="cn-kpi-ico">{icone(ic, 20)}</span>{num}<div class="cn-rot">{escape(rot)}</div></div>')
    st.markdown(f'<div class="cn-kpis">{"".join(blocos)}</div>', unsafe_allow_html=True)


def cartao(titulo, corpo_html, tom="", dica="", badge=""):
    d = f'<div class="cn-dica">{dica}</div>' if dica else ""
    b = f' <span class="cn-badge {tom}">{escape(badge)}</span>' if badge else ""
    st.markdown(f'<div class="cn-card {tom}"><h5>{titulo}{b}</h5>{corpo_html}{d}</div>', unsafe_allow_html=True)


def badge(texto, tom="", pulso=False):
    dot = '<span class="cn-dot"></span>' if pulso else ""
    return f'<span class="cn-badge {tom}">{dot}{escape(texto)}</span>'


def vazio(titulo, texto="", icone_nome="inbox"):
    st.markdown(f'<div class="cn-vazio">{icone(icone_nome, 44, espessura=1.4)}<b>{escape(titulo)}</b><span>{escape(texto)}</span></div>', unsafe_allow_html=True)


def iniciais(nome):
    partes = [p for p in (nome or "?").replace(".", " ").replace("_", " ").split() if p]
    return (partes[0][0] + (partes[1][0] if len(partes) > 1 else "")).upper() if partes else "?"


def avatar(nome):
    return f'<span class="cn-avatar" title="{escape(nome)}">{escape(iniciais(nome))}</span>'


def forca_senha(senha):
    """(0-100, rótulo, cor) - apenas orientação visual; a regra mínima é validada no cadastro."""
    pts = 0
    pts += 25 if len(senha) >= 8 else (10 if len(senha) >= 6 else 0)
    pts += 15 if len(senha) >= 12 else 0
    pts += 20 if any(c.islower() for c in senha) and any(c.isupper() for c in senha) else 0
    pts += 20 if any(c.isdigit() for c in senha) else 0
    pts += 20 if any(not c.isalnum() for c in senha) else 0
    pts = min(pts, 100)
    if pts < 40:
        return pts, "Fraca", "#C81E3A"
    if pts < 70:
        return pts, "Razoável", "#B45309"
    return pts, "Forte", "#0F8F5F"


def barra_forca(senha):
    if not senha:
        return
    pts, rot, cor = forca_senha(senha)
    st.markdown(f'<div class="cn-forca" role="img" aria-label="Força da senha: {rot}"><span style="width:{max(pts,6)}%;background:{cor}"></span></div>'
                f'<div style="font-size:.78rem;color:{cor};font-weight:700">Senha {rot.lower()}</div>', unsafe_allow_html=True)
