// Station 05 FLASH: ports (real first, sim below, nothing opens on its own), detect job + variant takeover, firmware
// folder (own folder or the example), build job, flash only through the confirmation dialog.

function nextFlashStep(project, ports) {
  const det = project?.board?.detected
  const fw = project?.firmware || {}
  const listed = det?.port && (ports.ports || []).some(p => p.device === det.port)
  if (!det?.port || !listed) return 'detect'
  if (!fw.dir) return 'firmware'
  const conf = flashConfirm(project)
  if (!conf.ok) return 'build'
  return conf.alreadyFlashed ? 'done' : 'flash'
}

function JobLine({ job, note, kind }) {
  const pr = jobProgress(job)
  if (note) {
    return h('div', { className: 'cb-jobline cb-bad', 'data-cb': `job-${kind}-error`, role: 'alert' },
      h('span', null, `✕ ${note.message}`), note.hint ? h('span', { className: 'cb-dim' }, note.hint) : null,
      note.code === 'flash_disabled' ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'agent-settings-link', onClick: () => openAgentSettings() }, 'Agent settings ›') : null)
  }
  if (!job) return null
  // while the job runs: phase word from its log (writing, verifying …) and the progress of job.progress
  const phase = flashJobPhase(job)
  return h('div', { className: `cb-jobline cb-${pr.failed ? 'bad' : pr.done ? 'ok' : 'active'}`, 'data-cb': `job-${kind}`, 'data-cb-state': job.state, 'data-cb-job': job.job_id,
    'data-cb-phase': phase ? phase.word : undefined },
  h('span', { 'aria-hidden': 'true' }, pr.running ? '◴' : pr.failed ? '✕' : '✓'),
  phase ? h('span', { className: 'cb-vf-phase' }, h('b', null, kind), h('span', { className: 'cb-vf-phase-w' }, phase.word),
    phase.pct !== null ? h('span', { className: 'cb-mono-num' }, `${phase.pct} %`) : null)
    : h('span', null, `${kind} ${pr.text}`),
  pr.running ? h(Bar, { pct: pr.indeterminate ? null : pr.pct, label: `${kind} progress${phase ? ` · ${phase.word}` : ''}` }) : null,
  h('span', { className: 'cb-dim cb-push' }, job.job_id))
}

/** Connector symbol of a port (artPort, the same shape as on the board model); nothing when the kind is unknown. */
function FlashPortSymbol({ kind, board }) {
  if (!kind || !ART_PORT_SIZE[kind]) return null
  const [w, ht] = ART_PORT_SIZE[kind]
  const what = { micro_usb: 'Micro-USB', usb_c: 'USB-C', generic_usb: 'USB (connector type not in the board data)' }[kind] || kind
  return h('svg', { className: 'cb-vf-portsym', viewBox: `-2 -2 ${w + 4} ${ht + 4}`, role: 'img', 'aria-label': `${what} on ${board || 'the board'}`,
    'data-cb': 'port-symbol', 'data-cb-port': kind, focusable: 'false', dangerouslySetInnerHTML: { __html: artPort(kind, 0, 0) } })
}

