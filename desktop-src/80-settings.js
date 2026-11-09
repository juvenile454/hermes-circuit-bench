// Settings → Plugins → Circuit Bench (ctx.registerSettingsPage): desktop-only state. The agent settings
// (allow_flash, hardware_access, baud, limits …) come from config_schema and appear as "Agent settings" next to
// this page; it links there. Fixture mode only in development builds and only with ?dev=1.

function devSettingsVisible() {
  if (CB_FIXTURES === null) return false
  try { return /[?&]dev=1\b/.test(String(typeof window !== 'undefined' ? window.location?.hash || '' : '')) } catch { return false }
}

function setLook(look) {
  patchAtom($ui, { look })
  store('look', look)
}

function setTimestamps(on) {
  patchAtom($ui, { showTs: on })
  store('timestamps', on)
}

function SettingsRow({ title, desc, children, dataCb }) {
  return h('div', { className: 'cb-setrow', 'data-cb': dataCb }, h('div', null, h('div', { className: 'cb-settitle' }, title), desc ? h('div', { className: 'cb-setdesc' }, desc) : null),
    h('div', { className: 'cb-setctl' }, children))
}

function BenchSettingsPage() {
  const ui = sdk.useValue($ui)
  const bench = sdk.useValue($bench)
  const health = bench.health
  const dev = devSettingsVisible()
  useEffect(() => {
    if (!bench.health && CB.api) CB.api.health().then(env => { if (env.ok) patchAtom($bench, { health: env.result }) })
  }, [])
  return h('div', { className: 'cb-root cb-settings', 'data-cb': 'settings-page', 'data-cb-look': 'theme' }, h(Styles, null),
    h('h2', { className: 'cb-set-h' }, 'Circuit Bench'),
    h('p', { className: 'cb-setdesc' }, 'Desktop settings of the bench. Flashing, hardware access and serial limits are agent settings.'),
    h(SettingsRow, { title: 'Bench look', desc: 'Phosphor: fixed dark bench colours. Follow app theme: the bench uses the colours of your Hermes theme (light themes, accessibility).', dataCb: 'set-look' },
      h(Seg, { label: 'Bench look', dataCb: 'seg-look', value: ui.look, onChange: setLook,
        options: [{ id: 'phosphor', label: 'Phosphor' }, { id: 'theme', label: 'Follow app theme' }] })),
    h(SettingsRow, { title: 'Console timestamps', desc: 'Show the receive time of every serial line.', dataCb: 'set-ts' },
      h(Toggle, { checked: ui.showTs, onChange: setTimestamps, dataCb: 'toggle-ts' }, ui.showTs ? 'On' : 'Off')),
    h(SettingsRow, { title: 'Agent settings', dataCb: 'set-agent',
      desc: [`Allow flashing real boards (now ${health ? (health.allow_flash ? 'on' : 'off') : '—'}), hardware access (now ${health ? (health.hardware_access ? 'on' : 'off') : '—'}), `,
        'approval for serial ports, default baud rate, monitor and build time limits.'] },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'agent-settings', onClick: () => openAgentSettings() }, 'Agent settings ›')),
    dev ? h(SettingsRow, { title: 'Fixture data (development)', desc: 'Development build only: answer every route from the embedded fixtures instead of the backend. Reload after a change.', dataCb: 'set-fixtures' },
      h(Toggle, { checked: stored('useFixtures', true) !== false, dataCb: 'toggle-fixtures', onChange: on => store('useFixtures', on) }, 'Fixtures')) : null)
}

function registerSettings(ctx) {
  if (typeof ctx.registerSettingsPage !== 'function') return null
  try {
    return ctx.registerSettingsPage({ id: 'bench', title: 'Circuit Bench', icon: 'circuit-board', order: 50, render: () => h(BenchSettingsPage, null) })
  } catch (e) {
    console.warn('[circuit-bench] settings page not registered', e)
    return null
  }
}
