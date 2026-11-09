// Directive ::bench{project="…" view="pins|calc|wire|solder|flash|crash"}: a compact card in the
// chat. Garbage attributes render nothing (lib/directive.js). "Open in Bench" sets the nav atom first, then opens
// the Bench beside the chat (host.openWorkspace) or, without it, the route. Live through project.updated.

const DIRECTIVE_CACHE = new Map() // project id → {env, at}
const $directiveTick = sdk.atom(0)

function directiveProjectChanged(id) {
  if (DIRECTIVE_CACHE.has(id)) DIRECTIVE_CACHE.delete(id)
  $directiveTick.set($directiveTick.get() + 1)
}

function useDirectiveProject(id) {
  const tick = sdk.useValue($directiveTick)
  const live = sdk.useValue($project)
  const [env, setEnv] = useState(() => DIRECTIVE_CACHE.get(id)?.env || null)
  useEffect(() => {
    let gone = false
    if (live?.id === id) return undefined
    const hit = DIRECTIVE_CACHE.get(id)
    if (hit && Date.now() - hit.at < 5000) { setEnv(hit.env); return undefined }
    CB.api?.project(id).then(e => {
      DIRECTIVE_CACHE.set(id, { env: e, at: Date.now() })
      if (!gone) setEnv(e)
    })
    return () => { gone = true }
  }, [id, tick, live?.id === id ? live.rev : null])
  if (live?.id === id) return { project: live, env: { ok: true } }
  return { project: env?.ok ? env.result?.project || null : null, env }
}

function BenchDirectiveCard(props) {
  const a = parseDirectiveAttrs(props?.attrs)
  if (!a) return null
  return h(BenchDirectiveInner, { a, sessionId: directiveSession(props), streaming: Boolean(props?.streaming) })
}

// ─── The card shows the thing itself — a mini pin header, the schematic, frame #0 ────────────────────────────

const DIRECTIVE_BOARDS = new Map() // devkit id → layout (GET /boards/{id})
const DIRECTIVE_SVGS = new Map() // project|rev|circuit → {svg, summary} | {error}

function useBoardLayout(devkit) {
  const board = sdk.useValue($board)
  const [layout, setLayout] = useState(() => DIRECTIVE_BOARDS.get(devkit) || null)
  const live = board.id === devkit && board.layout ? board.layout : null
  useEffect(() => {
    if (!devkit || live || DIRECTIVE_BOARDS.has(devkit) || typeof CB.api?.board !== 'function') return undefined
    let gone = false
    CB.api.board(devkit).then(env => {
      if (!env?.ok || !env.result) return
      DIRECTIVE_BOARDS.set(devkit, env.result)
      if (!gone) setLayout(env.result)
    })
    return () => { gone = true }
  }, [devkit, Boolean(live)])
  return live || layout || DIRECTIVE_BOARDS.get(devkit) || null
}

const DIRECTIVE_MAPS = new Map() // [chip, variant, wifi, devkit] → POST /pins/check of all header GPIOs (the PLAN map)

/** Pin map of the card's board (free / caution / blocked for the unassigned pins), fetched once per board. */
function useDirectiveMap(project, layout) {
  const b = boardOf(project)
  const key = layout ? JSON.stringify([b.chip, b.variant, b.wifi, layout.id]) : null
  const [env, setEnv] = useState(() => (key && DIRECTIVE_MAPS.get(key)) || null)
  useEffect(() => {
    if (!key) return undefined
    if (DIRECTIVE_MAPS.has(key)) { setEnv(DIRECTIVE_MAPS.get(key)); return undefined }
    if (typeof CB.api?.pinsCheck !== 'function') return undefined
    let gone = false
    CB.api.pinsCheck({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: layout.id, assignments: mapAssignments(layout) }).then(e => {
      if (e?.ok) DIRECTIVE_MAPS.set(key, e)
      if (!gone) setEnv(e)
    })
    return () => { gone = true }
  }, [key])
  const hit = env || (key && DIRECTIVE_MAPS.get(key)) || null
  return hit?.ok ? mapByGpio(hit.result) : null
}

