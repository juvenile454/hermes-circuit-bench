// Serial line buffer: seq-based merge, duplicates dropped, gaps marked, epoch reset. Pure.
// Messages: {t: "line", seq, ts, text} | {t: "panic", seq, summary, log_ref} | {t: "state", port, state, epoch?}.
// seq rises monotonically per port and epoch. A new epoch (backend restart) starts seq at 1 again.

export const LINE_LIMIT = 2000

export function emptyBuffer() {
  return { epoch: null, lastSeq: 0, lines: [], panic: null, state: null, dropped: 0 }
}

/**
 * Merge messages into a buffer (returns a new buffer; the input is not changed).
 * opts.epoch   epoch of a polling batch (GET /serial/tail); stream messages carry it in `state`.
 * opts.limit   max kept entries (oldest dropped first).
 * Entries in `lines`: {k: "line", seq, ts, text} | {k: "gap", from, to} | {k: "epoch", epoch}.
 */
export function mergeLines(buf, msgs, opts = {}) {
  const limit = opts.limit ?? LINE_LIMIT
  const out = { ...buf, lines: buf.lines.slice() }
  const switchEpoch = epoch => {
    if (epoch === undefined || epoch === null || epoch === out.epoch) return
    if (out.epoch !== null) out.lines.push({ k: 'epoch', epoch })
    out.epoch = epoch
    out.lastSeq = 0
  }
  switchEpoch(opts.epoch)
  for (const m of Array.isArray(msgs) ? msgs : [msgs]) {
    if (!m || typeof m !== 'object') continue
    if (m.t === 'state') {
      switchEpoch(m.epoch)
      out.state = { port: m.port ?? null, state: m.state ?? null, detail: m.detail ?? null }
      continue
    }
    if (!Number.isInteger(m.seq) || m.seq < 1) continue
    if (m.t === 'panic') {
      out.panic = { seq: m.seq, summary: m.summary ?? '', log_ref: m.log_ref ?? null }
      continue
    }
    if (m.t !== 'line') continue
    if (m.seq <= out.lastSeq) { out.dropped++; continue }
    if (out.lastSeq > 0 && m.seq > out.lastSeq + 1) out.lines.push({ k: 'gap', from: out.lastSeq + 1, to: m.seq - 1 })
    out.lines.push({ k: 'line', seq: m.seq, ts: m.ts ?? '', text: String(m.text ?? '') })
    out.lastSeq = m.seq
  }
  if (out.lines.length > limit) out.lines = out.lines.slice(out.lines.length - limit)
  return out
}

/** Gaps (missed seq ranges) in a buffer. */
export function gapsOf(buf) {
  return buf.lines.filter(l => l.k === 'gap').map(l => ({ from: l.from, to: l.to }))
}

/** Highlight class for a log line: panic | bt (backtrace/registers) | hl (boot banner) | rom | ''. */
export function lineClass(text) {
  const s = String(text || '')
  if (/Guru Meditation|panic'ed|abort\(\) was called|Brownout detector|assert failed|Stack smashing/i.test(s)) return 'panic'
  if (/^\s*(Backtrace:|PC\s*:|EXCVADDR|EXCCAUSE|Core\s+\d+ register dump|A\d+\s*:|ELF file SHA256)/.test(s)) return 'bt'
  if (/^(ESP-ROM:|rst:0x|boot:0x|load:0x|entry 0x|mode:|SPIWP:|clk_drv|Saved PC:)/.test(s)) return 'rom'
  if (/\bboot\b.*\b(ok|ready|laser off)\b|^\[[a-z0-9-]+\]/i.test(s)) return 'hl'
  return ''
}

/** Plain-text log (for copy): "ts text" per line, gaps as markers. */
export function bufferText(buf) {
  return buf.lines.map(l => (l.k === 'line' ? `${l.ts ? `${l.ts} ` : ''}${l.text}` : l.k === 'gap'
    ? `… ${l.to - l.from + 1} line(s) missed (seq ${l.from}–${l.to}) …` : `— backend restarted (epoch ${l.epoch}) —`)).join('\n')
}

/**
 * Display model of a log: runs of blank lines fold into one (the copy text keeps them), and every panic —
 * from its "Guru Meditation…"/abort line to "Rebooting..." (or the next boot banner, or the end) — becomes one
 * block. → [{k: 'line'|'gap'|'epoch', …} | {k: 'panic', seq, lines: [...]}]
 */
export function logView(lines) {
  const out = []
  let block = null
  let blank = false
  for (const l of lines || []) {
    if (l.k !== 'line') {
      block = null
      blank = false
      out.push(l)
      continue
    }
    const empty = !String(l.text || '').trim()
    if (empty && blank) continue
    blank = empty
    if (!empty && lineClass(l.text) === 'panic' && /Guru Meditation|panic'ed|abort\(\) was called|Stack smashing|assert failed/i.test(l.text)) {
      block = { k: 'panic', seq: l.seq, lines: [l] }
      out.push(block)
      continue
    }
    if (block && /^(ESP-ROM:|rst:0x)/.test(l.text)) block = null
    if (block) {
      block.lines.push(l)
      if (/^Rebooting\.\.\./.test(l.text)) block = null
      continue
    }
    out.push(l)
  }
  return out
}

/** The panic blocks of a display model, newest last → [{seq, first, last}] (seq of the Guru line). */
export function panicBlocks(view) {
  return (view || []).filter(e => e.k === 'panic').map(e => ({ seq: e.seq, first: e.lines[0]?.seq ?? e.seq, last: e.lines[e.lines.length - 1]?.seq ?? e.seq }))
}
