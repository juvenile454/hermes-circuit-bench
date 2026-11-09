// BoardView: the board model. An SVG layer (lib/art-board.js, aria-hidden)
// draws the pcb, module, header strips with pads and state rings, reservation brackets, ports, buttons and on-board
// parts; the DOM above it carries the meaning: one button.cb-pin per GPIO (data-cb="pin-<gpio>", data-cb-state,
// aria-pressed, aria-label with the state word), labels and tags in fixed columns outside the pcb, and transparent
// anchors over ports, buttons, antenna and brackets (title + screen-reader text). Both layers take their numbers from
// boardGeom() (lib/board-geom.js), the DOM through the CSS variables on [data-cb=board].
// Any layout from data/boards, with or without `drawing` (without: generic placement, data-cb-schematic="true").

let BOARD_VIEW_SEQ = 0

/** State symbol for the board labels and legend: the kit Glyph's shapes (lib/art.js), without data-cb-state, so the
 *  E2E and tests that count [data-cb-state=…] see one element per pin row (the row itself). Always decorative. */
function BoardGlyph({ state, className }) {
  if (!ART_STATE_WORDS[state]) return null
  return h('svg', { className: cx('cb-glyph', `cb-glyph--${state}`, className), width: 12, height: 12, viewBox: '0 0 12 12', focusable: 'false', 'aria-hidden': 'true',
    'data-cb-glyph': state },
  artGlyphShapes(state, 6, 6, 'currentColor', state === 'assigned_blocked' ? 'var(--cb-bad-fill)' : 'var(--cb-ink)').map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}

/** Nearest scrolling ancestor inside the own root (the PLAN main column, or the work area when stacked). */
function boardScroller(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY
    if (oy === 'auto' || oy === 'scroll') return p
    if (p.classList?.contains('cb-root')) return null
  }
  return null
}

/** Room for the board: width of the wrap, height from the board top to the visible end of the scroll area. */
function useBoardBox(ref) {
  const [box, setBox] = useState(null)
  const [, setTick] = useState(0)
  // loop breaker: a size change that moves a scrollbar or wraps the toolbar can feed back; at most 4 updates / 0.5 s
  const burst = useRef({ n: 0, t: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const sc = boardScroller(el)
    const r = el.getBoundingClientRect()
    let hh = null
    if (sc) {
      const sr = sc.getBoundingClientRect()
      const pad = parseFloat(getComputedStyle(sc).paddingBottom) || 0
      hh = Math.floor(sc.clientHeight - (r.top - sr.top + sc.scrollTop) - Math.min(pad, 10))
      // room for the legend caption
      const cap = el.nextElementSibling
      if (cap && cap.classList.contains('cb-legend--cap')) hh -= Math.ceil(cap.getBoundingClientRect().height + (parseFloat(getComputedStyle(cap).marginTop) || 0))
    }
    const w = Math.floor(el.clientWidth)
    if (box && box.w === w && box.h === hh) return
    const now = Date.now()
    if (now - burst.current.t > 500) burst.current = { n: 0, t: now }
    if (++burst.current.n > 4) return
    setBox({ w, h: hh })
  })
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(() => setTick(t => t + 1))
    ro.observe(el)
    const sc = boardScroller(el)
    if (sc) ro.observe(sc)
    return () => ro.disconnect()
  }, [])
  return box
}

