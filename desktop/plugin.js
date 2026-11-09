// Psychopomp — the Desktop half: one page that explains itself, sets itself up, and can rehearse
// the whole passage on a virtual clock. Built from the app's own UI kit; talks only to its own
// backend (dashboard/plugin_api.py) through ctx.rest.
import {
  Badge, Button, Codicon, CopyButton, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
  DialogTitle, Input, Loader, ROUTES_AREA, SIDEBAR_NAV_AREA, SandboxedFrame, StatusDot, Switch, Textarea,
  TRANSCRIPT_DIRECTIVE_AREA, host
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'psychopomp'
const PATH = '/psychopomp'
const DAY = 86400

// h('div', {className}, child, child): JSX without a compiler. Falsy children are dropped.
const h = (tag, props, ...kids) => {
  const children = kids.flat().filter(k => k !== null && k !== undefined && k !== false && k !== '')
  return (children.length > 1 ? jsxs : jsx)(tag, { ...(props || {}), children: children.length > 1 ? children : children[0] })
}

// The caduceus, Hermes' staff. Strokes only, so it takes any theme colour.
const CADUCEUS = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="2.9" r="1.3"/><path d="M12 4.3V22"/><path d="M11 6.2C8.6 4.6 5.6 4.4 2.8 5.6c2.4.6 4.9 1.6 8.2 2.4"/><path d="M13 6.2c2.4-1.6 5.4-1.8 8.2-.6-2.4.6-4.9 1.6-8.2 2.4"/><path d="M9.2 9.4c4.6 0 6.2 1.2 6.2 2.6s-6.8 1.4-6.8 3.4 3.6 2.4 5.8 2.4"/><path d="M14.8 9.4c-4.6 0-6.2 1.2-6.2 2.6s6.8 1.4 6.8 3.4-3.6 2.4-5.8 2.4"/></svg>'
const CADUCEUS_URL = `url("data:image/svg+xml,${encodeURIComponent(CADUCEUS)}")`
// ponytail: the sidebar only takes codicon names, so `codicon-psychopomp` is drawn by this mask rule.
const NAV_CSS = `.codicon.codicon-psychopomp::before{content:"";display:inline-block;width:1em;height:1em;background:currentColor;-webkit-mask:${CADUCEUS_URL} center/contain no-repeat;mask:${CADUCEUS_URL} center/contain no-repeat}`

const CSS = `
.psy{container-type:inline-size;max-width:1000px;margin:0 auto;padding:32px clamp(1.25rem,4vw,4rem) 80px;color:var(--ui-text-primary);font-size:13px;line-height:1.55}
.psy *{box-sizing:border-box}
.psy .mark{width:44px;height:44px;flex:none;background:var(--ui-accent);-webkit-mask:${CADUCEUS_URL} center/contain no-repeat;mask:${CADUCEUS_URL} center/contain no-repeat}
.psy .head{display:flex;gap:16px;align-items:flex-start}
.psy .head h1{font-size:18px;font-weight:600;margin:4px 0 4px;letter-spacing:-.015em}
.psy .lede{color:var(--ui-text-secondary);font-size:13.5px;max-width:660px;margin:0}
.psy .why{margin:10px 0 0;padding:10px 14px;border-left:2px solid var(--ui-accent);color:var(--ui-text-secondary);max-width:660px;background:color-mix(in srgb,var(--ui-accent) 6%,transparent);border-radius:0 6px 6px 0}
.psy .why b{color:var(--ui-text-primary);font-weight:600}
.psy .pill{margin-left:auto;display:inline-flex;gap:8px;align-items:center;color:var(--ui-text-secondary);white-space:nowrap;font-size:12px;padding-top:6px}
.psy .card{border-top:1px solid var(--ui-stroke-tertiary);padding-top:20px;margin-top:32px}
.psy .label{font-size:11px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--ui-text-tertiary)}
.psy .row{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.psy .muted{color:var(--ui-text-tertiary)}
.psy .sec{color:var(--ui-text-secondary)}
.psy .small{font-size:12px}
/* the passage */
.psy .path{position:relative;display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:22px 0 4px}
.psy .rail{position:absolute;top:18px;left:10%;right:10%;height:2px;background:var(--ui-stroke-tertiary)}
.psy .rail>i{display:block;height:100%;background:var(--ui-accent);transition:width .5s ease}
.psy .st{position:relative;text-align:center;padding:0 4px}
.psy .node{width:38px;height:38px;margin:0 auto 10px;border-radius:50%;display:grid;place-items:center;font-size:16px;border:1.5px solid var(--ui-stroke-secondary);background:var(--ui-bg-editor,var(--ui-bg-primary));color:var(--ui-text-tertiary);transition:all .35s}
.psy .st[data-s=done] .node{border-color:var(--ui-accent);color:var(--ui-accent)}
.psy .st[data-s=now] .node{border-color:var(--ui-accent);background:var(--ui-accent);color:var(--ui-bg-editor,var(--ui-bg-primary));box-shadow:0 0 0 5px color-mix(in srgb,var(--ui-accent) 22%,transparent);animation:psy-glow 2.4s ease-in-out infinite}
@keyframes psy-glow{50%{box-shadow:0 0 0 9px color-mix(in srgb,var(--ui-accent) 8%,transparent)}}
.psy .st h4{margin:0;font-size:12.5px;font-weight:600}
.psy .st[data-s=next] h4{color:var(--ui-text-secondary)}
.psy .st p{margin:3px 0 0;font-size:11.5px;color:var(--ui-text-tertiary);line-height:1.45}
.psy .here{display:inline-block;margin-top:6px;font-size:10.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--ui-accent)}
.psy .promise{display:flex;gap:8px;align-items:center;margin-top:18px;color:var(--ui-text-tertiary);font-size:12px}
/* rehearsal */
.psy .theater{margin-top:22px}
.psy .clock{display:flex;align-items:baseline;gap:12px}
.psy .clock .d{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.psy .feed{margin-top:12px;max-height:340px;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px}
.psy .ev{display:grid;grid-template-columns:58px 1fr;gap:10px;align-items:start;animation:psy-in .35s ease}
@keyframes psy-in{from{opacity:0;transform:translateY(4px)}}
.psy .ev .day{font-size:11px;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums;padding-top:5px}
.psy .bub{border-left:2px solid var(--ui-stroke-secondary);padding:4px 0 4px 12px}
.psy .bub .to{display:flex;gap:6px;align-items:center;font-size:11px;font-weight:600;color:var(--ui-text-secondary);margin-bottom:2px}
.psy .bub[data-k=note],.psy .bub[data-k=start]{border-left-color:transparent;color:var(--ui-text-tertiary);font-style:italic}
.psy .bub[data-k=code]{border-left-color:var(--ui-accent)}
.psy .bub[data-k=book],.psy .bub[data-k=letter]{border-left-color:var(--ui-accent)}
.psy .bub[data-k=done]{border-left-color:var(--ui-green)}
.psy .bub[data-k=error]{border-left-color:var(--ui-red)}
@media (prefers-reduced-motion:reduce){.psy *{animation:none!important;transition:none!important}}
/* setup */
.psy .steps{margin-top:12px;display:flex;flex-direction:column}
.psy .step{display:grid;grid-template-columns:24px 1fr auto;gap:12px;align-items:center;padding:8px 0}
.psy .tick{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font-size:11px;border:1.5px solid var(--ui-stroke-secondary);color:var(--ui-text-tertiary)}
.psy .step[data-done=true] .tick{border-color:var(--ui-green);background:var(--ui-green);color:var(--ui-bg-editor,var(--ui-bg-primary))}
.psy .step[data-done=true] .t{color:var(--ui-text-tertiary);text-decoration:line-through}
.psy .step .t{font-weight:500}
.psy .meter{height:3px;border-radius:2px;background:var(--ui-stroke-tertiary);overflow:hidden;width:120px}
.psy .meter>i{display:block;height:100%;background:var(--ui-green)}
/* book + letters */
.psy .two{display:grid;grid-template-columns:1.25fr 1fr}
@container (max-width:780px){.psy .two{grid-template-columns:1fr}}
@container (max-width:620px){.psy .path{grid-template-columns:1fr;gap:14px}.psy .rail{display:none}.psy .st{display:grid;grid-template-columns:38px 1fr;text-align:left;gap:12px}.psy .node{margin:0}}
.psy .two{gap:0 48px}
.psy .serif{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
.psy .pages{margin-top:12px;display:flex;flex-direction:column;gap:2px}
.psy .pg{display:grid;grid-template-columns:62px 1fr;gap:12px;align-items:baseline;padding:8px 10px;margin:0 -10px;border-radius:6px;cursor:pointer;text-align:left;background:none;border:none;color:inherit;font:inherit;width:calc(100% + 20px)}
.psy .pg:hover{background:var(--ui-row-hover-background,color-mix(in srgb,var(--ui-text-primary) 5%,transparent))}
.psy .pg .when{font-size:11px;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums}
.psy .pg .ttl{font-size:14.5px}
.psy .pg .ex{font-size:12px;color:var(--ui-text-tertiary);display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden}
.psy .empty{margin-top:12px;color:var(--ui-text-tertiary);font-size:12.5px;max-width:520px}
.psy .empty b{display:block;color:var(--ui-text-secondary);font-weight:600;margin-bottom:2px}
.psy .envs{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-top:12px}
.psy .env{position:relative;aspect-ratio:1.55;border-radius:6px;border:1px solid var(--ui-stroke-secondary);background:color-mix(in srgb,var(--ui-text-primary) 4%,transparent);overflow:hidden}
.psy .env:before{content:"";position:absolute;inset:0 0 auto 0;height:56%;background:color-mix(in srgb,var(--ui-text-primary) 7%,transparent);clip-path:polygon(0 0,100% 0,50% 100%)}
.psy .wax{position:absolute;left:50%;top:50%;transform:translate(-50%,-62%);width:28px;height:28px;border-radius:50%;background:var(--ui-accent);display:grid;place-items:center;box-shadow:0 0 0 3px color-mix(in srgb,var(--ui-accent) 28%,transparent)}
.psy .wax>i{width:16px;height:16px;background:var(--ui-bg-editor,var(--ui-bg-primary));-webkit-mask:${CADUCEUS_URL} center/contain no-repeat;mask:${CADUCEUS_URL} center/contain no-repeat}
.psy .env[data-done=true] .wax{background:var(--ui-green)}
.psy .env .who{position:absolute;left:10px;right:24px;bottom:20px;font-weight:600;font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.psy .env .via{position:absolute;left:10px;right:24px;bottom:5px;font-size:10.5px;color:var(--ui-text-tertiary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.psy .env .x{position:absolute;right:2px;bottom:2px}
.psy .yr{margin-top:14px}
.psy .yr .grid{display:grid;grid-template-columns:repeat(26,1fr);gap:4px;max-width:560px}
.psy .wk{aspect-ratio:1;border-radius:2px;border:none;padding:0;font-size:0;background:color-mix(in srgb,var(--ui-text-primary) 7%,transparent)}
.psy .wk[data-s=future]{background:color-mix(in srgb,var(--ui-text-primary) 3.5%,transparent)}
.psy .wk[data-s=page]{background:var(--ui-accent);cursor:pointer}
.psy .wk[data-s=page]:hover{outline:2px solid color-mix(in srgb,var(--ui-accent) 45%,transparent)}
.psy .wk[data-s=now]{box-shadow:inset 0 0 0 1.5px var(--ui-accent);background:transparent}
.psy .log{margin:10px 0 0;padding:0;list-style:none;font-size:12px;color:var(--ui-text-secondary)}
.psy .log li{display:grid;grid-template-columns:130px 1fr;gap:10px;padding:3px 0}
.psy-dlg .serif{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
.psy-dlg .page{white-space:pre-wrap;font-size:15px;line-height:1.7;max-height:60vh;overflow:auto;color:var(--ui-text-primary)}
.psy-dlg .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.psy-dlg .stack{display:flex;flex-direction:column;gap:8px}
.psy-dlg .quote{white-space:pre-wrap;padding:12px;border-radius:6px;border:1px solid var(--ui-stroke-tertiary);font-size:12.5px;color:var(--ui-text-secondary)}
`

const fmtDate = (ts, o = { day: 'numeric', month: 'short' }) => (ts ? new Date(ts * 1000).toLocaleDateString(undefined, o) : '')
const ago = days => (days < 1 / 24 ? 'just now' : days < 1 ? `${Math.round(days * 24)} h ago` : `${Math.floor(days)} day${Math.floor(days) === 1 ? '' : 's'} ago`)
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
const errText = e => String(e?.message || e)
// ISO week, as the Book names its pages ("Week 46 · 2026").
function isoWeek(ts) {
  const d = new Date(ts * 1000), t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()))
  const day = t.getUTCDay() || 7
  t.setUTCDate(t.getUTCDate() + 4 - day)
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1))
  return { year: t.getUTCFullYear(), week: Math.ceil(((t - y0) / 86400000 + 1) / 7) }
}
const weekName = ts => { const w = isoWeek(ts); return `Week ${w.week}` }