function PortList({ ports, project, flow, health }) {
  const det = project?.board?.detected?.port || null
  const rows = portRows(ports.ports, { detectedPort: det, selected: flow.port })
  const jobs = sdk.useValue($jobs)
  const layout = sdk.useValue($board).layout
  const running = jobProgress(jobs.detect).running
  const byDevice = new Map((ports.ports || []).map(p => [p.device, p]))
  if (ports.status === 'error') return h('p', { className: 'cb-why cb-warn' }, '! Port list unavailable: ', ports.error?.error?.message || 'backend error')
  return h('div', { className: 'cb-ports', 'data-cb': 'port-list', role: 'radiogroup', 'aria-label': 'Serial ports' },
    rows.length ? rows.map(r => h('div', { key: r.device, className: cx('cb-port', r.simulated && 'cb-port--sim', r.selected && 'cb-port--sel'),
      'data-cb': `port-${r.simulated ? 'sim' : 'real'}`, 'data-cb-device': r.device },
    h('button', { type: 'button', role: 'radio', 'aria-checked': r.selected ? 'true' : 'false', className: 'cb-port-pick', onClick: () => selectPort(r.device),
      title: `${r.device} · ${r.description}` },
    h('span', { className: 'cb-radio', 'aria-hidden': 'true' }),
    h(FlashPortSymbol, { kind: flashPortConnector(byDevice.get(r.device), layout, det), board: layout?.title }),
    h('span', { className: 'cb-port-txt' },
      h('span', { className: 'cb-port-l1' }, h('b', { className: 'cb-ellip', title: r.device, 'data-cb-truncate-ok': '' }, r.device), r.simulated ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-port' }) : h('span', { className: 'cb-tagx' }, r.label)),
      h('span', { className: 'cb-port-l2' }, h('span', { className: 'cb-dim cb-vf-portdesc' }, r.simulated ? r.description : `${r.kind}${r.description ? ` · ${r.description}` : ''}`),
        r.detected ? h('span', { className: 'cb-ok', title: 'Detected for this project' }, '✓ detected') : null))),
    h(Btn, { kind: 'ghost', size: 'sm', disabled: running, 'data-cb': `detect-${r.simulated ? 'sim' : 'real'}`, 'data-cb-focus': flow.focus === 'detect' && r.selected ? 'true' : undefined,
      title: r.simulated ? 'Read the simulated chip (no hardware)' : 'Run esptool on this port (the board may reset)', onClick: () => detectBoard(r.device) },
    running && $detect.get().port === r.device ? 'Detecting…' : 'Detect')))
      : h('p', { className: 'cb-why cb-dim', 'data-cb': 'no-ports' }, 'No serial ports. Plug in a board or use the simulated board (sim://).'),
    health && health.hardware_access === false ? h('div', { className: 'cb-hintline', 'data-cb': 'hw-off' },
      h('span', { className: 'cb-active' }, '◌'), 'Hardware access is off: only simulated boards are listed.',
      h('button', { type: 'button', className: 'cb-linkbtn', onClick: () => openAgentSettings() }, 'Agent settings ›')) : null)
}

function DetectResult({ project }) {
  const d = sdk.useValue($detect)
  const det = project?.board?.detected
  const res = d.env?.ok ? d.env.result : det
  const s = detectSummary(res, project)
  if (!s) return null
  // the detection's caution/danger warnings (e.g. no auto reset, unknown chip) as warning lines
  const warns = (d.env?.ok ? d.env.warnings || [] : []).filter(w => w && (w.severity === 'caution' || w.severity === 'danger'))
  return h('div', { className: 'cb-detect', 'data-cb': 'detect-result' },
    warns.length ? h('ul', { className: 'cb-shints cb-vf-dwarn', 'data-cb': 'detect-warnings' }, warns.map((w, i) => h('li', { key: `${w.code}-${i}`,
      className: `cb-shint cb-shint--${w.severity}`, 'data-cb': `detect-warning-${w.code}`, 'data-cb-severity': w.severity },
    h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, SOLDER_HINT_SYMBOL[w.severity]),
    h('span', { className: 'cb-shint-cat' }, w.severity), h('span', { className: 'cb-shint-t' }, w.message)))) : null,
    h('div', { className: 'cb-kv' },
      h('span', null, 'chip'), h('b', null, s.chip),
      h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, s.mac),
      h('span', null, 'flash'), h('b', null, `${s.flash} · PSRAM ${s.psram}`),
      s.usb ? [h('span', { key: 'u' }, 'usb'), h('b', { key: 'v' }, s.usb)] : null),
    s.variantDiffers ? h('div', { className: 'cb-note cb-note--warn', style: { margin: '8px 0 0' }, 'data-cb': 'variant-differs' },
      h('span', null, '!'), `Detected ${String(s.suggestion).toUpperCase()}${s.unverified ? ' (unverified)' : ''}, the project says ${String(project.board.variant).toUpperCase()}.`,
      h(Btn, { kind: 'ghost', size: 'sm', className: 'cb-push', 'data-cb': 'variant-take', onClick: () => patchAtom($ui, { modal: { type: 'variant', variant: s.suggestion } }) },
        `Use ${String(s.suggestion).toUpperCase()}`))
      : s.suggestion ? h('div', { className: 'cb-ok', style: { marginTop: '6px' }, 'data-cb': 'variant-matches', 'data-cb-unverified': s.unverified ? 'true' : null },
        `✓ module variant ${String(s.suggestion).toUpperCase()} matches the project`,
        s.unverified ? ' (unverified: esptool cannot tell octal from quad PSRAM; check the module marking)' : '') : null)
}

