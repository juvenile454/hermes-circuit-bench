// Live bench: jobs (detect/build/flash) tracked over job.updated + GET /jobs/{id}, the serial monitor
// (POST /serial/open on a click → ctx.socket with the mandatory polling fallback, lib/serial.js), panic decode,
// and the workshop actions of stations 02–05. Nothing here runs on its own: detect, flash and the monitor start
// only from a click; after a reload no port is reopened.

const $detect = sdk.atom({ status: 'idle', port: null, env: null })
const $jobNote = sdk.atom({ detect: null, build: null, flash: null, example: null })
const $monitor = sdk.atom({ port: null, status: 'closed', mode: null, opening: false, error: null, epoch: null })
const $flow = sdk.atom({ port: null, focus: null, at: 0 })
const $calcs = sdk.atom({})
const $wire = sdk.atom({ status: 'idle', key: null, env: null, circuit: null })
const $solderPlan = sdk.atom({ status: 'idle', env: null })
// last GET /board/flash/check answer for the open project and the selected port (lib/flash.js flashGate)
const $flashCheck = sdk.atom({ project: null, port: null, env: null })
let FLASH_CHECK_SEQ = 0

const JOB_POLL_MS = 700
// a failed poll (network, backend busy) is retried; job_not_found ends the watch at once
const JOB_RETRY_MS = 2000
const JOB_RETRY_MAX = 30
const JOB_KINDS = ['detect', 'build', 'flash']
const JOB_WATCH = {}
const JOB_SETTLED = new Set()
let MONITOR = null

function timersOf(ctx) {
  return {
    setTimeout: (fn, ms) => (typeof ctx?.setTimeout === 'function' ? ctx.setTimeout(fn, ms) : setTimeout(fn, ms)),
    clearTimeout: t => { if (typeof t === 'function') t(); else clearTimeout(t) }
  }
}

function noteOf(env) {
  return env && !env.ok ? { code: env.error?.code || 'error', message: env.error?.message || env.summary || 'failed', hint: env.error?.hint || null, http: env.http ?? null, at: Date.now() } : null
}

// ─── jobs ──────────────────────────────────────────────────────────────

async function startJob(kind, call) {
  patchAtom($jobNote, { [kind]: null })
  if (kind === 'detect') $detect.set({ status: 'running', port: $flow.get().port, env: null })
  const env = await call()
  if (!env.ok || !env.result?.job_id) {
    patchAtom($jobNote, { [kind]: noteOf(env.ok ? { ok: false, error: { code: 'bad_response', message: 'no job id' } } : env) })
    if (kind === 'detect') patchAtom($detect, { status: 'error', env })
    return env
  }
  applyJob(env.result)
  if (kind !== 'detect') setConsoleTab(kind)
  watchJob(env.result.job_id, kind)
  return env
}

function watchJob(id, kind) {
  const stop = JOB_WATCH[kind]
  if (typeof stop === 'function') stop()
  let misses = 0
  const tick = async () => {
    JOB_WATCH[kind] = null
    const env = await CB.api.job(id)
    if (!env.ok) {
      if (env.error?.code === 'job_not_found') {
        patchAtom($jobNote, { [kind]: { code: 'job_not_found', message: 'The backend restarted; the job is gone.', hint: 'Reload and start it again.', at: Date.now() } })
        patchAtom($jobs, { [kind]: null })
        if (kind === 'detect') patchAtom($detect, { status: 'idle' })
        return
      }
      misses += 1
      if (misses > JOB_RETRY_MAX) {
        patchAtom($jobNote, { [kind]: { ...noteOf(env), message: 'Lost contact with the job. Reload the Bench.', hint: null } })
        return
      }
      JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, JOB_RETRY_MS)
      return
    }
    misses = 0
    applyJob(env.result)
    if (['queued', 'running'].includes(env.result?.state)) JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, JOB_POLL_MS)
  }
  JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, 250)
}

