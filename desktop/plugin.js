// Psychopomp — the Desktop half. A page with your heartbeat, your sealed letters and a composer.
// Talks only to its own backend (dashboard/plugin_api.py) through ctx.rest.
import { ROUTES_AREA, SIDEBAR_NAV_AREA, host } from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'psychopomp'
const PATH = '/psychopomp'

// h('div', {className}, child, child) — JSX without a compiler.
const h = (tag, props, ...children) =>
  (children.length > 1 ? jsxs : jsx)(tag, { ...(props || {}), children: children.length > 1 ? children : children[0] })

const CSS = `
.psy{max-width:880px;margin:0 auto;padding:28px 24px 64px;color:var(--ui-text-primary);font-size:13px}
.psy h1{font-size:22px;font-weight:600;margin:0;display:flex;gap:10px;align-items:center}
.psy .tag{color:var(--ui-text-tertiary);margin:4px 0 24px;font-style:italic}
.psy .card{border:1px solid var(--ui-stroke-secondary);border-radius:12px;padding:16px;margin-bottom:16px;background:var(--ui-bg-elevated)}
.psy .row{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.psy .muted{color:var(--ui-text-tertiary)}
.psy .phase{font-weight:600}
.psy .phase[data-p=watching]{color:var(--ui-success)}
.psy .phase[data-p=checking_in]{color:var(--ui-warning)}
.psy .phase[data-p=awaiting_trusted],.psy .phase[data-p=delivered]{color:var(--ui-danger)}
.psy .bar{height:6px;border-radius:3px;background:var(--ui-bg-tertiary);overflow:hidden;margin:12px 0 6px}
.psy .bar>i{display:block;height:100%;background:var(--ui-accent);transition:width .6s}
.psy .pulse{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--ui-success);animation:psy-beat 1.6s infinite}
.psy .pulse[data-on=false]{background:var(--ui-text-quaternary);animation:none}
@keyframes psy-beat{0%,100%{transform:scale(1);opacity:1}15%{transform:scale(1.5);opacity:.7}30%{transform:scale(1)}}
.psy button{font:inherit;border-radius:8px;padding:6px 12px;border:1px solid var(--ui-stroke-secondary);background:var(--ui-bg-tertiary);color:var(--ui-text-primary);cursor:pointer}
.psy button.primary{background:var(--ui-accent);border-color:var(--ui-accent);color:var(--ui-bg-primary)}
.psy button:disabled{opacity:.5;cursor:default}
.psy .letters{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px;margin:12px 0 4px}
.psy .env{position:relative;aspect-ratio:1.6;border-radius:6px;border:1px solid var(--ui-stroke-secondary);background:var(--ui-bg-quaternary);overflow:hidden;padding:46px 12px 10px}
.psy .env:before{content:"";position:absolute;inset:0 0 auto 0;height:58%;background:var(--ui-bg-quinary);clip-path:polygon(0 0,100% 0,50% 100%);border-bottom:1px solid var(--ui-stroke-tertiary)}
.psy .seal{position:absolute;left:50%;top:44%;transform:translate(-50%,-50%);width:34px;height:34px;border-radius:50%;background:var(--ui-accent);color:var(--ui-bg-primary);display:grid;place-items:center;font-size:18px;box-shadow:0 0 0 3px color-mix(in srgb,var(--ui-accent) 35%,transparent)}
.psy .env[data-done=true] .seal{background:var(--ui-success)}
.psy .env .to{position:absolute;bottom:22px;left:12px;right:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.psy .env .sub{position:absolute;bottom:7px;left:12px;right:28px;color:var(--ui-text-tertiary);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.psy .env .x{position:absolute;right:6px;bottom:4px;padding:0 6px;border:none;background:none;color:var(--ui-text-quaternary)}
.psy input,.psy textarea{font:inherit;width:100%;box-sizing:border-box;border-radius:8px;border:1px solid var(--ui-stroke-secondary);background:var(--ui-bg-primary);color:var(--ui-text-primary);padding:8px 10px;margin-bottom:8px}
.psy textarea{min-height:140px;font-family:Georgia,serif;font-size:14px;line-height:1.55}
.psy .grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.psy ol{margin:8px 0 0;padding-left:18px;color:var(--ui-text-secondary)}
.psy .err{color:var(--ui-danger);margin-top:6px}
`

const PHASE = {
  watching: 'Watching over you. All is well.',
  checking_in: 'You have been quiet. Hermes is checking in.',
  awaiting_trusted: 'No answer. Your trusted contact has been asked for the code.',
  delivered: 'The letters have been carried.'
}

const when = ts => (ts ? new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '')