// Where in the passage a state stands: 0 live · 1 silence · 2 check-ins · 3 trusted · 4 carried.
function stageOf(phase, silentDays, silence) {
  if (phase === 'delivered') return 4
  if (phase === 'awaiting_trusted') return 3
  if (phase === 'checking_in') return 2
  return silentDays >= 1 && silentDays / silence > 0.2 ? 1 : 0
}

function Passage({ s, reh }) {
  const silence = s.silence_days
  const trusted = s.trusted.name || 'Someone you trust'
  const live = reh || null
  const silent = live ? live.day : s.silent_days
  const phase = live ? (live.status === 'done' ? 'delivered' : live.phase) : s.phase
  const resting = !live && !s.armed && s.phase !== 'delivered'
  const stage = resting ? -1 : stageOf(phase, silent, silence)
  const fill = stage < 0 ? 0 : stage >= 1 ? Math.min(100, stage * 25) : Math.min(25, (silent / silence) * 25)
  const st = [
    { icon: 'book', t: 'You live', p: 'Talk to Hermes as usual. Each week you write a page of your Book together.' },
    { icon: 'watch', t: `${silence} days of silence`, p: 'Not a word to Hermes, on any channel. Hermes going offline doesn’t count.' },
    { icon: 'bell', t: `${s.checkins} check-ins`, p: `Hermes writes to you, ${s.checkin_every_days} days apart. One word from you resets everything.` },
    { icon: 'key', t: 'Your witness', p: `${trusted} is asked for a one-time code. Without a person, nothing moves.` },
    { icon: 'heart', t: 'Carried', p: 'Your Book reaches your family and friends; each letter, its person.' }
  ]
  return h('div', { className: 'path' },
    h('div', { className: 'rail' }, h('i', { style: { width: `${fill}%` } })),
    st.map((x, i) => jsxs('div', {
      className: 'st', 'data-s': i < stage ? 'done' : i === stage ? 'now' : 'next', children: [
        h('div', { className: 'node' }, jsx(Codicon, { name: x.icon })),
        h('div', null, h('h4', null, x.t), h('p', null, x.p),
          i === stage ? h('span', { className: 'here' }, live ? `Rehearsal · day ${live.day}` : i === 0 ? 'You are here' : 'Now') : null)
      ]
    }, x.icon)))
}