/** GPIO list of a reservation in short words: consecutive → "IO33–37", else "IO19/20". */
function directiveIoRun(ios) {
  const n = [...new Set(ios)].sort((a, b) => a - b)
  if (!n.length) return ''
  const run = n.length > 2 && n.every((v, i) => !i || v === n[i - 1] + 1)
  return ` IO${run ? `${n[0]}–${n[n.length - 1]}` : n.join('/')}`
}

const DIRECTIVE_PIN_STATE = { ok: 'assigned', caution: 'caution', blocked: 'assigned_blocked' }
const DIRECTIVE_PIN_WORD = { ok: 'ok', caution: 'caution', blocked: 'blocked' }

/** Key figures of the pins card in the HUD's words (lib/art-shell.js shellKpis): symbol + number + word, the whole
 *  sentence in aria-label. The card has the room, so zero counts keep their word too (dimmed). */
function DirectiveKpis({ assignments }) {
  const kpi = shellKpis(countVerdicts(assignments), null, null).pins
  kpi.label = `${assignments.length} pins assigned: ${kpi.label.replace(/^Pins: /, '')}`
  return h('div', { className: 'cb-dcard-hl cb-dkpis', 'data-cb': 'directive-headline', role: 'group', 'aria-label': kpi.label, title: kpi.label },
    h(Label, { className: 'cb-dkpis-l' }, `${assignments.length} assigned`),
    kpi.items.map(it => h('span', { key: it.key, className: `cb-dkpi cb-${it.tone}`, 'data-cb-kpi': it.key },
      h('span', { 'aria-hidden': 'true' }, it.symbol), h('b', null, String(it.n)), h('span', { className: 'cb-dkpi-w' }, it.word))))
}

/** The thing itself for view pins: the compact board model (own id prefix per card), the assignments beside it, the legend
 *  with the model's symbols below. Without a layout the list stands alone. */
