// Station 02 CALC: calculator cards; inputs parse as you type (4k7, 10mA, 3V3), the backend computes, every number is
// a `display` text of the answer. Card: mini schematic (art-calc), headline in its worst check's tone, bands
// (calcBands), check chips, formula steps, assumptions drawer, sources foot; same action row, equal row heights.
// Module catalog: groups from GET /calc (`basics` default; others generic cards).

/** Calculator input with the unit inside the field (V, A, Ω, F, °C) and the parsed value as the hint below. */
function CalcField({ def, f, value, onChange, hint, error, onEnter }) {
  const id = `cb-${def.type}-${f.name}`
  // the unit shows in the field unless the typed text already carries it (10mA, 3V3, 100pF): never twice
  const unit = f.suffix || (f.unit && !calcTypedUnit(value, f.unit) ? f.unit : '')
  const control = f.choice
    ? h('select', { id, value, 'data-cb': `in-${def.type}-${f.name}`, onChange: e => onChange(e.target.value) }, f.choice.map(c => h('option', { key: c, value: c }, c || '—')))
    : h('input', { id, value, 'data-cb': `in-${def.type}-${f.name}`, autoComplete: 'off', spellCheck: false, 'aria-invalid': error ? 'true' : 'false',
      'aria-describedby': unit ? `${id}-u` : undefined, title: String(value || '').length > 12 ? value : undefined,
      onChange: e => onChange(e.target.value), onKeyDown: e => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter() } } })
  return h('div', { className: cx('cb-field', 'cb-calc-field', error && 'cb-field--err') },
    h('label', { htmlFor: id }, f.label),
    h('span', { className: cx('cb-calc-box', unit && !f.choice && 'cb-calc-box--unit') }, control,
      unit && !f.choice ? h('span', { className: 'cb-calc-unit', id: `${id}-u` }, unit) : null),
    h('span', { className: error ? 'cb-fhint cb-calc-hint cb-bad' : 'cb-fhint cb-calc-hint' }, error || hint || '\u00a0'))
}

/** Ruler exact → chosen E-series value, the deviation on the arrow. */
function CalcRuler({ b, type, tone }) {
  return h('div', { className: cx('cb-calc-ruler', b.down && 'cb-calc-ruler--down'), 'data-cb': `calc-ruler-${type}` },
    h('span', { className: 'cb-calc-rend' }, h('small', null, b.from.label), h('b', null, nbspUnits(b.from.display))),
    h('span', { className: 'cb-calc-rtrack' }, h('i', { 'aria-hidden': 'true' }),
      b.delta ? h('em', { 'data-cb': 'calc-dev', title: 'deviation of the chosen value from the exact one' }, nbspUnits(b.delta)) : null),
    h('span', { className: 'cb-calc-rend cb-calc-rend--to' }, h('small', null, b.to.label), h('b', { className: `cb-${tone}` }, nbspUnits(b.to.display))))
}

/** A value against its limit: label, value, limit, track (only when the position can be drawn), note from the answer. */
function CalcMeter({ b, type }) {
  return h('div', { className: 'cb-calc-meter', 'data-cb': `calc-meter-${type}-${b.id}`, 'data-cb-check': b.status || undefined },
    h('div', { className: 'cb-calc-mhead' },
      h('span', { className: 'cb-calc-mk' }, b.label),
      h('b', { className: `cb-${b.tone}` }, nbspUnits(b.value)),
      h('span', { className: 'cb-calc-mlim' }, `${b.limitLabel} `, h('b', null, nbspUnits(b.limit)))),
    b.frac !== null && b.frac !== undefined ? h('div', { className: 'cb-calc-mtrack', 'aria-hidden': 'true' },
      h('i', { className: `cb-calc-mfill cb-calc-mfill--${b.tone}`, style: { width: `${(b.frac * 100).toFixed(1)}%` } })) : null,
    b.start ? h('div', { className: 'cb-calc-mscale' }, h('span', null, `from T_A ${b.start}`.replace(/(\d) (?=°C)/g, '$1\u00a0')), h('span', null, `max ${b.limit}`.replace(/(\d) (?=°C)/g, '$1\u00a0'))) : null,
    b.note ? h('p', { className: 'cb-calc-mnote' }, h('span', { className: 'cb-fg' }, `${b.note.lead} ${nbspUnits(b.note.value)}`),
      b.note.reason ? h('span', null, ` · ${b.note.reason}`) : null) : null)
}

