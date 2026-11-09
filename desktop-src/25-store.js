// Store: module-wide sdk.atom state shared by every mounted surface (page, workspace tile, pane, status chip),
// actions that talk to the API, gateway events `plugin.circuit-bench.*` and the 3 s polling fallback.

const $nav = sdk.atom({ project: null, station: 'plan', n: 0 })
const $bench = sdk.atom({ phase: 'idle', error: null, health: null, projects: [], projectId: null, mode: 'live' })
const $project = sdk.atom(null)
const $board = sdk.atom({ status: 'idle', id: null, layout: null, error: null, sources: [] })
const $view = sdk.atom({ chip: null, variant: null, devkit: null, wifi: true, selected: null, variantPicked: false })
const $check = sdk.atom({ status: 'idle', key: null, env: null })
const $map = sdk.atom({ status: 'idle', key: null, env: null })
const $info = sdk.atom({ status: 'idle', gpio: null, env: null })
const $suggest = sdk.atom({ status: 'idle', env: null, role: null })
const $ports = sdk.atom({ status: 'idle', ports: [], error: null })
const $serial = sdk.atom({ port: null, buf: emptyBuffer(), status: 'idle', note: null, mode: null, simulated: null })
const $jobs = sdk.atom({ detect: null, build: null, flash: null })
const $panic = sdk.atom({ status: 'idle', env: null, key: null, summary: null, flashAt: null })
const $pulse = sdk.atom({ pins: [], roles: [], at: 0 })
// the Bench's notice zone (30-ui-bench.js NoticeZone): [{id, text, tone ok|info|warn|bad, at}]
const $notices = sdk.atom([])
const $ui = sdk.atom({ tab: 'serial', cons: 'open', consPinned: false, paneOpen: false, modal: null, look: 'phosphor', panicSeen: null, showTs: true,
  celebrated: null, sweepAt: 0 })

const CB = { ctx: null, api: null, mounts: 0, lastEventAt: 0, polling: false, offlineUntil: 0, paneDispose: null, tileClose: null }

function patchAtom(atom, patch) {
  atom.set({ ...atom.get(), ...patch })
}

function store(key, value) {
  try { CB.ctx?.storage?.set?.(key, value) } catch { /* storage is best effort */ }
}

function stored(key, fallback) {
  try { return CB.ctx?.storage?.get?.(key, fallback) ?? fallback } catch { return fallback }
}

const NOTICE_MAX = 3
let NOTICE_N = 0
const noticeFades = n => n.tone === 'ok' || n.tone === 'info'

/** A notice in the zone: ok/info fade after 3 s, warn/bad stay until ✕. The same text again replaces the old one;
 *  at most three, the oldest fading one goes first. */
function setNotice(text, tone = 'info') {
  if (!text) return
  const list = $notices.get().filter(n => !(n.text === text && n.tone === tone))
  list.push({ id: ++NOTICE_N, text: String(text), tone, at: Date.now() })
  while (list.length > NOTICE_MAX) {
    const i = list.findIndex(noticeFades)
    list.splice(i >= 0 ? i : 0, 1)
  }
  $notices.set(list)
}

function dropNotices(pred) {
  const list = $notices.get()
  const keep = list.filter(n => !pred(n))
  if (keep.length !== list.length) $notices.set(keep)
}

/** Board settings the PLAN station checks against: the what-if view or the project's own board. */
function boardOf(project) {
  return {
    chip: project?.board?.chip ?? null,
    variant: project?.board?.variant ?? null,
    devkit: project?.board?.devkit ?? null,
    wifi: project?.options?.wifi !== false
  }
}

function viewBoard() {
  const v = $view.get()
  const chip = chipInfo(v.chip)
  // the DevKit of the view when it belongs to the chip (ESP32: DevKitC V4 or WT32-ETH01), else the chip default
  return { chip: v.chip, variant: chip?.variants.length ? v.variant : null, wifi: Boolean(v.wifi), devkit: resolveDevkit(v.chip, v.devkit) }
}