function applyJob(job) {
  if (!job?.job_id || !JOB_KINDS.includes(job.kind)) return
  const cur = $jobs.get()[job.kind]
  if (cur && cur.job_id !== job.job_id && cur.started && job.started && job.started < cur.started) return // an older job
  patchAtom($jobs, { [job.kind]: job })
  if (job.state !== 'done' && job.state !== 'failed') return
  if (JOB_SETTLED.has(job.job_id)) return
  JOB_SETTLED.add(job.job_id)
  const res = job.result
  if (job.kind === 'detect') $detect.set({ status: res?.ok ? 'ready' : 'error', port: res?.result?.port || $detect.get().port, env: res })
  if (res && !res.ok) patchAtom($jobNote, { [job.kind]: noteOf(res) })
  // flashed while the monitor watches that port: the boot log is what matters now
  const mon = $monitor.get()
  if (job.kind === 'flash' && res?.ok && mon.port && monitorActive(mon.port) && (!res.result?.port || res.result.port === mon.port)) setConsoleTab('serial')
  // where the new firmware's output starts in the serial buffer (cleanRunAfter, fix loop)
  if (job.kind === 'flash' && res?.ok) {
    const b = $serial.get().buf
    patchAtom($flow, { flashMark: { elf: res.result?.elf_sha256 || null, port: res.result?.port || null, seq: b.lastSeq || 0, epoch: b.epoch ?? null } })
  }
  const p = $project.get()
  if (p) loadProject(p.id)
  loadPorts()
  if ($nav.get().station === 'flash') refreshFlashCheck()
}

/** Ask the backend whether a flash on the selected port (else the detected one) would be refused. Runs when FLASH
 *  opens, on every project revision, port or settings change (44-station-flash.js) and after each job. */
async function refreshFlashCheck() {
  const p = $project.get()
  if (!p) return null
  const port = $flow.get().port || p.board?.detected?.port || null
  const seq = ++FLASH_CHECK_SEQ
  const env = await CB.api.flashCheck(p.id, port)
  if (seq === FLASH_CHECK_SEQ && $project.get()?.id === p.id) $flashCheck.set({ project: p.id, port, env })
  return env
}

/** job.updated (event payload {job_id, kind, state, progress}) → read the job. */
async function onJobEvent(payload) {
  if (!payload?.job_id) return
  const env = await CB.api.job(payload.job_id)
  if (env.ok) applyJob(env.result)
}

function selectPort(port) {
  patchAtom($flow, { port })
}

function detectBoard(port) {
  const p = $project.get()
  if (!port) return null
  selectPort(port)
  return startJob('detect', () => CB.api.detect({ port, ...(p ? { project: p.id } : {}) }))
}

function buildFirmware() {
  const p = $project.get()
  if (!p) return null
  const det = p.board?.detected?.port
  return startJob('build', () => CB.api.build({ project: p.id, ...(isSimPort(det) ? { port: det } : {}) }))
}

function flashFirmware(confirm) {
  const p = $project.get()
  if (!p || !confirm) return null
  return startJob('flash', () => CB.api.flash({ project: p.id, confirm }))
}

async function useExampleFirmware({ overwrite = false } = {}) {
  const p = $project.get()
  if (!p) return null
  patchAtom($jobNote, { example: null })
  const env = await CB.api.firmwareExample(p.id, overwrite)
  if (env.ok && env.result?.project) {
    applyProject(env.result.project, { prev: p })
    setNotice('Example firmware copied into the project (firmware/).', 'ok')
  } else if (env.error?.code === 'project_conflict' && !overwrite) {
    patchAtom($ui, { modal: { type: 'example-overwrite' } })
  } else {
    patchAtom($jobNote, { example: noteOf(env) })
  }
  return env
}

function setFirmwareDir(dir, env) {
  return patchOps([{ op: 'set_firmware', dir, env }], { okText: 'Firmware folder saved.' })
}

function applyVariant(value) {
  const p = $project.get()
  // set_board knows bare ids only: drop the "?" of an unverified guess ("n16r8?" → "n16r8")
  const variant = bareVariant(value)
  if (!p || !variant) return null
  const b = boardOf(p)
  return patchOps([{ op: 'set_board', chip: b.chip, variant, devkit: b.devkit, wifi: b.wifi }], { okText: `Module variant ${String(variant).toUpperCase()} saved to the project.` })
}

// ─── serial monitor ────────────────────────────────────────────────────

/** Open the monitor; reset: pulse EN through RTS with IO0 released (the firmware restarts from flash; this also
 *  leaves the ROM download mode a board stays in after a flash or BOOT). Only on a click. */
