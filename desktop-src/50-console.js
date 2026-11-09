// Console: tabs SERIAL | BUILD | FLASH, seq-based serial buffer, auto-scroll that pauses while the user reads
// older lines. The same component renders on the Bench page and in the serial pane.
// On the page it folds to one bar while no port is open (consoleMode, lib/serial.js); blank runs fold,
// a panic is one block with a red side bar, the log jumps once to "Guru Meditation…" and pauses following.

const CONSOLE_TABS = [['serial', 'Serial'], ['build', 'Build'], ['flash', 'Flash']]

function recordLines(kind, project, job) {
  if (job?.log_tail?.length) {
    return job.log_tail.map((text, i) => ({ k: 'line', seq: i + 1, ts: '', text }))
  }
  const fw = project?.firmware || {}
  const rec = kind === 'build' ? fw.last_build : fw.last_flash
  if (!rec) return []
  const at = rec.at ? formatClock(rec.at) : ''
  // a simulated build has no ELF, its hash is a "firmware hash", never "ELF SHA256"
  const sim = Boolean(job?.result?.simulated ?? project?.simulated)
  const hashLabel = sim ? 'firmware hash' : 'elf sha256'
  if (kind === 'build') {
    return [{ k: 'line', seq: 1, ts: at, text: `last build ${rec.ok ? 'ok' : 'FAILED'} · RAM ${formatPct(rec.ram_pct)} · flash ${formatPct(rec.flash_pct)}` },
      { k: 'line', seq: 2, ts: at, text: `${sim ? 'simulated build, no ELF' : `elf ${rec.elf || '—'}`} · ${hashLabel} ${shortHash(rec.elf_sha256, 16)}` }]
  }
  return [{ k: 'line', seq: 1, ts: at, text: `last flash ${rec.ok ? 'ok' : 'FAILED'} → ${rec.port || '—'} · mac ${rec.mac || '—'}` },
    { k: 'line', seq: 2, ts: at, text: `${hashLabel} ${shortHash(rec.elf_sha256, 16)}` }]
}

/** Console state of the page from the store. */
function useConsoleMode(project) {
  const ui = sdk.useValue($ui)
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const jobs = sdk.useValue($jobs)
  const monitorOpen = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const serialOpen = serial.status === 'open' && serial.buf.lines.some(l => l.k === 'line')
  const jobRunning = ['build', 'flash'].some(k => jobProgress(jobs[k]).running)
  const panic = Boolean((serial.port && serialPanicLive(serial.buf, project)) || projectPanicCurrent(project))
  return consoleMode({ paneOpen: ui.paneOpen, cons: ui.cons, pinned: ui.consPinned, monitorOpen, serialOpen, jobRunning, panic })
}

/** Log text with the hovered frame / register marked (lib/crash.js logMarkRanges; only inside the marked panic block). */
function LogText({ text, mark }) {
  const ranges = mark ? logMarkRanges(text, mark) : []
  if (!ranges.length) return h('span', null, text || ' ')
  return h('span', null, splitMarked(text, ranges).map((p, k) => (p.mark ? h('mark', { key: k, className: 'cb-logmark', 'data-cb': 'log-mark' }, p.t) : p.t)))
}

function LogLine({ l, i, mark = null }) {
  if (l.k === 'gap') return h('div', { className: 'cb-line cb-line--gap' }, h('span', { className: 'cb-ts' }, ''), h('span', null, `… ${l.to - l.from + 1} line(s) missed (seq ${l.from}–${l.to}) …`))
  if (l.k === 'epoch') return h('div', { className: 'cb-line cb-line--epoch' }, h('span', { className: 'cb-ts' }, ''), h('span', null, '— backend restarted, new stream —'))
  const cls = String(l.text || '').trim() ? lineClass(l.text) : 'blank'
  return h('div', { className: `cb-line${cls ? ` cb-line--${cls}` : ''}`, 'data-cb-seq': l.seq ?? i },
    h('span', { className: 'cb-ts' }, l.ts || ''), h(LogText, { text: l.text, mark }))
}

