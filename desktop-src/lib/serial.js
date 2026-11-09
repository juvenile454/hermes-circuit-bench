// Live serial client: WebSocket stream with the mandatory polling fallback. Pure (all
// side effects are injected), so node tests drive it with fake timers, sockets and tail answers.
//
//   createSerialClient({ port, socket, tail, timers, onUpdate, initial })
//     socket(path, onMessage) → disposer      ctx.socket (receive-only, reconnects on its own)
//     tail(port, after) → Promise<envelope>   GET /serial/tail?port=&after=  (result: lines, panic, epoch, state)
//     timers: { setTimeout, clearTimeout }    ctx.setTimeout-like (returns an id or a disposer)
//     onUpdate({ buf, mode, state, simulated, error })
//   .start()   subscribe the socket; if it delivers nothing within SOCKET_GRACE_MS → polling every POLL_MS
//   .stop()    dispose the socket and stop polling (the port itself is closed by the caller: POST /serial/close)
//
// Rules: duplicates are dropped per epoch by seq (lib/seq.js); a new epoch (backend restart) resets the dedupe; a
// `lagging` state or a gap makes the client fetch the missing range from the tail and fill it in; when the socket
// starts delivering again while polling, polling stops (the server resends state + the last ≤ 200 lines on connect).
// The client never opens a port: opening is POST /serial/open, done by the caller after a click.
// `seq` = { mergeLines, emptyBuffer } from lib/seq.js (injected: lib files are concatenated, never import each other).

export const SOCKET_GRACE_MS = 3000
export const POLL_MS = 1000
export const FILL_DELAY_MS = 250

export function streamPath(port) {
  return `/serial/stream?port=${encodeURIComponent(port)}`
}

/** Insert lines that fall into gap markers (missed ranges) of `buf`; returns a new buffer. */
export function fillGaps(buf, lines) {
  const fill = (lines || []).filter(l => l && l.t === 'line' && Number.isInteger(l.seq)).sort((a, b) => a.seq - b.seq)
  if (!fill.length || !buf.lines.some(l => l.k === 'gap')) return buf
  const out = []
  for (const entry of buf.lines) {
    if (entry.k !== 'gap') { out.push(entry); continue }
    let from = entry.from
    for (const l of fill) {
      if (l.seq < from || l.seq > entry.to) continue
      if (l.seq > from) out.push({ k: 'gap', from, to: l.seq - 1 })
      out.push({ k: 'line', seq: l.seq, ts: l.ts ?? '', text: String(l.text ?? '') })
      from = l.seq + 1
    }
    if (from <= entry.to) out.push({ k: 'gap', from, to: entry.to })
  }
  return { ...buf, lines: out }
}

/** First missed seq of a buffer (lowest gap start) or null. */
export function firstGap(buf) {
  const g = buf.lines.find(l => l.k === 'gap')
  return g ? g.from : null
}

