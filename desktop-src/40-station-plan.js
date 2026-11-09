// Station 01 PLAN: chip/variant/DevKit/Wi-Fi → POST /pins/check, pin → inspector, suggest pins, assign via dialog,
// agent changes pulse the affected pins twice.

/** Native select for the toolbar, grouped (optgroups); the closed state shows the short label, the title the detail. */
function ToolSelect({ dataCb, label, value, groups, onChange, placeholder = null, title }) {
  return h('select', { className: 'cb-tsel', 'data-cb': dataCb, 'data-cb-kind': 'select', 'aria-label': label, value: value ?? '', title,
    onChange: e => { if (e.target.value) onChange(e.target.value) } },
  placeholder && !value ? h('option', { key: '-', value: '', disabled: true }, placeholder) : null,
  groups.map(g => h('optgroup', { key: g.label, label: g.label },
    g.options.map(o => h('option', { key: o.id, value: o.id, title: o.title }, o.label)))))
}

/** Module variant choice: a segmented control for up to three variants (ESP32, C6), else a dropdown grouped by PSRAM
 *  kind (S3: no / quad / octal PSRAM, 9 entries). Nothing chosen = "variant unknown" (WT32-S1, unconfirmed module). */
function VariantPicker({ chip, value, onChange }) {
  if (chip.variants.length <= 3) {
    return h(Seg, { label: 'Module variant', dataCb: 'seg-variant', value, options: chip.variants.map(v => ({ id: v.id, label: v.label, title: variantTitle(v) })), onChange })
  }
  const cur = variantInfo(chip.id, value)
  return h(ToolSelect, { dataCb: 'seg-variant', label: 'Module variant', value: cur?.id ?? null, placeholder: '? unknown', onChange,
    title: cur ? `${cur.label}: ${variantTitle(cur)}` : 'Module variant unknown',
    groups: variantGroups(chip.id).map(g => ({ label: g.label, options: g.variants.map(v => ({ id: v.id, label: v.label, title: variantTitle(v) })) })) })
}

/** "Suggest pins" (Hermes action): in the station's title row, so the toolbar fits one line. */
function SuggestPinsBtn({ rows }) {
  const sug = sdk.useValue($suggest)
  const problems = rows.filter(r => r.verdict === 'blocked' || r.verdict === 'caution')
  return h(Btn, { kind: 'agent', className: 'cb-push', 'data-cb': 'suggest-pins', disabled: sug.status === 'loading',
    title: problems.length ? `Find free pins for ${problems.map(p => p.role).join(', ')}` : 'All assigned pins are ok',
    onClick: () => suggestPins(rows) }, sug.status === 'loading' ? 'Suggesting…' : 'Suggest pins')
}

function PlanToolbar({ view }) {
  const chip = chipInfo(view.chip)
  const devkit = resolveDevkit(view.chip, view.devkit)
  const kit = devkitInfo(devkit)
  // CHIP, DEVKIT and MODULE in one line; short chip names, the full name is the title
  // DEVKIT: only the layouts in data/boards (DEVKITS), a dropdown grouped by chip (seven layouts); a DevKit
  // selects its chip and module variant (module.variant), a chip its default DevKit (CHIPS[].devkit)
  return [h('div', { key: 'tb', className: 'cb-toolbar', 'data-cb': 'plan-toolbar' },
    h('div', { className: 'cb-group', 'data-cb': 'group-chip' }, h(Label, null, 'chip'),
      h(Seg, { label: 'Chip', dataCb: 'seg-chip', value: view.chip, options: CHIPS.map(c => ({ id: c.id, label: c.label.replace(/^ESP32-/, ''), title: c.label })),
        onChange: id => setWhatIf({ chip: id }) })),
    h('div', { className: 'cb-group', 'data-cb': 'group-devkit' }, h(Label, null, 'devkit'),
      h(ToolSelect, { dataCb: 'seg-devkit', label: 'DevKit layout', value: devkit, placeholder: 'none',
        title: kit ? `${devkitTitle(kit)} header map (${chipInfo(kit.chip)?.label || kit.chip})` : 'No DevKit layout',
        groups: CHIPS.filter(c => devkitsOf(c.id).length).map(c => ({ label: c.label,
          options: devkitsOf(c.id).map(d => ({ id: d.id, label: d.label, title: `${devkitTitle(d)} header map (${c.label})` })) })),
        onChange: id => setWhatIf({ chip: devkitInfo(id)?.chip ?? view.chip, devkit: id }) })),
    chip?.variants.length ? h('div', { className: 'cb-group', 'data-cb': 'group-module' }, h(Label, null, 'module'),
      h(VariantPicker, { chip, value: view.variant, onChange: id => setWhatIf({ variant: id }) })) : null,
    h(Toggle, { checked: view.wifi, dataCb: 'toggle-wifi', title: 'Wi-Fi changes which ADC rules apply', onChange: on => setWhatIf({ wifi: on }) }, 'Wi-Fi'),
    // what-if line inside the toolbar: it shares a row with the controls when there is room, so a 2×22
    // DevKit stays above the console at 1280×800 too
    h(WhatIfLine, null))]
}

