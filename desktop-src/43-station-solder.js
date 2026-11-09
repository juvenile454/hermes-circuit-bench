// Station 04 SOLDER: plan from the project's parts or a pasted BOM (CSV), one card per step in order, check marks →
// POST /projects/{id}/solder/{step}; key n (or the button "Mark done (N)") = mark the current step done.
// Every step shows its part (lib/art-parts.js), a polarity mark only with a sourced polarity hint, hint
// lines by kind (polarity, heat, safety, tip) with symbol + tone by severity and their sources, done steps fold to one
// line and open again (nothing is cut), one progress formula in the head, a height strip (rule of thumb).

const HINT_TONE = { danger: 'bad', caution: 'warn', info: 'dim' }
const SOLDER_HINT_SYMBOL = { danger: '✕', caution: '!', info: 'i' }

const solderKindWord = k => String(k || '').replace(/_/g, ' ')
const solderN = n => String(n).padStart(2, '0')

/** Source label of an id: the title from the plan answer when known (sourceLabel), else the id itself. */
function solderSourceOf(id, sources) {
  const s = (sources || []).find(x => x && x.id === id)
  if (s) return { id, text: sourceLabel(s), title: `${s.title}\n${s.url || 'no URL (rule of thumb)'}\nretrieved ${s.retrieved || '—'}`, url: s.url || null }
  if (id === 'rule-of-thumb') return { id, text: 'rule of thumb', title: 'Practice rule, not a standard', url: null }
  return { id, text: String(id).replace(/^solder-/, ''), title: `source ${id} (details in the plan answer: re-plan to load the titles)`, url: null }
}

function SolderSrc({ ids, sources }) {
  const list = [...new Set(ids || [])].map(id => solderSourceOf(id, sources))
  if (!list.length) return null
  return h('span', { className: 'cb-shint-src', 'data-cb': 'hint-src' }, h('span', { className: 'cb-k' }, 'src ›'),
    list.map((s, i) => [i ? h('span', { key: `d${i}`, className: 'cb-shint-src-sep', 'aria-hidden': 'true' }, '·') : null, s.url
      ? h('button', { key: s.id, type: 'button', title: s.title, onClick: () => openLink(s.url) }, `${s.text} ↗`)
      : h('span', { key: s.id, title: s.title }, s.text)]))
}

/** One hint line: symbol + category tag (state never by colour alone), text, sources. */
function SolderHintRow({ hint, sources }) {
  const sev = HINT_TONE[hint.severity] ? hint.severity : 'info'
  const cat = solderArtHintKind(hint)
  return h('li', { className: cx('cb-shint', `cb-shint--${sev}`), 'data-cb': `hint-${hint.code}`, 'data-cb-hint-kind': cat, 'data-cb-severity': sev },
    h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, SOLDER_HINT_SYMBOL[sev]),
    h('span', { className: 'cb-shint-cat' }, h('span', { className: 'cb-sr' }, `${sev}: `), cat),
    h('span', { className: 'cb-shint-t' }, nbspUnits(hint.text), ' ', h(SolderSrc, { ids: hint.source_ids, sources })))
}

function SolderHints({ hints, sources }) {
  if (!hints?.length) return null
  return h('ul', { className: 'cb-shints', 'data-cb': 'step-hints' }, hints.map((x, i) => h(SolderHintRow, { key: `${x.code}-${i}`, hint: x, sources })))
}

/** Pictogram of a step's part (side view on the board). size: lg (open step) | md (later step) | sm (done line). */
function SolderPic({ step, parts, size = 'lg', polarity }) {
  const dims = { lg: [132, 88], md: [84, 56], sm: [36, 24] }[size] || [96, 64]
  const label = size === 'sm' ? '' : `${solderKindWord(step.kind)}${polarity ? `, ${polarity.label}` : ''} (side view, schematic)`
  const safe = sanitizeSvg(solderArtPart(step.kind, { polarity: size === 'sm' ? null : polarity, pkg: solderArtPackage(step, parts), w: dims[0], h: dims[1], label }))
  if (!safe.ok) return null
  return h('span', { className: cx('cb-part-pic', `cb-part-pic--${size}`), 'data-cb': `step-pic-${step.n}`, dangerouslySetInnerHTML: { __html: safe.svg } })
}