function Page({ ctx }) {
  const [s, setS] = useState(null)
  const [err, setErr] = useState('')
  const [draft, setDraft] = useState({ to_name: '', to_email: '', subject: '', body: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => ctx.rest('/state').then(setS).catch(e => setErr(String(e?.message || e))), [ctx])
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    const off = host.onEvent(`plugin.${ID}.state.changed`, load)
    return () => { clearInterval(t); off && off() }
  }, [load])

  const post = async (path, body) => {
    setBusy(true); setErr('')
    try { await ctx.rest(path, { method: 'POST', body }); await load(); return true }
    catch (e) { setErr(String(e?.message || e)); return false }
    finally { setBusy(false) }
  }
  const seal = async () => {
    if (await post('/seal', draft)) setDraft({ to_name: '', to_email: '', subject: '', body: '' })
  }
  const askHermes = () => {
    const who = draft.to_name || 'someone I love'
    host.composer.insertText(null,
      `Help me write a Psychopomp letter to ${who}${draft.to_email ? ` (${draft.to_email})` : ''}. ` +
      'Use what you know about me and about them, keep my voice, ask me what I want them to remember, ' +
      'and only seal it with psychopomp_seal_letter after I approve the final text.', { mode: 'block' })
  }
  const field = (k, placeholder) =>
    h('input', { value: draft[k], placeholder, onChange: e => setDraft({ ...draft, [k]: e.target.value }) })

  if (!s) return h('div', { className: 'psy' }, h('style', null, CSS), h('p', { className: 'muted' }, err || 'Waking Hermes…'))
  const unit = s.day_seconds < 86400 ? 'minutes (demo)' : 'days'
  const pct = Math.min(100, (s.silent_days / s.silence_days) * 100)

  return h('div', { className: 'psy' },
    h('style', null, CSS),
    h('h1', null, h('span', null, '☤'), 'Psychopomp'),
    h('p', { className: 'tag' }, 'Hermes guided souls across the threshold. Now he carries your words across time.'),

    h('div', { className: 'card' },
      h('div', { className: 'row' },
        h('div', null,
          h('span', { className: 'pulse', 'data-on': String(s.armed && s.phase === 'watching') }), ' ',
          h('span', { className: 'phase', 'data-p': s.phase }, s.armed || s.phase === 'delivered' ? PHASE[s.phase] : 'The switch is resting.')),
        h('button', { className: s.armed ? '' : 'primary', disabled: busy, onClick: () => post('/arm', { armed: !s.armed }) },
          s.armed ? 'Disarm' : 'Arm the switch')),
      h('div', { className: 'bar' }, h('i', { style: { width: `${pct}%` } })),
      h('div', { className: 'row muted' },
        h('span', null, `Silent for ${s.silent_days} of ${s.silence_days} ${unit}`),
        h('span', null, `Then ${s.checkins} check-ins, every ${s.checkin_every_days}`)),
      h('p', { className: 'muted' },
        `Trusted contact: ${s.trusted.name || '—'} · ${s.trusted.channels.length} channel(s) · Check-ins go to ${s.owner.channels.length} channel(s). `,
        'Edit in Settings › Plugins › Psychopomp.')),

    h('div', { className: 'card' },
      h('div', { className: 'row' }, h('strong', null, `Sealed letters (${s.letters.length})`),
        h('span', { className: 'muted' }, 'Once sealed, not even Hermes can read them.')),
      s.letters.length
        ? h('div', { className: 'letters' }, ...s.letters.map(l =>
          jsxs('div', {
            className: 'env', 'data-done': String(!!l.delivered_at), title: l.to_email, children: [
              h('div', { className: 'seal' }, l.delivered_at ? '✓' : '☤'),
              h('div', { className: 'to' }, `For ${l.to_name}`),
              h('div', { className: 'sub' }, l.delivered_at ? `Carried ${when(l.delivered_at)}` : `${l.subject} · ${when(l.sealed_at)}`),
              !l.delivered_at && h('button', { className: 'x', title: 'Withdraw', onClick: () => post('/withdraw', { id: l.id }) }, '×')
            ]
          }, l.id)), null)
        : h('p', { className: 'muted' }, 'No letters yet. Write the first one below.')),

    h('div', { className: 'card' },
      h('strong', null, 'Write a letter'),
      h('div', { className: 'grid2', style: { marginTop: 10 } }, field('to_name', 'For whom'), field('to_email', 'Their email')),
      field('subject', 'Subject'),
      h('textarea', { value: draft.body, placeholder: 'What do you want them to know?', onChange: e => setDraft({ ...draft, body: e.target.value }) }),
      h('div', { className: 'row' },
        h('button', { onClick: askHermes }, 'Write it with Hermes'),
        h('button', { className: 'primary', disabled: busy || !draft.body.trim() || !draft.to_email.includes('@'), onClick: seal }, 'Seal letter')),
      err && h('div', { className: 'err' }, err)),

    s.log.length > 0 && h('div', { className: 'card' },
      h('strong', null, 'Journey'),
      h('ol', null, ...s.log.slice().reverse().map((e, i) => jsx('li', { children: `${new Date(e.at * 1000).toLocaleString()} — ${e.text}` }, i)), null))
  )
}

export default {
  id: ID,
  name: 'Psychopomp',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: PATH }, render: () => jsx(Page, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: PATH, label: 'Psychopomp', codicon: 'mail' } }
    ])
  }
}
