// Module dialog: openModules({q?, category?, interface?, module?, ref?, address?}); list → detail
// (add_module) or, with ref, the instance view

const MOD_CLASS_TITLE = { A: 'manufacturer', A1: 'manufacturer, archive copy', A2: 'manufacturer, third-party copy', B: 'unverified' }

function ModTags({ m }) {
  const ifs = modInterfaces(m.interfaces)
  const addrs = Array.isArray(m.addresses) ? m.addresses : modAddressChoices(m).list
  const sup = typeof m.supply === 'string' ? m.supply : modSupply(m.supplies)
  const cls = m.class || null
  return h('span', { className: 'cb-mod-tags' },
    ifs.map(t => h('span', { key: t, className: 'cb-mod-tag' }, t)),
    addrs.length ? h('span', { className: 'cb-mod-tag', title: `I²C addresses: ${modAddresses(addrs)}` },
      addrs.length > 3 ? `${modAddress(addrs[0])}–${modAddress(addrs[addrs.length - 1])} (${addrs.length})` : modAddresses(addrs)) : null,
    sup && sup !== '—' ? h('span', { className: 'cb-mod-tag cb-mod-tag--pwr', title: 'supply range' }, sup) : null,
    cls ? h('span', { className: `cb-mod-tag${cls === 'B' ? ' cb-mod-tag--warn' : ''}`, title: `source class ${cls}: ${MOD_CLASS_TITLE[cls] || cls}` },
      `${cls === 'B' ? '? ' : ''}class ${cls}`) : null)
}

const modShort = t => { const s = String(t || ''); const i = s.indexOf(' '); return i > 0 ? [s.slice(0, i), s.slice(i + 1)] : [s, ''] }