/** I²C window R_min … R_max with the suggested value marked on the track. */
function CalcWindow({ b, type }) {
  return h('div', { className: 'cb-calc-window', 'data-cb': `calc-window-${type}`, 'data-cb-check': b.status || undefined },
    h('div', { className: 'cb-calc-wtrack', 'aria-hidden': 'true' }, h('i', { className: `cb-calc-wbar cb-calc-mfill--${b.tone}` }),
      b.frac !== null && b.frac !== undefined ? h('span', { className: 'cb-calc-wmark', style: { left: `${(b.frac * 100).toFixed(1)}%` } }) : null),
    h('div', { className: 'cb-calc-wscale' },
      h('span', null, h('small', null, `${b.min.label} `), h('b', null, nbspUnits(b.min.display))),
      h('span', { className: 'cb-calc-wmid' }, h('small', null, '▲ '), h('b', { className: `cb-${b.tone}` }, nbspUnits(b.mark))),
      h('span', { className: 'cb-calc-wend' }, h('small', null, `${b.max.label} `), h('b', null, nbspUnits(b.max.display)))))
}

/** Headline: label, the big value in the tone of its worst check, the verdict as symbol + words, the bands. */
function CalcReadout({ def, v, env, bands }) {
  const worst = worstCheck(env.checks)
  const tone = valueTone(env.checks)
  const verdict = calcVerdict(env.checks)
  return h('div', { className: 'cb-calc-readout', 'data-cb': `calc-result-${def.type}` },
    h('div', { className: 'cb-calc-main' },
      h(Label, null, v.mainLabel),
      h('b', { className: `cb-calc-big cb-${tone}`, 'data-cb': `calc-value-${def.type}`, 'data-cb-check': worst || 'none',
        title: { failed: 'A check failed: see below', not_checked: 'Not every check could be made: see below', passed: 'All checks passed' }[worst] || 'No checks for this value' }, nbspUnits(v.main.display)),
      verdict ? h('span', { className: `cb-calc-verdict cb-${verdict[2]}` }, h('span', { 'aria-hidden': 'true' }, verdict[0]), ` ${verdict[1]}`) : null),
    bands.map(b => b.kind === 'ruler' ? h(CalcRuler, { key: b.id, b, type: def.type, tone })
      : b.kind === 'meter' ? h(CalcMeter, { key: b.id, b, type: def.type })
        : b.kind === 'window' ? h(CalcWindow, { key: b.id, b, type: def.type }) : null))
}

/** Checks as chips; failed and not-checked ones also with their detail line (the passed details are in the formula
 *  drawer). Warnings below with their severity word. */