async function openMonitor(port, { reset = false } = {}) {
  if (!port || $monitor.get().opening) return null
  patchAtom($monitor, { opening: true, error: null })
  const p = $project.get()
  const env = await CB.api.serialOpen({ port, ...(p ? { project: p.id } : {}), ...(reset ? { reset: true } : {}) })
  if (!env.ok) {
    patchAtom($monitor, { opening: false, error: noteOf(env) })
    return env
  }
  patchAtom($monitor, { port, status: env.result?.state || 'open', opening: false, error: null, epoch: env.result?.epoch ?? null })
  setConsoleTab('serial') // the live log is what the click asked for
  startStream(port)
  return env
}

const SERIAL_FLUSH_MS = 150 // at most ~7 store updates per second from the serial stream

function stopStream() {
  if (!MONITOR) return
  MONITOR.stop()
  MONITOR.coalesce?.cancel()
  MONITOR = null
}

function startStream(port) {
  stopStream()
  const cur = $serial.get()
  let lastEpoch = cur.port === port ? cur.buf.epoch : null
  const fixtures = CB.api.mode === 'fixtures'
  MONITOR = createSerialClient({
    port,
    socket: fixtures || typeof CB.ctx?.socket !== 'function' ? null : (path, fn) => CB.ctx.socket(path, fn),
    tail: (pt, after) => CB.api.serialTail(pt, after),
    timers: timersOf(CB.ctx),
    seq: { mergeLines, emptyBuffer },
    initial: cur.port === port ? cur.buf : null,
    onUpdate: u => { if (!MONITOR || MONITOR.port === port) coalesce.push(u) }
  })
  const coalesce = coalescer(timersOf(CB.ctx), SERIAL_FLUSH_MS, u => {
      if (!MONITOR || MONITOR.port !== port) return
      $serial.set({ port, buf: u.buf, status: u.state || (u.mode === 'stopped' ? 'closed' : 'open'), note: u.error, mode: u.mode, simulated: u.simulated })
      patchAtom($monitor, { mode: u.mode, status: u.mode === 'stopped' ? 'closed' : u.state || 'open' })
      if (u.buf.epoch && lastEpoch && u.buf.epoch !== lastEpoch) {
        // backend restarted: jobs and broker are new, reload project and ports
        const p = $project.get()
        if (p) loadProject(p.id)
        loadPorts()
      }
      lastEpoch = u.buf.epoch || lastEpoch
      watchSerialPanic(u.buf)
  })
  MONITOR.port = port
  MONITOR.coalesce = coalesce
  MONITOR.start()
}

async function closeMonitor() {
  const port = $monitor.get().port
  stopStream()
  patchAtom($monitor, { status: 'closed', mode: null, opening: false })
  patchAtom($serial, { status: 'closed', mode: null })
  if (port) await CB.api.serialClose(port)
}

function monitorActive(port) {
  return Boolean(MONITOR && MONITOR.port === port)
}

/** Decode the newest current panic once (a reboot loop announces one per boot; only the latest is decoded). */
function watchSerialPanic(buf) {
  const pn = buf?.panic
  if (!pn?.log_ref || !serialPanicLive(buf, $project.get())) return
  if (!panicNeedsDecode($panic.get(), pn, $project.get()?.firmware?.last_flash?.at ?? null)) return
  if ($panic.get().status === 'loading') {
    CB.pendingPanic = pn
    return
  }
  decodePanic(pn).then(() => {
    const next = CB.pendingPanic
    CB.pendingPanic = null
    if (next && next.log_ref !== $panic.get().key) watchSerialPanic({ ...$serial.get().buf, panic: next })
  })
}

// ─── workshop: calc, wire, solder, projects, doctor ────────────────────

async function runCalc(type, body) {
  patchAtom($calcs, { [type]: { status: 'loading', env: $calcs.get()[type]?.env || null, body } })
  const env = await CB.api.calc(type, body)
  patchAtom($calcs, { [type]: { status: env.ok ? 'ready' : 'error', env, body } })
  return env
}

function addCalcToProject(type) {
  const p = $project.get()
  const env = $calcs.get()[type]?.env
  if (!p || !env?.ok) return null
  const { id, ops, parts } = calcOps(type, env, p)
  return patchOps(ops, { okText: `${id} saved${parts.length ? ` with ${parts.map(x => `${x.ref} ${x.value}`).join(', ')}` : ''}.` })
}

