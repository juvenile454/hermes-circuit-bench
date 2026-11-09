// Station 03 WIRE: building block + parameters → POST /schematic, the SVG inline in bench colours (currentColor),
// wiring table; hovering a part, a net (wire, port, net label) or a table row highlights the same thing in the plan
// and in the tables; Save SVG via ctx.files (when the host has it) or a Blob download.
// Stroke widths and net colours come from the backend's data-kind / data-net attributes
// (15-styles-wire.js); the plan is fitted and centred, never below scale 1 (text ≥ 10 px), Save SVG sits in the
// plan's header, danger/caution warnings are warning cards under the parts.
// Module catalog: grouped block pick; the module block draws a module part of the project.

function fmtParam(v, unit) {
  return formatSI(v, '').replace(/\s+/g, '')
}

async function saveSvg(svg, name) {
  const files = CB.ctx?.files
  if (files && typeof files.requestFolder === 'function' && typeof files.writeText === 'function') {
    const pick = await files.requestFolder()
    if (!pick?.ok || !pick.folder) return pick?.ok ? 'cancelled' : 'failed'
    const res = await files.writeText(pick.folder.id, name, svg)
    if (res?.ok) { setNotice(`Saved ${name} in ${pick.folder.name}.`, 'ok'); return 'files' }
    setNotice(res?.message || 'Could not save the SVG.', 'bad')
    return 'failed'
  }
  if (typeof Blob === 'undefined' || typeof URL?.createObjectURL !== 'function' || typeof document === 'undefined') return 'failed'
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.rel = 'noopener'
  a.click() // a detached anchor with `download` saves the file (own element, no app markup)
  timersOf(CB.ctx).setTimeout(() => URL.revokeObjectURL(url), 2000)
  return 'download'
}

// the blocks the backend knows, asked once (catalogue route if the API has one, else the hint of a
// render without a block); no names (fixtures, older backends) = the four base blocks.
const $wireBlocks = sdk.atom({ status: 'idle', names: null, env: null })

async function loadWireBlocks() {
  if ($wireBlocks.get().status !== 'idle') return
  $wireBlocks.set({ status: 'loading', names: null, env: null })
  const env = typeof CB.api?.schematicBlocks === 'function' ? await CB.api.schematicBlocks() : await CB.api.schematic({})
  $wireBlocks.set({ status: 'ready', names: wireBlockNames(env), env: env?.ok && Array.isArray(env.result?.blocks) ? env : null })
}

/** Block pick: one Seg per group inside [data-cb=seg-block]; one group = the plain Seg as before. */
function WireBlockPick({ groups, value, onChange }) {
  const seg = (g, dataCb) => h(Seg, { key: g.id, label: groups.length > 1 ? `Building block · ${g.id}` : 'Building block', dataCb, value,
    options: g.blocks.map(b => ({ id: b.block, label: b.block.replace(/_/g, ' '), title: b.title })), onChange })
  if (groups.length < 2) return seg(groups[0] || { id: 'basic', blocks: [] }, 'seg-block')
  return h('div', { className: 'cb-wblocks', 'data-cb': 'seg-block', role: 'group', 'aria-label': 'Building block' },
    groups.map(g => h('span', { key: g.id, className: 'cb-wblocks-g', 'data-cb-group': g.id }, h('span', { className: 'cb-wblocks-k' }, g.id), seg(g, undefined))))
}

const WIRE_NET_GLYPH = { power: 'power', ground: 'ground', signal: 'signal' }
const WIRE_NET_WORD = { power: 'supply', ground: 'ground', signal: 'signal' }

/** Net name as a chip in its net colour (supply tinted, ground dashed): the name carries the meaning, the colour
 *  matches the net in the plan. A long name is cut with the full name as title. */
function WireNetChip({ net, cls }) {
  return h('span', { className: `cb-netchip cb-netchip--${cls}`, 'data-cb': 'net-chip', 'data-cb-net-class': cls, title: `${net} · ${WIRE_NET_WORD[cls]} net`, 'data-cb-truncate-ok': '' },
    h('span', { className: 'cb-netchip-t' }, net))
}

/** The schematic: header (title, net legend, actions), the backend SVG fitted and centred, caption. `hl` is
 *  {refs, net} (lib/wire.js wireHl); matching SVG elements get data-cb-on="true" (own DOM, attribute only). */
