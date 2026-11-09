// AssignmentTable and the assign dialog (op assign)

function AssignmentTable({ rows, checkState, onAssign }) {
  const view = sdk.useValue($view)
  const pulse = sdk.useValue($pulse)
  const pulseRoles = new Set(pulse.roles)
  const env = checkState.env
  const [at, setAt] = useState(null)
  useEffect(() => { if (checkState.status === 'ready') setAt(new Date().toISOString()) }, [checkState.key, checkState.status])
  // mod_* findings only in the card // buses
  const warnings = env?.ok ? (env.warnings || []).filter(w => !String(w.code || '').startsWith('mod_')) : []
  const project = sdk.useValue($project)
  const insts = useProjectModules(project)
  const stale = rows.some(r => !r.checked) && checkState.status === 'ready'
  return h('div', { className: 'cb-card', 'data-cb': 'assignments' },
    h('div', { className: 'cb-card-head' }, h(Label, null, '// assignments'),
      h(Label, { 'data-cb': 'checked-at', className: 'cb-push' }, checkState.status === 'loading' ? 'checking…' : checkState.status === 'error' ? 'check failed'
        : at ? `checked ${formatClock(at)}` : ''),
      h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'assign-new', title: 'Assign a role to a pin',
        onClick: () => onAssign({ role: '', mode: 'out', pin: view.selected ?? null, net: '' }) }, '+ assign')),
    // fixed columns (no h-scroll, WT32): role ellipsis + title; verdict symbol + word
    rows.length || insts.length ? h('table', { className: 'cb-table cb-table--assign' },
      h('colgroup', null, h('col', null), h('col', { className: 'cb-col-pin' }), h('col', { className: 'cb-col-mode' }),
        h('col', { className: 'cb-col-verdict' }), h('col', { className: 'cb-col-x' })),
      h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, 'role'), h('th', { className: 'cb-label' }, 'pin'),
        h('th', { className: 'cb-label' }, 'mode'), h('th', { className: 'cb-label' }, h('span', { className: 'cb-vw' }, 'verdict')), h('th', { className: 'cb-label cb-r' }, h('span', { className: 'cb-sr' }, 'remove')))),
      h('tbody', null, rows.map(r => {
        const v = verdictMeta(r.verdict)
        return h('tr', { key: r.role, 'data-cb-row': r.role, 'data-cb': `row-${r.role}`, 'aria-selected': view.selected === r.pin ? 'true' : 'false',
          'data-cb-pulse': pulseRoles.has(r.role) ? 'true' : undefined, onClick: () => selectPin(r.pin),
          title: r.updated_by ? `last change by ${r.updated_by}${r.checked ? '' : ' · stored verdict (not re-checked)'}` : undefined },
        h('td', { className: 'cb-fg cb-cell-ellip', title: r.role, 'data-cb-truncate-ok': 'true' }, r.role),
        h('td', { className: r.verdict === 'blocked' ? 'cb-bad' : 'cb-active' }, `IO${r.pin}`),
        // one mode word; full mode as title (+ label when shortened)
        h('td', { className: 'cb-dim cb-cell-ellip', title: modeLabel(r.mode), 'data-cb-mode': r.mode,
          'aria-label': modeShort(r.mode) !== modeLabel(r.mode) ? modeLabel(r.mode) : undefined }, modeShort(r.mode)),
        h('td', { className: `cb-verdict-cell cb-cell-ellip cb-${v.tone === 'none' ? 'dim' : v.tone}`, 'data-cb-verdict': r.verdict || 'unchecked',
          title: v.text, 'data-cb-truncate-ok': 'true' },
          h('span', { 'aria-hidden': 'true' }, v.symbol), h('span', { className: 'cb-vw' }, ' ', r.verdict ? v.text : 'unchecked')),
        h('td', { className: 'cb-r' }, h('button', { type: 'button', className: 'cb-x', title: `Remove ${r.role}`, 'aria-label': `Remove ${r.role}`,
          onClick: e => { e.stopPropagation(); unassignRole(r.role) } }, '×')))
      }), insts.length ? h(ModuleRows, { key: 'mods', insts, project, env, onAssign }) : null)) : h('p', { className: 'cb-why cb-dim' }, 'No pins assigned yet. Click a free pin on the board, then “Assign role…”.'),
    warnings.map(w => h('div', { key: w.code, className: w.severity === 'danger' ? 'cb-hint cb-bad' : 'cb-hint' }, `⚠ ${w.message}`)),
    stale ? h('div', { className: 'cb-hint cb-dim' }, 'Some verdicts are stored values; the latest check did not cover them.') : null)
}