async function renderSchematic(block, params, { circuit = null, gpio = null } = {}) {
  const p = $project.get()
  const key = JSON.stringify([block, params, gpio])
  $wire.set({ status: 'loading', key, env: $wire.get().env, circuit })
  const env = await CB.api.schematic({ block, params, ...(p ? { project: p.id } : {}), ...(Number.isInteger(gpio) ? { gpio } : {}) })
  if ($wire.get().key === key) $wire.set({ status: env.ok ? 'ready' : 'error', key, env, circuit })
  return env
}

function removePartsFromProject(refs) {
  return patchOps([{ op: 'remove_parts', refs }], { okText: `Removed ${refs.join(', ')} from the project.` })
}

function addCircuitToProject(id, block, params) {
  return patchOps([{ op: 'add_circuit', circuit: { id, block, params } }], { okText: `Circuit ${id} saved to the project.` })
}

async function planSolder(bomText = null) {
  const p = $project.get()
  if (!p) return null
  $solderPlan.set({ status: 'loading', env: null })
  const env = await CB.api.solderPlan({ project: p.id, ...(bomText ? { bom: bomText } : {}) })
  $solderPlan.set({ status: env.ok ? 'ready' : 'error', env })
  if (env.ok) await loadProject(p.id)
  else setNotice(env.error?.message || env.summary || 'The solder plan failed.', 'bad')
  return env
}

async function toggleSolderStep(stepId, done) {
  const p = $project.get()
  if (!p) return null
  const env = await CB.api.solderStep(p.id, stepId, done)
  if (env.ok && env.result?.project) applyProject(env.result.project, { prev: p })
  else setNotice(env.error?.message || 'The check mark was not saved.', 'bad')
  return env
}

async function createProject(form) {
  const env = await CB.api.createProject(form)
  if (env.ok) {
    await loadBench({ projectId: form.id })
    goStation('plan', form.id)
  }
  return env
}

/** Project manager (HUD project pill, palette): refresh the list, open another project, move one to the trash. */
async function refreshProjects() {
  const env = await CB.api.projects()
  if (env.ok) patchAtom($bench, { projects: env.result?.projects || [] })
  return env
}

async function openProject(id) {
  if (!id || $project.get()?.id === id) return null
  await loadBench({ projectId: id })
  return $project.get()
}

async function removeProject(id) {
  const env = await CB.api.deleteProject(id)
  if (!env.ok) return env
  forgetProject(id)
  return env
}

/** A project is gone (deleted here or elsewhere): drop it from the list; if it was open, open the next one. */
function forgetProject(id) {
  if (stored('lastProject', null) === id) store('lastProject', null)
  patchAtom($bench, { projects: ($bench.get().projects || []).filter(p => p.id !== id) })
  if ($project.get()?.id === id) {
    resetProjectScoped()
    $project.set(null)
    patchAtom($nav, { project: null })
    loadBench()
  }
}

/** Per-project results of the stations (calculator answers, drawn schematic, solder plan preview, pin info) and
 *  of the finished jobs (their log, detect result, notes). Running jobs stay; the last panic belongs to the board. */
function resetProjectScoped() {
  $calcs.set({})
  $wire.set({ status: 'idle', key: null, env: null, circuit: null })
  $solderPlan.set({ status: 'idle', env: null })
  $suggest.set({ status: 'idle', env: null, role: null })
  $info.set({ status: 'idle', gpio: null, env: null })
  $flashCheck.set({ project: null, port: null, env: null })
  $notices.set([])
  const jobs = $jobs.get()
  const live = j => Boolean(j) && j.state !== 'done' && j.state !== 'failed'
  $jobs.set(Object.fromEntries(Object.entries(jobs).map(([k, j]) => [k, live(j) ? j : null])))
  if (!live(jobs.detect) && $detect.get().status !== 'running') $detect.set({ status: 'idle', port: null, env: null })
  $jobNote.set({ detect: null, build: null, flash: null, example: null })
}

async function runDoctor() {
  patchAtom($ui, { modal: { type: 'doctor', env: null } })
  const env = await CB.api.doctor()
  if ($ui.get().modal?.type === 'doctor') patchAtom($ui, { modal: { type: 'doctor', env } })
  return env
}

/** Open the Agent settings (config_schema form) of the plugin. */
function openAgentSettings() {
  sdk.host?.navigate?.('/settings?tab=plugins&agent=circuit-bench')
}