/** Polarity tag under the pictogram: only with a sourced hint (solderArtPolarity), with its sources in the title. */
function SolderPolTag({ polarity }) {
  if (!polarity) return null
  return h('span', { className: 'cb-pol', 'data-cb': 'step-polarity', 'data-cb-mark': polarity.mark, title: `from the ${polarity.code} hint · src ${polarity.source_ids.join(', ')}` },
    h('span', { 'aria-hidden': 'true' }, polarity.mark === 'pinout-datasheet' ? '?' : '±'), polarity.label)
}

function SolderStepCard({ step, done, current, onToggle, onMark, busy, parts, sources }) {
  const ref = useRef(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!current || !ref.current?.scrollIntoView) return
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ref.current.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  }, [current])
  const polarity = solderArtPolarity(step)
  const later = !done && !current
  const detailId = `cb-step-detail-${step.id}`
  const check = h('button', { type: 'button', role: 'checkbox', 'aria-checked': done ? 'true' : 'false', className: 'cb-check', disabled: busy, 'data-cb': `step-check-${step.n}`,
    title: done ? 'Mark as not done' : 'Mark as done', 'aria-label': `step ${step.n} ${solderKindWord(step.kind)} ${done ? 'done' : 'not done'}`, onClick: () => onToggle(step, !done) }, done ? '✓' : '')
  const num = h('div', { className: 'cb-step-n' }, solderN(step.n))
  const refs = h('span', { className: 'cb-step-refs' }, step.refs.join(' · '))
  if (done) {
    return h('div', { ref, className: cx('cb-step', 'cb-step--done', open && 'cb-step--open'), 'data-cb': `step-${step.n}`, 'data-cb-step': step.id },
      check, num,
      h('div', { className: 'cb-step-body' },
        h('div', { className: 'cb-step-head cb-step-line' }, h(SolderPic, { step, parts, size: 'sm' }), h('b', null, solderKindWord(step.kind)), refs,
          h('span', { className: 'cb-ok cb-step-donew' }, '✓ done'),
          h('button', { type: 'button', className: 'cb-step-more cb-push', 'data-cb': `step-expand-${step.n}`, 'aria-expanded': open ? 'true' : 'false', 'aria-controls': detailId,
            onClick: () => setOpen(!open) }, open ? 'hide ▴' : 'details ▾')),
        open ? h('div', { id: detailId, className: 'cb-step-detail', 'data-cb': `step-detail-${step.n}` },
          h('div', { className: 'cb-step-act' }, nbspUnits(step.action)), h(SolderHints, { hints: step.hints, sources })) : null))
  }
  return h('div', { ref, className: cx('cb-step', current && 'cb-step--cur', later && 'cb-step--todo'), 'data-cb': `step-${step.n}`, 'data-cb-step': step.id,
    'aria-current': current ? 'step' : undefined },
  check, num,
  h('div', { className: 'cb-step-body' },
    h('div', { className: 'cb-step-head' }, h('b', null, solderKindWord(step.kind)), refs,
      current ? h('span', { className: 'cb-now' }, 'NOW') : null,
      current ? h(Btn, { kind: 'ghost', size: 'sm', className: 'cb-push cb-mark-done', disabled: busy, 'data-cb': 'solder-mark-done', 'aria-keyshortcuts': 'n',
        title: 'Mark this step done (key n)', onClick: () => onMark(step) }, 'Mark done (N)') : null),
    h('div', { className: 'cb-step-main' },
      h('div', { className: 'cb-step-fig' }, h(SolderPic, { step, parts, size: current ? 'lg' : 'md', polarity }), h(SolderPolTag, { polarity })),
      h('div', { className: 'cb-step-text' }, h('div', { className: 'cb-step-act' }, nbspUnits(step.action)), h(SolderHints, { hints: step.hints, sources })))))
}