function isWhatIf() {
  const p = $project.get()
  if (!p) return false
  const b = boardOf(p)
  const v = viewBoard()
  return b.chip !== v.chip || (b.variant ?? null) !== (v.variant ?? null) || b.wifi !== v.wifi || resolveDevkit(b.chip, b.devkit) !== v.devkit
}

function initStore(ctx) {
  CB.ctx = ctx
  CB.api = createApi(ctx)
  patchAtom($bench, { mode: CB.api.mode })
  const station = stored('lastStation', 'plan')
  $nav.set({ project: stored('lastProject', null), station: isStation(station) ? station : 'plan', n: 0 })
  patchAtom($ui, {
    cons: stored('console', 'open') === 'collapsed' ? 'collapsed' : 'open',
    look: stored('look', 'phosphor') === 'theme' ? 'theme' : 'phosphor',
    panicSeen: stored('panicSeen', null),
    celebrated: stored('celebrated', null),
    showTs: stored('timestamps', true) !== false,
    tab: ['serial', 'build', 'flash'].includes(stored('consoleTab', 'serial')) ? stored('consoleTab', 'serial') : 'serial'
  })
  const ev = (name, fn) => ctx.onEvent(`plugin.${PLUGIN_ID}.${name}`, e => {
    CB.lastEventAt = Date.now()
    try { fn(e?.payload ?? e?.data ?? e ?? {}) } catch (err) { console.warn('[circuit-bench] event handler', name, err) }
  })
  ev('project.updated', onProjectUpdated)
  ev('board.changed', () => loadPorts())
  ev('job.updated', onJobUpdated)
  ev('panic.detected', e => { if (!monitorActive(e?.port)) loadSerial({ fresh: false }) })
  ctx.setInterval(pollTick, 3000)
  loadPorts()
}

// ─── loading ───────────────────────────────────────────────────────────

let loadSeq = 0

async function loadBench({ projectId = null } = {}) {
  const my = ++loadSeq
  patchAtom($bench, { phase: 'loading', error: null })
  const health = await CB.api.health()
  if (my !== loadSeq) return
  if (!health.ok) {
    patchAtom($bench, { phase: 'error', error: health, health: null })
    CB.offlineUntil = Date.now() + 30_000
    return
  }
  loadPorts()
  const list = await CB.api.projects()
  if (my !== loadSeq) return
  if (!list.ok) {
    patchAtom($bench, { phase: 'error', error: list, health: health.result })
    return
  }
  const projects = list.result?.projects || []
  patchAtom($bench, { health: health.result, projects })
  if (!projects.length) {
    $project.set(null)
    patchAtom($bench, { phase: 'empty', projectId: null })
    return
  }
  const wanted = projectId || $nav.get().project || stored('lastProject', null)
  const id = projects.some(p => p.id === wanted) ? wanted : projects[0].id
  await loadProject(id, { initial: true })
  if (my !== loadSeq) return
  patchAtom($bench, { phase: $project.get() ? 'ready' : 'error' })
  loadSerial({ fresh: true })
}

function ensureBench() {
  const phase = $bench.get().phase
  if (phase === 'idle') loadBench()
}

async function loadProject(id, { initial = false, pulse = false } = {}) {
  const env = await CB.api.project(id)
  if (!env.ok) {
    if (initial) patchAtom($bench, { phase: 'error', error: env })
    else setNotice(env.error?.message || 'Could not reload the project.', 'bad')
    return null
  }
  const prev = $project.get()
  const next = env.result?.project
  if (!next) return null
  applyProject(next, { initial: initial || prev?.id !== next.id, pulse, prev })
  return next
}

