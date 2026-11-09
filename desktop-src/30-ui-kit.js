// Small UI primitives in own DOM (Bench Phosphor look; SDK components carry the app theme).

function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

function Label({ children, className, ...rest }) {
  return h('span', { className: cx('cb-label', className), ...rest }, children)
}

/** Button. kind: primary | ghost | quiet | warn | danger | agent. `agent` = an action Hermes carries out: active
 *  fill, the Hermes mark ◢ in front (aria-hidden), at most one per surface as the primary button. */
function Btn({ kind = 'primary', size, className, children, ...rest }) {
  return h('button', { type: 'button', className: cx('cb-btn', kind !== 'primary' && `cb-btn--${kind}`, size && `cb-btn--${size}`, className), ...rest },
    kind === 'agent' ? h('span', { className: 'cb-btn-mark', 'aria-hidden': 'true' }, '◢') : null, children)
}

/** Segmented control: options [{id, label, title?}] */
function Seg({ options, value, onChange, label, dataCb }) {
  return h('div', { className: 'cb-seg', role: 'group', 'aria-label': label, 'data-cb': dataCb },
    options.map(o => h('button', { key: o.id, type: 'button', 'aria-pressed': o.id === value ? 'true' : 'false', title: o.title,
      'data-cb-opt': o.id, onClick: () => { if (o.id !== value) onChange(o.id) } }, o.label)))
}

function Toggle({ checked, onChange, children, dataCb, title }) {
  return h('button', { type: 'button', role: 'switch', className: 'cb-switch', 'aria-checked': checked ? 'true' : 'false',
    'data-cb': dataCb, title, onClick: () => onChange(!checked) }, h('i', { 'aria-hidden': 'true' }), children)
}

function Stamp({ tone = 'bad', children, ...rest }) {
  return h('span', { className: cx('cb-stamp', tone !== 'bad' && `cb-stamp--${tone}`), ...rest }, children)
}

/** Station title: Hermes' DecodeText once per station change, plain text when the SDK lacks it. */
function DecodeTitle({ text, meta }) {
  const Decode = typeof sdk.DecodeText === 'function' ? sdk.DecodeText : null
  return h('div', { className: 'cb-title' },
    h('h1', { 'data-cb': 'station-title', 'aria-label': text },
      Decode ? h(Decode, { key: text, text, prefix: Math.max(0, text.indexOf('//') + 3), className: 'cb-decode', 'aria-hidden': 'true' })
        : h('span', { className: 'cb-decode' }, text),
      h('span', { className: 'cb-cursor', 'aria-hidden': 'true' })),
    meta ? h(Label, null, meta) : null)
}

/** Empty or error state: a clear sentence and the next step. One form for every station: kicker,
 *  title (with ✕ / ! for bad / warn, so the state is never colour alone), text, actions. */
function EmptyBox({ tone, kicker, title, children, actions, dataCb = 'empty' }) {
  const mark = tone === 'bad' ? '✕' : tone === 'warn' ? '!' : null
  return h('div', { className: cx('cb-empty', 'cb-bracket', tone && `cb-empty--${tone}`, tone === 'bad' && 'cb-bracket--bad'), 'data-cb': dataCb,
    role: tone === 'bad' ? 'alert' : undefined },
  kicker ? h(Label, null, kicker) : null,
  h('h2', null, mark ? h('span', { className: 'cb-empty-mark', 'aria-hidden': 'true' }, mark) : null, title),
  children,
  actions ? h('div', { className: 'cb-actions' }, actions) : null)
}

/** In-root modal (own DOM): focus moves into the dialog and stays there (Tab / Shift+Tab cycle), Escape closes
 *  it (document keydown, capture phase; only for keys inside the own Bench root or while the focus is lost to
 *  <body>, so the app's own keys keep working), the backdrop closes on a click. On close the
 *  focus returns to `returnFocus(root)` (e.g. the pin the dialog was about), else to the element that opened
 *  it, else to the station title — never to <body>. */
const MODAL_STACK = []

function focusablesIn(el) {
  if (!el) return []
  return [...el.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])')]
    .filter(n => n.tabIndex !== -1 && n.getClientRects().length > 0)
}

/** The own .cb-root around a node of ours (walks parentNode; never looks at app markup). */
function ownRoot(node) {
  for (let n = node; n; n = n.parentNode) if (n.classList?.contains('cb-root')) return n
  return null
}