/** Height strip (S): the parts in solder order as silhouettes on one board line, current step framed. */
function SolderHeights({ steps, done, currentId, parts }) {
  if (steps.length < 2) return null
  return h('div', { className: 'cb-heights', 'data-cb': 'solder-heights' },
    h('div', { className: 'cb-heights-head' }, h(Label, null, '// part height in solder order'),
      h('span', { className: 'cb-heights-why' }, 'low before tall · mechanical parts last'), h('span', { className: 'cb-heights-rot' }, 'rule of thumb')),
    h('ol', { className: 'cb-heights-row' }, steps.map(s => {
      const st = done.has(s.id) ? 'done' : s.id === currentId ? 'now' : 'todo'
      const cls = SOLDER_ART_HEIGHT[s.kind] ?? 4
      return h('li', { key: s.id, className: cx('cb-hcell', `cb-hcell--${st}`), 'data-cb': `height-${s.n}`, 'data-cb-state': st,
        title: `${solderN(s.n)} ${solderKindWord(s.kind)} · ${SOLDER_ART_HEIGHT_WORDS[cls]} (rule of thumb)` },
      h('span', { className: 'cb-hcell-pic', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: solderArtPart(s.kind, { pkg: solderArtPackage(s, parts), w: 48, h: 32 }) } }),
      h('span', { className: 'cb-hcell-n' }, solderN(s.n), ' ', h('span', { 'aria-hidden': 'true' }, st === 'done' ? '✓' : st === 'now' ? '●' : '○'),
        h('span', { className: 'cb-sr' }, ` ${solderKindWord(s.kind)}, ${SOLDER_ART_HEIGHT_WORDS[cls]}, ${st === 'now' ? 'current step' : st}`)))
    })))
}

function StationSolder({ project }) {
  const steps = project?.solder?.steps || []
  const done = new Set(project?.solder?.done || [])
  const parts = project?.parts || []
  const sp = solderProgress(project)
  const next = nextSolderStep(project)
  const plan = sdk.useValue($solderPlan)
  const sources = plan.env?.ok ? plan.env.sources || [] : []
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const toggle = async (step, on) => {
    setBusy(true)
    try { await toggleSolderStep(step.id, on) } finally { setBusy(false) }
  }
  useEffect(() => { ref.current?.focus?.({ preventScroll: true }) }, [])
  useEffect(() => {
    const el = ref.current?.querySelector?.('[aria-current=step]')
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [next?.id])
  const onKey = e => {
    if (e.key !== 'n' || e.ctrlKey || e.metaKey || e.altKey || busy) return
    const t = e.target
    if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')) return
    e.preventDefault()
    if (next) toggle(next, true)
  }
  // after the button: focus back on the station, so n keeps working without a click
  const mark = async step => { await toggle(step, true); ref.current?.focus?.({ preventScroll: true }) }
  const all = sp.total > 0 && sp.done >= sp.total
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-solder', 'data-cb-audit-root': 'station', ref, tabIndex: -1, onKeyDown: onKey },
      h(DecodeTitle, { text: '04 // SOLDER ORDER', meta: 'flat → tall, robust → sensitive, connectors last' }),
      sp.total ? h('div', { className: 'cb-solder-prog', 'data-cb': 'solder-progress' },
        h('span', { className: 'cb-solder-formula', 'data-cb': 'solder-formula' }, h('b', { className: all ? 'cb-ok' : 'cb-fg' }, `${sp.done}/${sp.total}`), ' done',
          next ? [' · now ', h('b', { key: 'r', className: 'cb-solder-nowrefs' }, next.refs.join(' · '))] : [' · ', h('span', { key: 'a', className: 'cb-ok' }, '✓ all steps done')]),
        h(Bar, { pct: (sp.done / sp.total) * 100, tone: all ? 'ok' : 'active', label: 'solder progress' })) : null,
      h(SolderStale, { project }),
      steps.length ? h(SolderHeights, { steps, done, currentId: next?.id, parts }) : null,
      steps.length ? h('div', { className: 'cb-steps-list', 'data-cb': 'solder-steps' }, steps.map(s => h(SolderStepCard, { key: s.id, step: s, done: done.has(s.id),
        current: next?.id === s.id, onToggle: toggle, onMark: mark, busy, parts, sources })))
        : h(EmptyBox, { kicker: '// 04 solder', title: 'No solder plan yet', dataCb: 'solder-empty',
          actions: [h(Btn, { key: 'p', kind: 'ghost', disabled: !parts.length, onClick: () => planSolder(), 'data-cb': 'solder-plan-parts' }, 'Plan from project parts')] },
        h('p', null, parts.length ? `Press Plan from project parts to order the ${parts.length === 1 ? 'part' : `${parts.length} parts`}. A plan Hermes makes with this project also shows up here.`
          : 'Add parts in 02 CALC, or open import bom (csv) in the plan source panel.'))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'data-cb-audit-root': 'inspector', 'aria-label': 'Inspector' }, h(SolderSource, { project }))
  ]
}

