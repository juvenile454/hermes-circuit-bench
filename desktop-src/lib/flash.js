// Station 05 FLASH helpers: port list (never opens anything), detection summary, flash confirmation object, job
// progress text. Pure.

const PORT_KIND_LABEL = {
  usb_serial_jtag: 'USB-Serial/JTAG', usb_cdc_app: 'USB CDC (app)', cp210x: 'CP210x', ch340: 'CH340', ch343: 'CH343',
  ch9102: 'CH9102', ftdi: 'FTDI', unknown: 'serial', sim: 'simulated'
}

/**
 * Rows for the port list: real ports first (likely ESP boards on top), simulated ports below, each marked.
 * Only describes; detection and the monitor start on a click.
 */
export function portRows(ports, { detectedPort = null, selected = null } = {}) {
  const list = Array.isArray(ports) ? ports.filter(p => p && typeof p.device === 'string') : []
  const real = list.filter(p => !p.simulated).sort((a, b) => Number(Boolean(b.likely_esp)) - Number(Boolean(a.likely_esp)))
  const sim = list.filter(p => p.simulated)
  return [...real, ...sim].map(p => ({
    device: p.device,
    simulated: Boolean(p.simulated),
    label: p.simulated ? 'SIMULATED' : p.likely_esp ? 'ESP' : 'SERIAL',
    kind: PORT_KIND_LABEL[p.kind] || p.kind || 'serial',
    description: p.description || '',
    detected: p.device === detectedPort,
    selected: p.device === selected,
    noAutoReset: p.kind === 'usb_cdc_app'
  }))
}

/** Default port for the station: the detected one if still listed, else the first ESP-like real port, else sim. */
export function defaultPort(ports, detectedPort = null) {
  const rows = portRows(ports, { detectedPort })
  return rows.find(r => r.detected)?.device || rows.find(r => !r.simulated && r.label === 'ESP')?.device || rows.find(r => r.simulated)?.device || null
}

export function isSimPort(port) {
  return typeof port === 'string' && port.startsWith('sim://')
}

/**
 * Confirmation of the flash dialog: {port, mac, elf_sha256} from project.board.detected and
 * project.firmware.last_build (the flash route compares exactly these). `buildJob` (done) may be newer than
 * the project copy in the UI. → {ok, confirm, missing: [..], stale}
 */
export function flashConfirm(project, buildJob = null) {
  const det = project?.board?.detected || null
  let build = project?.firmware?.last_build || null
  const jobRes = buildJob?.state === 'done' ? buildJob.result?.result : null
  if (jobRes?.elf_sha256 && buildJob.result?.ok && (!build?.at || !buildJob.finished || buildJob.finished >= build.at)) {
    build = { ok: true, elf_sha256: jobRes.elf_sha256, at: buildJob.finished, ram_pct: jobRes.ram_pct, flash_pct: jobRes.flash_pct }
  }
  const missing = []
  if (!det?.port) missing.push('detect')
  if (!det?.mac) missing.push('mac')
  if (!build || build.ok !== true || !build.elf_sha256) missing.push('build')
  const confirm = missing.length ? null : { port: det.port, mac: String(det.mac).toLowerCase(), elf_sha256: String(build.elf_sha256).toLowerCase() }
  const flash = project?.firmware?.last_flash
  return {
    ok: !missing.length,
    confirm,
    missing,
    simulated: isSimPort(det?.port),
    alreadyFlashed: Boolean(confirm && flash?.ok && flash.elf_sha256 === confirm.elf_sha256 && flash.port === confirm.port)
  }
}

/** GET /board/flash/check → {state: ready | locked | unknown, code, message, hint}. Reads the answer
 *  only (the backend decides); no answer or an error envelope is `unknown`, never a lock. */
export function flashGate(env) {
  const r = env && env.ok === true ? env.result : null
  if (!r || typeof r.ready !== 'boolean') return { state: 'unknown', code: null, message: null, hint: null }
  if (r.ready) return { state: 'ready', code: null, message: null, hint: null }
  const f = r.refusal || {}
  return { state: 'locked', code: f.code || 'refused', message: f.message || env.summary || 'flashing would be refused', hint: f.hint || null }
}

/** Job object → {state, pct (0..100|null), indeterminate, text, done, failed}. pio reports no percentage. */
export function jobProgress(job) {
  if (!job) return { state: 'none', pct: null, indeterminate: false, text: '', done: false, failed: false, running: false }
  const state = job.state
  const running = state === 'queued' || state === 'running'
  const pct = typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.round(Math.max(0, Math.min(1, job.progress)) * 100) : null
  const failed = state === 'failed' || (state === 'done' && job.result && job.result.ok === false)
  const text = state === 'queued' ? 'queued…' : state === 'running' ? (pct === null ? 'running…' : `${pct} %`)
    : failed ? 'failed' : state === 'done' ? 'done' : String(state || '')
  return { state, pct: running ? pct : state === 'done' ? 100 : pct, indeterminate: running && pct === null, text, done: state === 'done' && !failed, failed, running }
}