function applyProject(next, { initial = false, pulse = false, prev = null } = {}) {
  const before = prev || $project.get()
  if (before && before.id !== next.id) resetProjectScoped() // 26-live.js: no results of the previous project
  $project.set(next)
  patchAtom($bench, { projectId: next.id })
  if ($nav.get().project !== next.id) patchAtom($nav, { project: next.id })
  store('lastProject', next.id)
  const boardChanged = !prev || prev.board?.chip !== next.board?.chip || prev.board?.variant !== next.board?.variant
    || prev.board?.devkit !== next.board?.devkit || (prev.options?.wifi !== false) !== (next.options?.wifi !== false)
  if (initial || boardChanged) {
    const b = boardOf(next)
    patchAtom($view, { chip: b.chip, variant: b.variant, devkit: b.devkit, wifi: b.wifi, variantPicked: variantPickedOf(b),
      ...(initial ? { selected: null } : {}) })
  }
  if (pulse && prev) pulseDiff(prev.assignments || [], next.assignments || [])
  const devkit = viewBoard().devkit
  if (devkit !== $board.get().id || $board.get().status === 'error') loadBoard(devkit)
  else runChecks()
}

async function loadBoard(id) {
  if (!id) {
    $board.set({ status: 'none', id: null, layout: null, error: null, sources: [] })
    runChecks()
    return
  }
  $board.set({ status: 'loading', id, layout: null, error: null, sources: [] })
  const env = await CB.api.board(id)
  if ($board.get().id !== id) return
  $board.set(env.ok ? { status: 'ready', id, layout: env.result, error: null, sources: env.sources || [] }
    : { status: 'error', id, layout: null, error: env, sources: [] })
  runChecks()
}

function checkKey(b, assignments, extras) {
  return JSON.stringify([b.chip, b.variant, b.wifi, b.devkit, (assignments || []).map(a => [a.role, a.pin, a.mode]),
    extras && extras.parts ? [extras.parts, extras.options] : null])
}

async function runChecks() {
  const p = $project.get()
  if (!p) return
  const b = viewBoard()
  const extras = modCheckExtras(p) // module instances and rails join the check
  const assignments = (p.assignments || []).map(a => (extras.parts && a.net
    ? { role: a.role, mode: a.mode, pin: a.pin, net: a.net } : { role: a.role, mode: a.mode, pin: a.pin }))
  const key = checkKey(b, assignments, extras)
  if ($check.get().key !== key || $check.get().status === 'error') {
    $check.set({ status: 'loading', key, env: $check.get().env })
    const body = { chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit, assignments, ...extras }
    const run = assignments.length ? CB.api.pinsCheck(body) : Promise.resolve(null)
    run.then(env => { if ($check.get().key === key) $check.set({ status: env && !env.ok ? 'error' : 'ready', key, env }) })
  }
  const layout = $board.get().layout
  const mapKeyNow = layout ? checkKey(b, [['map', layout.id]]) : null
  if (!layout) {
    $map.set({ status: 'none', key: null, env: null })
  } else if ($map.get().key !== mapKeyNow || $map.get().status === 'error') {
    $map.set({ status: 'loading', key: mapKeyNow, env: $map.get().env })
    const env = await CB.api.pinsCheck({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit, assignments: mapAssignments(layout) })
    if ($map.get().key === mapKeyNow) $map.set({ status: env.ok ? 'ready' : 'error', key: mapKeyNow, env })
  }
  const sel = $view.get().selected
  if (sel !== null && $info.get().gpio === sel) loadInfo(sel, { force: true })
}

async function loadInfo(gpio, { force = false } = {}) {
  if (!force && $info.get().gpio === gpio && $info.get().status !== 'error') return
  const b = viewBoard()
  $info.set({ status: 'loading', gpio, env: $info.get().gpio === gpio ? $info.get().env : null })
  const env = await CB.api.pinsInfo({ chip: b.chip, pin: gpio, variant: b.variant, devkit: b.devkit })
  if ($info.get().gpio === gpio) $info.set({ status: env.ok ? 'ready' : 'error', gpio, env })
}

async function loadPorts() {
  if (!CB.api) return
  patchAtom($ports, { status: $ports.get().status === 'idle' ? 'loading' : $ports.get().status })
  const env = await CB.api.ports()
  $ports.set(env.ok ? { status: 'ready', ports: env.result?.ports || [], error: null } : { status: 'error', ports: [], error: env })
}

