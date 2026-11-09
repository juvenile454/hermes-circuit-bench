// PanicCard: stamp PANIC CAUGHT, reason, frames (#0 red), interpretation, Fix with Hermes / Open.
// Page console outside 06 DEBUG: PanicStrip.
// Shown while a panic is current: the serial stream shows no reboot into other firmware after it, or the project's
// stored panic is newer than the last successful flash (lib/crash.js, lib/serial.js).

function usePanicData(project) {
  const panic = sdk.useValue($panic)
  const serial = sdk.useValue($serial)
  const serialLive = serial.port && serial.buf.panic ? serialPanicLive(serial.buf, project) : false
  const projectLive = projectPanicCurrent(project)
  const live = serialLive || projectLive
  const last = project?.debug?.last_panic || null
  // a decode belongs to the serial panic it was made for, or to the stored panic (same log_ref)
  const env = panic.env?.ok && (panic.key === serial.buf.panic?.log_ref || panic.key === last?.log_ref || !last?.log_ref) ? panic.env : null
  const data = live ? panicCardData(env, projectLive ? last : null, serialLive ? serial.buf.panic : null) : null
  return { data, env, status: panic.status, live }
}

/** "Open src/main.cpp:44": reveal the source file of frame #0 in the file manager (ctx.os.revealPath).
 *  Only project-relative paths inside the firmware folder; core paths (~/.platformio, /…) are never opened. */
function sourceTarget(project, top) {
  const fwDir = project?.firmware?.dir || null
  const show = Boolean(top && top.file && top.file !== '??')
  const rel = show && !/^~|^\//.test(top.file) && !/(^|\/)\.\.(\/|$)/.test(top.file)
  const can = Boolean(rel && fwDir && typeof CB.ctx?.os?.revealPath === 'function')
  return { show, can, path: can ? `${fwDir.replace(/\/$/, '')}/${top.file}` : null, label: show ? `Open ${top.file}:${top.line ?? '?'}` : '',
    title: can ? `Show ${top.file} in the file manager` : !rel ? 'Only files inside the project firmware folder open from here' : 'Firmware folder unknown' }
}

async function openSource(src) {
  if (!src?.can) return false
  const ok = await CB.ctx.os.revealPath(src.path)
  if (ok === false) sdk.host?.notify?.({ kind: 'warning', title: 'Could not show the file', message: src.path })
  return ok !== false
}

async function fixWithHermes(project, data, env) {
  patchAtom($flow, { fixDraftAt: Date.now() })
  const decode = env || { summary: data?.summary || '', result: { reason: data?.reason, core: data?.core, frames: (data?.frames || []).map(f => ({ i: f.i, function: f.fn, file: f.file, line: f.line })) } }
  return composeDraft(fixWithHermesText(project, decode))
}

// Frame ↔ log coupling: a hovered or focused frame / register marks its address in the raw
// panic lines of the console log (lib/crash.js logMarkRanges). One mark for every surface; null = none.
const $logMark = sdk.atom(null)

function setLogMark(mark) {
  const cur = $logMark.get()
  if (!mark) { if (cur) $logMark.set(null); return }
  if (cur && cur.kind === mark.kind && cur.value === mark.value && cur.name === mark.name) return
  $logMark.set(mark)
}

/** Handlers for an element that marks `mark` in the log while hovered or focused. */
function logMarkProps(mark) {
  if (!mark?.value) return {}
  return { onMouseEnter: () => setLogMark(mark), onMouseLeave: () => setLogMark(null), onFocus: () => setLogMark(mark), onBlur: () => setLogMark(null) }
}

const frameMark = f => (f?.pc ? { kind: 'pc', value: f.pc } : null)

/** ELF check of the decode as text pieces (verdict, then the reason right behind it). */
function elfWords(elf) {
  return elf ? { sym: elf.symbol, word: elf.word || elf.status, reason: elf.reason || elf.detail || '' } : null
}