/** The view differs from the project board: say what the project has, apply or reset. */
function WhatIfLine() {
  const project = sdk.useValue($project)
  sdk.useValue($view)
  if (!isWhatIf()) return null
  const b = boardOf(project)
  const kit = devkitInfo(b.devkit)
  // compact: the project board stands in the HUD (board pill); the full text is the title and screen-reader text
  const text = `Project board: ${kit ? `${devkitTitle(kit)}, ` : ''}${chipInfo(b.chip)?.label || b.chip}${b.variant ? ` ${b.variant.toUpperCase()}` : ''}, Wi-Fi ${b.wifi ? 'on' : 'off'}.`
  return h('div', { className: 'cb-whatif', 'data-cb': 'whatif', role: 'status', title: `The pin map shows a what-if board. ${text}` },
  h('span', null, '◇ WHAT-IF'),
  h('span', { className: 'cb-sr', 'data-cb': 'whatif-project' }, text),
  h('span', { style: { marginLeft: 'auto', display: 'flex', gap: '8px' } },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'whatif-apply', title: 'Save this board to the project', onClick: () => applyBoardToProject() }, 'Apply to project'),
    h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'whatif-reset', title: 'Back to the project board', onClick: () => resetWhatIf() }, 'Reset')))
}

function StationPlan({ project, rows }) {
  const view = sdk.useValue($view)
  const board = sdk.useValue($board)
  const map = sdk.useValue($map)
  const check = sdk.useValue($check)
  const sug = sdk.useValue($suggest)
  const auto = useRef(null)
  useEffect(() => {
    if (check.status !== 'ready' || auto.current === check.key) return
    auto.current = check.key
    if (view.selected === null) {
      const first = rows.find(r => r.verdict === 'blocked') || rows.find(r => r.verdict === 'caution')
      if (first) selectPin(first.pin)
    }
  }, [check.key, check.status])
  const opts = project?.options || {}
  const meta = [`wi-fi ${view.wifi ? 'on' : 'off'}`, opts.framework, opts.logic_v ? `${opts.logic_v} v logic` : null].filter(Boolean).join(' · ')
  const suggestPinsList = sug.status === 'ready' && sug.env?.ok ? suggestionChips(sug.env.result, sug.role).map(s => s.gpio) : []
  const onAssign = init => patchAtom($ui, { modal: { type: 'assign', init } })
  const b = viewBoard()
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-plan' },
      h('div', { className: 'cb-planhead' }, h(DecodeTitle, { text: '01 // PIN MAP', meta }),
        h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'add-module', 'aria-haspopup': 'dialog', title: 'Add a sensor, display or driver module from the catalog',
          onClick: () => openModules() }, '+ Add module'), h(SuggestPinsBtn, { rows })),
      h(PlanToolbar, { view }),
      board.status === 'ready' ? h(BoardWarnings, { layout: board.layout, sources: board.sources, compact: true }) : null,
      h(BoardView, { layoutState: board, mapState: map, rows, board: b, selected: view.selected, suggestPins: suggestPinsList, onSelect: selectPin }),
      // legend as the board's caption
      board.status === 'ready' ? h(Legend, { key: 'lg', className: 'cb-legend--cap', suggesting: suggestPinsList.length > 0, kinds: layoutKinds(board.layout) }) : null,
      map.status === 'error' ? h('div', { className: 'cb-note cb-note--warn', style: { marginTop: '12px' }, 'data-cb': 'map-error' },
        '! Pin map unavailable — free pins show as “not checked”.', h('span', { className: 'cb-dim' }, map.env?.error?.message || '')) : null),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' },
      board.status === 'ready' ? h(BoardWarnings, { layout: board.layout, sources: board.sources }) : null,
      h(Inspector, { rows, board: b, layoutState: board, mapState: map, checkState: check, onAssign }),
      h(BusPanel, null),
      h(AssignmentTable, { rows, checkState: check, onAssign }))
  ]
}

/** Pin kinds present on the layout (legend entries for signal / nc only where they exist). */
function layoutKinds(layout) {
  const { left, right } = headerRows(layout)
  return [...new Set([...left, ...right].map(p => p.kind))]
}

STATION_VIEWS.plan = { component: StationPlan, inspector: true }