function DirectivePins({ project }) {
  const layout = useBoardLayout(project?.board?.devkit)
  const base = useDirectiveMap(project, layout)
  const prefix = useTwinPrefix('chat')
  // hover coupling: the row rings its pad
  const [hot, setHot] = useState(null)
  const as = project.assignments || []
  const where = new Map()
  for (const side of ['left', 'right']) for (const hp of layout?.[side] || []) if (Number.isInteger(hp.gpio)) where.set(hp.gpio, `${hp.header}-${hp.n}`)
  const shown = as.slice(0, 6)
  const b = project.board || {}
  const variant = variantInfo(b.chip, b.variant)
  // the same model the drawing gets (BoardTwin): map + assignments, so the words match the dashed frames
  const model = layout ? boardArtModel({ layout, chip: chipInfo(b.chip), variant, base: base || new Map(), used: new Map(as.map(a => [a.pin, a])) }) : null
  // the dashed frames on the strips: their reservation in words (the compact drawing has no text)
  const reserved = []
  for (const side of ['left', 'right']) {
    for (const br of model?.brackets?.[side] || []) {
      const ios = model.views[side].filter(v => v.view && v.slot >= br.from && v.slot <= br.to && Number.isInteger(v.hp.gpio)).map(v => v.hp.gpio)
      const key = `${br.label}|${ios.join(',')}`
      if (!reserved.some(r => r.key === key)) reserved.push({ key, label: br.label, tone: br.tone, ios })
    }
  }
  const spec = model ? [model.module.name, model.module.flash_mb ? `${model.module.flash_mb} MB flash` : null,
    model.module.psram_mb ? `${model.module.psram_mb} MB ${variant?.psram === 'octal' ? 'octal ' : ''}PSRAM` : null].filter(Boolean) : []
  return h('div', { className: cx('cb-dpins', !layout && 'cb-dpins--list'), 'data-cb': 'directive-pins' },
    layout ? h(BoardTwin, { layout, project, base, prefix, hot, dataCb: 'directive-mini-pins', className: 'cb-dpins-board',
      label: `${layout.title} board model: ${twinPinsText(project)}` }) : null,
    h('div', { className: 'cb-dpins-side' },
      h(DirectiveKpis, { assignments: as }),
      as.length ? h('ul', { className: 'cb-dpins-list', 'data-cb': 'directive-rows' }, shown.map(a => {
        const st = DIRECTIVE_PIN_STATE[a.verdict] || 'assigned'
        const word = DIRECTIVE_PIN_WORD[a.verdict] || 'not checked'
        return h('li', { key: `${a.role}-${a.pin}`, className: `cb-dpin cb-dpin--${a.verdict || 'none'}`, 'data-cb-role': a.role,
          'data-cb-hot': hot === a.pin ? 'true' : undefined, onMouseOver: () => setHot(a.pin), onMouseOut: () => setHot(null),
          title: `${a.role} → GPIO${a.pin} (${modeLabel(a.mode)}): ${word}` },
        h(BoardGlyph, { state: st }), h('b', { className: 'cb-dpin-role' }, a.role), h('span', { className: 'cb-dpin-io' }, `IO${a.pin}`),
        h('span', { className: 'cb-dpin-at cb-dim' }, where.get(a.pin) || ''), h('span', { className: 'cb-dpin-mode cb-dim' }, modeLabel(a.mode)), h('span', { className: `cb-dpin-w cb-${a.verdict === 'blocked' ? 'bad' : a.verdict === 'caution' ? 'warn' : 'dim'}` }, word))
      }), as.length > shown.length ? h('li', { key: 'more', className: 'cb-dpin cb-dpin--more cb-dim' }, `+ ${as.length - shown.length} more in 01 PLAN`) : null)
        : h('p', { className: 'cb-why cb-dim' }, 'No pins assigned yet.'),
      model ? h('div', { className: 'cb-dpins-foot', 'data-cb': 'directive-board-facts' },
        reserved.length ? h('div', { className: 'cb-dpins-res' }, h(Label, null, 'reserved'),
          reserved.map(r => h('span', { key: r.key, className: `cb-dres cb-dres--${r.tone}`, title: `${r.label}: ${r.ios.map(n => `GPIO${n}`).join(', ')} (dashed frame on the strip)` },
            h('i', { 'aria-hidden': 'true' }), h('b', null, r.label), directiveIoRun(r.ios)))) : null,
        spec.length ? h('div', { className: 'cb-dpins-spec' }, h(Label, null, 'module'), spec.map(t => h('span', { key: t }, t))) : null) : null),
    layout ? h(Legend, { dataCb: 'directive-legend', className: 'cb-dpins-legend' }) : null)
}

function useCircuitSvg(project) {
  const c = (project?.circuits || [])[0] || null
  const key = c ? `${project.id}|${project.rev}|${c.id}` : null
  const [res, setRes] = useState(() => (key && DIRECTIVE_SVGS.get(key)) || null)
  useEffect(() => {
    if (!key) return undefined
    if (DIRECTIVE_SVGS.has(key)) { setRes(DIRECTIVE_SVGS.get(key)); return undefined }
    if (typeof CB.api?.schematic !== 'function') return undefined
    let gone = false
    const gpio = circuitGpio(project, c)
    CB.api.schematic({ block: c.block, params: c.params, project: project.id, ...(Number.isInteger(gpio) ? { gpio } : {}) }).then(env => {
      const safe = env?.ok ? sanitizeSvg(env.result?.svg) : { ok: false, reason: env?.error?.message || 'schematic unavailable' }
      const v = safe.ok ? { svg: safe.svg, summary: env.summary, circuit: c.id, block: c.block } : { error: safe.reason }
      DIRECTIVE_SVGS.set(key, v)
      if (!gone) setRes(v)
    })
    return () => { gone = true }
  }, [key])
  return { circuit: c, res }
}

