// Dialogs opened from the palette, the HUD or the empty state: new bench project, project manager, bench doctor.

const NEW_PROJECT_ID_RE = /^[a-z0-9-]{1,48}$/

function NewProjectDialog({ onClose }) {
  const [id, setId] = useState('')
  const [title, setTitle] = useState('')
  const [chip, setChip] = useState('esp32s3')
  const [devkit, setDevkit] = useState('esp32-s3-devkitc-1')
  const [variant, setVariant] = useState('n16r8')
  const [picked, setPicked] = useState(false) // the user chose the module (kept across boards of the same chip)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const info = chipInfo(chip)
  const kits = devkitsOf(chip)
  const kit = devkitInfo(resolveDevkit(chip, devkit))
  const okId = NEW_PROJECT_ID_RE.test(id)
  // board → module variant: the layout's module.variant unless the user chose one; empty on a board
  // with an unknown module (WT32-S1); a new chip starts from its default board's preset
  const pickChip = c => { const d = chipInfo(c)?.devkit ?? null; setChip(c); setDevkit(d); setVariant(defaultVariant(c, d) || ''); setPicked(false) }
  const pickDevkit = d => { setDevkit(d); if (!picked) setVariant(defaultVariant(chip, d) || '') }
  const pickVariant = v => { setVariant(v); setPicked(Boolean(v)) }
  const submit = async e => {
    e?.preventDefault?.()
    if (!okId || busy) return
    setBusy(true)
    setFail(null)
    const env = await createProject({ id, title: title.trim() || id, chip, ...(info?.variants?.length ? { variant: variant || null } : {}), ...(kit ? { devkit: kit.id } : {}) })
    setBusy(false)
    if (env?.ok) onClose()
    else setFail(env?.error?.message || 'Not created.')
  }
  return h(Modal, { title: 'New bench project', onClose, dataCb: 'new-project-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 's', onClick: submit, disabled: !okId || busy, 'data-cb': 'new-project-submit' }, busy ? 'Creating…' : 'Create ›')] },
  h('form', { className: 'cb-form', onSubmit: submit },
    h('label', { htmlFor: 'cb-np-id' }, 'Id'), h('input', { id: 'cb-np-id', value: id, placeholder: 'my-project', maxLength: 48, 'data-cb': 'new-project-id', autoComplete: 'off', spellCheck: false,
      onChange: e => setId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')) }),
    h('label', { htmlFor: 'cb-np-title' }, 'Title'), h('input', { id: 'cb-np-title', value: title, placeholder: 'optional', maxLength: 80, onChange: e => setTitle(e.target.value) }),
    h('label', { htmlFor: 'cb-np-chip' }, 'Chip'), h('select', { id: 'cb-np-chip', value: chip, 'data-cb': 'new-project-chip', onChange: e => pickChip(e.target.value) },
      CHIPS.map(c => h('option', { key: c.id, value: c.id }, c.label))),
    kits.length ? [h('label', { key: 'l', htmlFor: 'cb-np-kit' }, 'Board'), h('select', { key: 's', id: 'cb-np-kit', value: kit?.id || '', 'data-cb': 'new-project-devkit',
      onChange: e => pickDevkit(e.target.value) }, kits.map(d => h('option', { key: d.id, value: d.id }, devkitTitle(d))))] : null,
    info?.variants?.length ? [h('label', { key: 'l', htmlFor: 'cb-np-var' }, 'Module'), h('select', { key: 's', id: 'cb-np-var', value: variant || '', 'data-cb': 'new-project-variant',
      onChange: e => pickVariant(e.target.value) },
    h('option', { key: '-', value: '' }, kit?.module && !kit.variant ? `${kit.module} · variant not stated, set it later if you know it` : 'not set · set it later'),
    variantGroups(chip).map(g => h('optgroup', { key: g.label, label: g.label }, g.variants.map(v => h('option', { key: v.id, value: v.id }, `${v.label} · ${variantTitle(v)}`)))))] : null,
    h('button', { type: 'submit', className: 'cb-sr', tabIndex: -1 }, 'submit')),
  h('p', { className: 'cb-dim', style: { margin: '10px 0 0' } }, kit ? `Board view: ${devkitTitle(kit)}.` : 'No DevKit header map for this chip; pins are still checked.'),
  fail ? h('div', { className: 'cb-note cb-note--bad', style: { marginTop: '12px', marginBottom: 0 } }, fail) : null)
}

/** Project manager: every bench project with board and last change; open one, or move one to the trash (two clicks:
 *  Delete, then "Move to trash" in the row). The backend keeps the folder under trash/, nothing is erased. */
function ProjectsDialog({ onClose }) {
  const bench = sdk.useValue($bench)
  const current = sdk.useValue($project)?.id || null
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let live = true
    refreshProjects().then(env => {
      if (!live) return
      setLoaded(true)
      if (!env.ok) setMsg({ tone: 'bad', text: env.error?.message || 'Could not list the projects.' })
    })
    return () => { live = false }
  }, [])
  const list = bench.projects || []
  const open = async id => {
    setBusy(id)
    await openProject(id)
    setBusy(null)
    onClose()
  }
  const del = async id => {
    setBusy(id)
    const env = await removeProject(id)
    setBusy(null)
    setConfirm(null)
    setMsg(env.ok ? { tone: 'ok', text: env.summary } : { tone: 'bad', text: env.error?.message || env.summary || 'Not deleted.' })
  }
  const boardText = p => {
    const v = variantInfo(p.chip, p.variant)
    return [devkitInfo(p.devkit)?.label || chipInfo(p.chip)?.label || p.chip, v?.label].filter(Boolean).join(' · ')
  }
  return h(Modal, { title: 'Bench projects', onClose, dataCb: 'projects-dialog', wide: true,
    footer: [h(Btn, { key: 'n', kind: 'ghost', 'data-cb': 'projects-new', onClick: () => patchAtom($ui, { modal: { type: 'new-project' } }) }, 'New project'),
      !list.some(p => p.id === 'laser-trigger') ? h(Btn, { key: 'd', kind: 'quiet', 'data-cb': 'projects-demo', onClick: async () => { onClose(); await loadDemo() } }, 'Load demo') : null,
      h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Close')] },
  !loaded && !list.length ? h('div', { className: 'cb-loading', style: { padding: '12px 0' } }, 'listing projects')
    : !list.length ? h('p', { className: 'cb-why cb-dim', 'data-cb': 'projects-empty' }, 'No bench projects yet.')
      : h('ul', { className: 'cb-projlist', 'data-cb': 'projects-list' }, list.map(p => {
        const here = p.id === current
        const asking = confirm === p.id
        return h('li', { key: p.id, className: 'cb-projrow', 'data-cb': 'project-row', 'data-cb-id': p.id, 'aria-current': here ? 'true' : undefined },
          h('div', { className: 'cb-projmain' },
            h('div', { className: 'cb-projtitle' }, h('span', { className: here ? 'cb-ok' : 'cb-dim', 'aria-hidden': 'true' }, here ? '▶' : '·'),
              h('b', null, p.id), p.title && p.title !== p.id ? h('span', { className: 'cb-dim cb-ellip', title: p.title, 'data-cb-truncate-ok': 'true' }, p.title) : null),
            // second line: the SIM badge first (it never gives way), then the meta text, which may end in an ellipsis
            h('div', { className: 'cb-projmeta cb-dim' },
              p.simulated ? h(SimBadge, { compact: true, dataCb: 'sim-badge-project' }) : null,
              h('span', { className: 'cb-ellip', title: `${boardText(p)} · rev ${p.rev} · ${formatStamp(p.updated)}`, 'data-cb-truncate-ok': 'true' },
                `${boardText(p)} · rev ${p.rev} · ${formatStamp(p.updated)}`))),
          asking
            ? h('div', { className: 'cb-projconfirm', role: 'group', 'aria-label': `Delete ${p.id}?` },
              h('span', { className: 'cb-warn' }, here ? 'Delete the open project?' : 'Delete?'),
              h(Btn, { kind: 'quiet', size: 'sm', onClick: () => setConfirm(null) }, 'Keep'),
              h(Btn, { kind: 'danger', size: 'sm', 'data-cb': 'project-delete-confirm', disabled: busy === p.id, onClick: () => del(p.id) },
                busy === p.id ? 'Moving…' : 'Move to trash'))
            : h('div', { className: 'cb-projact' },
              here ? h('span', { className: 'cb-tag' }, 'open') : h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'project-open', disabled: Boolean(busy), onClick: () => open(p.id) }, busy === p.id ? 'Opening…' : 'Open'),
              h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'project-delete', disabled: Boolean(busy), title: `Move ${p.id} to the trash`, onClick: () => { setMsg(null); setConfirm(p.id) } }, 'Delete')))
      })),
  confirm ? h('p', { className: 'cb-dim', 'data-cb': 'projects-trash-note', style: { margin: '10px 0 0', lineHeight: 1.5 } },
    'The project folder (pins, parts, calculations, wiring, solder steps, a copied firmware/) moves to the bench trash folder; ',
    'nothing is erased, and firmware folders outside the project are not touched.') : null,
  msg ? h('div', { className: `cb-note cb-note--${msg.tone}`, 'data-cb': 'projects-msg', role: 'status', style: { marginTop: '12px', marginBottom: 0, wordBreak: 'break-word' } }, msg.text) : null)
}

