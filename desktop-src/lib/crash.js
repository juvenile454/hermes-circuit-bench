// Crash-decode presentation helpers (pure; tested in tests-js/test_ui1_api.mjs and test_ui2_panic.mjs).

/**
 * ELF check of a crash.decode envelope: passed (match), failed (mismatch), skipped (no ELF, e.g. sim build).
 * `label` carries the reason right after the verdict (e.g. "elf check skipped · simulated build, no
 * ELF"); `short` is the compact form for the console card. A skipped check is never shown as passed.
 */
export function elfCheck(env) {
  const r = env?.result || {}
  const c = (env?.checks || []).find(x => x.id === 'crash.elf_match')
  const status = c?.status || (r.elf_match === true ? 'passed' : r.elf_match === false ? 'failed' : 'skipped')
  // word + reason: the 06 DEBUG check line ("elf check  ○ skipped · simulated build, no ELF")
  if (status === 'passed') {
    return { status, tone: 'ok', symbol: '✓', text: 'elf match', label: 'elf match', short: 'elf match', detail: c?.detail,
      word: 'match', reason: c?.detail || 'ELF hash matches the log' }
  }
  if (status === 'failed') {
    return { status, tone: 'bad', symbol: '✕', text: 'elf mismatch', label: 'elf mismatch · other build', short: 'elf mismatch',
      detail: c?.detail || 'The log was produced by a different firmware build.', word: 'mismatch', reason: 'the log comes from another build' }
  }
  const reason = env?.simulated ? 'simulated build, no ELF' : 'no ELF to compare'
  return { status: 'skipped', tone: 'faint', symbol: '○', text: 'elf check skipped', label: `elf check skipped · ${reason}`,
    short: env?.simulated ? 'elf skipped · sim' : 'elf skipped', detail: c?.detail || 'no ELF file to compare', word: 'skipped', reason }
}

/**
 * Key registers of a panic per architecture, with what the register holds (ESP-IDF Fatal Errors: EXCVADDR / MTVAL
 * hold the accessed address). Only names; the values come from the decoder.
 */
export const KEY_REGISTERS = {
  xtensa: [['PC', 'program counter'], ['EXCCAUSE', 'exception cause'], ['EXCVADDR', 'accessed address']],
  riscv: [['MEPC', 'exception pc'], ['MCAUSE', 'trap cause'], ['MTVAL', 'trap value']]
}

/**
 * Register bank of a crash.decode result → {key: [{k, v, label, note}], all: [{k, v, key}]} or
 * null. `key` keeps the architecture's order (only registers the dump has); `note` on the cause register is the
 * decoder's reason name, which it read from that register (cpu exceptions only). `all` is the dump in log order.
 */
export function registerBank(result) {
  const regs = result?.registers || {}
  const names = Object.keys(regs)
  if (!names.length) return null
  const arch = result.arch === 'riscv' || (!result.arch && ('MEPC' in regs || 'MCAUSE' in regs)) ? 'riscv' : 'xtensa'
  const keys = KEY_REGISTERS[arch].filter(([k]) => regs[k])
  const cause = arch === 'riscv' ? 'MCAUSE' : 'EXCCAUSE'
  const note = k => (k === cause && result.kind === 'cpu_exception' && result.reason ? result.reason : null)
  const keySet = new Set(keys.map(([k]) => k))
  return {
    arch,
    key: keys.map(([k, label]) => ({ k, v: regs[k], label, note: note(k) })),
    all: names.map(k => ({ k, v: regs[k], key: keySet.has(k) }))
  }
}

const crashHexLow = s => String(s || '').toLowerCase()

/**
 * Where a hovered frame or register shows up in a raw log line (frame ↔ log coupling) →
 * [[start, end], …] character ranges. mark = {kind: 'pc', value} matches the PC of a "PC:SP" pair in a
 * "Backtrace:" line; {kind: 'reg', name, value} matches "NAME : value" in a register dump line. Hex is compared
 * case-insensitively; a value never matches inside a longer number.
 */