/** Parts added after planning (02 CALC → Add to project) or removed since — say so and offer the re-plan. */
function SolderStale({ project }) {
  const plan = sdk.useValue($solderPlan)
  const st = solderStale(project)
  if (!st.stale) return null
  const n = st.missing.length
  const parts = [n ? `${n} new part${n === 1 ? '' : 's'} not in the plan (${st.missing.join(', ')})` : null,
    st.gone.length ? `${st.gone.length} planned part${st.gone.length === 1 ? '' : 's'} no longer in the project (${st.gone.join(', ')})` : null].filter(Boolean)
  const reopen = st.reopen.map(r => `step ${String(r.n).padStart(2, '0')} (${r.kind.replace(/_/g, ' ')}) reopens${r.gains.length ? ` for ${r.gains.join(', ')}` : ''}`)
  return h('div', { className: 'cb-note cb-note--warn cb-stale', 'data-cb': 'solder-stale', role: 'status' },
    h('span', { 'aria-hidden': 'true' }, '!'),
    h('span', { className: 'cb-stale-t' }, h('b', null, parts.join('; ')),
      h('span', { className: 'cb-dim' }, reopen.length ? `Re-plan keeps the other check marks; ${reopen.join('; ')}.`
        : 'Re-planning keeps the check marks of unchanged steps.')),
    h(Btn, { kind: 'warn', size: 'sm', className: 'cb-push', 'data-cb': 'solder-stale-replan', disabled: plan.status === 'loading', onClick: () => planSolder() },
      plan.status === 'loading' ? 'Planning…' : 'Re-plan ›'))
}

/** All parts of the project with their step; the current step's refs are marked (NOW + frame, not colour alone). */
function SolderPartList({ project }) {
  const parts = (project?.parts || []).filter(p => p && p.ref)
  if (!parts.length) return null
  const steps = project?.solder?.steps || []
  const done = new Set(project?.solder?.done || [])
  const next = nextSolderStep(project)
  const stepOf = new Map()
  for (const s of steps) for (const r of s.refs || []) stepOf.set(r, s)
  // in solder order (step number), parts without a step at the end; the project order inside a step
  const ordered = parts.map((p, i) => ({ p, i, n: stepOf.get(p.ref)?.n ?? Infinity })).sort((a, b) => a.n - b.n || a.i - b.i).map(x => x.p)
  return h('ul', { className: 'cb-sparts', 'data-cb': 'solder-parts' }, ordered.map(p => {
    const s = stepOf.get(p.ref)
    const st = !s ? 'none' : done.has(s.id) ? 'done' : next?.id === s.id ? 'now' : 'todo'
    return h('li', { key: p.ref, className: cx('cb-spart', `cb-spart--${st}`), 'data-cb': `part-${p.ref}`, 'data-cb-state': st, 'aria-current': st === 'now' ? 'true' : undefined },
      h('span', { className: 'cb-spart-mark', 'aria-hidden': 'true' }, st === 'done' ? '✓' : st === 'now' ? '●' : st === 'none' ? '–' : '○'),
      h('b', { className: 'cb-spart-ref' }, p.ref),
      h('span', { className: 'cb-spart-what' }, solderKindWord(p.kind), p.value ? h('span', { className: 'cb-dim' }, ` · ${p.value}`) : null),
      h('span', { className: 'cb-spart-step' }, s ? solderN(s.n) : 'not planned', st === 'now' ? h('span', { className: 'cb-sr' }, ' current step') : null))
  }))
}