function FirmwareCard({ project, n }) {
  const fw = project?.firmware || {}
  const note = sdk.useValue($jobNote).example
  const [dir, setDir] = useState(fw.dir || '')
  const [env, setEnv] = useState(fw.env || '')
  useEffect(() => { setDir(fw.dir || ''); setEnv(fw.env || '') }, [fw.dir, fw.env])
  const changed = (dir.trim() && dir.trim() !== (fw.dir || '')) || (env.trim() && env.trim() !== (fw.env || ''))
  const dirShort = fw.dir ? fw.dir.replace(/^.*\/projects\/([^/]+)\/firmware\/?$/, 'projects/$1/firmware/') : null
  return h(Section, { n, title: 'firmware', dataCb: 'flash-firmware', aside: fw.dir ? h('span', { className: 'cb-ok' }, '✓ set') : h('span', { className: 'cb-warn' }, '! not set') },
    h('div', { className: 'cb-fwgrid' },
      h(Field, { id: 'cb-fw-dir', label: 'Folder', value: dir, onChange: setDir, placeholder: '/path/to/platformio/project', dataCb: 'fw-dir', wide: true, tail: true,
        hint: dirShort && dirShort !== fw.dir ? `in the bench project: ${dirShort}` : fw.dir ? 'PlatformIO project folder' : 'a folder with platformio.ini' }),
      h(Field, { id: 'cb-fw-env', label: 'Env', value: env, onChange: setEnv, placeholder: 's3', dataCb: 'fw-env', hint: '[env:…]' })),
    h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'quiet', size: 'sm', disabled: !changed || !dir.trim() || !env.trim(), 'data-cb': 'fw-save', onClick: () => setFirmwareDir(dir.trim(), env.trim()) }, 'Save folder'),
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'fw-example', title: 'Copy the laser-trigger example into this bench project (firmware/)',
        onClick: () => useExampleFirmware() }, 'Use example project')),
    note ? h('div', { className: 'cb-jobline cb-bad', role: 'alert' }, `✕ ${note.message}`, note.hint ? h('span', { className: 'cb-dim' }, note.hint) : null) : null)
}

function BuildCard({ project, n, primary }) {
  const jobs = sdk.useValue($jobs)
  const note = sdk.useValue($jobNote).build
  const flow = sdk.useValue($flow)
  const fw = project?.firmware || {}
  const b = fw.last_build
  const job = jobs.build
  const pr = jobProgress(job)
  const res = job?.state === 'done' ? job.result?.result : null
  const sim = job ? Boolean(job.result?.simulated) : Boolean(project?.simulated)
  return h(Section, { n, title: 'build', dataCb: 'flash-build', tone: pr.running ? 'active' : undefined,
    aside: b ? h('span', { className: b.ok ? 'cb-ok' : 'cb-bad' }, b.ok ? `✓ ${formatClock(b.at)}` : '✕ failed') : h('span', { className: 'cb-dim' }, 'not built') },
  b?.ok ? h('div', { className: 'cb-build', 'data-cb': 'build-result' },
    h('div', { className: 'cb-meter' }, h(Label, null, 'ram'), h(Bar, { pct: b.ram_pct, tone: b.ram_pct > 85 ? 'warn' : 'ok', label: 'RAM' }), h('b', null, formatPct(b.ram_pct))),
    h('div', { className: 'cb-meter' }, h(Label, null, 'flash'), h(Bar, { pct: b.flash_pct, tone: b.flash_pct > 85 ? 'warn' : 'ok', label: 'Flash' }), h('b', null, formatPct(b.flash_pct))),
    h('div', { className: 'cb-kv', style: { marginTop: '6px' } },
      h('span', null, sim ? 'firmware hash' : 'elf sha256'), h('b', null, h(FlashHashShort, { hash: b.elf_sha256 })),
      h('span', null, 'duration'), h('b', null, res?.duration_s ? formatDuration(res.duration_s) : '—')),
    sim ? h('div', { className: 'cb-hintline' }, h('span', { className: 'cb-active' }, '◌'), 'Simulated build: the hash covers the sources, no ELF is produced.') : null)
    : h('p', { className: 'cb-why cb-dim' }, fw.dir ? 'Build the firmware before flashing. The build never uploads.' : 'Set a firmware folder first.'),
  h(JobLine, { job, note, kind: 'build' }),
  h('div', { className: 'cb-actions' },
    h(Btn, { kind: primary ? 'primary' : 'ghost', size: 'sm', disabled: !fw.dir || pr.running, 'data-cb': 'build-start',
      'data-cb-focus': flow.focus === 'build' ? 'true' : undefined, onClick: () => buildFirmware() }, pr.running ? 'Building…' : b?.ok ? 'Build again' : 'Build firmware')))
}