export function createSerialClient({ port, socket, tail, timers, onUpdate, seq, initial = null, graceMs = SOCKET_GRACE_MS, pollMs = POLL_MS }) {
  const { mergeLines } = seq
  let buf = initial || seq.emptyBuffer()
  let mode = 'connecting' // connecting | socket | poll | stopped
  let error = null
  let simulated = null
  let disposeSocket = null
  let graceTimer = null
  let pollTimer = null
  let fillTimer = null
  let polling = false
  let stopped = false
  let socketMessages = 0

  const clear = t => {
    if (t === null || t === undefined) return
    if (typeof t === 'function') { try { t() } catch { /* already gone */ } } else timers.clearTimeout(t)
  }
  const emit = () => onUpdate?.({ buf, mode, state: buf.state?.state ?? null, simulated, error })

  function scheduleFill() {
    if (fillTimer !== null || stopped) return
    fillTimer = timers.setTimeout(async () => {
      fillTimer = null
      const from = firstGap(buf)
      if (from === null) return
      const env = await tail(port, from - 1)
      if (stopped || !env?.ok) return
      if (env.result?.epoch && buf.epoch && env.result.epoch !== buf.epoch) return // restarted meanwhile: gap is moot
      buf = fillGaps(buf, env.result?.lines || [])
      emit()
    }, FILL_DELAY_MS)
  }

  function onSocket(msg) {
    if (stopped || !msg || typeof msg !== 'object') return
    socketMessages++
    if (graceTimer !== null) { clear(graceTimer); graceTimer = null }
    if (mode !== 'socket') {
      mode = 'socket'
      if (pollTimer !== null) { clear(pollTimer); pollTimer = null }
    }
    if (msg.t === 'state' && typeof msg.simulated === 'boolean') simulated = msg.simulated
    const before = firstGap(buf)
    buf = mergeLines(buf, msg)
    error = null
    if ((msg.t === 'state' && /lagging/i.test(String(msg.detail || ''))) || (firstGap(buf) !== null && firstGap(buf) !== before)) scheduleFill()
    emit()
  }

  async function pollOnce() {
    if (stopped || polling) return
    polling = true
    try {
      let env = await tail(port, buf.lastSeq)
      if (stopped || mode === 'socket') return
      if (env?.ok && env.result?.epoch && buf.epoch !== null && env.result.epoch !== buf.epoch && buf.lastSeq > 0) {
        env = await tail(port, 0) // backend restarted: seq starts at 1 again, read the new epoch from its start
        if (stopped || mode === 'socket') return
      }
      if (!env?.ok) {
        error = env?.error?.message || 'serial tail failed'
      } else {
        const r = env.result || {}
        if (typeof r.simulated === 'boolean') simulated = r.simulated
        const msgs = [{ t: 'state', port: r.port ?? port, state: r.state ?? null, epoch: r.epoch }, ...(r.lines || []).map(l => ({ t: 'line', ...l }))]
        if (r.panic) msgs.push({ ...r.panic, t: 'panic' })
        buf = mergeLines(buf, msgs, { epoch: r.epoch })
        error = null
      }
      emit()
    } finally {
      polling = false
      if (!stopped && mode === 'poll') pollTimer = timers.setTimeout(pollOnce, pollMs)
    }
  }

  function startPolling() {
    graceTimer = null
    if (stopped || mode === 'socket') return
    mode = 'poll'
    emit()
    pollOnce()
  }

  return {
    start() {
      stopped = false
      mode = 'connecting'
      emit()
      try {
        disposeSocket = typeof socket === 'function' ? socket(streamPath(port), onSocket) : null
      } catch (e) {
        disposeSocket = null
        error = String(e?.message || e)
      }
      // no socket (OAuth remote, host isolation, error): poll at once; else give the socket SOCKET_GRACE_MS
      if (!disposeSocket) startPolling()
      else graceTimer = timers.setTimeout(startPolling, graceMs)
    },
    stop() {
      stopped = true
      for (const t of [graceTimer, pollTimer, fillTimer]) clear(t)
      graceTimer = pollTimer = fillTimer = null
      if (disposeSocket) { try { disposeSocket() } catch { /* gone */ } }
      disposeSocket = null
      mode = 'stopped'
      emit()
    },
    buffer: () => buf,
    mode: () => mode,
    socketMessages: () => socketMessages
  }
}

/**
 * Coalesce a burst of updates into one apply per `ms` (observed: a real board in a reboot loop sends ~75 lines/s; one
 * store update per line re-rendered the whole Bench each time and froze the window). push(v) keeps the newest value;
 * the first push of a quiet period applies after `ms`. cancel() drops a pending value, flush() applies it now.
 */
export function coalescer(timers, ms, apply) {
  let pending
  let has = false
  let timer = null
  const clear = () => {
    if (timer === null) return
    if (typeof timer === 'function') { try { timer() } catch { /* gone */ } } else timers.clearTimeout(timer)
    timer = null
  }
  const flush = () => {
    clear()
    if (!has) return
    const v = pending
    has = false
    pending = undefined
    apply(v)
  }
  return {
    push(v) {
      pending = v
      has = true
      if (timer === null) timer = timers.setTimeout(() => { timer = null; flush() }, ms)
    },
    flush,
    cancel() { clear(); has = false; pending = undefined },
    pending: () => has
  }
}