export function logMarkRanges(text, mark) {
  const s = String(text || '')
  if (!mark?.value || !s) return []
  const v = crashHexLow(mark.value).replace(/[^0-9a-fx]/g, '')
  if (!/^0x[0-9a-f]+$/.test(v)) return []
  const low = s.toLowerCase()
  const out = []
  if (mark.kind === 'pc') {
    if (!/^\s*backtrace:/.test(low)) return []
    const re = /(0x[0-9a-f]+):0x[0-9a-f]+/g
    for (let m = re.exec(low); m; m = re.exec(low)) if (m[1] === v) out.push([m.index, m.index + m[1].length])
    return out
  }
  if (mark.kind === 'reg' && /^[A-Za-z][A-Za-z0-9]*$/.test(String(mark.name || ''))) {
    const re = new RegExp(`(^|[^a-z0-9])(${String(mark.name).toLowerCase()}\\s*:\\s*(0x[0-9a-f]+))`, 'g')
    for (let m = re.exec(low); m; m = re.exec(low)) {
      if (m[3] === v) { const at = m.index + m[1].length; out.push([at, at + m[2].length]) }
    }
  }
  return out
}

/** A text split into plain and marked parts → [{t, mark}] (for rendering logMarkRanges). */
export function splitMarked(text, ranges) {
  const s = String(text || '')
  if (!ranges?.length) return [{ t: s, mark: false }]
  const out = []
  let at = 0
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    if (a < at) continue
    if (a > at) out.push({ t: s.slice(at, a), mark: false })
    out.push({ t: s.slice(a, b), mark: true })
    at = b
  }
  if (at < s.length) out.push({ t: s.slice(at), mark: false })
  return out
}

/** "write_sensor_buffer(unsigned char*, unsigned int)" → "write_sensor_buffer(…)"; no-arg and plain names unchanged. */
export function shortFunction(fn) {
  const s = String(fn || '').trim()
  const m = /^([^(]+)\((.*)\)(\s*(?:const)?\s*)$/.exec(s)
  if (!m) return s || '??'
  return m[2].trim() ? `${m[1]}(…)${m[3].trimEnd()}` : s
}

/** "write_sensor_buffer(unsigned char*, unsigned int) (src/main.cpp:44)" → {fn, file, line} */
export function splitTopFrame(text) {
  const s = String(text || '')
  const m = /^(.*?)\s*\(([^()]*):(\d+)\)\s*$/.exec(s)
  return m ? { fn: m[1], file: m[2], line: Number(m[3]) } : { fn: s, file: null, line: null }
}

/**
 * Data for the PanicCard and the 06 DEBUG panic view, from (in this order of preference) the crash.decode envelope,
 * the project's stored debug.last_panic and the serial panic message ({seq, summary, log_ref}).
 * → null when there is nothing to show.
 */
export function panicCardData(decodeEnv, lastPanic = null, serialPanic = null) {
  const env = decodeEnv?.ok ? decodeEnv : null
  const r = env?.result || null
  if (!r && !lastPanic && !serialPanic) return null
  const reason = r?.reason || lastPanic?.reason || (serialPanic?.summary ? String(serialPanic.summary).split(' · ')[0] : null) || 'panic'
  const coreRaw = r?.core ?? lastPanic?.core ?? (/core\s+(\d+)/i.exec(serialPanic?.summary || '') || [])[1]
  const core = coreRaw === undefined || coreRaw === null ? null : Number(coreRaw)
  let frames = (r?.frames || []).map((f, i) => ({ i: f.i ?? i, fn: String(f.function || '??'), short: shortFunction(f.function),
    file: f.file || '??', base: String(f.file || '??').split('/').pop(), line: f.line ?? null, pc: f.pc || '', inlined: Boolean(f.inlined) }))
  if (!frames.length && lastPanic?.top_frame) {
    const t = splitTopFrame(lastPanic.top_frame)
    frames = [{ i: 0, fn: t.fn, short: shortFunction(t.fn), file: t.file || '??', base: String(t.file || '??').split('/').pop(), line: t.line, pc: '', inlined: false }]
  }
  const regs = r?.registers || {}
  return {
    reason,
    core,
    title: `${reason}${core !== null ? ` · core ${core}` : ''}`,
    decoded: Boolean(r),
    simulated: Boolean(env?.simulated),
    frames,
    top: frames[0] || null,
    interpretation: (r?.interpretation || []).map(x => ({ code: x.code, text: x.text, source_id: x.source_id || null })),
    registers: ['PC', 'EXCCAUSE', 'EXCVADDR'].filter(k => regs[k]).map(k => ({ k, v: regs[k] })),
    bank: registerBank(r),
    // the interpretation the decoder summary does not already say (the summary is the lead sentence on 06 DEBUG)
    extra: (r?.interpretation || []).filter(x => !saidIn(env?.summary || '', x.text)).map(x => ({ code: x.code, text: x.text, source_id: x.source_id || null })),
    resetReason: r?.reset_reason || null,
    elf: env ? elfCheck(env) : null,
    logRef: serialPanic?.log_ref || lastPanic?.log_ref || null,
    summary: env?.summary || (serialPanic ? `${serialPanic.summary}` : lastPanic ? `${reason}${core !== null ? ` on core ${core}` : ''}` : '')
  }
}

/** The project's stored panic still describes the firmware on the board (no successful flash after it). */
export function projectPanicCurrent(project) {
  const p = project?.debug?.last_panic
  if (!p) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at || !p.at) return true
  return String(p.at) >= String(f.at)
}