function CalcChecks({ def, chips, warnings }) {
  const ws = (Array.isArray(warnings) ? warnings : []).filter(w => w && w.message)
  const open = chips.filter(c => c.status !== 'passed' && c.detail)
  if (!chips.length && !ws.length) return null
  const sev = w => (w.severity === 'danger' ? ['!', 'danger', 'bad'] : w.severity === 'caution' ? ['!', 'caution', 'warn'] : ['i', 'note', 'dim'])
  return h('div', { className: 'cb-calc-checks', 'data-cb': `calc-checks-${def.type}` },
    chips.length ? h('div', { className: 'cb-calc-chips' }, chips.map(c => h('span', { key: c.id, className: `cb-calc-chip cb-calc-chip--${c.tone}`,
      'data-cb-check-status': c.status, title: c.detail || c.id },
    h('span', { className: 'cb-calc-chip-s', 'aria-hidden': 'true' }, c.sym), h('span', null, c.name), h('b', null, c.word)))) : null,
    open.map(c => h('p', { key: c.id, className: `cb-calc-chkd cb-${c.tone === 'dim' ? 'dim' : c.tone}` }, h('span', { 'aria-hidden': 'true' }, `${c.sym} `), `${c.name}: `, nbspUnits(c.detail))),
    ws.map((w, i) => {
      const [s, word, tone] = sev(w)
      return h('p', { key: w.code || i, className: `cb-calc-warnl cb-calc-warnl--${tone}` }, h('b', { className: `cb-${tone}` }, h('span', { 'aria-hidden': 'true' }, `${s} `), word), h('span', null, nbspUnits(w.message)))
    }))
}

/** Formula drawer: the equations one per line, the steps as a table (name, expression, value), the passed checks. */
function CalcFormula({ def, v, chips, open, setOpen }) {
  const lines = calcFormulaLines(v.formula)
  const steps = calcSteps(v.steps)
  const passed = chips.filter(c => c.status === 'passed' && c.detail)
  if (!lines.length && !steps.length) return null
  return h('details', { className: 'cb-formula cb-calc-drawer', open, onToggle: e => setOpen(e.currentTarget.open), 'data-cb': `calc-formula-${def.type}` },
    h('summary', null, h(Label, null, steps.length ? `formula · ${steps.length} steps` : 'formula')),
    lines.length ? h('div', { className: 'cb-calc-eqs' }, lines.map((l, i) => h('code', { key: i }, nbspUnits(l)))) : null,
    steps.length ? h('table', { className: 'cb-calc-steps', 'data-cb': `calc-steps-${def.type}` },
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'step'), h('th', { scope: 'col' }, 'expression'), h('th', { scope: 'col', className: 'cb-r' }, 'value'))),
      h('tbody', null, steps.map((s, i) => h('tr', { key: i }, h('th', { scope: 'row' }, s.name), h('td', null, nbspUnits(s.expr)), h('td', { className: 'cb-r' }, nbspUnits(s.value)))))) : null,
    passed.length ? h('div', { className: 'cb-calc-passed' }, h(Label, null, 'checks passed'),
      passed.map(c => h('p', { key: c.id, className: 'cb-calc-chkd' }, h('span', { className: 'cb-ok', 'aria-hidden': 'true' }, '✓ '), h('span', { className: 'cb-fg' }, `${c.name}: `), nbspUnits(c.detail)))) : null)
}

/** Assumptions drawer: the keys already in the summary, key / value / reason inside. */
function CalcAssumptions({ def, items }) {
  const list = (Array.isArray(items) ? items : []).filter(a => a && a.key)
  if (!list.length) return null
  return h('details', { className: 'cb-assume cb-calc-drawer', 'data-cb': `calc-assume-${def.type}` },
    h('summary', null, h(Label, null, `assumptions · ${list.length}`), h('span', { className: 'cb-calc-akeys' }, list.map(a => a.key).join(' · '))),
    h('dl', { className: 'cb-calc-alist' }, list.map(a => [
      h('dt', { key: `${a.key}-k` }, a.key),
      h('dd', { key: `${a.key}-v` }, h('span', { className: 'cb-fg' }, nbspUnits(a.value ?? '')), a.reason ? h('span', null, ` — ${a.reason}`) : null)])))
}

