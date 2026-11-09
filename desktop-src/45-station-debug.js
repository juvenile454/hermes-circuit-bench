// Station 06 DEBUG: the serial monitor opens only on a click (POST /serial/open → socket, polling fallback after
// 3 s), panic analysis from crash.decode, "Fix with Hermes" as a composer draft (never sent).

function MonitorCard({ project }) {
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const ports = sdk.useValue($ports)
  const det = project?.board?.detected?.port || null
  const rows = portRows(ports.ports, { detectedPort: det })
  const [port, setPort] = useState(mon.port || det || defaultPort(ports.ports, det))
  useEffect(() => { if (!port) setPort(mon.port || det || defaultPort(ports.ports, det)) }, [ports.ports, det])
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const buf = open ? serial.buf : null
  const nLines = buf ? buf.lines.filter(l => l.k === 'line').length : 0
  const modeText = mon.mode === 'socket' ? 'live stream' : mon.mode === 'poll' ? 'polling fallback (1 s)' : mon.mode === 'connecting' ? 'connecting…' : '—'
  const sim = isSimPort(open ? mon.port : port)
  return h(Section, { title: 'serial monitor', dataCb: 'monitor', tone: open ? 'active' : undefined,
    aside: h('span', { className: open ? 'cb-ok' : 'cb-dim', 'data-cb': 'monitor-state' }, open ? `● ${String(mon.status).toUpperCase()}` : '○ CLOSED') },
  h('div', { className: 'cb-monrow' },
    h('label', { className: 'cb-label', htmlFor: 'cb-mon-port' }, 'port'),
    h('select', { id: 'cb-mon-port', value: open ? mon.port : port || '', disabled: open, 'data-cb': 'monitor-port', onChange: e => setPort(e.target.value) },
      rows.map(r => h('option', { key: r.device, value: r.device, title: r.simulated ? 'simulated board' : r.description }, r.device))),
    open ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'monitor-close', onClick: () => closeMonitor() }, 'Close monitor')
      : h(Btn, { size: 'sm', disabled: !port || mon.opening, 'data-cb': 'monitor-open', title: sim ? 'Open the simulated board' : 'Open the port (DTR/RTS stay inactive; some boards still restart)',
        onClick: () => openMonitor(port) }, mon.opening ? 'Opening…' : 'Open monitor ›'),
    open && !sim ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'monitor-restart', disabled: mon.opening,
      title: 'Pulse EN (RTS) with BOOT released: the firmware restarts from flash; also leaves the download mode',
      onClick: () => openMonitor(mon.port, { reset: true }) }, 'Restart board') : null,
    sim && !open ? h(SimBanner, { compact: true }) : null),
  open && !sim && waitsForDownload(buf) ? h('div', { className: 'cb-jobline cb-warn', role: 'status', 'data-cb': 'monitor-download' },
    '! The board waits in download mode (after a flash or BOOT).',
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'monitor-download-restart', onClick: () => openMonitor(mon.port, { reset: true }) }, 'Restart board ›')) : null,
  h('div', { className: 'cb-kv', style: { marginTop: '10px' } },
    h('span', null, 'stream'), h('b', { className: mon.mode === 'poll' ? 'cb-warn' : mon.mode === 'socket' ? 'cb-ok' : 'cb-dim', 'data-cb': 'monitor-mode' }, open ? modeText : '—'),
    h('span', null, 'lines'), h('b', { className: 'cb-mono-num' }, open ? `${nLines} · next seq ${(buf?.lastSeq || 0) + 1}` : '—'),
    h('span', null, 'reset'), h('b', null, 'no reset on open (DTR/RTS inactive)')),
  mon.error ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'monitor-error' }, `✕ ${mon.error.message}`, mon.error.hint ? h('span', { className: 'cb-dim' }, mon.error.hint) : null) : null,
  !open && !mon.error ? h('p', { className: 'cb-why cb-dim' }, 'Nothing is opened automatically. The console below shows the live log once the monitor is open.') : null,
  // the live twin of the board (30-ui-board.js DebugTwin)
  h(DebugTwin, { project }))
}