function ModulesDialog({ init = null, onClose }) {
  const project = sdk.useValue($project)
  const [q, setQ] = useState(init?.q || '')
  const [qx, setQx] = useState(init?.q || '')
  const [cat, setCat] = useState(init?.category || '')
  const startRef = init?.ref ? moduleInstances(project).find(i => i.ref === String(init.ref).toUpperCase()) : null
  const [pick, setPick] = useState(init?.module || startRef?.module || null)
  const box = useRef(null)
  const mem = useRef({ top: 0, id: null }) // list scroll + row picked in the list (restored by ‹ Catalog)
  useEffect(() => { const t = setTimeout(() => setQx(q.trim()), 200); return () => clearTimeout(t) }, [q])
  useEffect(() => {
    const dlg = box.current?.parentNode // the list box and ModuleDetail's box sit straight in the Modal dialog
    if (!pick && box.current) box.current.scrollTop = mem.current.top
    ;((pick ? dlg?.querySelector('[data-cb=modules-back]') : mem.current.id && dlg?.querySelector(`[data-cb=module-row][data-cb-id="${mem.current.id}"]`))
      || dlg?.querySelector('[data-cb=modules-search]'))?.focus?.({ preventScroll: true })
  }, [pick])
  const filter = { q: qx, category: cat, interface: init?.interface }
  const cat0 = useModuleCatalog(filter)
  const env = cat0.env
  const items = env?.ok ? env.result?.items || [] : []
  const total = env?.ok ? env.result?.total ?? items.length : 0
  const cats = modCategories(env?.ok ? env.result : null, ...(cat0.cats || []), cat)
  const info = useModuleInfo(pick)
  const pm = info.env?.ok ? info.env.result?.module ?? info.env.result : null
  const listed = pick && mem.current.id === pick
  const inst = listed || !startRef ? null : { ...startRef, address: startRef.address || init.address }
  // ↑/↓ between search and rows
  const keys = e => {
    const d = { ArrowDown: 1, ArrowUp: -1 }[e.key]
    const rows = [...box.current.querySelectorAll('[data-cb=modules-search],[data-cb=module-row]')]
    const i = rows.indexOf(document.activeElement)
    const to = d && i >= 0 && rows[i + d]
    if (to) { e.preventDefault(); to.focus() }
  }
  return h(Modal, { title: pick ? `${inst ? `${inst.ref} · ` : ''}${pm?.title || 'Module'}` : 'Module catalog', dataCb: 'modules-dialog', wide: true,
    onClose: listed ? () => setPick(null) : onClose, // Escape: back to the list
    footer: [pick ? h(Btn, { key: 'b', kind: 'quiet', onClick: () => setPick(null), 'data-cb': 'modules-back' }, '‹ Catalog') : null,
      h(Btn, { key: 'c', kind: 'quiet', onClick: onClose, 'data-cb': 'modules-close' }, 'Close')] },
  pick ? h(ModuleDetail, { id: pick, project, st: info, onClose, box, inst }) :
  h('div', { ref: box, className: 'cb-mod-dlg', onKeyDown: keys },
    h('div', { className: 'cb-mod-filter' },
      h('input', { className: 'cb-mod-search', 'data-cb': 'modules-search', 'aria-label': 'Search modules', value: q, maxLength: 40,
        placeholder: 'search: part, title, alias', autoComplete: 'off', spellCheck: false, onChange: e => setQ(e.target.value) }),
      h('select', { className: 'cb-mod-cat', 'data-cb': 'modules-category', 'aria-label': 'Category', value: cat, onChange: e => setCat(e.target.value) },
        h('option', { value: '' }, 'all categories'), cats.map(c => h('option', { key: c, value: c }, modCategoryLabel(c))))),
    cat0.status === 'loading' && !env ? h('div', { className: 'cb-loading cb-mod-pad' }, 'loading the catalog')
      : env && !env.ok ? h('p', { className: 'cb-why cb-bad', 'data-cb': 'modules-error' }, `✕ ${env.error?.message || env.summary}`)
        : [h('p', { key: 's', className: 'cb-mod-sum', 'data-cb': 'modules-summary', role: 'status' },
          items.length ? `${items.length} of ${total} module${total === 1 ? '' : 's'}${cat ? ` · ${modCategoryLabel(cat)}` : ''}${items.length > 6 ? ' · scroll ↓' : ''}`
            : 'No module matches. Try another word or all categories.'),
        items.length ? h('ul', { key: 'l', className: 'cb-mod-items', 'data-cb': 'modules-list' }, items.map(m => {
          const [name, rest] = modShort(m.title || m.id)
          return h('li', { key: m.id },
            h('button', { type: 'button', className: 'cb-mod-item', 'data-cb': 'module-row', 'data-cb-id': m.id, title: m.title,
              'aria-current': mem.current.id === m.id ? 'true' : undefined, onClick: () => { mem.current = { top: box.current.scrollTop, id: m.id }; setPick(m.id) } },
            h('span', { className: 'cb-mod-itemhead' }, h('b', null, name), h('span', { className: 'cb-mod-ellip', 'data-cb-truncate-ok': 'true' }, rest),
              h('span', { className: 'cb-mod-catl' }, modCategoryLabel(m.category))),
            h(ModTags, { m })))
        })) : null,
        items.length && items.length < total ? h(Btn, { key: 'm', kind: 'quiet', size: 'sm', 'data-cb': 'modules-more', disabled: cat0.status === 'loading',
          onClick: () => loadModuleCatalog(filter, { more: true }) }, `Load more (${total - items.length} left)`) : null]))
}

// fact line: label, value, page (title = quoted evidence)
function ModFact({ k, v, f }) {
  const ev = modEvidence(f)
  return h('div', { className: 'cb-mod-fact', title: ev || undefined },
    h('span', { className: 'cb-mod-k' }, k), h('span', null, v), ev ? h('span', { className: 'cb-mod-page' }, ev.split(' · ')[0]) : null)
}