// module groups: row (button → instance view), open pins (— connect <net> | — assign)
function ModuleRows({ insts, project, env, onAssign }) {
  const infos = useModuleInfos(insts.map(i => i.module))
  const byRef = modRefFindings(modFindings(env).warnings)
  const assigns = project?.assignments || []
  // address from the check if the part has none
  const addr = Object.fromEntries((modulesResult(env)?.buses || []).flatMap(b => (b.segments || []).flatMap(s => s.devices || [])).map(d => [d.ref, d.address]))
  return insts.flatMap(i0 => {
    const inst = i0.address || !addr[i0.ref] ? i0 : { ...i0, address: addr[i0.ref] }
    const info = infos[inst.module]
    const links = modPinLinks(inst, info, assigns)
    const w = byRef[inst.ref]
    const label = modInstanceLabel(inst, info)
    const linked = links.filter(l => l.assignment).map(l => `${l.pin} IO${l.assignment.pin}`).join(' · ')
    const go = e => { e.stopPropagation(); openModules({ ref: inst.ref, address: inst.address }) }
    return [h('tr', { key: inst.ref, className: 'cb-mod-grp', 'data-cb': 'mod-group', 'data-cb-ref': inst.ref, title: `${label}: module details`, onClick: go },
    h('td', { colSpan: 5 }, h('div', { className: 'cb-mod-grphead' },
      h('button', { type: 'button', className: 'cb-mod-grpbtn cb-mod-ellip', 'data-cb': 'mod-group-open', 'data-cb-truncate-ok': 'true', onClick: go }, label),
      w ? h('span', { className: `cb-mod-t-${w.tone}`, title: w.message, 'data-cb': 'mod-group-finding' }, `${w.symbol} ${w.word}`) : null),
    linked ? h('div', { className: 'cb-mod-dim cb-mod-ellip', 'data-cb-truncate-ok': 'true', title: linked }, linked) : null)),
    ...links.filter(l => !l.assignment).map(l => h('tr', { key: `${inst.ref}-${l.pin}`, className: 'cb-mod-open', 'data-cb': 'mod-open', 'data-cb-ref': inst.ref, 'data-cb-pin': l.pin },
      h('td', { className: 'cb-cell-ellip', title: `${inst.ref} ${l.pin} (${l.signal.replace(/_/g, ' ')})`, 'data-cb-truncate-ok': 'true' }, `↳ ${l.pin}`),
      h('td', { colSpan: 4 }, l.bus
        ? h('button', { type: 'button', className: 'cb-mod-link', 'data-cb-act': 'connect', title: `${l.bus.role} · IO${l.bus.pin}`,
          onClick: () => connectModule(inst.ref, { [l.pin]: modAssignNet(l.bus) }) }, `— connect ${modAssignNet(l.bus)}`)
        : h('button', { type: 'button', className: 'cb-mod-link', 'data-cb-act': 'assign',
          onClick: () => onAssign(modAssignInit(inst, l, assigns)) }, `— assign${l.must ? ' · required' : l.optional ? ' · optional' : ''}`))))]
  })
}