/** Error of a finished job (or a refused start) as {code, message, hint}. */
export function jobError(envOrJob) {
  const env = envOrJob?.result && 'job_id' in (envOrJob.result || {}) ? envOrJob.result.result : envOrJob?.job_id ? envOrJob.result : envOrJob
  if (!env || env.ok !== false) return null
  return { code: env.error?.code || 'failed', message: env.error?.message || env.summary || 'failed', hint: env.error?.hint || null }
}

/** Module variant id without the trailing "?" that marks an unverified guess ("n16r8?" → "n16r8"); null if empty.
 *  set_board only knows bare ids. */
export function bareVariant(v) {
  if (typeof v !== 'string') return null
  return v.trim().replace(/\?+$/, '').trim().toLowerCase() || null
}

/** Detection result (board.detect result) → compact rows + whether the variant differs from the project.
 *  A real board's guess ends in "?" (esptool cannot tell octal from quad PSRAM): `suggestion` is the bare id,
 *  `unverified` keeps the mark. */
export function detectSummary(res, project) {
  if (!res) return null
  const raw = typeof res.variant_suggestion === 'string' ? res.variant_suggestion.trim() : ''
  const suggestion = bareVariant(raw)
  const want = bareVariant(project?.board?.variant)
  return {
    port: res.port || null,
    chip: res.chip || '—',
    mac: res.mac || '—',
    flash: res.flash_size ? String(res.flash_size).replace(/(\d)\s*([KMG]B)\b/, '$1 $2') : '—',
    psram: res.psram_mb ? `${res.psram_mb} MB` : res.features?.some?.(f => /PSRAM/i.test(f)) ? 'yes' : 'none',
    usb: res.usb_mode || null,
    features: Array.isArray(res.features) ? res.features : [],
    suggestion,
    unverified: Boolean(suggestion && raw.endsWith('?')),
    variantDiffers: Boolean(suggestion && want && suggestion !== want),
    simulated: Boolean(res.simulated)
  }
}

// ─── What the dialog and the station draw (pure; nothing is estimated) ──────────────────────────

/** A 64-digit SHA-256 in eight groups of eight (for reading aloud and comparing); anything else unchanged in one
 *  group, nothing → []. The groups join back to the input (the dialog text keeps the hash contiguous). */
export function flashHashGroups(hex) {
  const s = String(hex ?? '').trim()
  if (!s) return []
  return /^[0-9a-fA-F]{64}$/.test(s) ? s.match(/.{8}/g) : [s]
}

/** RAM/flash rows of a build: [{id, label, pct, used, total}] for every delivered percentage. Bytes only from a build
 *  job result of the same ELF (the project record keeps percentages only). */
export function flashMemRows(build, jobResult = null) {
  if (!build || build.ok !== true) return []
  const same = Boolean(jobResult && jobResult.elf_sha256 && jobResult.elf_sha256 === build.elf_sha256)
  const num = v => typeof v === 'number' && Number.isFinite(v) ? v : null
  return [['ram', 'RAM'], ['flash', 'Flash']].flatMap(([id, label]) => {
    const pct = num(build[`${id}_pct`])
    if (pct === null) return []
    const used = same ? num(jobResult[`${id}_used`]) : null
    const total = same ? num(jobResult[`${id}_total`]) : null
    return [{ id, label, pct, used: used !== null && total ? used : null, total: used !== null && total ? total : null }]
  })
}

/** Check list of the flash dialog in words. Each row: {id, state: 'match'|'differs'|'unchecked', word, text, at?}.
 *  Compares the confirmation (what the backend checks) with the detection and the last build. */
export function flashCheckRows(confirm, project) {
  const det = project?.board?.detected || {}
  const b = project?.firmware?.last_build || {}
  const cmp = (a, c) => (!a || !c ? 'unchecked' : String(a).toLowerCase() === String(c).toLowerCase() ? 'match' : 'differs')
  const word = { match: 'match', differs: 'differs', unchecked: 'not compared' }
  const port = cmp(det.port, confirm?.port)
  const mac = cmp(det.mac, confirm?.mac)
  const elf = cmp(b.ok ? b.elf_sha256 : null, confirm?.elf_sha256)
  return [
    { id: 'port', state: port, word: word[port],
      text: port === 'match' ? 'Port matches the detection' : port === 'differs' ? 'Port differs from the detection' : 'Port not compared: no detection' },
    { id: 'mac', state: mac, word: word[mac],
      text: mac === 'match' ? 'MAC matches the detected board' : mac === 'differs' ? 'MAC differs from the detected board' : 'MAC not compared: no detected MAC' },
    { id: 'elf', state: elf, word: word[elf], at: elf === 'match' ? b.at || null : null,
      text: elf === 'match' ? 'Firmware hash matches the last build' : elf === 'differs' ? 'Firmware hash differs from the last build' : 'Firmware hash not compared: no successful build' }
  ]
}