// Panic episodes: one per surface, stream (epoch + port) and flash. Each episode jumps once, to its first panic.
// A flash on the same stream starts a new episode after the lines seen so far (old panics never jump again); a new
// stream or the first episode counts every panic in it. Module-level, so a remount (route ↔ chat) does not jump again.
const EPISODE_START = new Map()
const EPISODE_JUMPED = new Set()
const STREAM_EPISODE = new Map()

function episodeStart(episode, stream, lastSeq) {
  if (!EPISODE_START.has(episode)) {
    const prev = STREAM_EPISODE.get(stream)
    EPISODE_START.set(episode, prev && prev !== episode ? lastSeq : 0)
    STREAM_EPISODE.set(stream, episode)
  }
  return EPISODE_START.get(episode)
}

/**
 * view: logView(lines). panicSeq: seq of the latest panic in the buffer (or null). lastSeq: newest line seq.
 * stream: surface|epoch|port; episode: stream|last flash (a new flash starts a new episode and releases the hold).
 * live: seq of the current panic (or null), for the marker. jumpReq: {seq, n} from the "▲ panic" chip.
 * While a panic is held, "Guru Meditation…" stays the top line and following pauses until the user scrolls, follows,
 * or a new flash arrives.
 */
const RENDER_LIMIT = 800 // DOM rows of the log (the buffer keeps 2000; copy and pane use the buffer)