/**
 * Should a newly announced panic be decoded? A board in a reboot loop announces the same crash on every boot; it is
 * decoded once per flash. A different summary, a new flash (`flashAt`) or no decode yet → decode. Decoding a repeat
 * after a rebuild would also use the new ELF for the old firmware's addresses (wrong lines).
 * cur = {status, key, summary, flashAt} of the decoded panic; pn = {log_ref, summary}.
 */
export function panicNeedsDecode(cur, pn, flashAt = null) {
  if (!pn?.log_ref) return false
  if (!cur?.key) return true
  if (cur.key === pn.log_ref) return false
  if (!['ready', 'loading'].includes(cur.status)) return true
  return !(cur.summary === pn.summary && (cur.flashAt ?? null) === (flashAt ?? null))
}

/**
 * The entries of a log view that go into the DOM: the newest `limit`, extended back to a held panic block so the
 * block the user reads stays put. → a slice of `view`.
 */
export function renderWindow(view, holdSeq = null, limit = 800) {
  const list = view || []
  let from = Math.max(0, list.length - limit)
  if (holdSeq !== null && holdSeq !== undefined && from > 0) {
    const i = list.findIndex(e => e.k === 'panic' && e.seq === holdSeq)
    if (i >= 0 && i < from) from = i
  }
  return from ? list.slice(from) : list
}

// Reset reasons in the ROM banner ("rst:0x15 (USB_UART_CHIP_RESET),boot:…") that mean the board was reset from
// outside: power-on 0x1, the USB-Serial/JTAG chip reset 0x15 (esptool, a flash, the RESET key) and 0x16. Observed
// on a real ESP32-S3 (2026-11-06): a panic reboots with rst:0xc (RTC_SW_CPU_RST), the reset after a flash shows rst:0x15.
// Watchdog and brownout resets also follow a panic. A UI heuristic, not a check (board-observed).
export const EXTERNAL_RESETS = [0x1, 0x15, 0x16]

/**
 * Is a serial panic still current? After a panic the board reboots on its own (rst:0xc) and, in a reboot loop,
 * panics again: the panic stays current. A boot banner with an outside reset (power-on, esptool/flash) or a ROM
 * banner without a reset reason followed by output means new firmware or a fresh start: stale. (Observed: the old rule,
 * stale at any banner, hid the panic of a real reboot loop between two announcements.)
 */
export function panicCurrent(buf) {
  const p = buf?.panic
  if (!p) return false
  const lines = buf.lines || []
  let rom = false
  for (const l of lines) {
    if (l.k !== 'line' || l.seq <= p.seq) continue
    const m = /^rst:0x([0-9a-fA-F]+)/.exec(l.text)
    if (m) {
      if (EXTERNAL_RESETS.includes(parseInt(m[1], 16))) return false
      rom = false
      continue
    }
    if (/^ESP-ROM:/.test(l.text)) { rom = true; continue }
    if (rom && !/^Build:/.test(l.text)) return false // a banner without a reset reason, then output: a new boot
  }
  return true
}

/** UTC time (ms) of a serial artifact name "panic-YYYYMMDD-HHMMSS[-n].log" (serialport.open_artifact), else NaN. */
export function logRefTime(ref) {
  const m = /^[a-z]+-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(?:-\d+)?\.log$/.exec(String(ref || ''))
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : NaN
}

/**
 * The serial panic is current (panicCurrent) and not older than the last good flash of the project: a panic from
 * before the flash came from the old firmware (observed: after the flash, lines lost while the USB port re-enumerated
 * left the old panic "current").
 */
