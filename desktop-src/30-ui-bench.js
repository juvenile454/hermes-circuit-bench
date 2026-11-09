// Bench page (route /bench, or a workspace tile beside the chat): HUD, rail, station, inspector, console.

let BENCH_MOUNTS = 0

function BenchPage({ surface = 'route' }) {
  const bench = sdk.useValue($bench)
  const project = sdk.useValue($project)
  const nav = sdk.useValue($nav)
  const ui = sdk.useValue($ui)
  const check = sdk.useValue($check)
  const map = sdk.useValue($map)
  const notices = sdk.useValue($notices)
  useEffect(() => {
    BENCH_MOUNTS++
    CB.mounts = BENCH_MOUNTS
    BENCH_SURFACES.set(surface, (BENCH_SURFACES.get(surface) || 0) + 1)
    // one Bench at a time: the full page replaces the tile docked beside the chat
    if (surface === 'route' && typeof CB.tileClose === 'function') {
      const close = CB.tileClose
      CB.tileClose = null
      try { close() } catch (e) { console.warn('[circuit-bench] closing the docked Bench failed', e) }
    }
    ensureBench()
    return () => {
      BENCH_MOUNTS--; CB.mounts = BENCH_MOUNTS
      BENCH_SURFACES.set(surface, Math.max(0, (BENCH_SURFACES.get(surface) || 1) - 1))
    }
  }, [])
  const rows = useMemo(() => mergeAssignments(project?.assignments, check.env?.ok ? check.env.result?.pins : null), [project, check.env])
  const view = STATION_VIEWS[nav.station]
  const hasInsp = Boolean(view?.inspector) && bench.phase === 'ready'
  let body
  if (bench.phase === 'idle' || (bench.phase === 'loading' && !project)) {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-loading' }, h('div', { className: 'cb-loading' }, 'connecting bench'))
  } else if (bench.phase === 'error') {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-error' }, h(BenchError, { env: bench.error }))
  } else if (bench.phase === 'empty') {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-empty' }, h(BenchEmpty, null))
  } else if (view) {
    body = h(view.component, { project, rows, key: `${project?.id || ''}:${nav.station}` }) // another project: fresh station state
  } else {
    body = h(StationSoon, { station: nav.station, project, key: `${project?.id || ''}:${nav.station}` })
  }
  const health = bench.health
  const consMode = useConsoleMode(project)
  const claim = () => { BENCH_ACTIVE.surface = surface }
  return h('div', { className: 'cb-root cb-page', 'data-cb': 'bench-root', 'data-cb-audit-root': 'bench', 'data-cb-look': ui.look, 'data-cb-surface': surface,
    'data-cb-sim': project ? (project.simulated ? 'true' : 'false') : undefined,
    'data-cb-phase': bench.phase, 'data-cb-station': nav.station, onPointerDownCapture: claim, onKeyDownCapture: claim },
  h(Styles, null),
  h('div', { className: 'cb-shell', 'data-cb': 'shell', 'data-cb-insp': hasInsp ? 'yes' : 'none',
    'data-cb-cons': consMode, 'data-cb-notes': notices.length ? 'yes' : undefined },
  h(Hud, { project, rows, health }),
  h(NoticeZone, { list: notices }),
  h(StageRail, { project, rows, health, checkEnv: check.env?.ok ? check.env : map.env }),
  h('div', { className: 'cb-work', 'data-cb': 'work' }, body),
  h(ConsoleRow, { project, mode: consMode }),
  h(BenchModal, { modal: ui.modal, map, surface })))
}

// one notice zone for the whole Bench (a row under the HUD, so it never covers the station): symbol + word +
// text, tone by severity (alarm colour only for errors), no motion. ok/info fade after 3 s (paused while the pointer or
// the focus is in the zone, WCAG 2.2.1), warn/bad stay until ✕; status for ok/info, alert for warn/bad.
const NOTICE_LOOK = { ok: ['✓', 'ok'], info: ['i', 'info'], warn: ['!', 'warning'], bad: ['✕', 'error'] }
const NOTICE_FADE_MS = 3000