function AssignDialog({ init, mapState, onClose }) {
  const [role, setRole] = useState(init.role || '')
  const [mode, setMode] = useState(init.mode || 'out')
  const [pin, setPin] = useState(init.pin === null || init.pin === undefined ? '' : String(init.pin))
  const [net, setNet] = useState(init.net || '')
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState([])
  const [fail, setFail] = useState(null)
  const saved = useRef(null) // assigned pin: focus returns to it
  const pinNum = /^\d{1,2}$/.test(pin) ? Number(pin) : null
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null).get(pinNum)
  const err = f => errors.find(e => e.field === f)?.message
  const submit = async e => {
    e?.preventDefault?.()
    const form = { role: role.trim().toUpperCase(), mode, pin: pinNum, net: net.trim() || null }
    const errs = validateAssign(form)
    setErrors(errs)
    if (errs.length) return
    setBusy(true)
    setFail(null)
    const link = init.link // module pin: assign + connect in one PATCH
    const env = link ? await patchOps([{ op: 'assign', ...form, net: form.net || undefined }, connectOp(link.ref, { [link.pin]: form.net || `GPIO${form.pin}` })],
      { okText: `${form.role} → GPIO${form.pin}, ${link.ref} ${link.pin} connected.` }) : await assignPin(form)
    setBusy(false)
    if (env?.ok) { saved.current = form.pin; selectPin(form.pin); onClose() } else setFail(env?.error?.message || 'Not saved.')
  }
  const field = (id, label, control, error) => [
    h('label', { key: `${id}-l`, htmlFor: `cb-f-${id}` }, label), control,
    error ? h('div', { key: `${id}-e`, className: 'cb-err' }, error) : null
  ]
  const returnFocus = root => (saved.current !== null && root ? root.querySelector(`[data-cb="pin-${saved.current}"]`) : null)
  return h(Modal, { title: init.link ? `Assign ${init.link.ref} ${init.link.pin}` : init.role ? `Edit ${init.role}` : 'Assign role', onClose, dataCb: 'assign-dialog', returnFocus,
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 's', onClick: submit, disabled: busy, 'data-cb': 'assign-submit', kind: base && base.verdict !== 'ok' ? 'warn' : 'primary',
        title: base && base.verdict === 'blocked' ? 'The pin is blocked; it is saved as a request so the bench can suggest a free pin' : undefined },
      busy ? 'Saving…' : base && base.verdict === 'blocked' ? 'Assign anyway ›' : 'Assign ›')] },
  h('form', { className: 'cb-form', onSubmit: submit },
    field('role', 'Role', h('input', { key: 'role', id: 'cb-f-role', value: role, placeholder: 'BUTTON', maxLength: 24, autoComplete: 'off', spellCheck: false,
      'data-cb': 'assign-role', onChange: e => setRole(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '')) }), err('role')),
    field('mode', 'Mode', h('select', { key: 'mode', id: 'cb-f-mode', value: mode, 'data-cb': 'assign-mode', onChange: e => setMode(e.target.value) },
      MODES.map(([m, l]) => h('option', { key: m, value: m }, l))), err('mode')),
    field('pin', 'GPIO', h('input', { key: 'pin', id: 'cb-f-pin', value: pin, inputMode: 'numeric', maxLength: 2, 'data-cb': 'assign-pin',
      onChange: e => setPin(e.target.value.replace(/\D/g, '')) }), err('pin')),
    field('net', 'Net', h('input', { key: 'net', id: 'cb-f-net', value: net, placeholder: 'optional, e.g. BTN', maxLength: 32, autoComplete: 'off',
      spellCheck: false, onChange: e => setNet(e.target.value) }), err('net')),
    h('button', { type: 'submit', className: 'cb-sr', tabIndex: -1 }, 'submit')),
  init.link ? h('p', { className: 'cb-mod-dim cb-mod-note', 'data-cb': 'assign-link' }, `Connects module pin ${init.link.ref} ${init.link.pin} to this net.`) : null,
  pinNum !== null && base ? h('div', { className: 'cb-preview', 'data-cb': 'assign-preview' },
    h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '4px' } },
      h(Stamp, { tone: base.verdict === 'blocked' ? 'bad' : base.verdict === 'caution' ? 'warn' : 'ok' }, `${verdictMeta(base.verdict).stamp} ${verdictMeta(base.verdict).symbol}`),
      h('b', { className: 'cb-fg' }, `GPIO${pinNum}`)),
    mainReason(base) ? mainReason(base).message : 'No findings for this board as a plain input.',
    h('div', { className: 'cb-dim', style: { marginTop: '6px' } }, 'Preview for a plain input. The backend re-checks the pin for the chosen mode when you assign.')) : null,
  fail ? h('div', { className: 'cb-note cb-note--bad', style: { marginTop: '12px', marginBottom: 0 } }, fail) : null)
}