function LogLines({ view, showTs = true, live = null, panicSeq = null, lastSeq = 0, stream = null, episode = null, jumpReq = null, mark = null, onFollow = null, resumeRef = null }) {
  const ref = useRef(null)
  const inner = useRef(null)
  const [paused, setPaused] = useState(false)
  const [unseen, setUnseen] = useState(0)
  const count = useRef(0)
  const pausedRef = useRef(false)
  const hold = useRef(null) // seq of the panic block kept at the top
  const expectTop = useRef(null) // scrollTop we set ourselves (its scroll event is not the user)
  const lastEpisode = useRef(episode)
  pausedRef.current = paused
  const size = view.reduce((n, e) => n + (e.k === 'panic' ? e.lines.length : 1), 0)
  const pause = on => { pausedRef.current = on; setPaused(on) }
  const setTop = (el, top) => { el.scrollTop = top; expectTop.current = el.scrollTop }
  const toBottom = () => { const el = ref.current; if (el) setTop(el, el.scrollHeight) }
  const placeHold = () => {
    const el = ref.current
    if (!el || hold.current === null) return false
    const blocks = [...el.querySelectorAll('[data-cb=panic-block]')]
    const blk = blocks.find(b => b.getAttribute('data-cb-seq') === String(hold.current)) || blocks[blocks.length - 1]
    if (!blk) return false
    setTop(el, Math.max(0, blk.offsetTop - 4))
    revealMark()
    return true
  }
  // a frame / register hovered on the station marks its address in the raw lines: scroll just enough to show it
  const revealMark = () => {
    const el = ref.current
    const m = el && el.querySelector('[data-cb=log-mark]')
    if (!m) return
    const box = el.getBoundingClientRect()
    const r = m.getBoundingClientRect()
    if (r.top >= box.top && r.bottom <= box.bottom) return
    setTop(el, Math.max(0, el.scrollTop + (r.bottom > box.bottom ? r.bottom - box.bottom + 8 : r.top - box.top - 8)))
  }
  const holdAt = seq => { hold.current = seq; pause(true); setUnseen(0); placeHold() }
  useEffect(() => {
    // keep the tail (or the held panic) in view when the content reflows (resize, wrapping)
    if (typeof ResizeObserver !== 'function' || !inner.current) return undefined
    const ro = new ResizeObserver(() => { if (hold.current !== null) placeHold(); else if (!pausedRef.current) toBottom() })
    ro.observe(inner.current)
    if (ref.current) ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const added = size - count.current
    count.current = size
    if (episode !== lastEpisode.current) {
      // a new flash (or stream): stop holding the old panic and follow the new firmware's output
      lastEpisode.current = episode
      if (hold.current !== null) { hold.current = null; pause(false); setUnseen(0) }
    }
    const start = episode ? episodeStart(episode, stream, lastSeq) : 0
    if (episode && panicSeq !== null && panicSeq > start && !EPISODE_JUMPED.has(episode)) {
      EPISODE_JUMPED.add(episode)
      holdAt(panicSeq)
      return
    }
    if (hold.current !== null) {
      placeHold()
      if (added > 0) setUnseen(n => n + added)
    } else if (!pausedRef.current) {
      toBottom()
      revealMark()
    } else if (added > 0) {
      setUnseen(n => n + added)
    }
  }, [view, panicSeq, episode])
  useEffect(() => { if (jumpReq) holdAt(jumpReq.seq) }, [jumpReq?.n])
  const onScroll = () => {
    const el = ref.current
    if (!el) return
    if (expectTop.current !== null && Math.abs(el.scrollTop - expectTop.current) <= 2) return // our own scroll
    expectTop.current = null
    hold.current = null // the user scrolls: stop holding the panic
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (atBottom === pausedRef.current) pause(!atBottom)
    if (atBottom) setUnseen(0)
  }
  const resume = () => {
    hold.current = null
    pause(false)
    setUnseen(0)
    toBottom()
  }
  // "▼ N new lines" lives in the console toolbar: report the count up, hand the resume over
  if (resumeRef) resumeRef.current = resume
  const newLines = paused && unseen > 0 ? unseen : 0
  useEffect(() => { onFollow?.(newLines) }, [newLines])
  useEffect(() => () => onFollow?.(0), [])
  // the mark applies to one panic block: the held one, else the live one, else the newest
  const blocks = view.filter(e => e.k === 'panic')
  const markSeq = mark && blocks.length ? (blocks.find(b => b.seq === hold.current) || blocks.find(b => b.seq === live) || blocks[blocks.length - 1]).seq : null
  const markKey = markSeq !== null ? `${mark.kind}:${mark.name || ''}:${mark.value}` : null
  useEffect(() => { if (markKey) revealMark() }, [markKey])
  return h('div', { className: cx('cb-log', !showTs && 'cb-log--nots'), ref, onScroll, 'data-cb': 'log', 'data-cb-paused': paused ? 'true' : 'false',
    'data-cb-hold': hold.current !== null ? String(hold.current) : undefined, 'data-cb-mark': markKey || undefined,
    role: 'log', 'aria-live': 'off' },
    h('div', { className: 'cb-log-inner', ref: inner }, renderWindow(view, hold.current, RENDER_LIMIT).map((e, i) => e.k === 'panic'
      ? h('div', { key: `p${e.seq}`, className: cx('cb-panicblk', e.seq === live && 'cb-panicblk--live'), 'data-cb': 'panic-block', 'data-cb-seq': e.seq,
        'data-cb-truncate-ok': 'true', role: 'group', 'aria-label': `Panic at seq ${e.seq}` }, e.lines.map((l, j) => h(LogLine, { key: l.seq ?? `${i}-${j}`, l, i: j, mark: e.seq === markSeq ? mark : null })))
      : h(LogLine, { key: e.k === 'line' ? e.seq ?? i : `${e.k}${e.from ?? e.epoch ?? ''}-${i}`, l: e, i }))))
}