function DoctorDialog({ env, onClose }) {
  const r = env?.ok ? env.result : null
  return h(Modal, { title: 'Bench doctor', onClose, dataCb: 'doctor-dialog', footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Close'),
    h(Btn, { key: 'r', kind: 'ghost', onClick: () => runDoctor() }, 'Run again')] },
  !env ? h('div', { className: 'cb-loading', style: { padding: '12px 0' } }, 'checking tools')
    : !env.ok ? h('p', { className: 'cb-why cb-bad' }, `✕ ${env.error?.message || env.summary}`)
      : [h('p', { key: 's', className: 'cb-why' }, env.summary),
        h(ChecksList, { key: 'c', checks: env.checks, warnings: env.warnings, dataCb: 'doctor-checks' }),
        r?.hardware ? h('div', { key: 'h', className: 'cb-kv', style: { marginTop: '10px' } },
          h('span', null, 'hardware'), h('b', { className: r.hardware.enabled ? 'cb-ok' : 'cb-active' }, r.hardware.enabled ? 'on' : 'off (simulated boards only)'),
          h('span', null, 'allow flash'), h('b', null, r.settings?.allow_flash ? 'on' : 'off'),
          h('span', null, 'data'), h('b', { className: 'cb-ellip', title: r.data_dir?.path }, r.data_dir?.writable ? 'writable' : 'not writable')) : null])
}
