// BoardChip in the status bar (STATUSBAR_AREAS.right): ● LINK ttyACM0 / ◌ SIM / ○ NO BOARD. App chrome, so it uses
// the app theme colours (look "theme"). Click opens the Bench.

function BoardChip() {
  const ports = sdk.useValue($ports)
  const link = linkState(ports, null)
  const glyph = link.kind === 'link' ? '●' : link.kind === 'sim' ? '◌' : '○'
  const tone = link.kind === 'link' ? 'cb-ok' : link.kind === 'sim' ? 'cb-active' : 'cb-dim'
  const short = link.device ? link.device.replace(/^\/dev\//, '') : ''
  const label = link.kind === 'unknown' ? 'BENCH' : link.kind === 'offline' ? 'BENCH OFFLINE' : link.label
  return h(Fragment, null, h(Styles, null), h('button', { type: 'button', className: 'cb-root cb-chip', 'data-cb': 'board-chip', 'data-cb-look': 'theme', 'data-cb-link': link.kind,
    title: link.device ? `Circuit Bench · ${link.label} ${link.device} — open the Bench` : 'Circuit Bench — open the Bench',
    onClick: () => openBench() },
  h('span', { className: `cb-g ${tone}`, 'aria-hidden': 'true' }, glyph),
  h('span', null, label),
  short ? h('b', null, short) : null))
}
