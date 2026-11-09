// Station registry + calm placeholders for 02–06 (later files set STATION_VIEWS.<id>).
//   STATION_VIEWS[id] = { component, inspector }  component({project, rows, ...}) renders main (+ aside when inspector)

const STATION_VIEWS = {}

const STATION_SOON = {
  calc: { what: 'LED, NPN switch, voltage divider and I²C pull-up calculators with formula, E-series value, assumptions and source.',
    next: 'Ask Hermes: “size the base resistor for an NPN switch”.' },
  wire: { what: 'Schematic per building block (SVG in bench colours) and the wiring table board ↔ part with net names.',
    next: 'Ask Hermes: “draw an NPN low-side switch on GPIO4”.' },
  solder: { what: 'One card per solder step, in order (flat → tall, robust → sensitive, connectors last), with polarity and heat warnings.',
    next: 'Ask Hermes: “plan the solder order for this project”.' },
  flash: { what: 'Board detection, build result (RAM/flash) and flashing with a confirmation dialog (port, MAC, firmware hash).',
    next: 'Nothing is flashed without your confirmation.' },
  debug: { what: 'Live serial stream, automatic panic detection, decoded frames (function, file:line) and the interpretation.',
    next: 'The console below already shows what the backend buffered.' }
}

function soonFacts(id, project) {
  if (!project) return []
  if (id === 'calc') return (project.calcs || []).map(c => ({ k: c.id, title: `${c.type} · ${c.id}`,
    text: Object.values(c.result || {}).map(q => formatQty(q)).join(' · ') || '—' }))
  if (id === 'wire') return (project.circuits || []).map(c => ({ k: c.id, title: `${c.block} · ${c.id}`,
    text: Object.entries(c.params || {}).map(([k, v]) => `${k} ${typeof v === 'number' ? formatSI(v, k.startsWith('r_') ? 'Ω' : '') : v}`).join(' · ') }))
  if (id === 'solder') {
    const sp = solderProgress(project)
    const done = new Set(project.solder?.done || [])
    return sp.total ? (project.solder.steps || []).slice(0, 8).map(s => ({ k: s.id, title: `${done.has(s.id) ? '[✓]' : '[ ]'} ${s.n} · ${s.kind}`,
      text: nbspUnits(s.action), tone: done.has(s.id) ? 'ok' : null })) : []
  }
  if (id === 'flash') {
    const fw = project.firmware || {}
    return [fw.last_build && { k: 'b', title: `build ${fw.last_build.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_build.at)}`,
      text: `RAM ${formatPct(fw.last_build.ram_pct)} · flash ${formatPct(fw.last_build.flash_pct)} · ${shortHash(fw.last_build.elf_sha256)}` },
    fw.last_flash && { k: 'f', title: `flash ${fw.last_flash.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_flash.at)}`,
      text: `${fw.last_flash.port} · ${shortHash(fw.last_flash.elf_sha256)}` }].filter(Boolean)
  }
  if (id === 'debug') {
    const p = project.debug?.last_panic
    return p ? [{ k: 'p', title: `last panic · ${formatClock(p.at)}`, text: `${p.reason} on core ${p.core} · ${p.top_frame}` }] : []
  }
  return []
}

function StationSoon({ station, project }) {
  const s = stationInfo(station)
  const soon = STATION_SOON[station] || { what: '', next: '' }
  const facts = soonFacts(station, project)
  return h('main', { className: 'cb-main cb-station', 'data-cb': `station-${station}`, key: station },
    h(DecodeTitle, { text: `${s.n} // ${s.heading}`, meta: 'read-only preview' }),
    h('p', { className: 'cb-why cb-dim', style: { maxWidth: '640px' } }, soon.what),
    station === 'solder' && solderProgress(project).total ? h('div', { className: 'cb-note', style: { marginTop: '14px', maxWidth: '640px' }, 'data-cb': 'solder-progress' },
      h(Label, null, 'progress'), h('b', { className: 'cb-fg' }, `${solderProgress(project).done}/${solderProgress(project).total}`),
      h('span', { className: 'cb-active', style: { letterSpacing: '-.05em' } }, cellBar(solderProgress(project).done, solderProgress(project).total, 12))) : null,
    facts.length ? [h(Label, { key: 'l', style: { display: 'block', marginTop: '16px' } }, '// from the project'),
      h('div', { key: 'g', className: 'cb-soon', 'data-cb': 'station-facts' }, facts.map(f => h('div', { key: f.k, className: 'cb-card' },
        h('b', { className: f.tone ? `cb-${f.tone}` : undefined }, f.title), f.text)))]
      : h(EmptyBox, { kicker: `// ${s.n} ${s.title.toLowerCase()}`, title: 'Nothing here yet', dataCb: 'station-empty' }, h('p', null, soon.next)))
}