const EV_ICON = { message: 'comment', code: 'key', letter: 'mail', book: 'book', done: 'pass', error: 'error' }

function Theater({ s, reh, busy, onStart, onStop, onConfirm, onClose }) {
  const feed = useRef(null)
  const [mirror, setMirror] = useState(false)
  useEffect(() => { if (feed.current) feed.current.scrollTop = feed.current.scrollHeight }, [reh?.events?.length])
  const canMirror = s.owner.channels.length > 0
  if (!reh || reh.idle) {
    return h('div', { className: 'theater' },
      h('div', { className: 'row' },
        h('div', { style: { maxWidth: 560 } },
          h('div', { style: { fontWeight: 600 } }, 'Rehearse the passage'),
          h('div', { className: 'sec small' },
            `Psychopomp only acts after ${s.silence_days}+ days, so watch it here instead: Hermes copies your setup and runs the real code on a virtual clock, a day every few seconds. ` +
            'Every message it would send appears below. Nothing leaves, nothing is unsealed, and your real switch doesn’t move.')),
        h('div', { className: 'row', style: { gap: 14 } },
          canMirror ? h('label', { className: 'row small sec', style: { gap: 8, cursor: 'pointer' } },
            jsx(Switch, { checked: mirror, onCheckedChange: setMirror }), 'Also send each step to my phone') : null,
          jsx(Button, { variant: 'ghost', onClick: onClose, children: 'Cancel' }),
          jsx(Button, { disabled: busy, onClick: () => onStart(mirror), children: [jsx(Codicon, { name: 'play' }, 'i'), 'Start'] }))))
  }
  const date = fmtDate(reh.started_at + reh.day * DAY, { weekday: 'short', day: 'numeric', month: 'short' })
  const running = reh.status === 'running'
  const trusted = s.trusted.name || 'your witness'
  return h('div', { className: 'theater' },
    h('div', { className: 'row' },
      h('div', { className: 'clock' },
        h('span', { className: 'd' }, `Day ${reh.day}`),
        h('span', { className: 'sec' }, `${date} · virtual clock`),
        jsx(Badge, { variant: reh.status === 'done' ? 'success' : 'default', children: { running: 'Rehearsing', awaiting_code: 'Waiting for the code', done: 'The chain works', stopped: 'Stopped', failed: 'Stalled' }[reh.status] || reh.status })),
      running || reh.status === 'awaiting_code'
        ? jsx(Button, { variant: 'ghost', onClick: onStop, children: 'Stop' })
        : h('div', { className: 'row', style: { gap: 6 } },
          jsx(Button, { variant: 'ghost', onClick: onClose, children: 'Close' }),
          jsx(Button, { variant: 'secondary', onClick: () => onStart(reh.mirror), children: 'Play again' }))),
    h('div', { className: 'feed', ref: feed },
      reh.events.map((e, i) => jsxs('div', {
        className: 'ev', children: [
          h('div', { className: 'day' }, `Day ${e.day}`),
          jsxs('div', {
            className: 'bub', 'data-k': e.kind, children: [
              e.kind !== 'note' && e.kind !== 'start' ? h('div', { className: 'to' }, jsx(Codicon, { name: EV_ICON[e.kind] || 'comment' }),
                e.kind === 'message' ? `Hermes → ${e.to}` : e.kind === 'letter' ? `Sealed letter → ${e.to}` : e.kind === 'book' ? `Your Book → ${e.to}` : e.kind === 'code' ? `Your turn: play ${trusted}` : e.kind === 'done' ? 'Rehearsal complete' : 'Problem') : null,
              h('div', { className: e.kind === 'book' || e.kind === 'letter' ? 'serif' : '' }, e.text),
              e.kind === 'code' && reh.status === 'awaiting_code' && reh.code
                ? h('div', { style: { marginTop: 8 } }, jsx(Button, { disabled: busy, onClick: () => onConfirm(reh.code), children: `Send ${reh.code} as ${trusted}` }))
                : null
            ]
          })
        ]
      }, i)),
      running ? h('div', { className: 'ev' }, h('div', { className: 'day' }, '…'), h('div', { className: 'muted small', style: { paddingTop: 5 } }, 'Time passes. Quiet days fly by.')) : null))
}