/** Long core paths (…/cores/esp32/main.cpp) keep their last two segments; the full path is the title. */
function shortFramePath(file) {
  const f = String(file || '?')
  if (f.length <= 26) return f
  const parts = f.split('/')
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : f
}

/** The newest output is the ROM waiting in download mode ("waiting for download"): the firmware does not run. */
function waitsForDownload(buf) {
  const lines = buf?.lines || []
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i]
    if (l.k !== 'line' || !String(l.text || '').trim()) continue
    return /waiting for download/i.test(l.text)
  }
  return false
}

/** The fix loop of the demo as a checklist: panic → draft → build → flash → boot ok (state from project + log). */
function fixLoopSteps(project, serial, flow) {
  const panic = project?.debug?.last_panic
  if (!panic?.at) return null
  const t = iso => (iso ? Date.parse(iso) : NaN)
  const pAt = t(panic.at)
  const b = project.firmware?.last_build
  const f = project.firmware?.last_flash
  // a reboot loop keeps reporting the panic while the fix is built: a flash of the current build after the last panic
  // also proves the rebuild (the panic record carries no firmware hash)
  const flashedAfter = Boolean(b?.ok && f?.ok && t(f.at) > pAt && f.elf_sha256 === b.elf_sha256)
  const built = Boolean(b?.ok && (t(b.at) > pAt || flashedAfter))
  const flashed = built && flashedAfter
  const boot = lastLineMatching(serial.buf, /\bboot ok\b/i)
  const mark = flow?.flashMark
  const clean = flashed && mark && mark.elf === f.elf_sha256 && (mark.epoch ?? null) === (serial.buf.epoch ?? null) ? cleanRunAfter(serial.buf, mark.seq) : null
  const live = serialPanicLive(serial.buf, project)
  const booted = Boolean(flashed && (boot || clean) && !live)
  const drafted = Boolean(flow.fixDraftAt) || built
  const steps = [
    { id: 'panic', label: 'panic caught', done: true, detail: `${panic.reason || 'panic'} · ${formatClock(panic.at)}` },
    { id: 'draft', label: 'fix drafted', done: drafted, detail: built ? 'fix in the source' : drafted ? 'composer draft (you send it)' : 'use Fix with Hermes' },
    { id: 'build', label: 'firmware rebuilt', done: built, detail: built ? `${project.simulated ? 'firmware hash' : 'elf'} ${String(b.elf_sha256 || '').slice(0, 12)}…` : 'after the fix' },
    { id: 'flash', label: 'flashed', done: flashed, detail: flashed ? `${formatClock(f.at)} · ${f.port || ''}` : 'with confirmation' },
    { id: 'boot', label: 'boot ok', done: booted, detail: booted ? (boot ? boot.text : `runs without panic · ${clean.n} lines`) : 'serial log' }
  ]
  const cur = steps.findIndex(s => !s.done)
  return steps.map((s, i) => ({ ...s, current: i === cur }))
}

function FixLoopCard({ project }) {
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const steps = fixLoopSteps(project, serial, flow)
  if (!steps) return null
  const done = steps.filter(s => s.done).length
  const cur = steps.find(s => s.current)
  const all = done === steps.length
  return h(Section, { title: 'fix loop', dataCb: 'fix-loop', tone: all ? undefined : 'active',
    aside: h('span', { className: all ? 'cb-ok' : 'cb-active', 'data-cb': 'fix-loop-count', 'aria-label': `fix loop: ${done} of ${steps.length} steps done`,
      title: `${done} of ${steps.length} steps done` }, all ? '✓ CLOSED' : `${done}/${steps.length} done`) },
  h('ol', { className: 'cb-loop' }, steps.map(s => h('li', { key: s.id, className: cx('cb-loop-step', s.done && 'cb-loop-step--done', s.current && 'cb-loop-step--cur'), 'data-cb': `loop-${s.id}`,
    'data-cb-done': s.done ? 'true' : 'false' },
  h('span', { className: s.done ? 'cb-ok' : s.current ? 'cb-active' : 'cb-dim', 'aria-hidden': 'true' }, s.done ? '✓' : s.current ? '▸' : '○'),
  h('b', null, s.label), h('span', { className: 'cb-dim cb-ellip', title: s.detail }, s.detail)))),
  cur && (cur.id === 'build' || cur.id === 'flash')
    ? h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'loop-goto-flash', onClick: () => goStation('flash') }, '05 FLASH ›')) : null)
}