/** The backend's answer why the flash would be refused (GET /board/flash/check), under the locked button. */
function FlashGateNote({ gate }) {
  const settings = gate.code === 'flash_disabled' || gate.code === 'sim_only'
  return h('div', { id: 'cb-flash-gate', className: 'cb-shints cb-vf-gate', 'data-cb': 'flash-gate', 'data-cb-code': gate.code, role: 'status' },
    h('div', { className: 'cb-shint cb-shint--danger' }, h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, '⊗'),
      h('span', { className: 'cb-shint-cat' }, 'locked'),
      h('span', { className: 'cb-shint-t' }, h('b', { 'data-cb': 'flash-gate-msg' }, gate.message),
        gate.hint ? h('span', { className: 'cb-vf-gate-hint', 'data-cb': 'flash-gate-hint' }, gate.hint) : null,
        settings ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'agent-settings-link', onClick: () => openAgentSettings() }, 'Agent settings ›') : null)))
}

function FlashCard({ project, n, primary }) {
  const jobs = sdk.useValue($jobs)
  const note = sdk.useValue($jobNote).flash
  const fc = sdk.useValue($flashCheck)
  const conf = flashConfirm(project)
  const pr = jobProgress(jobs.flash)
  const f = project?.firmware?.last_flash
  const gate = flashGate(fc.project === project?.id ? fc.env : null)
  const locked = gate.state === 'locked'
  const solderHint = flashSolderHint(project, conf.confirm?.port || project?.board?.detected?.port)
  return h(Section, { n, title: 'flash', dataCb: 'flash-flash', tone: pr.running ? 'active' : undefined,
    aside: f ? h('span', { className: f.ok ? 'cb-ok' : 'cb-bad' }, f.ok ? `✓ ${formatClock(f.at)}` : '✕ failed') : h('span', { className: 'cb-dim' }, 'not flashed') },
  conf.ok ? h('div', { className: 'cb-kv', 'data-cb': 'flash-preview' },
    h('span', null, 'port'), h('b', { className: 'cb-kv-port' }, h('span', { className: 'cb-ellip', title: conf.confirm.port, 'data-cb-truncate-ok': '' }, conf.confirm.port),
      conf.simulated ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-confirm' }) : null),
    h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, conf.confirm.mac),
    h('span', null, 'firmware'), h('b', null, h(FlashHashShort, { hash: conf.confirm.elf_sha256 })),
    conf.alreadyFlashed ? [h('span', { key: 'a' }, 'state'), h('b', { key: 'b', className: 'cb-ok' }, '✓ this build is on the board')] : null)
    : locked ? null : h('p', { className: 'cb-why cb-dim', 'data-cb': 'flash-missing' }, `Needs ${conf.missing.includes('detect') ? 'a detected board' : ''}${conf.missing.includes('detect') && conf.missing.includes('build') ? ' and ' : ''}${conf.missing.includes('build') ? 'a successful build' : ''}${!conf.missing.includes('detect') && conf.missing.includes('mac') ? 'the board MAC (detect again)' : ''}.`),
  solderHint ? h('div', { className: 'cb-hintline cb-warn', 'data-cb': 'flash-solder-hint', title: 'Only a hint: flashing stays possible' }, `! ${solderHint}`,
    h('button', { type: 'button', className: 'cb-linkbtn', onClick: () => goStation('solder') }, '04 SOLDER ›')) : null,
  h(JobLine, { job: jobs.flash, note, kind: 'flash' }),
  h(FlashMap, { job: jobs.flash }),
  h('div', { className: 'cb-actions' },
    h(Btn, { kind: primary && !locked ? 'warn' : 'ghost', size: 'sm', disabled: !conf.ok || pr.running || locked, 'data-cb': 'flash-start',
      'data-cb-gate': gate.state, 'aria-describedby': locked ? 'cb-flash-gate' : undefined,
      title: locked ? `Locked: ${gate.message}` : 'Opens the confirmation dialog; nothing is written before you confirm', onClick: () => patchAtom($ui, { modal: { type: 'flash', confirm: conf.confirm } }) },
    pr.running ? 'Flashing…' : locked ? '⊗ Flash locked' : 'Flash ›')),
  locked ? h(FlashGateNote, { gate }) : null)
}