// Your year in weeks: one cell per week, gold where a page was written. Click a gold week to read it.
function YearGrid({ pages, onOpen }) {
  const now = isoWeek(Date.now() / 1000)
  const byWeek = {}
  for (const p of pages) { const w = isoWeek(p.written_at); if (w.year === now.year && p.kind !== 'year') byWeek[w.week] = p }
  const written = Object.keys(byWeek).length
  const cells = []
  for (let w = 1; w <= 52; w++) {
    const p = byWeek[w]
    cells.push(jsx('button', {
      className: 'wk', 'data-s': p ? 'page' : w === now.week ? 'now' : w < now.week ? 'past' : 'future',
      'aria-label': p ? `Week ${w}: ${p.title}` : `Week ${w}`, disabled: !p, onClick: () => p && onOpen(p)
    }, w))
  }
  return h('div', { className: 'yr' },
    h('div', { className: 'grid' }, cells),
    h('div', { className: 'small muted', style: { marginTop: 6 } }, `${now.year} · ${plural(written, 'week')} written of ${now.week} so far`))
}

// The weekly page, drawn inside the chat when Hermes proposes it (::psychopomp-page{draft="…"}).
function PageCard({ ctx, attrs, sessionId }) {
  const [s, setS] = useState(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => ctx.rest('/state').then(setS).catch(() => setS({ error: true })), [ctx])
  useEffect(() => { load(); return host.onEvent(`plugin.${ID}.state.changed`, load) }, [load])
  if (!s) return null
  const draft = attrs.draft && s.book?.drafts?.[attrs.draft]
  const page = draft?.page_id ? s.book.pages.find(p => p.id === draft.page_id) : attrs.page ? s.book?.pages?.find(p => p.id === attrs.page) : null
  const shown = page || draft
  if (!shown) return h('div', { className: 'psy-card muted small' }, 'This page is no longer here.')
  const ts = shown.written_at || shown.drafted_at
  const approve = async () => {
    setBusy(true)
    try { await ctx.rest('/page/approve', { method: 'POST', body: { draft: attrs.draft } }); await load() }
    catch (e) { host.notifyError?.(e, 'Could not add the page') } finally { setBusy(false) }
  }
  return h('div', { className: 'psy-card' },
    h('style', null, CARD_CSS),
    h('div', { className: 'pc-head' }, h('i', { className: 'pc-mark' }),
      h('span', null, shown.kind === 'year' ? 'Year in review' : `${weekName(ts)} · a page of your Book`),
      page ? jsx(Badge, { variant: 'success', children: 'In your Book' }) : jsx(Badge, { children: 'Draft' })),
    h('div', { className: 'pc-title' }, shown.title),
    h('div', { className: 'pc-text' }, shown.text),
    page ? null : h('div', { className: 'pc-actions' },
      jsx(Button, { disabled: busy, onClick: approve, children: [jsx(Codicon, { name: 'book' }, 'i'), 'Add to my Book'] }),
      jsx(Button, { variant: 'ghost', onClick: () => host.composer.insertText(sessionId ?? null, 'Change the page: ', { mode: 'inline' }), children: 'Change something' })))
}