function BoardPin({ slot, side, selected, suggested, pulse, requested, onSelect }) {
  const { hp, view, art } = slot
  const interactive = view.gpio !== null
  const word = pinStateWord(view.state)
  const cut = Boolean(view.tag) && !slot.tagFits
  const tag = h('span', { className: 'cb-ptag', title: cut ? view.tag : undefined, 'data-cb-truncate-ok': cut ? 'true' : undefined }, view.tag)
  const name = h('span', { className: 'cb-name' }, view.name)
  const glyph = art ? h(BoardGlyph, { state: art, className: 'cb-pglyph' }) : h('span', { className: 'cb-pglyph cb-pglyph--none', 'aria-hidden': 'true' })
  const pad = h('span', { className: 'cb-pad', 'aria-hidden': 'true' })
  // caret between name and glyph; req = requested blocked pin
  const mark = selected ? h('span', { className: 'cb-mark', 'aria-hidden': 'true', 'data-cb-mark': requested ? 'req' : 'sel', title: requested ? 'requested' : 'selected' }) : null
  const parts = side === 'l' ? [tag, name, mark, glyph, pad] : [pad, glyph, mark, name, tag]
  const props = {
    className: 'cb-pin', 'data-cb': interactive ? `pin-${view.gpio}` : `pin-${hp.header}-${hp.n}`, 'data-cb-state': view.state, 'data-cb-art': art || 'unchecked',
    'data-cb-suggest': suggested ? 'true' : undefined, 'data-cb-pulse': pulse ? 'true' : undefined, title: `${hp.header}-${hp.n} · ${word} · ${view.title}`
  }
  if (!interactive) return h('div', props, parts, h('span', { className: 'cb-sr' }, view.title))
  return h('button', { ...props, type: 'button', 'aria-pressed': selected ? 'true' : 'false',
    'aria-label': `${view.name}, ${word}${suggested ? ', suggested' : ''}: ${view.title}, header ${hp.header} pin ${hp.n}`,
    onClick: () => onSelect(view.gpio) }, parts)
}

// data-cb anchors of the pcb notes (boardArtModel note ids)
const BOARD_NOTE_CB = { unknown: 'board-variant-unknown', spi: 'board-reserve', quad: 'board-quad' }
const BOARD_PORT_WORD = { usb_serial_jtag: 'USB Serial/JTAG', usb_uart_bridge: 'USB-to-UART bridge', usb_otg: 'USB OTG', rj45: 'RJ45 Ethernet jack' }
const BOARD_PART_WORD = { micro_usb: 'Micro-USB', usb_c: 'USB-C', generic_usb: 'connector form not quoted', rj45: 'RJ45' }

/** The anchors over the drawing (module name, antenna, ports, buttons, notes): transparent, title + sr text. */
function BoardAnchors({ layout, model, plan, g, detected }) {
  const ports = boardPorts(layout)
  const at = (x, y, w, hh) => ({ left: `${g.gutterL + x}px`, top: `${y}px`, width: `${w}px`, height: `${hh}px` })
  const partBox = p => {
    const fp = p.fp
    const bx = p.x + (fp.labelPos === 'right' ? 0 : (fp.w - fp.body.w) / 2)
    const by = fp.labelPos === 'above' ? p.y + fp.h - fp.body.h : p.y
    return at(bx, by, fp.body.w, fp.body.h)
  }
  const m = plan.module
  const drawnPort = u => plan.parts.find(p => (p.part.kind === 'usb_port' || p.part.kind === 'rj45') && (p.part.ref === u.label || (u.connector && p.part.kind === u.kind)))
  const drawnBtn = b => plan.parts.find(p => p.part.kind === 'button' && p.part.label === b)
  const live = u => Boolean(!u.connector && detected && /usb|jtag/i.test(u.kind) && /ACM|usbmodem/i.test(detected.port || ''))
  return h('div', { className: 'cb-module', 'data-cb': 'board-module' },
    h('span', { className: 'cb-banchor', style: at(m.can.x, m.can.y, m.can.w, m.can.h), title: [model.module.chip, model.module.name,
      model.module.flash_mb ? `${model.module.flash_mb} MB flash` : null, model.module.psram_mb ? `${model.module.psram_mb} MB PSRAM` : null].filter(Boolean).join(' · ') },
    h('span', { className: 'cb-sr' }, `${model.module.chip} module `), h('span', { className: 'cb-sr', 'data-cb': 'board-module-name' }, model.module.name)),
    // antenna: null in the layout → no antenna is drawn or named (nothing invented)
    model.module.antennaText ? h('span', { className: 'cb-banchor', 'data-cb': 'board-antenna', style: at(m.x, m.y, m.w, Math.max(m.antH, 18)),
      title: model.module.antenna === 'pcb' ? 'PCB antenna: keep metal clear (no ground plane, no metal case above it)' : 'Antenna connector (IPEX/U.FL): external antenna' },
    h('span', { className: 'cb-sr' }, model.module.antennaText)) : null,
    plan.notes.map((n, i) => {
      const note = model.notes[i]
      return h('div', { key: note.id, className: `cb-bnote cb-bnote--${note.tone}`, 'data-cb': BOARD_NOTE_CB[note.id], title: note.title, style: at(n.x, n.y, n.w, n.h) },
        note.tone === 'warn' ? h(BoardGlyph, { state: 'caution' }) : null, h('span', null, note.text))
    }),
    // USB ports, then connectors (WT32: RJ45 LAN instead of USB), in data order
    h('div', { className: 'cb-usb', 'data-cb': 'board-ports' }, ports.map(u => {
      const p = drawnPort(u)
      return h('span', { key: `${u.kind}-${u.label}`, 'data-cb-port': u.kind, className: 'cb-banchor cb-bport', 'data-cb-live': live(u) ? 'true' : 'false',
        'data-cb-schematic': p?.part.schematic || p?.part.connector === 'generic_usb' ? 'true' : undefined, style: p ? partBox(p) : { display: 'none' },
        title: `${u.title}${p ? ` · ${BOARD_PART_WORD[p.part.connector] || ''}` : ''}` }, h('span', { className: 'cb-sr' }, `${u.label} ${BOARD_PORT_WORD[u.kind] || ''}`))
    })),
    h('div', { className: 'cb-btns', 'data-cb': 'board-buttons' }, model.buttons.map(b => {
      const p = drawnBtn(b)
      return h('span', { key: b, className: 'cb-banchor', style: p ? partBox(p) : { display: 'none' }, title: `${b} button`,
        'data-cb-schematic': p?.part.schematic ? 'true' : undefined }, h('span', { className: 'cb-sr' }, `[${b}]`))
    })))
}

