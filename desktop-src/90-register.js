// Registration: route /bench + nav, status chip, palette, theme, serial pane on demand.

function registerDevHooks() {
  // Development builds only (CB_FIXTURES embedded): lets the E2E harness play the agent against the fixture backend.
  if (CB_FIXTURES === null || !CB.api?.fixtures || typeof window === 'undefined') return
  window.__cbDev = {
    mode: () => CB.api.mode,
    agentAssign: async op => {
      const p = $project.get()
      if (!p) return null
      const env = await CB.api.fixtures.handle('PATCH', `/projects/${p.id}`, { expected_rev: p.rev, ops: [{ op: 'assign', ...op }], by: 'agent' })
      if (env.ok) {
        CB.lastEventAt = Date.now()
        onProjectUpdated({ id: p.id, rev: env.result.rev, changed: env.result.changed, by: 'agent' })
      }
      return env
    },
    jobEvent: (payload = {}) => {
      CB.lastEventAt = Date.now()
      const job = CB_FIXTURES[`job.${payload.kind || 'build'}.done`]?.result
      return onJobUpdated({ job_id: job?.job_id, kind: job?.kind, state: 'done', progress: 1, ...payload })
    },
    state: () => ({ phase: $bench.get().phase, station: $nav.get().station, selected: $view.get().selected, rev: $project.get()?.rev,
      check: $check.get().status, map: $map.get().status, mounts: CB.mounts, paneOpen: $ui.get().paneOpen, monitor: $monitor.get().status,
      serialMode: $serial.get().mode, jobs: Object.fromEntries(Object.entries($jobs.get()).map(([k, j]) => [k, j?.state || null])) })
  }
}

export default {
  id: PLUGIN_ID,
  name: 'Circuit Bench',
  description: 'ESP32 electronics bench: pin map, calculators, wiring, solder order, flash and serial debug.',
  register(ctx) {
    initStore(ctx)
    const regs = [
      { id: 'page', area: sdk.ROUTES_AREA, data: { path: '/bench' }, render: () => h(BenchPage, { surface: 'route' }) },
      { id: 'nav', area: sdk.SIDEBAR_NAV_AREA, data: { path: '/bench', label: 'Circuit Bench', codicon: 'circuit-board' } }
    ]
    if (sdk.STATUSBAR_AREAS?.right) regs.push({ id: 'board-chip', area: sdk.STATUSBAR_AREAS.right, order: 480, render: () => h(BoardChip, null) })
    if (typeof sdk.PALETTE_AREA !== 'undefined') {
      const cmd = (id, label, keywords, run, detail) => ({ id: `palette-${id}`, area: sdk.PALETTE_AREA,
        data: { id: `circuit-bench.${id}`, label, keywords: [...keywords, 'bench', 'circuit'], run, ...(detail ? { detail } : {}) } })
      const focus = what => { openBench({ station: 'flash' }); patchAtom($flow, { focus: what, at: Date.now() }) }
      regs.push(
        cmd('open', 'Open Bench', ['circuit', 'esp32', 'pins'], () => openBench(), () => $project.get()?.id || ''),
        cmd('serial', 'Open serial monitor', ['serial', 'monitor', 'console', 'uart'], () => openSerialPane()),
        cmd('new', 'New bench project', ['project', 'create', 'new'], () => { openBench(); patchAtom($ui, { modal: { type: 'new-project' } }) }),
        cmd('projects', 'Manage bench projects', ['projects', 'switch', 'open', 'delete'], () => { openBench(); patchAtom($ui, { modal: { type: 'projects' } }) }),
        cmd('demo', 'Load demo project', ['demo', 'laser-trigger', 'simulated'], () => { openBench(); loadDemo() }),
        // detect and build only open station 05 and point at its button: no hardware access from the palette
        cmd('detect', 'Detect board', ['detect', 'esptool', 'port', 'board'], () => focus('detect'), () => 'opens 05 FLASH'),
        cmd('build', 'Build firmware', ['build', 'platformio', 'pio', 'firmware'], () => focus('build'), () => 'opens 05 FLASH'),
        cmd('doctor', 'Run bench doctor', ['doctor', 'tools', 'check', 'health'], () => { openBench(); runDoctor() }))
    }
    if (typeof sdk.THEMES_AREA !== 'undefined') regs.push({ id: 'theme', area: sdk.THEMES_AREA, data: BENCH_THEME })
    if (typeof sdk.TRANSCRIPT_DIRECTIVE_AREA !== 'undefined') {
      regs.push({ id: 'directive-bench', area: sdk.TRANSCRIPT_DIRECTIVE_AREA, data: { name: 'bench', render: props => h(BenchDirectiveCard, props) } })
    }
    // own card for bench_schematic images only where the host has the area (absent in v0.22.5)
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') {
      regs.push({ id: 'media-schematic', area: sdk.TOOL_MEDIA_RENDERER_AREA, data: { tools: ['bench_schematic'], render: props => h(SchematicMediaCard, props) } })
    }
    ctx.registerMany(regs)
    registerSettings(ctx)
    if (stored('paneOpen', false)) openSerialPane()
    ctx.onDispose(() => {
      CB.paneDispose = null
      if (MONITOR) { MONITOR.stop(); MONITOR = null } // the backend keeps the port; the next start does not reopen it
      for (const k of Object.keys(JOB_WATCH)) { if (typeof JOB_WATCH[k] === 'function') JOB_WATCH[k](); JOB_WATCH[k] = null }
    })
    registerDevHooks()
  }
}