function Modal({ title, onClose, children, footer, dataCb = 'modal', returnFocus = null, wide = false }) {
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const backRef = useRef(returnFocus)
  backRef.current = returnFocus
  useEffect(() => {
    if (typeof document === 'undefined') return undefined
    const prev = document.activeElement
    const dialog = ref.current
    const root = ownRoot(dialog) // own root (the dialog is rendered inside it)
    const token = {}
    MODAL_STACK.push(token)
    const first = dialog?.querySelector('input,select,textarea') || focusablesIn(dialog)[0]
    first?.focus?.()
    const onKey = e => {
      if (MODAL_STACK[MODAL_STACK.length - 1] !== token || !ref.current) return
      // only keys inside the own Bench root, or with the focus lost to <body>; the app's keys (chat composer) pass
      const active = document.activeElement
      const lost = !active || active === document.body
      const own = root ? ownRoot(e.target) === root : ref.current.contains(e.target)
      if (!own && !lost) return
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        closeRef.current?.()
        return
      }
      if (e.key !== 'Tab') return
      const list = focusablesIn(ref.current)
      if (!list.length) { e.preventDefault(); return }
      const inside = ref.current.contains(document.activeElement)
      const i = list.indexOf(document.activeElement)
      if (!inside || (e.shiftKey && i <= 0) || (!e.shiftKey && i === list.length - 1)) {
        e.preventDefault()
        ;(e.shiftKey ? list[list.length - 1] : list[0]).focus()
      }
    }
    // focus that leaves the dialog by a click elsewhere in the Bench comes back on the next Tab (above)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      const at = MODAL_STACK.indexOf(token)
      if (at >= 0) MODAL_STACK.splice(at, 1)
      const back = () => {
        const wanted = typeof backRef.current === 'function' ? backRef.current(root) : null
        const target = [wanted, prev && prev.isConnected && prev.tagName !== 'BODY' ? prev : null,
          root?.querySelector?.('[data-cb=station-title]')].find(n => n && n.isConnected && typeof n.focus === 'function')
        if (target) {
          if (target.matches?.('h1') && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
          try { target.focus({ preventScroll: true }) } catch { /* element gone */ }
        }
      }
      // after the re-render that follows the close (the opener may have been replaced)
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(back)
      else setTimeout(back, 0)
    }
  }, [])
  return h('div', { className: 'cb-modal-back', 'data-cb': 'modal-back', onMouseDown: e => { if (e.target === e.currentTarget) onClose() } },
    h('div', { className: `cb-modal cb-bracket${wide ? ' cb-modal--wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title, ref, 'data-cb': dataCb },
      h(Label, null, '// circuit bench'),
      h('h2', null, title),
      children,
      footer ? h('div', { className: 'cb-modal-foot' }, footer) : null))
}

/** Open a URL through the plugin OS door (ctx.os), never window.open on app markup. */
function openLink(url) {
  if (!url) return
  const os = CB.ctx?.os
  if (typeof os?.openExternal === 'function') os.openExternal(url)
  else if (typeof sdk.host?.openExternal === 'function') sdk.host.openExternal(url)
}

function sourceLabel(src) {
  if (!src) return ''
  const t = String(src.title || src.id || '').replace(/,?\s*GPIO & RTC GPIO/, ' · GPIO').replace(/\s*\(([^)]+)\)\s*$/, ' · $1')
  const cut = t.indexOf(', ')
  if (t.length <= 36 || cut < 0) return t
  // never cut an enumeration (E6, E12, E24)
  if (/^[A-Z]{0,2}\d+\b/.test(t.slice(cut + 2))) { const dot = t.indexOf(' · '); return dot > 0 ? t.slice(0, dot) : t }
  return t.slice(0, cut)
}

function SourceLine({ sources, ids }) {
  const list = (sources || []).filter(s => !ids || ids.includes(s.id))
  if (!list.length) return null
  return h('div', { className: 'cb-src', 'data-cb': 'src' },
    h('span', { className: 'cb-k' }, 'src ›'),
    h('span', { style: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 } },
      list.slice(0, 3).map(s => h('button', { key: s.id, type: 'button', title: `${s.title}\n${s.url || 'no URL (rule of thumb)'}\nretrieved ${s.retrieved || '—'}`,
        onClick: () => openLink(s.url) }, `${sourceLabel(s)}${s.url ? ' ↗' : ''}`))))
}

// ─── Station primitives ───────────────────────────────────────────────

/** Card with a comment-style label, optional step number and a right-side slot. */
function Section({ n, title, aside, children, tone, dataCb, className }) {
  return h('section', { className: cx('cb-card cb-sec', tone === 'bad' && 'cb-sec--bad', tone === 'active' && 'cb-sec--active', tone === 'ok' && 'cb-sec--ok', className), 'data-cb': dataCb },
    h('div', { className: 'cb-card-head' }, n ? h('span', { className: 'cb-secn', 'aria-hidden': 'true' }, n) : null, h(Label, null, `// ${title}`),
      aside ? h('span', { className: 'cb-sec-aside' }, aside) : null),
    children)
}