function boardRowsOf(layout, side) {
  return headerRows(layout)[side]
}

function BoardView({ layoutState, mapState, rows, board, selected, suggestPins, onSelect }) {
  const pulse = sdk.useValue($pulse)
  const wrapRef = useRef(null)
  const prefix = useRef(null)
  if (!prefix.current) prefix.current = `board-${++BOARD_VIEW_SEQ}`
  const box = useBoardBox(wrapRef)
  const layout = layoutState.layout
  const ready = layoutState.status === 'ready' && layout
  const chip = chipInfo(board.chip)
  const variant = variantInfo(board.chip, board.variant)
  const detected = $project.get()?.board?.detected
  // the detected chip revision belongs to the detected chip only (not to a what-if board of another chip)
  const sameChip = detected?.chip && /^(ESP32(?:-[A-Z0-9]+)?)/i.exec(detected.chip)?.[1]?.toUpperCase() === String(chip?.label || '').toUpperCase()
  const rev = sameChip ? /revision\s+(v[\d.]+)/i.exec(detected.chip)?.[1] : null
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null)
  const used = new Map(rows.map(r => [r.pin, r]))
  const liveRefs = (Array.isArray(layout?.usb) ? layout.usb : [])
    .filter(u => detected && /usb|jtag/i.test(u.kind) && /ACM|usbmodem/i.test(detected.port || '')).map(u => String(u.label))
  const model = ready ? boardArtModel({ layout, chip, variant, base, used, selected, suggest: suggestPins, live: liveRefs, rev }) : null
  const tags = model ? [...model.views.left, ...model.views.right].filter(s => s.view).map(s => boardTagW(s.view.tag)) : []
  // the console counts as open only when it really takes its height (an idle or collapsed bar leaves the room
  // to the board: pitch up to 28 instead of 20)
  const consMode = useConsoleMode(sdk.useValue($project))
  const g = ready ? boardGeom({ layout, consoleOpen: consMode === 'open', width: box?.w, height: box?.h, tagWidth: Math.ceil(Math.max(0, ...tags) / 8) * 8 }) : null
  // the SVG string only changes with what it draws (hooks run on every render, before the early returns)
  const svgKey = model ? JSON.stringify([layout.id, model.sides, model.brackets, model.module, model.parts, model.notes.map(n => n.text), model.ledState, model.live, g]) : ''
  const svg = useMemo(() => (model ? artBoard(model, g, { prefix: prefix.current }) : ''), [svgKey])
  if (layoutState.status === 'loading' || layoutState.status === 'idle') return h('div', { className: 'cb-loading', 'data-cb': 'board-loading' }, 'loading board layout')
  if (layoutState.status === 'none') {
    return h('div', { className: 'cb-board-empty', 'data-cb': 'board-none' },
      h(Label, null, '// board view'),
      h('p', { className: 'cb-why' }, `No DevKit header map for ${chipInfo(board.chip)?.label || board.chip} yet. The assignments below are still checked against the chip's pin rules.`),
      h('p', { className: 'cb-dim' }, `Header maps exist for: ${DEVKITS.map(devkitTitle).join(', ')}.`))
  }
  if (layoutState.status === 'error' || !model) {
    return h(EmptyBox, { tone: 'bad', kicker: '// board view', title: 'Board layout unavailable', dataCb: 'board-error',
      actions: [h(Btn, { key: 'r', kind: 'ghost', onClick: () => loadBoard(layoutState.id) }, 'Retry')] },
    h('p', null, layoutState.error?.error?.message || 'The backend did not return the header layout.'))
  }
  const plan = artBoardPlan(model, g)
  const pulsePins = new Set(pulse.pins)
  const all = [...boardRowsOf(layout, 'left'), ...boardRowsOf(layout, 'right')]
  const col = side => {
    const s = side === 'left' ? 'l' : 'r'
    const out = []
    for (const slot of model.views[side]) {
      if (slot.sep !== undefined) {
        out.push(h('div', { key: `sep-${slot.sep}-${slot.slot}`, className: 'cb-hdr-sep cb-label', 'data-cb': 'header-sep' }, h('span', null, slot.sep)))
        continue
      }
      const { hp, view } = slot
      const u = Number.isInteger(hp.gpio) ? used.get(hp.gpio) : null
      out.push(h(BoardPin, { key: `${hp.header}-${hp.n}`, slot: { ...slot, mark: g.markW > 0, tagFits: g.tagFits }, side: s,
        selected: view.gpio !== null && view.gpio === selected, suggested: view.gpio !== null && suggestPins.includes(view.gpio),
        pulse: view.gpio !== null && pulsePins.has(view.gpio), requested: Boolean(u && u.verdict === 'blocked'), onSelect }))
    }
    // reservation brackets: transparent anchors in the lane with the full text (title + screen reader); the octal
    // PSRAM run keeps its anchor name psram-bracket
    for (const br of model.brackets[side]) {
      const gp = model.views[side].filter(v => v.view && v.slot >= br.from && v.slot <= br.to).map(v => v.hp.gpio).filter(Number.isInteger).sort((a, b) => a - b)
      const octal = br.label === 'OCTAL PSRAM'
      const missing = octal ? [33, 34, 35, 36, 37].filter(x => !all.some(r => r.gpio === x)) : []
      const text = octal
        ? `Octal PSRAM: GPIO33–37 are wired to the PSRAM bus on this module; IO${gp[0]}–${gp[gp.length - 1]} reserved${missing.length ? `; GPIO${missing.join('/')} not on the header` : ''}`
        : `${br.label}: GPIO${gp.join('/')} reserved (${br.tone === 'bad' ? 'blocked' : 'caution'})`
      out.push(h('span', { key: `br-${br.from}`, className: 'cb-bbracket', 'data-cb': octal ? 'psram-bracket' : 'board-bracket', 'data-cb-tone': br.tone, title: text,
        style: { top: `${br.from * g.pitch - 2}px`, height: `${(br.to - br.from + 1) * g.pitch - g.rowGap + 4}px` } }, h('span', { className: 'cb-sr' }, text)))
    }
    return h('div', { className: `cb-col cb-col--${s}`, 'data-cb': `header-${side}` }, out)
  }
  const ids = side => headerIds(boardRowsOf(layout, side))
  return h('div', { className: 'cb-board-wrap', ref: wrapRef },
    h('div', { className: 'cb-board', 'data-cb': 'board', 'data-cb-map': mapState.status, 'data-cb-board': layout.id, role: 'group',
      'data-cb-audit-root': 'board', 'data-cb-pitch': g.pitch, 'data-cb-schematic': model.schematic ? 'true' : undefined,
      'aria-label': `${layout.title}${layout.revision ? ` ${layout.revision}` : ''} header map, schematic, not to scale`, style: boardGeomVars(g) },
    h('div', { className: 'cb-board-art', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: svg } }),
    h('div', { className: 'cb-board-hdr cb-label', title: ids('left').join(' · ') }, boardRowsOf(layout, 'left')[0]?.header || 'J1'),
    h('div', { className: 'cb-board-hdr cb-label', title: ids('right').join(' · ') }, boardRowsOf(layout, 'right')[0]?.header || 'J3'),
    h(BoardAnchors, { layout, model, plan, g, detected }),
    col('left'), col('right')))
}