function PanicAnalysis({ project }) {
  const { data, env, status } = usePanicData(project)
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const [busy, setBusy] = useState(false)
  const [showDraft, setShowDraft] = useState(false)
  if (!data) {
    const bootOk = lastLineMatching(serial.buf, /\bboot ok\b/i)
    const mark = flow?.flashMark
    const clean = !bootOk && mark && (mark.epoch ?? null) === (serial.buf.epoch ?? null) ? cleanRunAfter(serial.buf, mark.seq) : null
    const stale = project?.debug?.last_panic && !projectPanicCurrent(project)
    const fixed = fixLoopFixed(project, serial, flow)
    return h(Section, { title: bootOk || clean ? 'firmware status' : 'panic', dataCb: 'debug-calm', tone: fixed ? 'ok' : undefined,
      aside: h('span', { className: bootOk || clean ? 'cb-ok' : 'cb-dim' }, bootOk || clean ? '✓ RUNNING' : 'no panic') },
    fixed ? h('div', { className: 'cb-fixed', 'data-cb': 'fixed-row' }, h(Stamp, { tone: 'ok', 'data-cb': 'fixed-stamp' }, bootOk ? '✓ FIXED · boot ok' : '✓ FIXED · runs'),
      h('span', { className: 'cb-dim' }, `${project.debug.last_panic.reason || 'panic'} gone after the flash at ${formatClock(project.firmware.last_flash.at)}`)) : null,
    bootOk ? h('div', { className: 'cb-bootok', 'data-cb': 'boot-ok' }, h('span', { className: 'cb-ok' }, '✓'), h('code', null, bootOk.text),
      h('span', { className: 'cb-dim' }, `seq ${bootOk.seq}${bootOk.ts ? ` · ${bootOk.ts}` : ''}`))
      : clean ? h('div', { className: 'cb-bootok', 'data-cb': 'run-ok' }, h('span', { className: 'cb-ok' }, '✓'), h('code', null, clean.last.text),
        h('span', { className: 'cb-dim' }, `${clean.n} lines since the flash, no panic`)) : null,
    fixed ? null : h('p', { className: 'cb-why cb-dim' }, stale ? `The last panic (${project.debug.last_panic.reason}, ${formatClock(project.debug.last_panic.at)}) happened before the last flash.`
      : 'No panic on the current firmware. Panics are caught from the serial log and decoded automatically.'))
  }
  const fix = async () => {
    setBusy(true)
    try { await fixWithHermes(project, data, env) } finally { setBusy(false) }
  }
  const draft = fixWithHermesText(project, env || { summary: data.summary, result: { reason: data.reason, core: data.core, frames: data.frames.map(f => ({ i: f.i, function: f.fn, file: f.file, line: f.line })) } })
  const extra = data.decoded ? data.extra : data.interpretation
  const srcs = (env?.sources || []).filter(s => data.interpretation.some(x => x.source_id === s.id))
  const src = sourceTarget(project, data.top)
  const elf = elfWords(data.elf)
  // no stamp here: the panic anchor in the station head carries "PANIC · reason · core" once
  return h(Section, { title: 'panic analysis', dataCb: 'panic-analysis', tone: 'bad', className: 'cb-bracket cb-bracket--bad cb-pa',
    // no SIM badge here: HUD and console carry it; the ELF line says "simulated build"
    aside: data.decoded ? null : h(Label, null, status === 'loading' ? 'decoding…' : 'not decoded') },
  h('div', { 'data-cb-audit-root': 'panic', className: 'cb-pa-body' },
    data.decoded && data.summary ? h('p', { className: 'cb-pa-lead', 'data-cb': 'panic-summary' }, data.summary) : null,
    elf ? h('div', { className: `cb-elfline cb-elfline--${data.elf.tone}`, 'data-cb': 'elf-check', 'data-cb-status': data.elf.status, title: data.elf.detail || undefined },
      h('span', { className: 'cb-label' }, 'elf check'),
      h('span', { className: 'cb-elfline-v' }, h('span', { 'aria-hidden': 'true' }, elf.sym), ` ${elf.word}`),
      h('span', { className: 'cb-elfline-why' }, `· ${elf.reason}`)) : null,
    // the Hermes action right under the verdict (visible without scrolling, catalog 06)
    h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'agent', onClick: fix, disabled: busy, 'data-cb': 'fix-with-hermes-main', title: 'Put a fix request into the chat composer (not sent)' }, busy ? 'Opening chat…' : 'Fix with Hermes'),
      src.show ? h(Btn, { kind: 'quiet', size: 'sm', disabled: !src.can, 'data-cb': 'open-source-main', title: src.title, onClick: () => openSource(src) }, src.label) : null,
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'draft-toggle', 'aria-expanded': showDraft ? 'true' : 'false', onClick: () => setShowDraft(!showDraft) }, showDraft ? 'Hide prompt' : 'Show prompt'),
      data.logRef ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'decode-again', onClick: () => decodePanic({ log_ref: data.logRef }) }, 'Decode again') : null),
    showDraft ? h('pre', { className: 'cb-pre cb-draft', 'data-cb': 'fix-draft' }, draft) : null,
    h('p', { className: 'cb-why cb-dim', style: { margin: '8px 0 0' } }, 'The prompt goes into the chat composer. Nothing is sent until you press Enter.'),
    data.frames.length ? h('table', { className: 'cb-table cb-frames-t', 'data-cb': 'panic-frames-full' },
      h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, '#'), h('th', { className: 'cb-label' }, 'function'), h('th', { className: 'cb-label' }, 'file:line'), h('th', { className: 'cb-label cb-r' }, 'pc'))),
      h('tbody', null, data.frames.slice(0, 8).map((f, i) => h('tr', { key: f.i ?? i, className: cx(i === 0 && 'cb-frow--top', f.pc && 'cb-frow--link'), 'data-cb': `panic-frame-${f.i ?? i}`,
        tabIndex: f.pc ? 0 : undefined, title: f.pc ? `${f.pc}: marks this address in the Backtrace line of the log` : undefined, ...logMarkProps(frameMark(f)) },
        h('td', { className: 'cb-dim' }, `#${f.i}`), h('td', { className: i === 0 ? 'cb-bad' : 'cb-fg', title: f.fn }, f.short),
        h('td', { className: 'cb-active', title: `${f.file}:${f.line ?? '?'}` }, `${shortFramePath(f.file)}:${f.line ?? '?'}`), h('td', { className: 'cb-r cb-mono-num' }, f.pc))))) : null,
    data.bank?.key.length ? h(RegisterBank, { bank: data.bank }) : null,
    extra.length ? h('ul', { className: 'cb-interp', 'data-cb': 'panic-interp' }, extra.map(x => h('li', { key: x.code }, x.text))) : null,
    srcs.length ? h(SourceLine, { sources: srcs }) : null))
}