const CARD_CSS = `
.psy-card{max-width:620px;margin:6px 0;padding:18px 20px;border-left:2px solid var(--ui-accent);background:color-mix(in srgb,var(--ui-accent) 5%,transparent);border-radius:0 8px 8px 0;color:var(--ui-text-primary)}
.psy-card .pc-head{display:flex;gap:8px;align-items:center;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ui-text-tertiary)}
.psy-card .pc-mark{width:14px;height:14px;background:var(--ui-accent);-webkit-mask:${CADUCEUS_URL} center/contain no-repeat;mask:${CADUCEUS_URL} center/contain no-repeat}
.psy-card .pc-title{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-size:21px;margin:8px 0 6px}
.psy-card .pc-text{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-size:15px;line-height:1.7;white-space:pre-wrap;color:var(--ui-text-secondary)}
.psy-card .pc-actions{display:flex;gap:8px;margin-top:14px}
`

function Setup({ s, rehearsed, act }) {
  const steps = [
    { done: s.owner.channels.length > 0, t: 'Tell Hermes where to reach you', p: 'From your phone, send /psychopomp here to your Hermes (Telegram, WhatsApp, Signal…). That chat is where your weekly page and any check-ins arrive.', copy: '/psychopomp here' },
    { done: s.trusted.channels.length > 0, t: 'Choose your witness', p: 'The one person who confirms, if it ever comes to that. They send a code to your Hermes once: no app, no account.', b: s.invite_pending ? 'New invitation' : 'Invite', on: act.invite },
    { done: s.book.pages.length > 0, t: 'Write the first page of your Book', p: 'Ten minutes with Hermes, looking back at your week. It drafts; you approve.', b: 'Write with Hermes', on: act.writePage },
    { done: rehearsed, t: 'Rehearse the passage', p: 'Watch the whole chain run in 20 seconds, safely.', b: 'Rehearse', on: act.rehearse },
    { done: s.armed, t: 'Let Hermes keep watch', p: 'From then on, every word you say to Hermes, anywhere, is a heartbeat.', b: 'Keep watch', on: act.arm }
  ]
  const n = steps.filter(x => x.done).length
  if (n === steps.length) return null
  return h('div', { className: 'card' },
    h('div', { className: 'row' },
      h('span', { className: 'label' }, 'Get started · five minutes'),
      h('div', { className: 'row small muted', style: { gap: 10 } }, `${n} of ${steps.length}`,
        h('div', { className: 'meter' }, h('i', { style: { width: `${(n / steps.length) * 100}%` } })))),
    h('div', { className: 'steps' },
      steps.map((x, i) => jsxs('div', {
        className: 'step', 'data-done': String(x.done), children: [
          h('div', { className: 'tick' }, x.done ? '✓' : String(i + 1)),
          h('div', null, h('div', { className: 't' }, x.t), x.done ? null : h('div', { className: 'small muted' }, x.p)),
          x.done ? h('span') : x.copy
            ? jsx(CopyButton, { text: x.copy, label: `Copy ${x.copy}`, buttonVariant: i === steps.findIndex(y => !y.done) ? 'default' : 'secondary' })
            : jsx(Button, { size: 'sm', variant: i === steps.findIndex(y => !y.done) ? 'default' : 'secondary', onClick: x.on, children: x.b })
        ]
      }, i))))
}