function NoticeZone({ list }) {
  const [hold, setHold] = useState(false)
  const fading = list.filter(noticeFades)
  useEffect(() => {
    if (hold || !fading.length) return undefined
    const due = Math.min(...fading.map(n => n.at)) + NOTICE_FADE_MS - Date.now()
    const t = timersOf(CB.ctx).setTimeout(() => dropNotices(n => noticeFades(n) && n.at + NOTICE_FADE_MS <= Date.now() + 50), Math.max(0, due))
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [hold, fading.map(n => `${n.id}:${n.at}`).join(',')])
  // leaving the zone gives the fading notices their 3 s again
  const release = () => { setHold(false); $notices.set($notices.get().map(n => (noticeFades(n) ? { ...n, at: Date.now() } : n))) }
  return h('div', { className: 'cb-notes', 'data-cb': 'notices', 'aria-label': 'Notices', 'aria-live': 'polite',
    onMouseEnter: () => setHold(true), onMouseLeave: release, onFocus: () => setHold(true), onBlur: release },
  list.map(n => {
    const [sym, word] = NOTICE_LOOK[n.tone] || NOTICE_LOOK.info
    return h('div', { key: n.id, className: `cb-notice cb-notice--${NOTICE_LOOK[n.tone] ? n.tone : 'info'}`, role: noticeFades(n) ? 'status' : 'alert',
      'data-cb': `notice-${n.tone}`, 'data-cb-notice': n.id },
    h('span', { className: 'cb-notice-sym', 'aria-hidden': 'true' }, sym),
    h('span', { className: 'cb-notice-w' }, word),
    h('span', { className: 'cb-notice-t' }, n.text),
    h('button', { type: 'button', className: 'cb-notice-x', title: 'Dismiss', 'aria-label': `Dismiss: ${n.text}`, 'data-cb': 'notice-dismiss',
      onClick: () => dropNotices(x => x.id === n.id) }, '×'))
  }))
}

// Route and tile can be mounted at once (Bench beside the chat): a dialog belongs to the surface the user last
// touched, otherwise to the route, otherwise to the tile — never to both.
const BENCH_SURFACES = new Map()
const BENCH_ACTIVE = { surface: null }

const MODAL_OWNER = new WeakMap()

function modalSurface(modal) {
  const live = k => (BENCH_SURFACES.get(k) || 0) > 0
  const pinned = MODAL_OWNER.get(modal)
  if (pinned && live(pinned)) return pinned
  const owner = BENCH_ACTIVE.surface && live(BENCH_ACTIVE.surface) ? BENCH_ACTIVE.surface : live('route') ? 'route' : 'tile'
  MODAL_OWNER.set(modal, owner)
  return owner
}

function BenchModal({ modal, map, surface }) {
  const close = () => patchAtom($ui, { modal: null })
  const t = modal?.type
  if (!t || modalSurface(modal) !== surface) return null
  if (t === 'assign') return h(AssignDialog, { init: modal.init, mapState: map, onClose: close })
  if (t === 'flash') return h(FlashDialog, { confirm: modal.confirm, onClose: close })
  if (t === 'variant') return h(VariantDialog, { variant: modal.variant, onClose: close })
  if (t === 'example-overwrite') return h(ExampleOverwriteDialog, { onClose: close })
  if (t === 'new-project') return h(NewProjectDialog, { onClose: close })
  if (t === 'projects') return h(ProjectsDialog, { onClose: close })
  if (t === 'doctor') return h(DoctorDialog, { env: modal.env, onClose: close })
  if (t === 'modules') return h(ModulesDialog, { init: modal.init ?? null, onClose: close }) // 47-dialog-modules.js
  return null
}

function BenchError({ env }) {
  const code = env?.error?.code
  const offline = code === 'backend_unavailable' || code === 'network_error'
  return h(EmptyBox, { tone: offline ? 'warn' : 'bad', kicker: `// bench · ${code || 'error'}`, dataCb: offline ? 'bench-offline' : 'bench-failed',
    title: offline ? 'Bench backend not available' : 'The bench could not load',
    actions: [h(Btn, { key: 'r', kind: 'ghost', onClick: () => loadBench(), 'data-cb': 'retry' }, 'Retry')] },
  h('p', null, env?.error?.message || env?.summary || 'Unknown error.'),
  env?.error?.hint ? h('p', null, env.error.hint) : null,
  offline ? h('p', null, 'The page retries on its own every 30 s while it is open.') : null)
}

function BenchEmpty() {
  const [busy, setBusy] = useState(false)
  return h(EmptyBox, { kicker: '// bench · no project', title: 'No bench project yet', dataCb: 'no-project',
    actions: [h(Btn, { key: 'd', onClick: async () => { setBusy(true); await loadDemo(); setBusy(false) }, disabled: busy, 'data-cb': 'load-demo' },
      busy ? 'Loading…' : 'Load demo project'),
    h(Btn, { key: 'n', kind: 'ghost', onClick: () => patchAtom($ui, { modal: { type: 'new-project' } }), 'data-cb': 'new-project' }, 'New project'),
    h(Btn, { key: 'a', kind: 'agent', onClick: () => composeDraft('Start a Circuit Bench project for an ESP32-S3-DevKitC-1 (N16R8). Use bench_project to create it.'),
      'data-cb': 'ask-create' }, 'Ask Hermes to create one')] },
  h('p', null, 'A bench project holds the board, pin assignments, calculations, wiring, solder steps and firmware.'),
  h('p', null, 'Try the demo project ', h('code', null, 'laser-trigger'), ' (simulated board, no hardware needed) or let Hermes create one from the chat.'))
}