/** The first two groups of a hash (the dialog shows all eight); the full hash in the title. */
function FlashHashShort({ hash }) {
  const g = flashHashGroups(hash)
  if (g.length !== 8) return h('span', { className: 'cb-mono-num', title: hash || '' }, hash ? shortHash(hash, 16) : '—')
  return h('span', { className: 'cb-vf-hashshort cb-mono-num', title: hash, 'data-cb-truncate-ok': '' }, h('span', null, g[0]), h('span', null, g[1]), h('span', { className: 'cb-dim', 'aria-hidden': 'true' }, '…'))
}

/** Flash map after a real flash: the written images (result.images) as marks on an address axis, offsets and names
 *  only. The simulated flash reports no images: then nothing is drawn (nothing is estimated). */
function FlashMap({ job }) {
  const res = job?.state === 'done' && job.result?.ok ? job.result.result : null
  const map = flashMapMarks(res?.images)
  if (!map) return null
  return h('div', { className: 'cb-vf-map', 'data-cb': 'flash-map' },
    h(Label, null, `// written · ${map.marks.length} image${map.marks.length === 1 ? '' : 's'}`),
    h('div', { className: 'cb-vf-axis', role: 'img', 'aria-label': `Address axis: ${map.marks.map(m => `${m.name} at ${m.offset}`).join(', ')}` },
      h('span', { className: 'cb-vf-axis-line', 'aria-hidden': 'true' }),
      map.marks.map((m, i) => h('span', { key: m.offset, className: cx('cb-vf-mark', i % 2 && 'cb-vf-mark--lo'), style: { left: `${m.frac * 100}%` }, 'aria-hidden': 'true',
        'data-cb-offset': m.offset }, h('i', null), h('b', null, m.n)))),
    h('ol', { className: 'cb-vf-legend' }, map.marks.map(m => h('li', { key: m.offset, 'data-cb': 'flash-map-image', 'data-cb-offset': m.offset },
      h('b', { className: 'cb-vf-n', 'aria-hidden': 'true' }, m.n), h('span', { className: 'cb-mono-num' }, m.offset), h('span', { className: 'cb-vf-name' }, m.name),
      m.sha256 ? h('span', { className: 'cb-dim cb-mono-num', title: m.sha256 }, shortHash(m.sha256, 8)) : null))))
}