function PanicCard({ project }) {
  const { data, env, status } = usePanicData(project)
  const [busy, setBusy] = useState(false)
  if (!data) return null
  const src = sourceTarget(project, data.top)
  const fix = async () => {
    setBusy(true)
    try { await fixWithHermes(project, data, env) } finally { setBusy(false) }
  }
  return h('div', { className: 'cb-panic', 'data-cb': 'panic-card', 'data-cb-audit-root': 'panic', role: 'region', 'aria-label': 'Panic' },
    h('div', { className: 'cb-alarm' },
      h(Stamp, { tone: 'bad' }, 'PANIC CAUGHT'),
      h('span', { className: 'cb-bad' }, data.title),
      data.elf ? h('span', { className: `cb-elf cb-elf--${data.elf.tone}`, 'data-cb': 'elf-check', 'data-cb-status': data.elf.status, title: `elf check ${data.elf.word || data.elf.status} · ${data.elf.reason || data.elf.detail || ''}` },
        h('span', { 'aria-hidden': 'true' }, data.elf.symbol), ` elf ${elfWords(data.elf).word}`)
        : h(Label, null, status === 'loading' ? 'decoding…' : 'not decoded')),
    // no SIM tag of its own: the console bar beside the card carries the SIM badge
    data.frames.length ? h('div', { className: 'cb-frames', 'data-cb': 'panic-frames' }, data.frames.slice(0, 3).map((f, i) =>
      h('div', { key: f.i ?? i, className: `cb-frame${i === 0 ? ' cb-frame--top' : ''}`, title: `${f.pc} ${f.fn} — ${f.file}:${f.line ?? '?'}`,
        tabIndex: f.pc ? 0 : undefined, 'data-cb': `panic-card-frame-${f.i ?? i}`, ...logMarkProps(frameMark(f)) },
        h('span', { className: 'cb-i' }, `#${f.i ?? i}`), h('span', { className: 'cb-f' }, f.short),
        h('span', { className: 'cb-l' }, `${f.base}:${f.line ?? '?'}`)))) : null,
    data.interpretation.slice(-1).map(x => h('div', { key: x.code, className: 'cb-hint cb-panic-hint', style: { marginTop: 0 },
      title: [x.text, data.resetReason?.name ? `reset reason: ${data.resetReason.name} (${data.resetReason.code}, ${String(data.resetReason.when || '').replace(/_/g, ' ')})` : null].filter(Boolean).join('\n') }, x.text)),
    h('div', { className: 'cb-row cb-panic-actions' },
      h(Btn, { kind: 'agent', size: 'sm', onClick: fix, disabled: busy, 'data-cb': 'fix-with-hermes', title: 'Put a fix request into the chat composer (not sent)' }, busy ? 'Opening chat…' : 'Fix with Hermes'),
      src.show ? h(Btn, { kind: 'quiet', size: 'sm', disabled: !src.can, 'data-cb': 'open-source', title: src.title,
        onClick: () => openSource(src) }, `Open ${data.top.base}:${data.top.line ?? '?'}`) : null))
}

/** One-line panic strip, no agent button. Keeps data-cb=panic-card + .cb-panic-actions (smoke). */
function PanicStrip({ project }) {
  const { data } = usePanicData(project)
  if (!data) return null
  const top = data.top
  const at = top ? `${top.base}:${top.line ?? '?'}` : null
  return h('div', { className: 'cb-panicstrip', 'data-cb': 'panic-card', 'data-cb-form': 'strip', 'data-cb-audit-root': 'panic', role: 'status',
    'aria-label': `Panic: ${data.title}${at ? ` at ${at}` : ''}` },
  h('span', { className: 'cb-panicstrip-mark' }, h('span', { 'aria-hidden': 'true' }, '▲ '), 'PANIC'),
  h('span', { className: 'cb-panicstrip-t', title: [data.title, top ? `${top.fn} — ${top.file}:${top.line ?? '?'}` : ''].filter(Boolean).join('\n'), 'data-cb-truncate-ok': 'true' }, data.title,
    top ? h('span', { className: 'cb-panicstrip-at' }, ` · ${top.short} · ${at}`) : null),
  h('div', { className: 'cb-panic-actions' },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'panic-open-debug', title: 'Open 06 DEBUG: frames, registers, Fix with Hermes',
      onClick: () => goStation('debug') }, 'Open Debug ›')))
}