/** Read what the backend already buffered for the project's detected port. Never opens a port:
 *  only sim:// ports are read automatically, real ports wait for the user (06 DEBUG). */
async function loadSerial({ fresh = false } = {}) {
  const p = $project.get()
  const port = p?.board?.detected?.port || null
  if (monitorActive($monitor.get().port)) return // the live monitor (06 DEBUG) owns the buffer
  if (!port || !/^sim:\/\//.test(port)) {
    $serial.set({ port, buf: emptyBuffer(), status: 'closed', note: port ? 'real-port' : 'no-port', mode: null, simulated: null })
    return
  }
  const cur = $serial.get()
  const base = fresh || cur.port !== port ? emptyBuffer() : cur.buf
  patchAtom($serial, { port, status: cur.status === 'idle' ? 'loading' : cur.status })
  const env = await CB.api.serialTail(port, base.lastSeq)
  if (!env.ok) {
    patchAtom($serial, { status: 'error', note: env.error?.message || 'serial tail failed' })
    return
  }
  const r = env.result || {}
  const msgs = [...(r.lines || []), ...(r.panic ? [r.panic] : [])]
  const buf = mergeLines(base, [{ t: 'state', port, state: r.state, epoch: r.epoch }, ...msgs])
  $serial.set({ port, buf, status: r.state || 'open', note: null, mode: null, simulated: r.simulated ?? null })
  watchSerialPanic(buf)
}

async function decodePanic(panic) {
  const p = $project.get()
  const tag = { key: panic.log_ref, summary: panic.summary ?? null, flashAt: p?.firmware?.last_flash?.at ?? null }
  $panic.set({ status: 'loading', env: null, ...tag })
  const env = await CB.api.crashDecode({ log_ref: panic.log_ref, project: p?.id, chip: p?.board?.chip })
  if ($panic.get().key === panic.log_ref) $panic.set({ status: env.ok ? 'ready' : 'error', env, ...tag })
}

// ─── events + polling ──────────────────────────────────────────────────

function onProjectUpdated(payload) {
  const p = $project.get()
  if (!payload?.id) return
  directiveProjectChanged(payload.id)
  if (Array.isArray(payload.changed) && payload.changed.includes('deleted')) {
    forgetProject(payload.id) // 26-live.js
    return
  }
  if (!p || payload.id !== p.id) {
    if ($bench.get().phase === 'empty') loadBench({ projectId: payload.id })
    else if ($bench.get().phase === 'ready' && !($bench.get().projects || []).some(x => x.id === payload.id)) refreshProjects()
    return
  }
  if (Number.isInteger(payload.rev) && payload.rev <= p.rev) return
  loadProject(p.id, { pulse: payload.by === 'agent' })
}

function onJobUpdated(payload) {
  return onJobEvent(payload) // 26-live.js
}