function StationFlash({ project }) {
  const ports = sdk.useValue($ports)
  const flow = sdk.useValue($flow)
  const bench = sdk.useValue($bench)
  const health = bench.health
  const note = sdk.useValue($jobNote).detect
  const jobs = sdk.useValue($jobs)
  useEffect(() => {
    if (!flow.port || !(ports.ports || []).some(p => p.device === flow.port)) {
      const d = defaultPort(ports.ports, project?.board?.detected?.port)
      if (d && d !== flow.port) selectPort(d)
    }
  }, [ports.ports, project?.board?.detected?.port])
  useEffect(() => {
    if (!flow.focus) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => patchAtom($flow, { focus: null }), 4000)
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [flow.focus, flow.at])
  // ask again on open, per project revision (agent, jobs), port and settings change; jobs ask too (26-live.js)
  useEffect(() => { refreshFlashCheck() }, [project?.id, project?.rev, flow.port, health?.epoch, health?.allow_flash, health?.hardware_access])
  const step = nextFlashStep(project, ports)
  const det = project?.board?.detected
  const simulated = isSimPort(flow.port) || isSimPort(det?.port)
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-flash', 'data-cb-next': step },
      h(DecodeTitle, { text: '05 // BUILD & FLASH', meta: 'nothing is flashed without your confirmation' }),
      simulated ? h('div', { className: 'cb-simrow' }, h(SimBanner, null), h('span', { className: 'cb-dim' }, 'Nothing physical is written. The dialog still checks port, MAC and firmware.')) : null,
      h('div', { className: 'cb-flashgrid' },
        h(Section, { n: '1', title: 'board', dataCb: 'flash-board', tone: jobProgress(jobs.detect).running ? 'active' : undefined,
          aside: det ? h('span', { className: 'cb-ok', title: det.description || '' }, `✓ ${formatClock(det.at)}`) : h('span', { className: 'cb-dim' }, 'not detected') },
        h(PortList, { ports, project, flow, health }),
        h(JobLine, { job: jobs.detect, note, kind: 'detect' }),
        h(DetectResult, { project })),
        h(FirmwareCard, { project, n: '2' }),
        h(BuildCard, { project, n: '3', primary: step === 'build' }),
        h(FlashCard, { project, n: '4', primary: step === 'flash' }))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' }, h(FlashInspector, { project, step }))
  ]
}

function FlashInspector({ project, step }) {
  const fw = project?.firmware || {}
  const det = project?.board?.detected
  const jobs = sdk.useValue($jobs)
  const STEP_TEXT = { detect: 'Pick a port and press Detect. Detection reads the chip, MAC and flash size.',
    firmware: 'Set a PlatformIO folder or copy the example project.', build: 'Build the firmware. The ELF hash becomes part of the flash confirmation.',
    flash: 'Flash opens a dialog with board, MAC, port and firmware hash. Nothing is written before you confirm.',
    done: 'This build is on the board. Open 06 DEBUG to watch the serial output.' }
  const tail = (jobs.detect?.log_tail || []).slice(-6)
  return [
    h('div', { key: 'n', className: 'cb-card cb-bracket', 'data-cb': 'flash-next' },
      h(Label, null, '// next step'),
      h('p', { className: 'cb-why' }, STEP_TEXT[step]),
      step === 'done' ? h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'goto-debug', onClick: () => goStation('debug') }, 'Open 06 DEBUG ›')) : null),
    // the live twin of the board (30-ui-board.js FlashTwin)
    h(FlashTwin, { key: 't', project }),
    h('div', { key: 'r', className: 'cb-card', 'data-cb': 'flash-records' },
      h(Label, null, '// records'),
      h('div', { className: 'cb-kv', style: { marginTop: '8px' } },
        h('span', null, 'board'), h('b', null, det ? `${det.chip?.replace(/\s*\(revision.*$/, '') || '—'}` : '—'),
        h('span', null, 'port'), h('b', null, det?.port || '—'),
        h('span', null, 'build'), h('b', { className: fw.last_build?.ok ? 'cb-ok' : fw.last_build ? 'cb-bad' : 'cb-dim' }, fw.last_build ? `${fw.last_build.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_build.at)}` : '—'),
        h('span', null, 'flash'), h('b', { className: fw.last_flash?.ok ? 'cb-ok' : fw.last_flash ? 'cb-bad' : 'cb-dim' }, fw.last_flash ? `${fw.last_flash.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_flash.at)}` : '—'),
        h('span', null, 'env'), h('b', null, fw.env || '—'))),
    tail.length ? h('div', { key: 'l', className: 'cb-card', 'data-cb': 'detect-log' }, h(Label, null, '// detect log'),
      h('pre', { className: 'cb-pre' }, tail.join('\n'))) : null
  ]
}