/** Key registers as labelled readouts (PC, EXCCAUSE, EXCVADDR or MEPC, MCAUSE, MTVAL) and the whole dump below,
 *  key registers highlighted there too. Hover or focus marks the register in the log's dump. */
function RegisterBank({ bank }) {
  return h('div', { className: 'cb-regbank', 'data-cb': 'panic-regs', 'data-cb-arch': bank.arch },
    h('div', { className: 'cb-regkeys' }, bank.key.map(r => h('div', { key: r.k, className: 'cb-regkey', 'data-cb': `reg-${r.k}`, tabIndex: 0,
      title: `${r.k}: ${r.label}${r.note ? ` (${r.note})` : ''}`, ...logMarkProps({ kind: 'reg', name: r.k, value: r.v }) },
    h('span', { className: 'cb-regkey-n' }, r.k), h('span', { className: 'cb-regkey-l' }, r.label),
    h('b', { className: 'cb-regkey-v cb-mono-num' }, r.v), r.note ? h('span', { className: 'cb-regkey-note' }, `= ${r.note}`) : null))),
    bank.all.length > bank.key.length ? h('details', { className: 'cb-regdump', 'data-cb': 'panic-regdump' },
      h('summary', null, h(Label, null, `register dump · ${bank.all.length}`)),
      h('div', { className: 'cb-reggrid' }, bank.all.map(r => h('span', { key: r.k, className: cx('cb-regcell', r.key && 'cb-regcell--key'), ...logMarkProps({ kind: 'reg', name: r.k, value: r.v }) },
        h('span', { className: 'cb-regcell-n' }, r.k), h('span', { className: 'cb-mono-num' }, r.v))))) : null)
}