async function pollTick() {
  if (CB.polling || CB.mounts <= 0) return
  if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
  if (Date.now() - CB.lastEventAt < 10_000 || Date.now() < CB.offlineUntil) return
  CB.polling = true
  try {
    const phase = $bench.get().phase
    if (phase === 'error' && isOffline($bench.get().error)) {
      await loadBench()
    } else if (phase === 'ready') {
      const p = $project.get()
      const env = p ? await CB.api.project(p.id) : null
      if (env?.ok && env.result?.project && env.result.project.rev !== p.rev) {
        const next = env.result.project
        const byAgent = (next.assignments || []).some(a => a.updated_by === 'agent')
        applyProject(next, { prev: p, pulse: byAgent })
      } else if (env && !env.ok && isOffline(env)) {
        CB.offlineUntil = Date.now() + 30_000
      }
      await loadPorts()
      if ($serial.get().port && /^sim:\/\//.test($serial.get().port)) await loadSerial()
    }
  } finally {
    CB.polling = false
  }
}

/** Pins and rows whose assignment changed between two project revisions pulse twice. */
function pulseDiff(prevRows, nextRows) {
  const before = new Map(prevRows.map(a => [a.role, a]))
  const pins = new Set()
  const roles = new Set()
  for (const a of nextRows) {
    const b = before.get(a.role)
    if (!b || b.pin !== a.pin || b.mode !== a.mode || b.net !== a.net) {
      roles.add(a.role)
      pins.add(a.pin)
      if (b) pins.add(b.pin)
    }
    before.delete(a.role)
  }
  for (const gone of before.values()) pins.add(gone.pin)
  if (!pins.size && !roles.size) return
  $pulse.set({ pins: [...pins], roles: [...roles], at: Date.now() })
  CB.ctx?.setTimeout?.(() => { if (Date.now() - $pulse.get().at >= 1300) $pulse.set({ pins: [], roles: [], at: 0 }) }, 1400)
}

// ─── PLAN actions ──────────────────────────────────────────────────────

function selectPin(gpio) {
  patchAtom($view, { selected: gpio })
  if (gpio !== null && gpio !== undefined) loadInfo(gpio)
}

/** A stored variant counts as the user's choice when it is not the DevKit's preset (module.variant / chip default). */
function variantPickedOf(b) {
  return b.variant !== null && b.variant !== undefined && b.variant !== defaultVariant(b.chip, resolveDevkit(b.chip, b.devkit))
}

/**
 * What-if change of chip, DevKit, variant or Wi-Fi. A variant chosen in the toolbar is the user's
 * choice and stays across DevKits of the same chip. Otherwise a new DevKit presets its `module.variant` (C6-DevKitC-1
 * → WROOM-1, C6-DevKitM-1 → MINI-1, DevKitC V4 → WROOM-32E); a DevKit whose module variant is unknown (WT32-S1)
 * leaves it empty; a layout without module data (S3-DevKitC-1 v1.1) takes the chip default. A new chip starts from its
 * DevKit's preset. `opts.project`: the patch is the project board (reset), its variant counts as chosen when it is
 * not the preset.
 */
function setWhatIf(patch, opts = {}) {
  const cur = $view.get()
  const v = { ...cur, ...patch }
  const chip = chipInfo(v.chip)
  const before = resolveDevkit(cur.chip, cur.devkit)
  v.devkit = resolveDevkit(v.chip, v.devkit)
  const explicit = 'variant' in patch
  if (!chip?.variants.length) {
    v.variant = null
    v.variantPicked = false
  } else if (explicit) {
    if (v.variant !== null && !chip.variants.some(x => x.id === v.variant)) v.variant = defaultVariant(v.chip, v.devkit)
    v.variantPicked = opts.project ? variantPickedOf(v) : v.variant !== null
  } else if (cur.chip !== v.chip) {
    v.variant = defaultVariant(v.chip, v.devkit)
    v.variantPicked = false
  } else if (v.devkit !== before && !cur.variantPicked) {
    v.variant = defaultVariant(v.chip, v.devkit)
  }
  $view.set(v)
  $suggest.set({ status: 'idle', env: null, role: null })
  const devkit = viewBoard().devkit
  if (devkit !== $board.get().id) loadBoard(devkit)
  else runChecks()
}

function resetWhatIf() {
  const p = $project.get()
  if (p) setWhatIf(boardOf(p), { project: true })
}

async function patchOps(ops, { okText = null } = {}) {
  const p = $project.get()
  if (!p) return null
  const env = await CB.api.patchProject(p.id, p.rev, ops)
  if (env.ok && env.result?.project) {
    applyProject(env.result.project, { prev: p })
    if (okText) setNotice(okText, 'ok')
    return env
  }
  if (env.error?.code === 'project_conflict') {
    await loadProject(p.id)
    setNotice('The project changed meanwhile (agent or another window): reloaded the project, try again.', 'warn')
  } else {
    setNotice(env.error?.message || env.summary || 'The change was not saved.', 'bad')
  }
  return env
}

function assignPin({ role, mode, pin, net }) {
  return patchOps([{ op: 'assign', role, mode, pin, ...(net ? { net } : {}) }], { okText: `${role} → GPIO${pin} saved.` })
}

function unassignRole(role) {
  return patchOps([{ op: 'unassign', role }], { okText: `${role} removed.` })
}

function applyBoardToProject() {
  const b = viewBoard()
  return patchOps([{ op: 'set_board', chip: b.chip, variant: b.variant, devkit: b.devkit, wifi: b.wifi }],
    { okText: 'Board saved to the project.' })
}

/** Suggest replacements for the assignment `role` (or every blocked/caution one). */
async function suggestPins(rows, role = null) {
  const b = viewBoard()
  const targets = rows.filter(r => (role ? r.role === role : r.verdict === 'blocked' || r.verdict === 'caution'))
  if (!targets.length) {
    $suggest.set({ status: 'none', env: null, role: null })
    setNotice('All assigned pins are ok — nothing to replace.', 'ok')
    return
  }
  $suggest.set({ status: 'loading', env: null, role: targets[0].role })
  const taken = rows.filter(r => !targets.includes(r)).map(r => r.pin)
  const env = await CB.api.pinsSuggest({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit,
    requests: targets.map(t => ({ role: t.role, mode: t.mode, requested: t.pin })), taken })
  $suggest.set({ status: env.ok ? 'ready' : 'error', env, role: targets[0].role })
  if (!env.ok) setNotice(env.error?.message || 'Suggestion failed.', 'bad')
  if (env.ok && !role) selectPin(targets[0].pin)
}

async function loadDemo() {
  patchAtom($bench, { phase: 'loading' })
  const env = await CB.api.demo()
  if (!env.ok) {
    patchAtom($bench, { phase: 'error', error: env })
    return
  }
  await loadBench({ projectId: env.result?.id || env.result?.project?.id || 'laser-trigger' })
}

// ─── navigation ────────────────────────────────────────────────────────

function goStation(station, project = null) {
  if (!isStation(station)) return
  const cur = $nav.get()
  $nav.set({ project: project || cur.project, station, n: cur.n + 1 })
  if (station !== cur.station) dropNotices(noticeFades) // a confirmation belongs to its station; errors stay
  store('lastStation', station)
  if (station === 'debug') {
    const pk = panicKey($project.get())
    if (pk) { patchAtom($ui, { panicSeen: pk }); store('panicSeen', pk) }
  }
  if (project && $project.get()?.id !== project && $bench.get().phase !== 'idle') loadBench({ projectId: project })
}

/** Open the Bench from palette, status bar or a card: atom first, then a workspace tile beside the chat
 *  when the host has openWorkspace, else the route. Never navigate while a Bench is already on screen. */
function openBench({ station = null, project = null, beside = true } = {}) {
  if (station) goStation(station, project)
  if (CB.mounts > 0) return
  const host = sdk.host
  if (beside && typeof host?.openWorkspace === 'function') {
    try {
      const close = host.openWorkspace('bench', { title: 'Circuit Bench', render: () => h(BenchPage, { surface: 'tile' }),
        dock: { pane: 'workspace', pos: 'right' }, minWidth: '34rem', onClose: () => { CB.tileClose = null } })
      CB.tileClose = typeof close === 'function' ? close : null
      return
    } catch (e) {
      console.warn('[circuit-bench] openWorkspace failed, falling back to the route', e)
    }
  }
  host?.navigate?.('/bench')
}

/** User shows/hides the page console. Showing also pins it open for the session (idle bar → open). */
function setConsole(state) {
  patchAtom($ui, { cons: state, consPinned: state === 'open' })
  store('console', state)
}

/** Switch the console tab (user click, job start, monitor open); the console then stays open for the session. */
function setConsoleTab(tab) {
  patchAtom($ui, { tab, consPinned: true })
  store('consoleTab', tab)
}