/** Hash in eight groups of eight with a copy button; the text stays one contiguous hash (title, search, e2e). */
function FlashHash({ hash, label }) {
  const [copied, setCopied] = useState(null)
  const groups = flashHashGroups(hash)
  const canCopy = typeof CB.ctx?.os?.writeClipboard === 'function' && groups.length > 0
  const copy = async () => {
    let ok = false
    try { ok = (await CB.ctx.os.writeClipboard(String(hash))) !== false } catch { ok = false }
    setCopied(ok ? 'ok' : 'fail')
    timersOf(CB.ctx).setTimeout(() => setCopied(null), 1600)
  }
  return h('div', { className: 'cb-vf-hashrow' },
    h('div', { className: 'cb-vf-hash cb-mono-num', 'data-cb': 'flash-hash', title: hash || '', 'aria-label': `${label} ${hash || 'none'}` },
      groups.length ? groups.map((g, i) => h('span', { key: i, className: 'cb-vf-hg' }, g)) : '—'),
    canCopy ? h('button', { type: 'button', className: 'cb-iconbtn cb-vf-copy', 'data-cb': 'flash-hash-copy', onClick: copy,
      'aria-label': copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : `Copy the ${label}`, title: `Copy the full ${label} to the clipboard` },
    copied === 'ok' ? '✓ copied' : copied === 'fail' ? '✕ not copied' : '⧉ copy') : null)
}

const FLASH_CHECK_MARK = { match: { s: '✓', t: 'ok' }, differs: { s: '✕', t: 'bad' }, unchecked: { s: '○', t: 'dim' } }

/** Flash confirmation (own modal in the Bench look): target, firmware hash, memory use, check list in words, warning.
 *  The confirm object (port, mac, elf_sha256) goes to the backend unchanged; the primary button only starts it. */