function Page({ ctx }) {
  const [s, setS] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [why, setWhy] = useState(false)
  const [theater, setTheater] = useState(false) // false · 'intro' · 'live'
  const [page, setPage] = useState(null)
  const [writing, setWriting] = useState(false)
  const [inviteCode, setInviteCode] = useState('')
  const [inviting, setInviting] = useState(false)
  const [witness, setWitness] = useState('')
  const [bookHtml, setBookHtml] = useState('')
  const [showLog, setShowLog] = useState(false)
  const [draft, setDraft] = useState({ to_name: '', to_target: '', subject: '', body: '' })

  const load = useCallback(() => ctx.rest('/state').then(v => { setS(v); setErr('') }).catch(e => setErr(errText(e))), [ctx])
  const rehearsing = s?.rehearsal?.status === 'running'
  useEffect(() => {
    load()
    const stop = ctx.setInterval(load, rehearsing ? 700 : 5000)
    const off = host.onEvent(`plugin.${ID}.state.changed`, load)
    return () => { stop && stop(); off && off() }
  }, [load, rehearsing])

  const post = async (path, body = {}) => {
    setBusy(true)
    try { const r = await ctx.rest(path, { method: 'POST', body }); await load(); return r }
    catch (e) { host.notifyError ? host.notifyError(e, 'Psychopomp could not reach Hermes') : setErr(errText(e)); return null }
    finally { setBusy(false) }
  }

  // Hand a prompt to a fresh chat: the user reads it, edits it if they like, and presses Enter.
  const askHermes = async text => {
    ctx.runAction?.('session.new')
    for (let i = 0; i < 12; i++) {
      await new Promise(r => setTimeout(r, 150))
      if (await host.composer.setDraft('new', text).catch(() => false)) { host.composer.focus('new'); return }
    }
    if (await host.composer.insertText(null, text, { mode: 'block' }).catch(() => false)) return
    host.notify?.({ kind: 'info', message: `Ask Hermes: “${text}”` })
  }

  const act = {
    invite: () => { setWitness(s?.trusted?.name || ''); setInviting(true) },
    openBook: async () => { try { const r = await ctx.rest('/book'); setBookHtml(r.html) } catch (e) { host.notifyError?.(e, 'Could not open your Book') } },
    writePage: () => askHermes(s?.book?.due === 'year' ? "Let's write my year in review for my Book." : "Let's write this week's page of my Book."),
    rehearse: () => { setTheater('intro'); document.querySelector('.psy-top')?.scrollIntoView({ behavior: 'smooth' }) },
    arm: () => post('/arm', { armed: true })
  }

  if (!s) return h('div', { className: 'psy' }, h('style', null, CSS), err ? h('p', { className: 'muted' }, err) : jsx(Loader, { label: 'Psychopomp' }))

  const reh = s.rehearsal
  const active = reh && (reh.status === 'running' || reh.status === 'awaiting_code')
  const showReh = !!theater || active
  const liveReh = (theater === 'live' || active) && reh && reh.status !== 'stopped' ? reh : null
  const rehearsed = (s.log || []).some(e => /Rehearsal complete/.test(e.text)) || reh?.status === 'done'
  const pages = s.book.pages.slice().reverse()
  const trusted = s.trusted.name || 'your witness'
  const status = s.phase === 'delivered' ? ['good', 'Carried'] : !s.armed ? ['muted', 'Resting'] :
    s.phase === 'watching' ? ['good', `Keeping watch · last heard ${ago(s.silent_days)}`] :
      s.phase === 'checking_in' ? ['warn', `Checking in (${s.checkins_sent} of ${s.checkins})`] : ['bad', `Waiting for ${trusted}`]
  const inviteText = inviteCode
    ? `${witness ? witness + ', I' : 'I'}'d like you to be my witness in Psychopomp. If I ever go silent for a long time, my Hermes (my AI assistant) will ask you to confirm before it passes on what I've left for the people I love: a Book of my life, and a few letters.\n\nTo accept, send this to my Hermes${s.owner.channels[0]?.startsWith('telegram:') ? ' bot on Telegram' : ''}:\n\n${inviteCode}`
    : ''

  return h('div', { className: 'psy' },
    h('style', null, CSS),

    // Header: what it is, in one breath, and why the name.
    h('div', { className: 'head psy-top' },
      h('div', { className: 'mark', role: 'img', 'aria-label': 'Caduceus' }),
      h('div', { style: { flex: 1 } },
        h('div', { className: 'row', style: { alignItems: 'flex-start' } },
          h('h1', null, 'Psychopomp'),
          h('span', { className: 'pill' }, jsx(StatusDot, { tone: status[0] }), status[1])),
        h('p', { className: 'lede' },
          'Every week, Hermes helps you write a page of your life: your Book. You can also seal letters to the people you love. ' +
          'If you ever go silent for good, Hermes makes sure both reach them.'),
        jsx(Button, { variant: 'text', size: 'inline', onClick: () => setWhy(!why), style: { marginTop: 6 }, children: why ? 'Why “psychopomp”? ▴' : 'Why “psychopomp”? ▾' }),
        why ? h('div', { className: 'why small' },
          'In Greek myth, Hermes had two jobs. He was the ', h('b', null, 'messenger'), ' of the gods, and he was the ',
          h('b', null, 'psychopomp'), ' (from the Greek ', h('i', null, 'psychopompós'), ', “guide of souls”): the companion who walked beside every person to the threshold, so no one made that journey alone. ',
          'Your Hermes already carries your messages. This gives it the second, gentler job: keeping your story while you live it, and carrying your words to the people you love when you no longer can.')
          : null)),

    // The passage: how it works, where you are, and the rehearsal stage.
    h('div', { className: 'card' },
      h('div', { className: 'row' },
        h('span', { className: 'label' }, 'How it works'),
        showReh ? null : jsx(Button, { variant: 'secondary', size: 'sm', onClick: act.rehearse, children: [jsx(Codicon, { name: 'play-circle' }, 'i'), 'Rehearse it in 20 seconds'] })),
      jsx(Passage, { s, reh: liveReh }),
      showReh
        ? jsx(Theater, {
          s, busy, reh: theater === 'intro' && !active ? { idle: true } : liveReh || { idle: true },
          onStart: async mirror => { const r = await post('/rehearse', { mirror }); if (r && r.started === false) host.notify?.({ kind: 'warning', message: r.message }); setTheater('live') },
          onStop: () => post('/rehearsal/stop'),
          onConfirm: code => post('/rehearsal/confirm', { code }),
          onClose: () => setTheater(false)
        })
        : h('div', { className: 'promise' }, jsx(Codicon, { name: 'shield' }),
          'Say anything to Hermes, anywhere, at any step, and everything resets. Nothing is ever carried without a person’s code.')),

    jsx(Setup, { s, rehearsed, act }),

    h('div', { className: 'two' },
      // The Book: the part you use every week.
      h('div', { className: 'card' },
        h('div', { className: 'row' },
          h('div', { className: 'row', style: { gap: 8 } }, h('span', { className: 'label' }, 'Your Book'),
            h('span', { className: 'muted small' }, plural(s.book.pages.length, 'page')),
            s.book.due ? jsx(Badge, { children: s.book.due === 'year' ? 'Year in review due' : 'This week’s page is due' }) : null),
          h('div', { className: 'row', style: { gap: 6 } },
            pages.length ? jsx(Button, { size: 'sm', variant: 'ghost', onClick: act.openBook, children: 'Open your Book' }) : null,
            jsx(Button, { size: 'sm', variant: s.book.due ? 'default' : 'secondary', onClick: act.writePage, children: [jsx(Codicon, { name: 'edit' }, 'i'), 'Write with Hermes'] }))),
        jsx(YearGrid, { pages: s.book.pages, onOpen: setPage }),
        pages.length
          ? h('div', { className: 'pages' }, pages.slice(0, 8).map(p => jsxs('button', {
            className: 'pg', onClick: () => setPage(p), children: [
              h('span', { className: 'when' }, p.kind === 'year' ? `Year ${isoWeek(p.written_at).year}` : h('span', null, weekName(p.written_at), h('br'), fmtDate(p.written_at))),
              h('span', null, h('div', { className: 'ttl serif' }, p.title), h('div', { className: 'ex' }, p.text))
            ]
          }, p.id)))
          : h('div', { className: 'empty' }, h('b', null, 'Your first page is waiting.'),
            'Once a week Hermes offers to look back with you, using what it already knows from your chats: what you did, what moved you, who you loved, what you’re grateful for. It drafts a page in your voice, and nothing is kept until you approve it. Once a year, the pages become your year in review.')),

      // Letters: sealed, carried only after the passage.
      h('div', { className: 'card' },
        h('div', { className: 'row' },
          h('div', { className: 'row', style: { gap: 8 } }, h('span', { className: 'label' }, 'Sealed letters'),
            h('span', { className: 'muted small' }, String(s.letters.length))),
          jsx(Button, { size: 'sm', variant: 'secondary', onClick: () => setWriting(true), children: [jsx(Codicon, { name: 'mail' }, 'i'), 'Write a letter'] })),
        s.letters.length
          ? h('div', { className: 'envs' }, s.letters.map(l => jsxs('div', {
            className: 'env', 'data-done': String(!!l.delivered_at), children: [
              h('div', { className: 'wax' }, h('i')),
              h('div', { className: 'who' }, `For ${l.to_name}`),
              h('div', { className: 'via' }, l.delivered_at ? `Carried ${fmtDate(l.delivered_at)}` : l.to_target ? `via ${l.to_target.split(':')[0].replace(/^./, c => c.toUpperCase())}` : `via ${trusted}`),
              !l.delivered_at ? h('div', { className: 'x' }, jsx(Button, { variant: 'ghost', size: 'icon-xs', 'aria-label': `Withdraw the letter for ${l.to_name}`, onClick: () => post('/withdraw', { id: l.id }), children: jsx(Codicon, { name: 'close' }) })) : null
            ]
          }, l.id)))
          : h('div', { className: 'empty' }, h('b', null, 'Words for the people you love.'),
            'Write them yourself or with Hermes. Once sealed, not even Hermes can read them again. Each one is carried to its person only after the passage, or handed to ' + trusted + ' to pass on.'))),

    // Activity, folded away.
    (s.log || []).length ? h('div', { style: { marginTop: 14 } },
      jsx(Button, { variant: 'text', size: 'inline', onClick: () => setShowLog(!showLog), children: showLog ? 'Hide activity ▴' : 'Activity ▾' }),
      showLog ? h('ul', { className: 'log' }, s.log.slice().reverse().map((e, i) =>
        jsxs('li', { children: [h('span', { className: 'muted' }, new Date(e.at * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })), h('span', null, e.text)] }, i))) : null) : null,
    err ? h('p', { className: 'small', style: { color: 'var(--ui-red)', marginTop: 12 } }, err) : null,

    // Dialogs
    jsx(Dialog, {
      open: !!page, onOpenChange: o => !o && setPage(null), children: page ? jsxs(DialogContent, {
        className: 'psy-dlg', style: { maxWidth: 640 }, children: [
          jsxs(DialogHeader, { children: [jsx(DialogTitle, { className: 'serif', children: page.title }), jsx(DialogDescription, { children: `${page.kind === 'year' ? 'Year in review' : weekName(page.written_at)} · ${fmtDate(page.written_at, { day: 'numeric', month: 'long', year: 'numeric' })}` })] }),
          h('div', { className: 'page serif' }, page.text)
        ]
      }) : null
    }),
    jsx(Dialog, {
      open: writing, onOpenChange: setWriting, children: jsxs(DialogContent, {
        className: 'psy-dlg', style: { maxWidth: 600 }, children: [
          jsxs(DialogHeader, { children: [jsx(DialogTitle, { children: 'Write a letter' }), jsx(DialogDescription, { children: 'Sealed the moment you finish. Not even Hermes can read it again; it is carried only after the passage.' })] }),
          h('div', { className: 'stack' },
            h('div', { className: 'grid' },
              jsx(Input, { value: draft.to_name, placeholder: 'For whom (e.g. Mum)', onChange: e => setDraft({ ...draft, to_name: e.target.value }) }),
              jsx(Input, { value: draft.subject, placeholder: 'Subject (optional)', onChange: e => setDraft({ ...draft, subject: e.target.value }) })),
            jsx(Input, { value: draft.to_target, placeholder: `Their Telegram, e.g. telegram:123456 (optional: else ${trusted} passes it on)`, onChange: e => setDraft({ ...draft, to_target: e.target.value }) }),
            jsx(Textarea, { className: 'serif', value: draft.body, rows: 9, placeholder: 'What do you want them to know?', onChange: e => setDraft({ ...draft, body: e.target.value }), style: { fontSize: 14, lineHeight: 1.6 } })),
          jsxs(DialogFooter, {
            children: [
              jsx(Button, {
                variant: 'ghost', onClick: () => {
                  setWriting(false)
                  askHermes(`Help me write a Psychopomp letter to ${draft.to_name || 'someone I love'}. Use what you know about me and about them, keep my voice, ask me what I want them to remember, and only seal it with psychopomp_seal_letter after I approve the final text.`)
                }, children: 'Write it with Hermes instead'
              }),
              jsx(Button, {
                disabled: busy || !draft.body.trim() || !draft.to_name.trim(), onClick: async () => {
                  if (await post('/seal', draft)) { setDraft({ to_name: '', to_target: '', subject: '', body: '' }); setWriting(false) }
                }, children: 'Seal the letter'
              })
            ]
          })
        ]
      })
    }),
    jsx(Dialog, {
      open: inviting && !inviteCode, onOpenChange: setInviting, children: jsxs(DialogContent, {
        className: 'psy-dlg', style: { maxWidth: 480 }, children: [
          jsxs(DialogHeader, { children: [jsx(DialogTitle, { children: 'Choose your witness' }), jsx(DialogDescription, { children: 'One person you trust completely. Hermes only writes to them if you go silent for a long time, and nothing is ever carried without their code.' })] }),
          jsx(Input, { value: witness, placeholder: 'Their name, e.g. Leo', autoFocus: true, onChange: e => setWitness(e.target.value) }),
          jsxs(DialogFooter, { children: [
            jsx(Button, { variant: 'ghost', onClick: () => setInviting(false), children: 'Cancel' }),
            jsx(Button, { disabled: !witness.trim() || busy, onClick: async () => { const r = await post('/invite', { name: witness.trim() }); if (r?.code) setInviteCode(r.code) }, children: 'Create invitation' })] })
        ]
      })
    }),
    jsx(Dialog, {
      open: !!bookHtml, onOpenChange: o => !o && setBookHtml(''), children: jsxs(DialogContent, {
        className: 'psy-dlg', style: { maxWidth: 760, width: '92vw' }, children: [
          jsxs(DialogHeader, { children: [jsx(DialogTitle, { children: 'Your Book, as your witness will receive it' }), jsx(DialogDescription, { children: 'One file that opens on any phone and prints well. It travels only after the passage.' })] }),
          bookHtml ? jsx(SandboxedFrame, { src: `data:text/html;charset=utf-8,${encodeURIComponent(bookHtml)}`, title: 'Your Book', sandbox: '', style: { width: '100%', height: '68vh', border: 'none', borderRadius: 6 } }) : null
        ]
      })
    }),
    jsx(Dialog, {
      open: !!inviteCode, onOpenChange: o => { if (!o) { setInviteCode(''); setInviting(false) } }, children: jsxs(DialogContent, {
        className: 'psy-dlg', style: { maxWidth: 560 }, children: [
          jsxs(DialogHeader, { children: [jsx(DialogTitle, { children: `Invite ${witness || 'your witness'}` }), jsx(DialogDescription, { children: 'Send them this message. When they send the code to your Hermes, it learns how to reach them, on whatever channel they used.' })] }),
          h('div', { className: 'quote' }, inviteText),
          jsxs(DialogFooter, { children: [jsx(CopyButton, { text: inviteText, label: 'Copy message', buttonVariant: 'default' }), jsx(Button, { variant: 'ghost', onClick: () => { setInviteCode(''); setInviting(false) }, children: 'Done' })] })
        ]
      })
    })
  )
}

export default {
  id: ID,
  name: 'Psychopomp',
  register(ctx) {
    const style = document.createElement('style')
    style.dataset.plugin = ID
    style.textContent = NAV_CSS
    document.head.appendChild(style)
    ctx.onDispose(() => style.remove())
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PATH }, render: () => jsx(Page, { ctx }) },
      { id: 'page-card', area: TRANSCRIPT_DIRECTIVE_AREA, data: { name: 'psychopomp-page', render: ({ attrs, sessionId }) => jsx(PageCard, { ctx, attrs: attrs || {}, sessionId }) } },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: PATH, label: 'Psychopomp', codicon: 'psychopomp' } }
    ])
  }
}