/** Station-head anchor: the one PANIC statement of 06 DEBUG (reason · core, where it stopped). */
function PanicAnchor({ data }) {
  const top = data.top
  return h('div', { className: 'cb-panicanchor', 'data-cb': 'panic-anchor', role: 'status' },
    h(Stamp, { tone: 'bad', 'data-cb': 'panic-anchor-stamp' }, `PANIC · ${data.title}`),
    top && top.file && top.file !== '??' ? h('span', { className: 'cb-anchor-at' }, h('span', { className: 'cb-dim' }, 'in '), h('b', null, top.short),
      h('span', { className: 'cb-active' }, ` ${shortFramePath(top.file)}:${top.line ?? '?'}`)) : null)
}

/** The demo fix loop is closed: panic → (draft) → build → flash → boot ok on the new firmware (Wow 4). */
function fixLoopFixed(project, serial, flow) {
  const steps = fixLoopSteps(project, serial, flow)
  return Boolean(steps && steps.every(s => s.done))
}

function StationDebug({ project }) {
  const mon = sdk.useValue($monitor)
  const ui = sdk.useValue($ui)
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const pk = panicKey(project)
  // a panic that arrives while 06 is open counts as seen (the rail stops blinking)
  useEffect(() => {
    if (pk && ui.panicSeen !== pk) { patchAtom($ui, { panicSeen: pk }); store('panicSeen', pk) }
  }, [pk])
  const fixed = fixLoopFixed(project, serial, flow)
  const fixedKey = fixed ? `${pk}|${project.firmware?.last_flash?.at || ''}` : null
  // Wow 4: the rail lights up once, station after station, when the loop closes (static with reduced motion)
  useEffect(() => {
    if (fixedKey && ui.celebrated !== fixedKey) { patchAtom($ui, { celebrated: fixedKey, sweepAt: Date.now() }); store('celebrated', fixedKey) }
  }, [fixedKey])
  const { data } = usePanicData(project)
  const meta = fixed ? `firmware running${open ? ` · ${mon.port}` : ''}` : open ? `monitor open · ${mon.port}` : 'monitor opens only on your click'
  // reading order = DOM order: with a panic the analysis comes first, else the monitor
  const cards = data ? [h(PanicAnalysis, { key: 'p', project }), h(MonitorCard, { key: 'm', project }), h(FixLoopCard, { key: 'l', project })]
    : [h(MonitorCard, { key: 'm', project }), h(PanicAnalysis, { key: 'p', project }), h(FixLoopCard, { key: 'l', project })]
  return h('main', { className: 'cb-main cb-station', 'data-cb': 'station-debug', 'data-cb-audit-root': 'station' },
    h('div', { className: 'cb-dbghead' }, h(DecodeTitle, { text: '06 // SERIAL & PANIC', meta }), data ? h(PanicAnchor, { data }) : null),
    h('div', { className: 'cb-debuggrid', 'data-cb-panic': data ? 'true' : 'false' }, cards))
}

STATION_VIEWS.debug = { component: StationDebug, inspector: false }