function ModuleDetail({ id, project, st, onClose, box, inst = null }) {
  const env = st.env
  const m = env?.ok ? env.result?.module ?? env.result : null
  const assigns = project?.assignments || []
  const choice = modAddressChoices(m)
  const [addr, setAddr] = useState(null)
  const [wire, setWire] = useState(true)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const [ask, setAsk] = useState(false) // remove in two clicks
  const ws = useModuleCheck().findings.warnings.filter(w => inst && (w.refs || []).includes(inst.ref))
  const address = addr || choice.def || choice.list[0] || null
  const conn = m ? modSuggestConn(m, assigns, address) : {}
  const ref = modNextRef(project?.parts || [])
  const act = async () => {
    if (inst && !ask) return setAsk(true)
    setBusy(true)
    setFail(null)
    const res = await (inst ? removePartsFromProject([inst.ref]) : addModule({ module: id, ref, address: choice.list.length ? address : undefined, conn: wire ? conn : undefined }))
    setBusy(false)
    setAsk(false)
    if (res?.ok) onClose(); else setFail(res?.error?.message || res?.summary || 'Not saved.')
  }
  const sec = (title, body) => (body ? h('section', { key: title, className: 'cb-mod-sec' }, h(Label, null, title), body) : null)
  const io = m?.io || {}
  const IO = [['VIH', 'vih'], ['VIL', 'vil'], ['VOH', 'voh'], ['VOL', 'vol'], ['VIN max', 'v_in_max'], ['5 V tolerant', 'five_v_tolerant']].filter(([, k]) => io[k] != null)
  const sources = env?.sources || []
  return (
  h('div', { ref: box, className: 'cb-mod-dlg', 'data-cb': 'module-detail', 'data-cb-id': id },
    !m ? (env && !env.ok ? h('p', { className: 'cb-why cb-bad', 'data-cb': 'modules-error' }, `✕ ${env.error?.message || env.summary}`)
      : h('div', { className: 'cb-loading cb-mod-pad' }, 'loading the module'))
      : [h('div', { key: 'h', className: 'cb-mod-dhead' },
        h('span', { className: 'cb-mod-catl' }, [m.manufacturer, modCategoryLabel(m.category), m.kind].filter(Boolean).join(' · ')), h(ModTags, { m })),
      h('section', { key: 'a', className: 'cb-mod-addbox', 'data-cb': inst ? 'module-instance' : 'module-add' },
        h(Label, null, inst ? `// ${inst.ref} in this project` : `// add as ${ref}`),
        inst ? [h(ModFact, { key: 'a', k: 'address', v: modAddress(inst.address) || '—' }),
          h(ModFact, { key: 'c', k: 'conn', v: Object.entries(inst.conn).map(([p, n]) => `${p}→${n}`).join(' · ') || 'no pins connected' }),
          h('ul', { key: 'f', className: 'cb-mod-list', 'data-cb': 'module-inst-findings' }, ws.length ? ws.map(modFindingRow) : h('li', { className: 'cb-mod-dim' }, 'No module findings in the latest check.'))]
        : choice.list.length ? h('label', { className: 'cb-mod-inline' }, h('span', { className: 'cb-mod-k' }, 'address'),
          h('select', { 'data-cb': 'modules-address', value: address || '', onChange: e => setAddr(e.target.value) },
            choice.list.map(a => h('option', { key: a, value: a }, `${a}${a === choice.def ? ' (default)' : ''}`)))) : null,
        !inst && Object.keys(conn).length ? h('label', { className: 'cb-mod-inline' },
          h('input', { type: 'checkbox', checked: wire, 'data-cb': 'modules-connect', onChange: e => setWire(e.target.checked) }),
          h('span', null, 'connect pins: ', h('span', { className: 'cb-mod-dim', 'data-cb': 'modules-conn' }, Object.entries(conn).map(([p, n]) => `${p}→${n}`).join(' · ')))) : null,
        h('div', { className: 'cb-mod-addrow' },
          h('span', { className: 'cb-mod-dim cb-mod-note' }, inst ? 'Pins and roles are in the assignment table.' : 'Open signal pins appear as “— assign” in the table.'),
          inst ? h(Btn, { onClick: act, kind: ask ? 'danger' : 'quiet', size: 'sm', disabled: busy, 'data-cb': 'module-remove' }, busy ? 'Removing…' : `Remove ${inst.ref}${ask ? ' for good' : '…'}`)
            : h(Btn, { onClick: act, disabled: !m || busy || !project, 'data-cb': 'modules-add', title: project ? `Add as ${ref} to ${project.id}` : 'Open a project first' },
              busy ? 'Adding…' : 'Add to project ›')),
        fail ? h('div', { className: 'cb-note cb-note--bad', role: 'alert' }, `✕ ${fail}`) : null),
      h('div', { key: 'g', className: 'cb-mod-dgrid' },
        sec('// pins', h('table', { className: 'cb-mod-pins', 'data-cb': 'module-pins' }, h('tbody', null, (m.pins || []).map(p => h('tr', { key: p.name },
          h('td', { className: 'cb-mod-nw' }, h('b', null, p.name)), h('td', { className: 'cb-mod-dim cb-mod-nw' }, String(p.signal || '').replace(/_/g, ' ')),
          h('td', { className: 'cb-mod-dim' }, [p.tie ? `tie ${p.tie}` : '', p.must_connect ? 'must connect' : '', p.note || ''].filter(Boolean).join(' · '))))))),
        h('div', { className: 'cb-mod-dcol' },
          sec('// supply', Object.entries(m.supplies || {}).map(([pin, s]) => h(ModFact, { key: pin, k: pin, f: s.min || s.max,
            v: `${modSupply(s)}${s.typ ? ` · typ ${modFText(s.typ)}` : ''}${s.abs_max ? ` · abs max ${modFText(s.abs_max)}` : ''}` }))),
          sec('// levels', IO.length || io.outputs ? [io.domain ? h(ModFact, { key: 'd', k: 'domain', v: io.domain }) : null,
            ...IO.map(([k, key]) => h(ModFact, { key, k, v: modFText(io[key]), f: io[key] })),
            io.outputs ? h(ModFact, { key: 'o', k: 'outputs', v: String(io.outputs).replace(/_/g, ' ') }) : null] : null),
          sec('// current', m.current ? ['typ', 'max', 'peak', 'sleep'].filter(k => m.current[k]).map(k => h(ModFact, { key: k, k, v: modFText(m.current[k]), f: m.current[k] })) : null))),
      sec('// required parts', (m.requires || []).length ? h('ul', { key: 'r', className: 'cb-mod-list', 'data-cb': 'module-requires' }, m.requires.map((r, i) => {
        const calc = modRequireCalc(r, m)
        return h('li', { key: `${r.code}-${i}`, className: 'cb-mod-row cb-mod-row--r', title: modEvidence(r) || undefined },
          modSym('+'), h('span', null, modRequireText(r), r.page != null ? h('span', { className: 'cb-mod-page' }, ` p. ${r.page}`) : null),
          calc ? modCalcLink(calc, 'module', e => { const n = e.currentTarget; onClose(); openCalc(calc, n) }) : h('span'))
      })) : null),
      sec('// hazards', (m.hazards || []).length ? h('ul', { key: 'z', className: 'cb-mod-list' }, m.hazards.map((z, i) => h('li', { key: i, className: 'cb-mod-row cb-mod-row--f cb-mod-row--warn', title: modEvidence(z) || undefined },
        modSym('◇'), h('span', null, h('b', null, 'hazard'), ` ${z.text || z.code}`)))) : null),
      sec('// notes', (m.notes || []).length ? h('ul', { key: 'n', className: 'cb-mod-list' }, m.notes.map((n, i) => h('li', { key: i, className: `cb-mod-row cb-mod-row--f${n.verified ? '' : ' cb-mod-row--dim'}`, title: modEvidence(n) || undefined },
        modSym(n.verified ? 'i' : '?'), h('span', null, n.text, ' ', h('span', { className: 'cb-mod-page' }, n.verified ? `p. ${n.page ?? '—'}` : 'unverified'))))) : null),
      h('div', { key: 's', className: 'cb-mod-srcrow' }, h(SourceLine, { sources }))]))
}