function SolderSource({ project }) {
  const plan = sdk.useValue($solderPlan)
  const [csv, setCsv] = useState('')
  const env = plan.env
  const r = env?.ok ? env.result : null
  const n = (project?.parts || []).length
  const loading = plan.status === 'loading'
  const partsWhy = loading ? 'planning…' : !n ? 'no parts in the project yet: 02 CALC adds them, or import a BOM below' : null
  const csvWhy = loading ? 'planning…' : !csv.trim() ? 'paste a BOM first (one part per line: ref,value,package)' : null
  return [
    h('div', { key: 's', className: 'cb-card', 'data-cb': 'solder-source' },
      h(Label, null, '// plan source'),
      h('p', { className: 'cb-why' }, `From the project's parts (${n}) or from a pasted BOM. Re-planning keeps the check marks of unchanged steps.`),
      h(SolderPartList, { project }),
      h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', disabled: Boolean(partsWhy), 'data-cb': 'solder-replan',
        'aria-describedby': partsWhy ? 'cb-solder-parts-why' : undefined, onClick: () => planSolder() }, loading ? 'Planning…' : 'Plan from project parts')),
      partsWhy ? h('p', { id: 'cb-solder-parts-why', className: 'cb-solder-why', 'data-cb': 'solder-replan-why' }, partsWhy) : null,
      h('details', { className: 'cb-solder-csv', 'data-cb': 'solder-csv-box' },
        h('summary', null, h(Label, null, 'import bom (csv)')),
        h('label', { className: 'cb-label', htmlFor: 'cb-bom', style: { display: 'block', marginTop: '8px' } }, 'bom (csv)'),
        h('textarea', { id: 'cb-bom', className: 'cb-textarea', rows: 5, value: csv, placeholder: 'ref,value,package\nR1,1k,0805\nC1,10uF 16V,radial', spellCheck: false,
          'data-cb': 'solder-csv', onChange: e => setCsv(e.target.value.slice(0, 60000)) }),
        h('div', { className: 'cb-actions' }, h(Btn, { kind: 'quiet', size: 'sm', disabled: Boolean(csvWhy), 'data-cb': 'solder-plan-csv',
          'aria-describedby': csvWhy ? 'cb-solder-csv-why' : undefined, onClick: () => planSolder(csv) }, 'Plan from CSV')),
        csvWhy ? h('p', { id: 'cb-solder-csv-why', className: 'cb-solder-why', 'data-cb': 'solder-csv-why' }, csvWhy) : null)),
    // a failed plan is a notice in the Bench's zone (26-live.js planSolder)
    r && (r.unknown_parts?.length || r.unclear_parts?.length) ? h('div', { key: 'u', className: 'cb-card', 'data-cb': 'solder-unclear' },
      h(Label, null, '// check these parts'),
      h('ul', { className: 'cb-step-hints' }, [...(r.unknown_parts || []).map(x => ({ x, t: 'unknown kind' })), ...(r.unclear_parts || []).map(x => ({ x, t: 'unclear' }))].map((u, i) =>
        h('li', { key: i, className: 'cb-warn' }, `! ${typeof u.x === 'string' ? u.x : u.x.ref || JSON.stringify(u.x)} — ${u.t}`)))) : null,
    env?.ok ? h(SourceLine, { key: 'src', sources: env.sources }) : null
  ]
}

STATION_VIEWS.solder = { component: StationSolder, inspector: true }