/** Board-level warnings of the layout (e.g. WT32 "Feed either 3V3 or 5V, never both."):
 *  danger first, each with symbol and word, never colour only. `compact` = one line each above the board (PLAN). */
function BoardWarnings({ layout, sources = [], compact = false }) {
  const ws = boardWarnings(layout)
  if (!ws.length) return null
  const title = devkitTitle(devkitInfo(layout?.id)) || layout?.title || 'board'
  const list = h('ul', { className: 'cb-bwarn-list' }, ws.map(w => h('li', { key: w.id, className: `cb-bwarn cb-bwarn--${w.tone}`, 'data-cb': 'board-warning',
    'data-cb-severity': w.severity, title: w.id },
  h('span', { className: 'cb-bwarn-k' }, h('span', { 'aria-hidden': 'true' }, w.symbol), ` ${w.word}`),
  h('span', { className: 'cb-bwarn-m' }, w.message))))
  if (compact) {
    return h('div', { className: 'cb-bwarns', 'data-cb': 'board-warnings', role: 'note', 'aria-label': `${title}: board warnings` }, list)
  }
  const ids = ws.map(w => w.source_id).filter(Boolean)
  return h('div', { className: `cb-card cb-bracket cb-bwarn-card${ws.some(w => w.severity === 'danger') ? ' cb-bracket--bad' : ''}`, 'data-cb': 'insp-board-warnings',
    role: 'note', 'aria-label': `${title}: board warnings` },
  h(Label, null, `// board · ${title}`), list, h(SourceLine, { sources: (sources || []).filter(s => ids.includes(s.id)) }))
}