const normText = t => String(t || '').toLowerCase().replace(/\s+/g, ' ').replace(/[.\s]+$/, '').trim()

/** Is the interpretation already said by the summary? (whole text, or the part after "EXCVADDR 0x…: ") */
function saidIn(summary, text) {
  const s = normText(summary)
  const t = normText(text)
  if (!t) return true
  if (s.includes(t)) return true
  const tail = t.includes(': ') ? t.slice(t.indexOf(': ') + 2) : ''
  return Boolean(tail && tail.length > 12 && s.includes(tail))
}

/**
 * "Fix with Hermes" composer draft (never sent): the reason once (the decoder summary), the top frames, only
 * the interpretation the summary does not already say, where the firmware lives (as the agent reads it:
 * `bench_project get → firmware.dir`) and the ask (explain, fix, rebuild, ask before flashing).
 */
export function fixDraftText(project, decode) {
  const r = decode?.result || {}
  const frames = (r.frames || []).slice(0, 3).map(f => `#${f.i} ${f.function} (${f.file}:${f.line})`)
  const fw = project?.firmware || {}
  const port = project?.board?.detected?.port
  const summary = String(decode?.summary || '').trim()
  const headline = summary || `${r.reason || '?'} on core ${r.core ?? '?'}.`
  const extra = (r.interpretation || []).map(x => String(x.text || '').trim()).filter(t => t && !saidIn(summary, t))
  return [
    `Fix ${project?.id ?? 'bench'} panic`,  // first line = session title in sidebar and tab: keep it short
    `Circuit Bench — project "${project?.id ?? '?'}", station 06 DEBUG: the firmware panicked${port ? ` on ${port}${/^sim:/.test(port) ? ' (simulated board)' : ''}` : ''}.`,
    `Panic: ${headline}`,
    frames.length ? `Top frames:\n${frames.join('\n')}` : null,
    extra.length ? `Interpretation: ${extra.join(' ')}` : null,
    fw.dir || fw.env ? `Firmware: bench_project get → firmware.dir${fw.env ? ` (PlatformIO env ${fw.env})` : ''}.` : null,
    'Read the source, explain the cause, propose a fix, rebuild with bench_board, and ask before flashing.'
  ].filter(Boolean).join('\n')
}