/** Fixed card foot: the sources of the answer, full labels (never cut), a link where the source has a URL. */
function CalcFoot({ sources, state }) {
  const list = (Array.isArray(sources) ? sources : []).filter(s => s && s.id)
  return h('footer', { className: 'cb-calc-foot', 'data-cb': 'calc-src' },
    h('span', { className: 'cb-k' }, 'src ›'),
    list.length
      ? h('span', { className: 'cb-calc-srcs' }, list.map(s => s.url
        ? h('button', { key: s.id, type: 'button', title: `${s.title}\n${s.url}\nretrieved ${s.retrieved || '—'}`, onClick: () => openLink(s.url) }, `${sourceLabel(s)} ↗`)
        : h('span', { key: s.id, className: 'cb-calc-src0', title: `${s.title}\nretrieved ${s.retrieved || '—'}` }, sourceLabel(s))))
      : h('span', { className: 'cb-dim' }, state === 'stored' ? 'stored result · Calculate again for its sources' : 'the sources come with the result'))
}

function CalcCard({ def, project, stored }) {
  const st = sdk.useValue($calcs)[def.type] || { status: 'idle', env: null }
  const [form, setForm] = useState(() => initialForm(def, stored))
  const [errors, setErrors] = useState({})
  const [open, setOpen] = useState(false)
  const env = st.env || (stored ? { ok: true, summary: stored.result?.summary || '', result: { ...stored.result, inputs: stored.inputs }, checks: stored.result?.checks || [],
    warnings: [], assumptions: stored.assumptions || [], sources: [], fromProject: true } : null)
  const v = calcView(def, env)
  const run = () => {
    const b = buildCalcBody(def, form, parseQuantity)
    setErrors(b.errors)
    if (b.ok) runCalc(def.type, b.body)
  }
  const set = name => val => { setForm(f => ({ ...f, [name]: val })); if (errors[name] || errors._need) setErrors(e => ({ ...e, [name]: null, _need: null })) }
  const hintOf = f => {
    if (f.choice || f.text) return ''
    if (f.temp) {
      const t = parseTempC(form[f.name])
      return t.ok ? `= ${t.value} °C` : t.empty ? 'optional' : ''
    }
    const q = parseQuantity(calcPlainText(f, form[f.name]), f.unit)
    return q.ok ? `= ${formatSI(q.value, f.unit)}${f.suffix ? ` ${f.suffix}` : ''}` : q.empty ? (f.required ? 'required' : 'optional') : ''
  }
  const live = env && !env.fromProject
  const savedAs = live && env.ok ? null : stored?.id
  const tone = v.ok ? valueTone(env.checks) : 'fg'
  const art = calcArt(def.type, v.ok ? env : null, { tone })
  const bands = v.ok ? calcBands(def, env) : []
  const shown = new Set([...(art?.shown || []), ...bands.flatMap(b => b.keys)])
  const rows = v.ok ? v.rows.filter(r => !shown.has(r.k)) : []
  const chips = v.ok ? calcChips(env.checks) : []
  const loading = st.status === 'loading'
  return h('section', { className: cx('cb-card cb-calc', def.generic && 'cb-calc--gen'), 'data-cb': `calc-${def.type}`, 'data-cb-status': st.status,
    'data-cb-generic': def.generic ? 'true' : undefined },
    h('div', { className: 'cb-card-head' }, h('span', { className: 'cb-secn' }, def.short), h(Label, null, `// ${def.title}`),
      savedAs ? h('span', { className: 'cb-tag cb-push', title: 'Stored in the project' }, savedAs) : null),
    def.summary ? h('p', { className: 'cb-calc-sum', 'data-cb': `calc-sum-${def.type}` }, nbspUnits(def.summary)) : null,
    h('div', { className: 'cb-calc-top' },
      art ? h('div', { className: 'cb-calc-fig', role: 'img', 'aria-label': art.label, 'data-cb': `calc-art-${def.type}`, dangerouslySetInnerHTML: { __html: art.svg } }) : null,
      v.ok ? h(CalcReadout, { def, v, env, bands })
        : h('div', { className: 'cb-calc-readout cb-calc-readout--idle', 'data-cb': `calc-idle-${def.type}` },
          h(Label, null, v.mainLabel || 'result'),
          h('p', null, loading ? 'Calculating…' : 'Not calculated yet. Set the values and press Calculate.')),
      v.ok ? h('div', { className: 'cb-calc-meas', 'data-cb': `calc-meas-${def.type}` },
        h(CalcChecks, { def, chips, warnings: env.warnings }),
        rows.length || v.hfe ? h('div', { className: 'cb-kv cb-kv--calc' }, rows.map(r => [h('span', { key: `${r.k}l` }, r.label), h('b', { key: `${r.k}v` }, nbspUnits(r.q.display))]),
          v.hfe ? [h('span', { key: 'hl' }, 'hFE min'), h('b', { key: 'hv', title: v.hfe.conditions || '' }, `${v.hfe.value}${v.hfe.part ? ` (${v.hfe.part} datasheet)` : ''}`)] : null) : null) : null),
    h('div', { className: 'cb-calc-in' }, def.fields.map(f => h(CalcField, { key: f.name, def, f, value: form[f.name], onChange: set(f.name), hint: hintOf(f),
      error: errors[f.name] && errors[f.name] !== 'required' ? errors[f.name] : errors[f.name] ? 'required' : null, onEnter: run }))),
    def.oneOf ? h('div', { className: cx('cb-jobline', errors._need ? 'cb-bad' : 'cb-dim'), role: errors._need ? 'alert' : undefined,
      'data-cb': `calc-need-${def.type}` }, `${errors._need ? '✕ ' : ''}${calcNeedText(def)}`) : null,
    h('div', { className: 'cb-actions cb-calc-acts' },
      h(Btn, { size: 'sm', 'data-cb': `calc-run-${def.type}`, disabled: loading, onClick: run }, loading ? 'Calculating…' : 'Calculate'),
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': `calc-add-${def.type}`, disabled: !(live && env.ok && v.ok) || !project,
        title: live && env.ok ? 'Store the calculation and its parts in the project' : 'Calculate first, then store the result in the project',
        onClick: () => addCalcToProject(def.type) }, 'Add to project')),
    env && !env.ok ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': `calc-error-${def.type}` }, `✕ ${env.error?.message || env.summary}`,
      env.error?.hint ? h('span', { className: 'cb-dim' }, env.error.hint) : null) : null,
    v.ok ? h('div', { className: 'cb-calc-out', 'data-cb': `calc-detail-${def.type}` },
      h(CalcFormula, { def, v, chips, open, setOpen }),
      h(CalcAssumptions, { def, items: env.assumptions })) : null,
    h(CalcFoot, { sources: v.ok ? env.sources : null, state: v.ok && env.fromProject ? 'stored' : 'idle' }))
}