/** Legend with the same symbols as the board: shape + word, colour only adds to it. */
function Legend({ suggesting = false, kinds = [], dataCb = 'legend', className }) {
  const item = (state, word, cb) => h('span', { key: state, 'data-cb': cb, 'data-cb-legend': state, role: 'listitem' }, h(BoardGlyph, { state }), word)
  return h('div', { className: cx('cb-legend', className), 'data-cb': dataCb, role: 'list', 'aria-label': 'Pin states' },
    item('assigned', 'assigned'), item('free', 'free'), item('caution', 'caution'), item('blocked', 'blocked'),
    item('power', 'power'), item('ground', 'GND · RST'),
    kinds.includes('signal') ? item('signal', 'signal', 'legend-signal') : null,
    kinds.includes('nc') ? item('nc', 'not connected', 'legend-nc') : null,
    suggesting ? h('span', { key: 'sug', className: 'cb-legend-sug', 'data-cb': 'legend-suggested', role: 'listitem' }, h('i', { 'aria-hidden': 'true' }), 'suggested') : null)
}

// ─── Compact model and live twin ──────────────────────────────────────────────────────────────────────────────────
// One compact board model (lib/art-board.js artBoardTwin) for the chat card and the twins in 05 FLASH / 06 DEBUG.
// Every instance has its own SVG id prefix. The twin only shows store events: the lit port, the flash job, a panic,
// arriving serial lines. Reduced motion: the pulse dots stand still (14-styles-board.js).

let BOARD_TWIN_SEQ = 0

/** Stable id prefix of one instance (`chat-3`, `flash-4` …): several models on one page never share an id. */
function useTwinPrefix(kind) {
  const ref = useRef(null)
  if (!ref.current) ref.current = `${kind}-${++BOARD_TWIN_SEQ}`
  return ref.current
}