/** Empty serial console: a clear sentence and the next step. */
function ConsoleEmpty({ state, inline = false }) {
  const act = state?.action
  const run = () => {
    goStation('debug')
    if (act?.port) openMonitor(act.port)
  }
  return h(inline ? 'span' : 'div', { className: inline ? 'cb-cons-idle' : 'cb-cons-empty', 'data-cb': inline ? 'console-collapsed' : 'console-empty', 'data-cb-kind': state?.kind },
    h('span', { className: state?.kind === 'sim' ? 'cb-active' : 'cb-faint', 'aria-hidden': 'true' }, state?.kind === 'sim' ? '◌' : '>'),
    h('span', { className: 'cb-ellip' }, state?.text || ''),
    act ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'console-open-monitor', onClick: run,
      title: act.port ? `Open the monitor on ${act.port} (06 DEBUG)` : 'Go to 06 DEBUG' }, act.label) : null)
}

// the tab panel takes the place of the log in the console column (flex child that passes the height on)
const CONSOLE_PANEL_STYLE = { display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0, minWidth: 0 }
let CONSOLE_UID = 0

function Console({ surface = 'page', project, mode = 'open', jumpChip = true }) {
  const ui = sdk.useValue($ui)
  const serial = sdk.useValue($serial)
  const jobs = sdk.useValue($jobs)
  const bench = sdk.useValue($bench)
  const ports = sdk.useValue($ports)
  const mark = sdk.useValue($logMark)
  const [jump, setJump] = useState(null)
  const [copied, setCopied] = useState(null)
  const [newLines, setNewLines] = useState(0)
  const resumeRef = useRef(null)
  // ids for tab ↔ panel (route, tile and pane may show a console at once)
  const uid = useRef(null)
  if (uid.current === null) uid.current = ++CONSOLE_UID
  const tabId = id => `cb-cons${uid.current}-tab-${id}`
  const panelId = `cb-cons${uid.current}-panel`
  const tab = ui.tab
  const shut = surface === 'page' && (mode === 'collapsed' || mode === 'idle')
  let lines = []
  let meta = ''
  let metaParts = null
  let empty = null
  if (tab === 'serial') {
    lines = serial.buf.lines
    const nLines = lines.filter(l => l.k === 'line').length
    meta = serial.port ? `${serial.port} · ${serial.status}${serial.mode === 'poll' ? ' · polling' : serial.mode === 'socket' ? ' · live' : ''}` : 'no port'
    // the port gives way first in a narrow console (19-styles-debug.js); the state stays readable
    metaParts = serial.port ? { port: serial.port, state: `${serial.status}${serial.mode === 'poll' ? ' · polling' : serial.mode === 'socket' ? ' · live' : ''}` } : null
    if (!nLines) empty = serialEmptyState({ ports: ports.ports, serial, backendDown: bench.phase === 'error' })
  } else {
    const job = jobs[tab]
    lines = recordLines(tab, project, job)
    // pio reports no percentage: progress null → indeterminate ("running…")
    meta = job ? `job ${job.job_id} · ${job.state === 'running' && (job.progress === null || job.progress === undefined) ? 'running…'
      : `${job.state}${typeof job.progress === 'number' && job.state === 'running' ? ` · ${formatFraction(job.progress)}` : ''}`}` : lines.length ? 'last record' : ''
    if (!lines.length) empty = { kind: tab, text: tab === 'build' ? 'No build yet. Build from 05 FLASH or ask Hermes to build.' : 'Nothing flashed yet. Flashing always asks first (05 FLASH).', action: null }
  }
  const view = useMemo(() => logView(lines), [lines])
  const blocks = tab === 'serial' ? panicBlocks(view) : []
  const live = tab === 'serial' && serialPanicLive(serial.buf, $project.get()) ? serial.buf.panic.seq : null
  const stream = tab === 'serial' && serial.port ? `${surface}|${serial.buf.epoch ?? ''}|${serial.port}` : null
  const episode = stream ? `${stream}|${project?.firmware?.last_flash?.at || ''}` : null
  const lastBlock = blocks.length ? blocks[blocks.length - 1] : null
  // in a reboot loop the serial panic is "not current" between two crashes; the stored panic (no flash after it) is
  const chipLive = live !== null || projectPanicCurrent(project)
  const canCopy = typeof CB.ctx?.os?.writeClipboard === 'function' && lines.some(l => l.k === 'line')
  const copy = async () => {
    const text = tab === 'serial' ? bufferText(serial.buf) : lines.map(l => `${l.ts ? `${l.ts} ` : ''}${l.text}`).join('\n')
    let ok = false
    try { ok = (await CB.ctx.os.writeClipboard(text)) !== false } catch { ok = false }
    setCopied(ok ? 'ok' : 'fail')
    timersOf(CB.ctx).setTimeout(() => setCopied(null), 1600)
  }
  const toggle = surface === 'page'
    ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-toggle', 'aria-expanded': shut ? 'false' : 'true',
      title: shut ? 'Show console' : 'Hide console', 'aria-label': shut ? 'Show console' : 'Hide console', onClick: () => setConsole(shut ? 'open' : 'collapsed') },
    shut ? '▴' : '▾', h('span', { className: 'cb-tbl' }, shut ? ' show' : ' hide'))
    : null
  const pane = surface === 'page'
    ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-to-pane', title: 'Open the serial monitor as a pane below the chat',
      'aria-label': 'Open as pane', onClick: () => openSerialPane() }, '⇲', h('span', { className: 'cb-tbl' }, ' pane'))
    : h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'pane-close', title: 'Close the serial monitor pane', 'aria-label': 'Close pane', onClick: () => closeSerialPane() },
      '✕', h('span', { className: 'cb-tbl' }, ' close'))
  const idleText = shut && tab === 'serial' && empty ? h(ConsoleEmpty, { key: 'idle', state: empty, inline: true }) : null
  const showLog = !shut && !empty
  const follow = showLog && newLines > 0
    ? h('button', { type: 'button', className: 'cb-iconbtn cb-followbtn', 'data-cb': 'log-follow', title: 'Follow the log again (jump to the newest line)',
      'aria-label': `${newLines} new line${newLines === 1 ? '' : 's'}, follow the log`, onClick: () => resumeRef.current?.() },
    `▼ ${newLines}`, h('span', { className: 'cb-tbl' }, ` new line${newLines === 1 ? '' : 's'}`))
    : null
  return h('div', { className: 'cb-console', 'data-cb': `console-${surface}`, 'data-cb-mode': surface === 'page' ? mode : undefined },
    h('div', { className: 'cb-tabs', role: 'tablist', 'aria-label': 'Console' },
      CONSOLE_TABS.map(([id, label]) => h('button', { key: id, type: 'button', role: 'tab', 'aria-selected': tab === id ? 'true' : 'false',
        id: tabId(id), 'aria-controls': shut ? undefined : panelId, 'data-cb': `tab-${id}`, onClick: () => { setConsoleTab(id); if (shut) setConsole('open') } }, label,
      id === 'serial' && serialPanicLive(serial.buf, $project.get()) ? h('span', { className: 'cb-bad', 'aria-label': 'panic' }, '●') : null)),
      h('div', { className: 'cb-meta' },
        idleText,
        follow,
        !shut && lastBlock && jumpChip ? h('button', { type: 'button', className: cx('cb-iconbtn cb-pjump', chipLive && 'cb-pjump--live'), 'data-cb': 'panic-jump',
          title: `Scroll to the panic at seq ${lastBlock.seq} (Guru Meditation …)${chipLive ? '' : ' — not current: a flash came after it'}`,
          onClick: () => setJump({ seq: lastBlock.seq, n: (jump?.n || 0) + 1 }) },
        '▲ ', chipLive ? null : h('span', { className: 'cb-cmd-long' }, 'last '), 'panic', h('span', { className: 'cb-tbx' }, ` · seq ${lastBlock.seq}`)) : null,
        tab === 'serial' && (serial.simulated || isSimPort(serial.port)) ? h(SimBanner, { compact: true, dataCb: 'sim-banner-console' }) : null,
        idleText ? null : h('span', { className: 'cb-consmeta', title: meta }, metaParts
          ? [h('span', { key: 'p', className: 'cb-consport' }, `${metaParts.port} · `), metaParts.state] : meta),
      ),
      // tools in their own group
      h('div', { className: 'cb-cons-tools' },
        canCopy && !shut ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-copy', onClick: copy,
          'aria-label': copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : 'Copy log',
          title: `Copy the ${tab} log (${lines.filter(l => l.k === 'line').length} lines) to the clipboard` }, copied === 'ok' ? ['✓', h('span', { key: 'l', className: 'cb-tbl' }, ' copied')]
          : copied === 'fail' ? ['✕', h('span', { key: 'l', className: 'cb-tbl' }, ' not copied')] : ['⧉', h('span', { key: 'l', className: 'cb-tbl' }, ' copy log')]) : null,
        pane, toggle)),
    shut ? null : h('div', { role: 'tabpanel', id: panelId, 'aria-labelledby': tabId(tab), style: CONSOLE_PANEL_STYLE },
      empty ? h(ConsoleEmpty, { state: empty })
        : h(LogLines, { view, showTs: ui.showTs, live, panicSeq: tab === 'serial' ? serial.buf.panic?.seq ?? null : null, lastSeq: serial.buf.lastSeq || 0,
          stream, episode, jumpReq: jump, mark: tab === 'serial' ? mark : null, onFollow: setNewLines, resumeRef })))
}