/** Labelled input with parsed-value hint or error (calculators, wiring parameters). */
function Field({ id, label, value, onChange, hint, error, placeholder, choice, dataCb, wide, onEnter, tail }) {
  const ref = useRef(null)
  useEffect(() => { // paths: show the end (the project folder), not the common prefix
    const el = ref.current
    if (tail && el && typeof document !== 'undefined' && document.activeElement !== el) el.scrollLeft = el.scrollWidth
  }, [tail, value])
  const control = choice
    ? h('select', { id, value, 'data-cb': dataCb, onChange: e => onChange(e.target.value) }, choice.map(c => h('option', { key: c, value: c }, c)))
    : h('input', { id, ref, value, placeholder, onBlur: tail ? e => { e.target.scrollLeft = e.target.scrollWidth } : undefined, 'data-cb': dataCb, autoComplete: 'off', spellCheck: false, 'aria-invalid': error ? 'true' : 'false', title: String(value || '').length > 24 ? value : undefined,
      onChange: e => onChange(e.target.value), onKeyDown: e => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter() } } })
  return h('div', { className: cx('cb-field', wide && 'cb-field--wide', error && 'cb-field--err') },
    h('label', { htmlFor: id }, label), control,
    h('span', { className: error ? 'cb-fhint cb-bad' : 'cb-fhint' }, error || hint || '\u00a0'))
}

/** Horizontal level bar (RAM/flash use, progress); pct null = indeterminate. */
function Bar({ pct, tone = 'active', label, dataCb }) {
  const ind = pct === null || pct === undefined
  return h('div', { className: cx('cb-bar', `cb-bar--${tone}`, ind && 'cb-bar--ind'), 'data-cb': dataCb, role: 'progressbar', 'aria-label': label,
    'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': ind ? undefined : Math.round(pct) },
  h('i', { style: ind ? undefined : { width: `${Math.max(0, Math.min(100, pct))}%` } }))
}

/** check status → symbol and tone (only `passed` counts as checked). */
function checkMark(status) {
  return status === 'passed' ? { s: '✓', t: 'ok' } : status === 'failed' ? { s: '✕', t: 'bad' } : status === 'skipped' ? { s: '○', t: 'dim' } : { s: '?', t: 'dim' }
}

function ChecksList({ checks, warnings, dataCb }) {
  const cs = checks || []
  const ws = warnings || []
  if (!cs.length && !ws.length) return null
  return h('div', { className: 'cb-checks', 'data-cb': dataCb },
    cs.map(c => { const m = checkMark(c.status); return h('div', { key: c.id, className: `cb-chk cb-${m.t}`, title: c.id }, h('span', { 'aria-hidden': 'true' }, m.s), h('span', null, c.detail || c.id)) }),
    ws.map(w => h('div', { key: w.code, className: `cb-chk ${w.severity === 'danger' ? 'cb-bad' : w.severity === 'caution' ? 'cb-warn' : 'cb-dim'}` },
      h('span', { 'aria-hidden': 'true' }, w.severity === 'info' ? 'i' : '!'), h('span', null, w.message))))
}

/** SIM badge: solid frame, diagonal stripes, the word SIMULATED always visible. The class
 *  cb-simban stays for the layout rules of HUD and console; ' BOARD' may give way in narrow tiles (cb-simban-w). */
function SimBadge({ compact, short, dataCb = 'sim-banner', title, className }) {
  // short: without BOARD
  return h('span', { className: cx('cb-simban', 'cb-simbadge', compact && 'cb-simbadge--sm', className), 'data-cb': dataCb, title: title || 'Simulated board: nothing physical is read or written' },
    h('span', { className: 'cb-simbadge-s', 'aria-hidden': 'true' }),
    h('span', { className: 'cb-simbadge-t' }, 'SIMULATED', short ? null : h('span', { className: 'cb-simban-w' }, ' BOARD')))
}

/** Former name; every call site gets the badge unchanged (same props, same data-cb defaults). */
const SimBanner = SimBadge

/** art attribute names (stroke-width …) → React SVG props (strokeWidth …). */
function kitSvgProps(attrs) {
  const out = {}
  for (const [k, v] of Object.entries(attrs)) out[/^(data|aria)-/.test(k) ? k : k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v
  return out
}

/** State symbol as inline SVG (lib/art.js shapes, colour = currentColor from .cb-glyph--<state>). role=img with the
 *  state word as label; `decorative` hides it when the word stands next to it. Unknown state → nothing. */
function Glyph({ state, size = 12, decorative = false, knock = 'var(--cb-ink)', className }) {
  const word = ART_STATE_WORDS[state]
  if (!word) return null
  return h('svg', { className: cx('cb-glyph', `cb-glyph--${state}`, className), width: size, height: size, viewBox: '0 0 12 12', focusable: 'false',
    'data-cb-state': state, ...(decorative ? { 'aria-hidden': 'true' } : { role: 'img', 'aria-label': word }) },
  artGlyphShapes(state, 6, 6, 'currentColor', knock).map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}