function MiniSchematic({ project }) {
  const { circuit, res } = useCircuitSvg(project)
  if (!circuit) return null
  if (!res) return h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'drawing schematic')
  if (res.error) return h('p', { className: 'cb-why cb-dim', 'data-cb': 'directive-svg-error' }, `Schematic not shown: ${res.error}`)
  return h('div', { className: 'cb-svg cb-svg--media cb-svg--dcard', 'data-cb': 'directive-svg', role: 'img', 'aria-label': res.summary || circuit.block,
    dangerouslySetInnerHTML: { __html: res.svg } })
}

/** Frame #0 of the stored panic (red while it is current, dim once a flash came after it). */
function MiniFrame({ project, live }) {
  const p = project?.debug?.last_panic
  if (!p?.top_frame) return null
  const t = splitTopFrame(p.top_frame)
  const base = String(t.file || '??').split('/').pop()
  return h('div', { className: cx('cb-frame', live && 'cb-frame--top', 'cb-dframe'), 'data-cb': 'directive-frame', title: p.top_frame },
    h('span', { className: 'cb-i' }, '#0'), h('span', { className: 'cb-f' }, shortFunction(t.fn)),
    h('span', { className: 'cb-l' }, t.line !== null ? `${base}:${t.line}` : base))
}

function BenchDirectiveInner({ a, sessionId }) {
  const ui = sdk.useValue($ui)
  const { project, env } = useDirectiveProject(a.project)
  const sum = directiveSummary(a.view, project, { panicCurrent: projectPanicCurrent })
  const missing = env && !env.ok
  const open = beside => {
    goStation(a.station, a.project)
    if (CB.mounts > 0) return
    openBench({ beside })
  }
  const live = a.view === 'crash' && project ? projectPanicCurrent(project) : false
  const pins = a.view === 'pins'
  const visual = !project ? null
    : pins ? h(DirectivePins, { key: 'v', project })
      : a.view === 'wire' ? h(MiniSchematic, { key: 'v', project })
        : a.view === 'crash' ? h(MiniFrame, { key: 'v', project, live }) : null
  // the frame row replaces the "#0" text row; the pins card carries its own key figures and list (DirectivePins)
  const rows = pins ? [] : sum.rows.filter(r => !(a.view === 'crash' && r.k === 't' && project?.debug?.last_panic?.top_frame))
  return h(Fragment, null, h(Styles, null),
    h('div', { className: 'cb-root cb-dcard cb-bracket', 'data-cb': 'directive-card', 'data-cb-look': ui.look, 'data-cb-view': a.view, 'data-cb-project': a.project,
      'data-cb-session': sessionId || undefined, 'data-cb-audit-root': 'directive' },
    h('div', { className: 'cb-dcard-head' },
      h('span', { className: 'cb-brand cb-brand--sm' }, '◢ BENCH'),
      h('b', null, a.project), h(Label, null, `${STATIONS.find(s => s.id === a.station)?.n || ''} // ${a.title}`),
      project?.simulated ? h(SimBanner, { compact: true, dataCb: 'directive-sim' }) : null),
    missing ? h('p', { className: 'cb-why cb-warn' }, env.error?.code === 'project_not_found' ? `No bench project “${a.project}”.` : env.error?.message || 'Bench backend not available.')
      : !project ? h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'loading')
        : [pins ? null : h('div', { key: 'hl', className: `cb-dcard-hl cb-${sum.headline.tone}`, 'data-cb': 'directive-headline' }, sum.headline.text),
          visual,
          rows.length ? h('div', { key: 'r', className: 'cb-kv cb-kv--dcard', 'data-cb': 'directive-rows' },
            rows.map(r => [h('span', { key: `${r.k}l` }, r.label), h('b', { key: `${r.k}v`, className: `cb-${r.tone}` }, r.value)])) : null],
    h('div', { className: 'cb-actions' },
      // the card's one primary action
      h(Btn, { size: 'sm', 'data-cb': 'directive-open', onClick: () => open(true) }, 'Open in Bench ›'))))
}