/** Group pick only with more than one group. */
function StationCalc({ project }) {
  const calcs = project?.calcs || []
  const storedOf = type => [...calcs].reverse().find(c => c.type === type) || null
  const meta = useCalcMeta()
  const groups = calcGroups(meta.list, meta.env?.result?.groups)
  const [groupId, setGroup] = useState('basics')
  const group = groups.find(g => g.id === groupId) || groups[0]
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-calc', 'data-cb-audit-root': 'station' },
      h(DecodeTitle, { text: '02 // CALCULATORS', meta: 'computed by the bench backend · units like 4k7, 10mA, 3V3' }),
      groups.length > 1 ? h('div', { className: 'cb-toolbar' }, h('div', { className: 'cb-group cb-group--calc' }, h(Label, null, 'group'),
        h(Seg, { label: 'Calculator group', dataCb: 'seg-calc-group', value: group.id, onChange: setGroup,
          options: groups.map(g => ({ id: g.id, label: `${g.id} · ${g.defs.length}`, title: g.defs.map(d => d.title).join(', ') })) }))) : null,
      h('div', { className: 'cb-calcgrid', 'data-cb': 'calc-grid', 'data-cb-group': group.id },
        group.defs.map(d => h(CalcCard, { key: `${d.type}-${project?.id || ''}`, def: calcApplyMeta(d, calcRawMeta(meta.env, d.type)), project, stored: storedOf(d.type) })))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'data-cb-audit-root': 'inspector', 'aria-label': 'Inspector' }, h(BomCard, { project }))
  ]
}