function FlashDialog({ confirm, onClose }) {
  const project = sdk.useValue($project)
  const jobs = sdk.useValue($jobs)
  const [busy, setBusy] = useState(false)
  const wrap = useRef(null)
  const det = project?.board?.detected || {}
  const b = project?.firmware?.last_build || {}
  const sim = isSimPort(confirm?.port)
  const hashLabel = sim ? 'firmware hash' : 'elf sha256'
  const buildRes = jobs.build?.state === 'done' && jobs.build.result?.ok ? jobs.build.result.result : null
  const mem = flashMemRows(b, buildRes)
  const checks = flashCheckRows(confirm, project)
  // the first focus stays on Cancel as before (Modal focuses the first focusable; the copy button comes earlier).
  // Modal renders the content box straight into the dialog element, so its parent is the dialog.
  useEffect(() => {
    const dialog = wrap.current?.parentNode
    dialog?.querySelector?.('[data-cb=flash-cancel]')?.focus?.()
  }, [])
  const go = async () => {
    setBusy(true)
    const env = await flashFirmware(confirm)
    setBusy(false)
    if (env) onClose()
  }
  const kib = n => `${(n / 1024).toFixed(1)} KiB`
  return h(Modal, { title: 'Flash firmware', onClose, dataCb: 'flash-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose, 'data-cb': 'flash-cancel' }, 'Cancel'),
      h(Btn, { key: 'f', kind: 'warn', onClick: go, disabled: busy, 'data-cb': 'flash-confirm' }, busy ? 'Starting…' : sim ? 'Flash simulated board ›' : 'Flash board ›')] },
  h('div', { className: 'cb-vf-dlg', ref: wrap },
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-target' },
      h(Label, null, '// target'),
      h('div', { className: 'cb-kv cb-kv--dialog' },
        h('span', null, 'board'), h('b', null, det.description || det.chip || '—'),
        h('span', null, 'port'), h('b', { className: 'cb-kv-port' }, h('span', { className: 'cb-ellip', title: confirm?.port || '', 'data-cb-truncate-ok': '' }, confirm?.port || '—'),
          sim ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-dialog' }) : null),
        h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, confirm?.mac || '—'))),
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-firmware-block' },
      h(Label, null, `// ${hashLabel}`, flashHashGroups(confirm?.elf_sha256).length === 8 ? h('span', { className: 'cb-vf-algo' }, ' · sha-256 · 8 × 8') : null),
      h(FlashHash, { hash: confirm?.elf_sha256, label: hashLabel }),
      mem.length ? h('div', { className: 'cb-vf-mem', 'data-cb': 'flash-mem' }, mem.map(m => h('div', { key: m.id, className: 'cb-vf-meter', 'data-cb': `flash-mem-${m.id}` },
        h(Label, null, `${m.id} used`), h(Bar, { pct: m.pct, tone: m.pct > 85 ? 'warn' : 'ok', label: `${m.label} used` }), h('b', { className: 'cb-mono-num' }, formatPct(m.pct)),
        m.used !== null ? h('span', { className: 'cb-dim cb-mono-num' }, `${kib(m.used)} of ${kib(m.total)}`) : null))) : null),
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-checks' },
      h(Label, null, '// checks'),
      h('ul', { className: 'cb-vf-checks' }, checks.map(c => {
        const m = FLASH_CHECK_MARK[c.state]
        return h('li', { key: c.id, className: `cb-vf-chk cb-vf-chk--${c.state}`, 'data-cb': `flash-check-${c.id}`, 'data-cb-state': c.state },
          h('span', { className: `cb-vf-chk-s cb-${m.t}`, 'aria-hidden': 'true' }, m.s),
          h('span', { className: `cb-vf-chk-w cb-${m.t}` }, c.word),
          // the build time wraps as one unit
          h('span', { className: 'cb-vf-chk-t' }, c.text, c.at ? ' ' : null, c.at ? h('span', { className: 'cb-dim cb-mono-num cb-vf-chk-at' }, `· built ${formatStamp(c.at)}`) : null))
      }))),
    !sim && flashSolderHint(project, confirm?.port) ? h('div', { className: 'cb-hintline cb-warn', 'data-cb': 'flash-dialog-solder' }, `! ${flashSolderHint(project, confirm?.port)}`) : null,
    h('div', { className: `cb-note ${sim ? '' : 'cb-note--warn'}`, style: { marginTop: '12px', marginBottom: 0, alignItems: 'flex-start' } },
      h('span', null, sim ? '◌' : '!'),
      h('span', null, sim ? 'Simulated board: nothing physical is written. Port, MAC and firmware are still checked against the detection and the last build.'
        : 'This writes the firmware to the board and restarts it. Keep loads such as a laser module unpowered while flashing. Circuit Bench never erases flash.'))))
}

function VariantDialog({ variant, onClose }) {
  const project = sdk.useValue($project)
  return h(Modal, { title: 'Use the detected module variant', onClose, dataCb: 'variant-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 'o', 'data-cb': 'variant-confirm', onClick: async () => { await applyVariant(variant); onClose() } }, `Use ${String(variant).toUpperCase()} ›`)] },
  h('p', { className: 'cb-why' }, `The board reports ${String(variant).toUpperCase()}; the project uses ${String(project?.board?.variant || '—').toUpperCase()}. `,
    'Switching re-checks every pin assignment against the new module (PSRAM pins differ).'))
}

function ExampleOverwriteDialog({ onClose }) {
  return h(Modal, { title: 'Replace the firmware folder?', onClose, dataCb: 'example-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Keep my files'),
      h(Btn, { key: 'o', kind: 'warn', 'data-cb': 'example-overwrite', onClick: async () => { await useExampleFirmware({ overwrite: true }); onClose() } }, 'Replace with the example ›')] },
  h('p', { className: 'cb-why' }, 'The project already has a firmware folder. Copying the example replaces it, including changes from a fix (for example in src/main.cpp).'))
}

STATION_VIEWS.flash = { component: StationFlash, inspector: true }