// last log line → phase word (esptool 4.x/5.x and PlatformIO wording; the newest matching line wins)
const FLASH_PHASES = {
  flash: [[/Hard resetting|Leaving\.\.\.|Resetting/i, 'resetting'], [/Hash of data verified/i, 'verifying'],
    [/Writing at|Wrote \d+ bytes/i, 'writing'], [/Flash will be erased|Erasing|Compressed \d+ bytes/i, 'preparing'],
    [/Connecting|Detecting chip|Chip is|Chip type|Uploading stub|Stub (?:flasher )?running|Changing baud/i, 'connecting']],
  build: [[/Building .*\.bin|Creating .*image/i, 'making image'], [/Checking size|Retrieving maximum/i, 'checking size'],
    [/Linking/i, 'linking'], [/Compiling|Archiving/i, 'compiling'], [/Processing|Tool Manager|Installing|Resolving/i, 'preparing']],
  detect: [[/Hard resetting|Leaving/i, 'resetting'], [/MAC:|Crystal|Features|Chip is|Chip type/i, 'reading chip'],
    [/Connecting|Detecting chip/i, 'connecting']]
}
const FLASH_PHASE_DEFAULT = { flash: 'flashing', build: 'building', detect: 'detecting' }

/** Phase word of a running job from its log tail: {word, pct (0..100|null)}; null when the job does not run. */
export function flashJobPhase(job) {
  if (!job || (job.state !== 'queued' && job.state !== 'running')) return null
  const pct = typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.round(Math.max(0, Math.min(1, job.progress)) * 100) : null
  if (job.state === 'queued') return { word: 'queued', pct: null }
  const rules = FLASH_PHASES[job.kind] || []
  const tail = Array.isArray(job.log_tail) ? job.log_tail : []
  for (let i = tail.length - 1; i >= 0; i--) {
    const hit = rules.find(([re]) => re.test(String(tail[i] ?? '')))
    if (hit) return { word: hit[1], pct }
  }
  return { word: FLASH_PHASE_DEFAULT[job.kind] || 'running', pct }
}

/** Marks of the flash map: the written images (board.flash result.images: [{offset, name, sha256}]) on an address
 *  axis from 0 to just past the highest offset. Offsets and names only, no sizes. No images → null. */
export function flashMapMarks(images) {
  if (!Array.isArray(images) || !images.length) return null
  const marks = images.filter(im => im && /^0x[0-9a-f]+$/i.test(String(im.offset ?? '')) && im.name)
    .map(im => ({ offset: String(im.offset).toLowerCase(), addr: parseInt(im.offset, 16), name: String(im.name), sha256: im.sha256 ? String(im.sha256) : null }))
    .sort((a, b) => a.addr - b.addr)
  if (!marks.length) return null
  const max = marks[marks.length - 1].addr
  const span = max > 0 ? max * 1.12 : 1
  return { marks: marks.map((m, i) => ({ ...m, n: i + 1, frac: Math.round((m.addr / span) * 10000) / 10000 })), highest: marks[marks.length - 1].offset }
}

// port kind (board.ports) → kind of the board's usb[] interface it arrives on
const FLASH_PORT_USB = { usb_serial_jtag: 'usb_serial_jtag', cp210x: 'usb_uart_bridge', ch340: 'usb_uart_bridge', ch343: 'usb_uart_bridge',
  ch9102: 'usb_uart_bridge', ftdi: 'usb_uart_bridge' }

/** Connector to draw beside a port (same artPort kinds as the board model): only for the real port the project's
 *  board was detected on, whose kind leads to exactly one usb[] entry of the board with a drawn usb_port. connector
 *  null in the board data → 'generic_usb' (the board model's generic jack). Anything unknown → null (nothing drawn). */
export function flashPortConnector(port, layout, detectedPort) {
  if (!port || port.simulated || !detectedPort || port.device !== detectedPort) return null
  const want = FLASH_PORT_USB[port.kind]
  const usb = Array.isArray(layout?.usb) ? layout.usb.filter(u => u && u.kind === want) : []
  if (!want || usb.length !== 1) return null
  const parts = Array.isArray(layout?.drawing?.parts) ? layout.drawing.parts : []
  const part = parts.filter(p => p && p.kind === 'usb_port' && p.ref === usb[0].label)
  if (part.length !== 1) return null
  const c = part[0].connector
  return c === 'micro_usb' || c === 'usb_c' ? c : c === null || c === undefined ? 'generic_usb' : null
}