function SchematicView({ svg, hl, onHover, caption = null, title = '// schematic', actions = null }) {
  const ref = useRef(null)
  const safe = sanitizeSvg(svg)
  const vb = safe.ok ? svgViewBox(safe.svg) : null
  // one object per SVG text: a new {__html} object makes React write innerHTML again (and drop data-cb-on)
  const html = useMemo(() => ({ __html: safe.ok ? safe.svg : '' }), [safe.ok ? safe.svg : ''])
  // after every commit (cheap: a few dozen elements), so the marks always match `hl`
  useEffect(() => {
    const root = ref.current
    if (!root || typeof root.querySelectorAll !== 'function') return
    for (const el of root.querySelectorAll('[data-ref],[data-net],[data-pin]')) {
      const on = wireHlHas(hl, { ref: el.getAttribute('data-ref'), net: el.getAttribute('data-net'), pin: el.getAttribute('data-pin') })
      if (on) el.setAttribute('data-cb-on', 'true'); else el.removeAttribute('data-cb-on')
    }
  })
  if (!safe.ok) return h('div', { className: 'cb-jobline cb-bad', role: 'alert' }, `✕ Schematic not shown: ${safe.reason}`)
  // the plan fills the stage (meet, centred) and never shrinks below scale 1: the stage grows instead
  const size = vb ? { minWidth: `${vb.w}px`, minHeight: `${vb.h}px` } : undefined
  return h('div', { className: 'cb-svgwrap cb-bracket', 'data-cb': 'schematic', 'data-cb-audit-root': 'schematic' },
    h('div', { className: 'cb-svghead', 'data-cb': 'schematic-head' },
      h(Label, null, '// schematic', title !== '// schematic' ? h('span', { className: 'cb-svghead-b' }, title.replace(/^\/\/ schematic/, '')) : null),
      h('span', { className: 'cb-netlegend', 'data-cb': 'net-legend' },
        ['power', 'ground', 'signal'].map(c => h('span', { key: c, className: `cb-netkey cb-netchip--${c}` },
          h(Glyph, { state: WIRE_NET_GLYPH[c], decorative: true }), WIRE_NET_WORD[c]))),
      actions ? h('span', { className: 'cb-svghead-act' }, actions) : null),
    h('div', { className: 'cb-svgstage', style: vb ? { minHeight: `${vb.h}px` } : undefined },
      h('div', { className: 'cb-svg', ref, style: size, 'data-cb-hl': hl ? (hl.net ? 'net' : 'part') : undefined, role: 'img',
        onMouseOver: e => onHover(wireHoverTarget(e.target, ref.current)), onMouseLeave: () => onHover(null),
        dangerouslySetInnerHTML: html })),
    caption ? h('span', { className: 'cb-svgcap', 'data-cb': 'schematic-caption' }, caption) : null)
}

