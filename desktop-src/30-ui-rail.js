// StageRail: stations 01–06 with status, trace lines between them, provenance footer.

function StageRail({ project, rows, health, checkEnv }) {
  const nav = sdk.useValue($nav)
  const ui = sdk.useValue($ui)
  const bench = sdk.useValue($bench)
  const counts = countVerdicts(rows)
  const status = stageStatus(project, counts, ui.panicSeen, modCountWords(stageModCounts(checkEnv)))
  const solder = solderProgress(project)
  // Wow 4: one sweep over the stations when the fix loop closes (06 DEBUG sets sweepAt); reduced motion: no animation
  const sweeping = Boolean(ui.sweepAt) && Date.now() - ui.sweepAt < 2400
  useEffect(() => {
    if (!ui.sweepAt) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => patchAtom($ui, { sweepAt: 0 }), 2400)
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [ui.sweepAt])
  const tools = health?.tools || {}
  const toolNames = ['pio', 'esptool', 'addr2line']
  const toolsOk = toolNames.filter(t => tools[t]).length
  const rulesSrc = (checkEnv?.sources || []).find(s => /ESP-IDF/i.test(s.title || ''))
  const rules = rulesSrc ? (/ESP-IDF\s+v?[\d.]+/i.exec(rulesSrc.title) || [rulesSrc.title])[0] : null
  return h('nav', { className: 'cb-rail', 'aria-label': 'Bench stations', 'data-cb': 'rail', 'data-cb-audit-root': 'rail', 'data-cb-sweep': sweeping ? 'on' : undefined },
    h(Label, { className: 'cb-rail-label' }, '// workflow'),
    STATIONS.map((s, i) => {
      const st = status[s.id] || {}
      const word = shellRailWord(s.id, st, { project, counts, solder })
      return [
        // the trace between two stations lights up once the station above is done (state, not decoration)
        i ? h('div', { key: `t${s.id}`, className: 'cb-trace', 'aria-hidden': 'true', 'data-cb-done': status[STATIONS[i - 1].id]?.text === '[✓]' ? 'true' : undefined }) : null,
        h('button', { key: s.id, type: 'button', className: 'cb-stage', 'data-cb': `stage-${s.id}`, style: { '--cb-i': i },
          'aria-current': nav.station === s.id ? 'page' : undefined, 'data-cb-alert': st.alert ? 'true' : 'false', 'data-cb-tone': st.tone || 'faint',
          title: `${s.n} ${s.title}${word ? ` · ${word}` : ''}${st.detail ? ` · ${st.detail}` : ''}`, onClick: () => goStation(s.id) },
        h(StationIcon, { id: s.id }),
        h('span', { className: 'cb-stage-txt' },
          h('span', { className: 'cb-stage-l1' }, h('span', { className: 'cb-n' }, s.n), h('span', { className: 'cb-t' }, s.title)),
          word ? h('span', { className: 'cb-sw', 'data-cb': `stage-word-${s.id}` }, word) : null),
        h(RailMark, { text: st.text || '', tone: st.tone || 'faint' }))
      ]
    }),
    h('div', { className: 'cb-rail-foot', 'data-cb': 'rail-foot' },
      health ? h('div', { title: `circuit-bench ${health.version || ''} · Hermes ${health.hermes || ''}` },
        h('span', { className: 'cb-ok' }, '● '), `backend ${health.version || 'ok'}`)
        : h('div', null, h('span', { className: 'cb-bad' }, '○ '), 'backend offline'),
      health ? h('div', { title: toolNames.map(t => `${t}: ${tools[t] === true ? 'found' : tools[t] || 'missing'}`).join('\n') },
        h('span', { className: toolsOk === toolNames.length ? 'cb-ok' : 'cb-warn' }, '● '), `tools ${toolsOk}/${toolNames.length}`) : null,
      rules ? h('div', { title: `Pin rules: ${rulesSrc.title}` }, h('span', { className: 'cb-active' }, '● '), rules) : null,
      bench.mode === 'fixtures' ? h('div', { title: 'Development build with embedded fixtures' }, h('span', { className: 'cb-warn' }, '◌ '), 'fixture data') : null))
}

/** Rail status: glyph + number; the stageStatus text stays in the DOM (shellRailMark). */
function RailMark({ text, tone }) {
  const m = shellRailMark(text)
  const shapes = m.glyph === 'blocked' || m.glyph === 'caution' ? artGlyphShapes(m.glyph, 6, 6, 'currentColor') : shellMarkShapes(m.glyph, m.pct ?? 0)
  return h('span', { className: `cb-s cb-${tone}`, 'data-cb-mark': m.glyph || undefined },
    shapes.length ? h('svg', { className: 'cb-s-g', width: 12, height: 12, viewBox: '0 0 12 12', focusable: 'false', 'aria-hidden': 'true' },
      shapes.map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) }))) : null,
    m.num ? h('span', { className: 'cb-s-n' }, m.num) : null,
    m.code ? h('span', { className: 'cb-sr', 'aria-hidden': 'true' }, m.code) : null)
}

/** Station symbol (lib/art-shell.js shapes, 16 px, currentColor); decorative, the station name stands beside it. */
function StationIcon({ id }) {
  const shapes = shellStationShapes(id)
  if (!shapes.length) return h('span', { className: 'cb-stage-ic', 'aria-hidden': 'true' })
  return h('svg', { className: 'cb-stage-ic', width: 16, height: 16, viewBox: '0 0 16 16', focusable: 'false', 'aria-hidden': 'true', 'data-cb-icon': id },
    shapes.map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}