/** Calculations and parts in the project (BOM). A part is removed in two clicks (✕, then Remove in the row);
 *  its calculation stays, a solder plan that names it shows as out of date in 04 SOLDER. */
function BomCard({ project }) {
  const parts = project?.parts || []
  const calcs = project?.calcs || []
  const [asking, setAsking] = useState(null)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const remove = async ref => {
    setBusy(true)
    setFail(null)
    const env = await removePartsFromProject([ref])
    setBusy(false)
    setAsking(null)
    if (env && !env.ok) {
      setFail(env.error?.code === 'project_conflict' ? 'The project changed meanwhile and was reloaded. Check the list and try again.'
        : env.error?.message || env.summary || 'Not removed.')
    }
  }
  const partRow = p => asking === p.ref
    ? h('tr', { key: p.ref, 'data-cb': 'part-row', 'data-cb-ref': p.ref, className: 'cb-part-ask' },
      h('td', { className: 'cb-warn', colSpan: 2 }, `Remove ${p.ref}?`),
      h('td', { className: 'cb-r', colSpan: 2 },
        h('span', { className: 'cb-part-acts' },
          h(Btn, { kind: 'quiet', size: 'sm', onClick: () => setAsking(null), disabled: busy }, 'Keep'),
          h(Btn, { kind: 'danger', size: 'sm', 'data-cb': 'part-remove-confirm', disabled: busy, onClick: () => remove(p.ref) }, busy ? 'Removing…' : 'Remove'))))
    : h('tr', { key: p.ref, 'data-cb': 'part-row', 'data-cb-ref': p.ref },
      h('td', { className: 'cb-fg' }, p.ref), h('td', null, nbspUnits(p.value)), h('td', { className: 'cb-r cb-dim' }, p.from_calc || p.kind),
      h('td', { className: 'cb-r cb-part-x' }, h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'part-remove', disabled: busy,
        'aria-label': `Remove ${p.ref} from the project`, title: `Remove ${p.ref} from the project`, onClick: () => setAsking(p.ref) }, '✕')))
  return [
    h('div', { key: 'c', className: 'cb-card', 'data-cb': 'project-calcs' },
      h('div', { className: 'cb-card-head' }, h(Label, null, '// calculations'), h(Label, null, `${calcs.length}`)),
      calcs.length ? h('table', { className: 'cb-table' }, h('tbody', null, calcs.map(c => {
        const r = c.result || {}
        const main = r.r_chosen || r.i_b || r.v_out_max || r.suggested || r.p_loss || r.p_total || calcResultRows(r)[0]?.q
        const tone = valueTone(r.checks)
        return h('tr', { key: c.id }, h('td', { className: 'cb-fg' }, c.id), h('td', { className: 'cb-dim' }, c.type),
          h('td', { className: `cb-r cb-${tone}`, title: { bad: 'a check failed', ok: 'all checks passed' }[tone] || 'not every check made' },
            tone === 'bad' ? h('span', { 'aria-hidden': 'true' }, '✕ ') : null, nbspUnits(main?.display || '—')))
      }))) : h('p', { className: 'cb-why cb-dim' }, 'No calculations stored yet. “Add to project” keeps one with its parts.')),
    h('div', { key: 'p', className: 'cb-card', 'data-cb': 'project-parts' },
      h('div', { className: 'cb-card-head' }, h(Label, null, '// parts'), h(Label, null, `${parts.length}`)),
      parts.length ? h('table', { className: 'cb-table' }, h('tbody', null, parts.map(partRow))) : h('p', { className: 'cb-why cb-dim' }, 'No parts yet.'),
      fail ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'part-remove-error' }, `✕ ${fail}`) : null)
  ]
}

STATION_VIEWS.calc = { component: StationCalc, inspector: true }