function StationWire({ project }) {
  const wire = sdk.useValue($wire)
  const wb = sdk.useValue($wireBlocks)
  useEffect(() => { loadWireBlocks() }, [])
  const blocks = wireBlockList(wb.names, wb.env)
  const mods = wireModuleParts(project)
  const circuits = project?.circuits || []
  // a project without circuits starts empty: nothing is drawn until a block is picked (no example circuit)
  const [blockId, setBlockId] = useState(circuits[0]?.block || null)
  const [circuitId, setCircuitId] = useState(circuits[0]?.id || null)
  const block = blockId ? wireBlock(blockId, blocks) || WIRE_BLOCKS[0] : null
  const stored = circuits.find(c => c.id === circuitId) || null
  const [form, setForm] = useState(() => block ? wireForm(block, stored?.block === block.block ? stored.params : {}, fmtParam) : {})
  const [errors, setErrors] = useState({})
  const [hl, setHlRaw] = useState(null)
  // the same highlight again (mouseover bubbles from every child) keeps the old state: no re-render per event
  const setHl = next => setHlRaw(prev => wireHlKey(prev) === wireHlKey(next) ? prev : next)
  const [newId, setNewId] = useState('')
  const gpio = stored ? circuitGpio(project, stored) : null
  const partless = Boolean(block?.params.some(p => p.part)) && !mods.length
  const render = (b = block, f = form, cId = circuitId) => {
    if (!b) return
    const r = buildWireParams(b, f, parseQuantity)
    setErrors(r.errors)
    if (!r.ok) return
    const c = circuits.find(x => x.id === cId)
    renderSchematic(b.block, r.params, { circuit: cId, gpio: c ? circuitGpio(project, c) : null })
  }
  useEffect(() => { if (wire.status === 'idle' && stored) render() }, [])
  const pickCircuit = id => {
    const c = circuits.find(x => x.id === id)
    if (!c) return
    const b = wireBlock(c.block, blocks) || WIRE_BLOCKS[0]
    const f = wireForm(b, c.params, fmtParam)
    setCircuitId(id); setBlockId(b.block); setForm(f)
    render(b, f, id)
  }
  const pickBlock = id => {
    const b = wireBlock(id, blocks)
    const f = wireForm(b, {}, fmtParam)
    if (b.params.some(p => p.part) && !f.part) f.part = mods[0]?.ref || ''
    setBlockId(id); setCircuitId(null); setForm(f); setErrors({})
    if (!b.params.some(p => p.part) || f.part) render(b, f, null)
    else $wire.set({ status: 'idle', key: null, env: null, circuit: null }) // no module part: nothing to draw
  }
  const env = wire.env
  const res = env?.ok ? env.result : null
  const rows = wiringRows(res?.wiring)
  const warn = wireWarnings(env?.warnings)
  const fileName = svgFileName(project, circuitId || block?.block || 'circuit')
  const gpioRole = gpio !== null ? project.assignments.find(a => a.pin === gpio)?.role || '' : ''
  // the drawing gets the whole main area (toolbar above, nothing below); parameters live in the inspector
  return [
    h('main', { key: 'main', className: 'cb-main cb-station cb-main--fill', 'data-cb': 'station-wire' },
      h(DecodeTitle, { text: '03 // WIRING', meta: res ? env.summary : 'schematic per building block' }),
      h('div', { className: 'cb-toolbar' },
        circuits.length ? h('div', { className: 'cb-group' }, h(Label, null, 'project'),
          h(Seg, { label: 'Project circuits', dataCb: 'seg-circuit', value: circuitId, options: circuits.map(c => ({ id: c.id, label: c.id, title: c.block })), onChange: pickCircuit })) : null,
        h('div', { className: 'cb-group cb-group--wblocks' }, h(Label, null, 'block'),
          h(WireBlockPick, { groups: wireGroups(blocks), value: circuitId ? null : blockId, onChange: pickBlock }))),
      env && !env.ok ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'wire-error', 'data-cb-code': env.error?.code || undefined },
        h('span', null, `✕ ${env.error?.message || env.summary}`), env.error?.hint ? h('span', { className: 'cb-dim' }, env.error.hint) : null) : null,
      res ? h(SchematicView, { svg: res.svg, hl, onHover: setHl, title: `// schematic · ${String(res.block || block?.block || '').replace(/_/g, ' ')}`,
        actions: h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'wire-save',
          title: typeof CB.ctx?.files?.writeText === 'function' ? 'Save into a folder you pick' : `Download ${fileName}`, onClick: () => saveSvg(res.svg, fileName) }, 'Save SVG'),
        caption: gpio !== null ? `drawn on GPIO${gpio}${gpioRole ? ` · ${gpioRole}` : ''}`
          : circuitId ? null : 'preview · not in the project until you add it' })
        : wire.status === 'loading' ? h('div', { className: 'cb-loading' }, 'drawing schematic')
          : !block ? h(EmptyBox, { kicker: '// wiring · no circuit', title: 'No circuit in this project yet', dataCb: 'wire-empty' },
            h('p', null, 'Pick a building block above to draw a preview with its wiring table. Nothing is stored until you click Add to project.'),
            h('p', null, 'Or ask Hermes, e.g. “draw an LED on GPIO4”.')) : null),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' },
      h('div', { className: 'cb-card', 'data-cb': 'wire-params-card' },
        // only "// parameters"; the block is the selected tab above and in the schematic title
        h('div', { className: 'cb-card-head' }, h(Label, null, '// parameters'),
          circuitId ? h('span', { className: 'cb-tag cb-push', title: 'Stored in the project' }, circuitId) : null),
        h('div', { className: 'cb-wireparams', 'data-cb': 'wire-params' },
          !block ? h('p', { className: 'cb-why cb-dim' }, 'Pick a building block to set its parameters.')
            : partless ? h('p', { className: 'cb-why', 'data-cb': 'wire-no-module' }, 'No module part in this project yet. Add one, then pick it here.')
              : !block.params.length ? h('p', { className: 'cb-why cb-dim' }, 'No parameters: the backend draws its defaults.')
                : block.params.map(p => p.part ? h(Field, { key: p.name, id: `cb-w-${p.name}`, label: p.label, value: form[p.name], choice: mods.map(m => m.ref), error: errors[p.name],
                  hint: mods.find(m => m.ref === form[p.name])?.label.replace(/^\S+ /, '') || 'required', dataCb: `w-${p.name}`, onChange: v => setForm(f => ({ ...f, [p.name]: v })) }) : h(Field, { key: p.name, id: `cb-w-${p.name}`, label: p.label, value: form[p.name], choice: p.choice, error: errors[p.name],
            hint: p.unit && parseQuantity(form[p.name], p.unit).ok ? `= ${formatSI(parseQuantity(form[p.name], p.unit).value, p.unit)}` : p.required ? 'required' : '',
            onChange: v => setForm(f => ({ ...f, [p.name]: v })), dataCb: `w-${p.name}`, onEnter: () => render() }))),
        block ? h('div', { className: 'cb-actions', style: { marginTop: '2px' } },
          partless ? h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'wire-add-module', onClick: () => openModules() }, 'Add a module…')
            : h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'wire-render', disabled: wire.status === 'loading', onClick: () => render() }, wire.status === 'loading' ? 'Drawing…' : 'Draw'),
          res && !circuitId ? [h('input', { key: 'i', className: 'cb-inline-in', value: newId, placeholder: 'circuit id, e.g. led', maxLength: 32, 'data-cb': 'wire-new-id',
            'aria-label': 'Circuit id', onChange: e => setNewId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '')) }),
          h(Btn, { key: 'a', kind: 'quiet', size: 'sm', disabled: !/^[a-z0-9][a-z0-9_-]{0,31}$/.test(newId) || circuits.some(c => c.id === newId), 'data-cb': 'wire-add',
            onClick: async () => { const r = buildWireParams(block, form, parseQuantity); if (r.ok) { const e2 = await addCircuitToProject(newId, block.block, r.params); if (e2?.ok) setCircuitId(newId) } } }, 'Add to project')] : null) : null),
      h('div', { className: 'cb-card', 'data-cb': 'wiring-table' },
        h('div', { className: 'cb-card-head' }, h(Label, null, '// wiring'), h(Label, null, `${rows.length} wires`)),
        rows.length ? h('table', { className: 'cb-table cb-wiretable' },
          h('colgroup', null, h('col', { className: 'cb-wcol-from' }), h('col', { className: 'cb-wcol-to' }), h('col', { className: 'cb-wcol-net' })),
          h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, 'from'), h('th', { className: 'cb-label' }, 'to'), h('th', { className: 'cb-label' }, 'net'))),
          h('tbody', null, rows.map(r => h('tr', { key: r.i, 'data-cb-row': r.i, 'data-cb-net': r.net, 'data-cb-net-class': r.netClass, 'aria-selected': wireRowOn(hl, r) ? 'true' : 'false',
            // the net highlight also follows the keyboard (focus = hover)
            tabIndex: 0, onMouseEnter: () => setHl(wireRowHl(r, res?.parts)), onMouseLeave: () => setHl(null),
            onFocus: () => setHl(wireRowHl(r, res?.parts)), onBlur: () => setHl(null) },
          h('td', { className: 'cb-fg', title: r.from, 'data-cb-truncate-ok': '' }, r.from), h('td', { className: 'cb-fg', title: r.to, 'data-cb-truncate-ok': '' }, r.to),
          h('td', null, h(WireNetChip, { net: r.net, cls: r.netClass })))))) : h('p', { className: 'cb-why cb-dim' }, 'Draw a block to see its wiring.')),
      res?.parts?.length ? h('div', { className: 'cb-card', 'data-cb': 'wire-parts' },
        h(Label, null, '// parts'),
        h('table', { className: 'cb-table cb-wparts' }, h('tbody', null, res.parts.map(p => h('tr', { key: p.ref, 'data-cb-ref': p.ref, 'aria-selected': hl?.refs.includes(p.ref) ? 'true' : 'false',
          tabIndex: 0, onMouseEnter: () => setHl(wireHl([p.ref])), onMouseLeave: () => setHl(null), onFocus: () => setHl(wireHl([p.ref])), onBlur: () => setHl(null) },
          h('td', { className: 'cb-fg' }, p.ref), h('td', null, nbspUnits(p.value)), h('td', { className: 'cb-r cb-dim' }, p.kind)))))) : null,
      res ? warn.cards.map(w => h('div', { key: w.code, className: `cb-card cb-wwarn cb-wwarn--${w.severity}`, role: 'note', 'data-cb': 'wire-warning', 'data-cb-code': w.code, 'data-cb-severity': w.severity },
        h('div', { className: 'cb-card-head' }, h('span', { className: 'cb-wwarn-mark', 'aria-hidden': 'true' }, '!'), h(Label, null, w.severity === 'danger' ? '// danger' : '// caution')),
        h('p', { className: 'cb-wwarn-t' }, w.message))) : null,
      res ? h(ChecksList, { checks: [], warnings: warn.notes }) : null,
      res ? h(SourceLine, { sources: env.sources }) : null)
  ]
}

STATION_VIEWS.wire = { component: StationWire, inspector: true }