/** Console row on the page; outside 06 DEBUG the panic strip above the log. Pane open: a slim bar. */
function ConsoleRow({ project, mode }) {
  const nav = sdk.useValue($nav)
  if (mode === 'pane') {
    return h('section', { className: 'cb-cons', 'data-cb': 'console-row', 'data-cb-mode': mode, style: { gridTemplateColumns: 'minmax(0,1fr)' } },
      h('div', { className: 'cb-tabs' }, h('span', { className: 'cb-cons-empty', style: { padding: '0 14px', alignItems: 'center' } },
        h(Label, null, 'console'), 'The serial monitor is open in the pane below.',
        h('button', { type: 'button', className: 'cb-iconbtn', onClick: () => closeSerialPane(), 'data-cb': 'pane-back' }, '⇱ back to bench'))))
  }
  const debug = nav.station === 'debug'
  return h('section', { className: 'cb-cons cb-cons--page', 'data-cb': 'console-row', 'data-cb-audit-root': 'console', 'data-cb-mode': mode },
    mode !== 'open' || debug ? null : h(PanicStrip, { project }),
    h(Console, { surface: 'page', project, mode, jumpChip: debug }))
}

/** Serial pane (PANES_AREA, docked under the workspace). Registered on demand so it never takes room unasked; its
 *  own ✕ disposes the registration (the app's tab ✕ would disable the whole plugin: single-pane rule). */
function SerialPane() {
  const project = sdk.useValue($project)
  const ui = sdk.useValue($ui)
  useEffect(() => { ensureBench() }, [])
  return h('div', { className: 'cb-root cb-pane', 'data-cb': 'serial-pane', 'data-cb-look': ui.look },
    h(Styles, null),
    h('section', { className: 'cb-cons' }, h(Console, { surface: 'pane', project }), h(PanicCard, { project })))
}

function openSerialPane() {
  if (CB.paneDispose || !CB.ctx) {
    patchAtom($ui, { paneOpen: true })
    return
  }
  const area = sdk.PANES_AREA || 'panes'
  CB.paneDispose = CB.ctx.register({ id: 'serial', area, title: 'Serial',
    data: { placement: 'bottom', dock: { pane: 'workspace', pos: 'bottom' }, height: '240px', uncloseable: true },
    render: () => h(SerialPane, null) })
  patchAtom($ui, { paneOpen: true })
  store('paneOpen', true)
}

function closeSerialPane() {
  const d = CB.paneDispose
  CB.paneDispose = null
  try { d?.() } catch (e) { console.warn('[circuit-bench] pane dispose', e) }
  patchAtom($ui, { paneOpen: false })
  store('paneOpen', false)
}