/** Pins in words for the model's aria-label: "LASER on GPIO14 (ok), …". */
function twinPinsText(project) {
  return (project?.assignments || []).map(a => `${a.role} on GPIO${a.pin} (${a.verdict || 'not checked'})`).join(', ') || 'no assignments'
}

/**
 * The compact model: pcb, module, strips, pads with their state, ports; no text in the drawing (it scales), the
 * stamp on the module and the caption are DOM. port = GET /ports entry (lights only when its kind leads to exactly
 * one drawn usb port), flash = running | done | failed | null, stamp = { tone, text } | null.
 */
function BoardTwin({ layout, project, base = null, prefix, port = null, flash = null, stamp = null, turn = true, dataCb = 'board-twin', label, caption, className, hot = null }) {
  const b = project?.board || {}
  const model = boardArtModel({ layout, chip: chipInfo(b.chip), variant: variantInfo(b.chip, b.variant), base: base || new Map(),
    used: new Map((project?.assignments || []).map(a => [a.pin, a])) })
  const g = boardGeom({ layout, mode: 'compact' })
  const ref = twinPortRef(port, model, FLASH_PORT_USB)
  const key = JSON.stringify([layout.id, prefix, model.sides, model.brackets, model.module, model.ledState, ref, flash, turn])
  const art = useMemo(() => artBoardTwin(model, g, { prefix, turn, port: ref, flash }), [key])
  // chat card hover coupling: DOM ring on the pad
  const ring = Number.isInteger(hot) ? artBoardTwinPad(model, g, hot, turn) : null
  return h('div', { className: cx('cb-twin', className), 'data-cb': dataCb, 'data-cb-board': layout.id, 'data-cb-flash': flash || undefined,
    'data-cb-port-lit': art.port || undefined, 'data-cb-turn': turn ? 'true' : undefined },
  h('div', { className: 'cb-twin-box', role: 'img', 'aria-label': label || `${layout.title} board model: ${twinPinsText(project)}` },
    h('div', { className: 'cb-twin-art', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: art.svg } }),
    stamp ? h('span', { className: 'cb-twin-stamp', 'data-cb': `${dataCb}-stamp`, 'data-cb-tone': stamp.tone, 'aria-hidden': 'true',
      style: { left: `${art.module.x}%`, top: `${art.module.y}%` } }, h(Stamp, { tone: stamp.tone }, stamp.text)) : null,
    ring ? h('span', { className: 'cb-twin-ring', 'data-cb': `${dataCb}-hot`, 'data-cb-gpio': hot, 'aria-hidden': 'true',
      style: { left: `${ring.x}%`, top: `${ring.y}%` } }) : null),
  caption === false ? null : h('div', { className: 'cb-twin-cap' },
    h('span', { className: 'cb-twin-cap-t' }, caption || devkitTitle(devkitInfo(layout.id)) || layout.title),
    h('span', { className: 'cb-dim' }, 'schematic · not to scale')))
}

/** Pin map of the project's own board for a twin in the Bench: the loaded map, unless PLAN shows a what-if board. */
function twinBase(project, layout) {
  const map = $map.get()
  if (!layout || isWhatIf() || map.status !== 'ready' || !map.env?.ok || $board.get().id !== layout.id || project?.board?.devkit !== layout.id) return null
  return mapByGpio(map.env.result)
}

const TWIN_FLASH_STAMP = { running: { tone: 'active', text: '◴ FLASHING' }, done: { tone: 'ok', text: '✓ FLASHED' }, failed: { tone: 'bad', text: '✕ FAILED' } }

/** Live twin in 05 FLASH (inspector): the port of the selected serial port lights; during the flash job of this
 *  session the pulse runs from the flash target's port to the module, then the result stamp. */
