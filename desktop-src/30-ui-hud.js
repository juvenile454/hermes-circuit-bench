// HUD: brand, project, board + variant, link, key figures, primary action.

/** Link state from the port list (listing never opens a port): real ESP port → LINK, sim → SIM, none → NO BOARD.
 *  The words are information, so the quiet states use fg-dim, never the decoration colour fg-faint. */
function linkState(ports, project = null) {
  const list = ports?.ports || []
  if (ports?.status === 'error') return { kind: 'offline', label: 'OFFLINE', device: '', tone: 'dim', dot: 'off' }
  if (ports?.status === 'idle' || ports?.status === 'loading') return { kind: 'unknown', label: '…', device: '', tone: 'dim', dot: 'off' }
  // HUD: the port the project was detected on, if any (status chip: whatever is plugged in)
  const detected = project?.board?.detected?.port || null
  if (detected) {
    const hit = list.find(p => p.device === detected)
    if (!hit) return { kind: 'lost', label: 'LOST', device: detected, tone: 'warn', dot: 'off' }
    return hit.simulated ? { kind: 'sim', label: 'SIM', device: detected, tone: 'active', dot: 'active' }
      : { kind: 'link', label: 'LINK', device: detected, tone: 'ok', dot: 'ok' }
  }
  const real = list.find(p => !p.simulated && p.likely_esp)
  const sim = list.find(p => p.simulated)
  if (real) return { kind: 'link', label: 'LINK', device: real.device, tone: 'ok', dot: 'ok' }
  if (sim) return { kind: 'sim', label: 'SIM', device: sim.device, tone: 'active', dot: 'active' }
  return { kind: 'none', label: 'NO BOARD', device: '', tone: 'dim', dot: 'off' }
}

function Hud({ project, rows, health }) {
  const ports = sdk.useValue($ports)
  const nProjects = (sdk.useValue($bench).projects || []).length
  const nav = sdk.useValue($nav)
  const check = sdk.useValue($check)
  const counts = countVerdicts(rows)
  const fig = hudFigures(project, counts)
  const link = linkState(ports, project)
  const b = project?.board || {}
  const chip = chipInfo(b.chip)
  const variant = variantInfo(b.chip, b.variant)
  const [busy, setBusy] = useState(false)
  const ask = async () => {
    setBusy(true)
    try { await composeDraft(askHermesText(project, nav.station, rows)) } finally { setBusy(false) }
  }
  const version = health?.version ? `v${String(health.version).replace(/\.0$/, '')}` : 'v0.1'
  const kpi = shellKpis(counts, fig.solder, fig.build, modCountWords(stageModCounts(check.env)))
  return h('header', { className: 'cb-hud', 'data-cb': 'hud', 'data-cb-audit-root': 'hud' },
    h('div', { className: 'cb-brand', 'data-cb': 'hud-brand' }, '◢ CIRCUIT//BENCH', h('small', null, version)),
    h('div', { className: 'cb-sep', 'aria-hidden': 'true' }),
    // own button for the project manager (a clickable project chip was not recognisable as a control)
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'hud-projects', 'aria-haspopup': 'dialog', 'aria-label': `Projects (${nProjects})`,
      title: 'Open, create or delete bench projects', onClick: () => patchAtom($ui, { modal: { type: 'projects' } }) },
      h('span', { 'aria-hidden': 'true' }, '▤'), h('span', { className: 'cb-hud-btxt' }, 'Projects'),
      nProjects ? h('span', { className: 'cb-hud-count', 'aria-hidden': 'true' }, String(nProjects)) : null),
    project ? h('div', { className: 'cb-pill', 'data-cb': 'hud-project', title: project.title || project.id },
      // the project id is the one HUD text that may end in an ellipsis (full id + title in the tooltip)
      h(Label, null, 'prj'), h('b', { title: project.id, 'data-cb-truncate-ok': 'true' }, project.id)) : null,
    project ? h('div', { className: 'cb-pill', 'data-cb': 'hud-board', title: b.devkit || 'no DevKit layout' },
      h(Label, null, 'board'), h('b', null, devkitInfo(b.devkit)?.label || chip?.label || b.chip || '—'),
      variant ? h('span', { className: variant.psram === 'octal' ? 'cb-warn' : 'cb-fg',
        title: variant.psram === 'octal' ? 'Octal PSRAM: GPIO33–37 are reserved' : `${variant.label}` }, variant.label) : null) : null,
    // simulated link: the SIM badge is the only frame (no pill border around it); the device name may give way
    link.kind === 'sim'
      ? h('div', { className: 'cb-hudsim', 'data-cb': 'hud-link', 'data-cb-link': 'sim', title: `${link.device} — simulated board, nothing physical is read or written` },
        h(SimBadge, { dataCb: 'sim-banner-hud' }), h('b', { className: 'cb-simdev' }, link.device.replace(/^sim:\/\//, '')))
      : h('div', { className: 'cb-pill', 'data-cb': 'hud-link', 'data-cb-link': link.kind, title: link.device || link.label },
        h('span', { className: `cb-dot cb-dot--${link.dot}`, 'aria-hidden': 'true' }),
        h('span', { className: `cb-${link.tone}` }, link.label), link.device ? h('b', null, link.device) : null),
    project ? h('div', { className: 'cb-kpis', 'data-cb': 'hud-kpis' },
      h(HudKpi, { dataCb: 'kpi-pins', label: 'pins', aria: kpi.pins.label },
        // no zero groups
        (kpi.pins.items.some(i => !i.quiet) ? kpi.pins.items.filter(i => !i.quiet) : kpi.pins.items.slice(0, 1)).map(it =>
          h('span', { key: it.key, className: `cb-kpi-i cb-${it.tone}`, 'data-cb-kpi': it.key },
            h('span', { 'aria-hidden': 'true' }, it.symbol), h('b', null, String(it.n)), it.word ? h('span', { className: 'cb-kpi-w' }, it.word) : null))),
      h(HudKpi, { dataCb: 'kpi-solder', label: 'solder', aria: kpi.solder.label },
        h('b', { className: fig.solder.total ? 'cb-fg' : 'cb-dim' }, kpi.solder.text),
        fig.solder.total ? h('span', { className: 'cb-kpi-bar cb-active', 'aria-hidden': 'true' }, cellBar(fig.solder.done, fig.solder.total, 8)) : null),
      h(HudKpi, { dataCb: 'kpi-build', label: 'build', aria: kpi.build.label },
        h('span', { className: `cb-${kpi.build.tone}` }, kpi.build.word),
        kpi.build.ram !== null ? h('small', null, `ram ${formatPct(kpi.build.ram)}`) : null)) : h('div', { style: { marginLeft: 'auto' } }),
    h(Btn, { kind: 'agent', onClick: ask, disabled: busy || !project, 'data-cb': 'ask-hermes', title: 'Put a prompt about this project into the chat composer (not sent)' }, 'Ask Hermes'))
}

/** One HUD key figure: label above, value line below; the whole sentence as aria-label and title (the narrow HUD
 *  keeps only symbol + number). */
function HudKpi({ dataCb, label, aria, children }) {
  return h('div', { className: 'cb-kpi', 'data-cb': dataCb, role: 'group', 'aria-label': aria, title: aria },
    h(Label, { 'aria-hidden': 'true' }, label), h('span', { className: 'cb-v' }, children))
}