export function serialPanicLive(buf, project) {
  if (!buf?.panic || !panicCurrent(buf)) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at) return true
  const pt = logRefTime(buf.panic.log_ref)
  const ft = Date.parse(f.at)
  return !(Number.isFinite(pt) && Number.isFinite(ft) && pt < ft)
}

const ROM_LINE = /^(ESP-ROM:|Build:|rst:0x|Saved PC:|SPIWP:|mode:|load:|entry |SHA-256 comparison|Calculated:|Expected:|Attempting to boot|E \(\d+\) esp_core_dump)/
const PANIC_LINE = /Guru Meditation Error|abort\(\) was called|Brownout detector was triggered|panic'ed/

/**
 * Did the firmware run after a flash without a panic? Lines with seq > `afterSeq`: at least `min` lines of the
 * application (not ROM/bootloader output) and no panic line. A board whose "boot ok" line was missed (the port
 * re-enumerated after RESET) or a firmware that never prints one is still recognised. → {n, last} | null
 */
export function cleanRunAfter(buf, afterSeq, min = 3) {
  if (!Number.isInteger(afterSeq)) return null
  let n = 0
  let last = null
  for (const l of buf?.lines || []) {
    if (l.k !== 'line' || l.seq <= afterSeq) continue
    if (PANIC_LINE.test(l.text)) return null
    const t = String(l.text || '').trim()
    if (!t || ROM_LINE.test(t)) continue
    n++
    last = l
  }
  return n >= min ? { n, last } : null
}

/** Last line of the buffer matching `re` (e.g. /boot ok/). */
export function lastLineMatching(buf, re) {
  for (let i = (buf?.lines || []).length - 1; i >= 0; i--) {
    const l = buf.lines[i]
    if (l.k === 'line' && re.test(l.text)) return l
  }
  return null
}

/**
 * Console state on the Bench page: `pane` (serial pane open, a slim bar points there) |
 * `collapsed` (the user hid it) | `idle` (no port open and nothing to show: one 34 px bar, the board gets the room) |
 * `open`. An open monitor, a buffered log of an open port, a running job, a current panic or a click on the bar
 * (`pinned`, session only) open it.
 */
export function consoleMode({ paneOpen = false, cons = 'open', pinned = false, monitorOpen = false, serialOpen = false, jobRunning = false, panic = false } = {}) {
  if (paneOpen) return 'pane'
  if (cons === 'collapsed') return 'collapsed'
  if (monitorOpen || serialOpen || jobRunning || panic || pinned) return 'open'
  return 'idle'
}

/**
 * What an empty serial console says and offers → {kind, text, action: {label, port}|null}.
 * `ports` = GET /ports list, `serial` = {port, note, status}, `backendDown` when the bench backend is unreachable.
 */
export function serialEmptyState({ ports = [], serial = {}, backendDown = false } = {}) {
  if (backendDown) return { kind: 'offline', text: 'Bench backend not available — no serial data.', action: null }
  const list = Array.isArray(ports) ? ports : []
  const isSim = d => /^sim:\/\//.test(String(d || ''))
  if (serial.port && !isSim(serial.port) && serial.note === 'real-port') {
    return { kind: 'real', text: `Monitor closed for ${serial.port}. Ports open only on your click.`, action: { label: '06 DEBUG ›', port: null } }
  }
  if (serial.status === 'error' && serial.note) return { kind: 'error', text: `Serial read failed: ${serial.note}`, action: null }
  const sim = isSim(serial.port) ? serial.port : (list.find(p => p.simulated) || {}).device || null
  const real = list.find(p => !p.simulated && p.likely_esp)
  if (real) return { kind: 'real', text: `Board on ${real.device}. Ports open only on your click.`, action: { label: '06 DEBUG ›', port: null } }
  if (sim) return { kind: 'sim', text: 'Simulated board ready.', action: { label: 'Open monitor ›', port: sim } }
  return { kind: 'none', text: 'No serial port found. Plug in a board; 05 FLASH lists the ports.', action: null }
}