function FlashTwin({ project }) {
  const flow = sdk.useValue($flow)
  const ports = sdk.useValue($ports)
  const jobs = sdk.useValue($jobs)
  sdk.useValue($map)
  const prefix = useTwinPrefix('flash')
  const layout = useBoardLayout(project?.board?.devkit)
  if (!layout || !project) return null
  const flash = twinFlashState(jobProgress(jobs.flash))
  const device = flash ? project.board?.detected?.port || flow.port : flow.port
  const entry = (ports.ports || []).find(p => p.device === device) || null
  const stamp = flash ? TWIN_FLASH_STAMP[flash] : null
  const lit = entry && !entry.simulated && twinPortRef(entry, boardArtModel({ layout }), FLASH_PORT_USB)
  const portWord = !entry ? 'no port selected' : entry.simulated ? 'simulated · no port lit' : lit ? `on the ${lit} port` : 'port kind unknown · none lit'
  const portText = entry ? `${device}: ${portWord}` : portWord
  return h('div', { className: 'cb-card cb-twin-card', 'data-cb': 'flash-twin' },
    h(Label, null, '// live twin'),
    h(BoardTwin, { layout, project, base: twinBase(project, layout), prefix, port: entry, flash, stamp, dataCb: 'flash-twin-model',
      label: `${layout.title} board model. ${portText}.${flash ? ` Flash ${flash}.` : ''}` }),
    h('p', { className: 'cb-twin-note', 'data-cb': 'flash-twin-port', 'data-cb-lit': lit ? 'true' : 'false' },
      h(Label, null, 'port'), entry ? h('b', { title: device }, device) : null, h('span', { className: lit ? 'cb-active-t' : 'cb-dim' }, portWord)))
}

/** TX/RX of the board while the monitor is open: TX (board → Bench) lights only while serial lines arrive; the Bench
 *  never writes to the port, so RX stays dark. */
function TwinSerialLeds({ tx, open }) {
  const led = (id, on, word, title) => h('span', { key: id, className: 'cb-twin-led', 'data-cb': `twin-${id}`, 'data-cb-on': on ? 'true' : 'false', title },
    h('i', { 'aria-hidden': 'true' }), h('b', null, id.toUpperCase()), h('span', { className: 'cb-dim' }, word))
  return h('div', { className: 'cb-twin-leds', role: 'status', 'aria-label': `TX ${tx ? 'lines arriving' : 'idle'}, RX idle` },
    led('tx', tx, tx ? 'lines arriving' : open ? 'idle' : 'monitor closed', 'Board transmits: lights while serial lines arrive'),
    led('rx', false, 'nothing sent', 'The Bench only reads the port, nothing is sent to the board'))
}

/** Arriving serial lines (sequence grows) → active for TWIN_RX_WINDOW_MS, then a re-render turns the dot off. */
function useSerialActivity(buf) {
  const ref = useRef(null)
  const [, setTick] = useState(0)
  const now = Date.now()
  const st = twinSerialTrack(ref.current, buf, now)
  ref.current = st
  useEffect(() => {
    if (!st.active) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => setTick(x => x + 1), Math.max(50, st.until - Date.now() + 30))
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [st.until])
  return st.active
}

/** Live twin in 06 DEBUG (monitor card): the monitor's port lights, the panic stamp sits on the module while the
 *  panic is current, TX lights while lines arrive. */
function DebugTwin({ project }) {
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const ports = sdk.useValue($ports)
  sdk.useValue($map)
  const prefix = useTwinPrefix('debug')
  const layout = useBoardLayout(project?.board?.devkit)
  const { data } = usePanicData(project)
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const tx = useSerialActivity(open ? serial.buf : null) && open
  if (!layout || !project) return null
  const entry = open ? (ports.ports || []).find(p => p.device === mon.port) || null : null
  const stamp = data ? { tone: 'bad', text: 'PANIC' } : null
  return h('div', { className: 'cb-twin-row', 'data-cb': 'debug-twin', 'data-cb-panic': data ? 'true' : 'false' },
    h(Label, { className: 'cb-twin-lab' }, '// live twin'),
    h(BoardTwin, { layout, project, base: twinBase(project, layout), prefix, port: entry, stamp, dataCb: 'debug-twin-model',
      label: `${layout.title} board model.${data ? ` Panic: ${data.title}.` : ''}${open ? ` Monitor open on ${mon.port}.` : ''}` }),
    h(TwinSerialLeds, { tx, open }))
}
