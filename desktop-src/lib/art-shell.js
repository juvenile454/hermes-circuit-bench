// Frame of the Bench: station symbols of the rail, the rail's state words and the HUD key figures as
// words. Pure functions, no SDK, no DOM; every name carries the prefix `shell` (one shared bundle scope). Shapes are
// [[tag, attrs], …] like artGlyphShapes (lib/art.js), drawn by the kit as inline SVG with currentColor.

/** Station symbols in a 16×16 box, 1.5 px strokes, drawn with `ink`. Unknown id → []. */
export function shellStationShapes(id, ink = 'currentColor') {
  const line = { fill: 'none', stroke: ink, 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
  switch (id) {
    // 01 PLAN: a chip with pins on both sides
    case 'plan': return [['rect', { x: 4.5, y: 3, width: 7, height: 10, rx: 1, ...line }],
      ['path', { d: 'M2 5.5H4.5M2 8H4.5M2 10.5H4.5M11.5 5.5H14M11.5 8H14M11.5 10.5H14', ...line }]]
    // 02 CALC: a resistor (zigzag) between two leads
    case 'calc': return [['path', { d: 'M1.5 8H3.5L5 5L7 11L9 5L11 11L12.5 8H14.5', ...line }]]
    // 03 WIRE: two nodes, one orthogonal net between them
    case 'wire': return [['path', { d: 'M4 4H8V12H12', ...line }], ['circle', { cx: 3, cy: 4, r: 1.6, fill: ink }], ['circle', { cx: 13, cy: 12, r: 1.6, fill: ink }]]
    // 04 SOLDER: an iron (handle + tip) and a joint
    case 'solder': return [['path', { d: 'M14 2L9 7', ...line, 'stroke-width': 3 }], ['path', { d: 'M9 7L4.5 11.5', ...line }],
      ['circle', { cx: 3.5, cy: 12.5, r: 1.8, fill: ink }]]
    // 05 FLASH: a lightning bolt
    case 'flash': return [['path', { d: 'M9 1.5L3.5 9H7.5L6.5 14.5L12.5 6.5H8.5Z', ...line }]]
    // 06 DEBUG: a trace with a spike (the serial monitor)
    case 'debug': return [['path', { d: 'M1.5 9H4.5L6 3.5L8.5 13L10 9H14.5', ...line }]]
    default: return []
  }
}

/** Rail grammar: stageStatus text → { glyph, num, code, pct }; num + code (hidden) = the original text. */
export function shellRailMark(text) {
  const t = String(text ?? '')
  let m
  if (t === '[✓]') return { glyph: 'done', num: '', code: t, pct: null }
  if (t === '[ ]' || t === '') return { glyph: t ? 'todo' : '', num: '', code: t, pct: null }
  if ((m = /^(\d+)✕$/.exec(t))) return { glyph: 'blocked', num: m[1], code: '✕', pct: null }
  if ((m = /^(\d*)!$/.exec(t))) return { glyph: 'caution', num: m[1], code: '!', pct: null }
  if ((m = /^(\d+)%$/.exec(t))) return { glyph: 'progress', num: t, code: '', pct: Math.max(0, Math.min(100, Number(m[1]))) }
  if (t === 'PANIC') return { glyph: 'panic', num: t, code: '', pct: null }
  if (t === 'FAIL') return { glyph: 'blocked', num: '', code: t, pct: null }
  if (t === 'BUILT') return { glyph: 'built', num: '', code: t, pct: null }
  return { glyph: '', num: t, code: '', pct: null }
}

/** Rail mark shapes (12×12): done, todo, built, progress (arc by pct); none for panic. */
export function shellMarkShapes(glyph, pct = 0, ink = 'currentColor') {
  const ring = { fill: 'none', stroke: ink, 'stroke-width': 2 }
  switch (glyph) {
    case 'done': return [['circle', { cx: 6, cy: 6, r: 5, ...ring }], ['path', { d: 'M3.5 6.2L5.3 8L8.6 4.4', fill: 'none', stroke: ink, 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }]]
    case 'todo': return [['circle', { cx: 6, cy: 6, r: 5, fill: 'none', stroke: ink, 'stroke-width': 1.2, opacity: 0.7 }]]
    case 'built': return [['circle', { cx: 6, cy: 6, r: 5, ...ring }], ['circle', { cx: 6, cy: 6, r: 2, fill: ink }]]
    case 'progress': {
      const p = Math.max(0, Math.min(100, Number(pct) || 0))
      const out = [['circle', { cx: 6, cy: 6, r: 5, ...ring, opacity: 0.35 }]]
      if (p >= 100) out.push(['circle', { cx: 6, cy: 6, r: 5, ...ring }])
      else if (p > 0) {
        const a = (p / 100) * 2 * Math.PI
        const x = Math.round((6 + 5 * Math.sin(a)) * 100) / 100
        const y = Math.round((6 - 5 * Math.cos(a)) * 100) / 100
        out.push(['path', { d: `M6 1A5 5 0 ${p > 50 ? 1 : 0} 1 ${x} ${y}`, ...ring, 'stroke-linecap': 'round' }])
      }
      return out
    }
    default: return []
  }
}

/** The rail's state word under the station name (short: ≤ 10 characters). `status` is stageStatus()[id]
 *  (lib/stages.js), `counts` countVerdicts(), `solder` solderProgress(). The PANIC badge stays the only panic hint
 *  of the navigation, so the debug word never says "panic". */
export function shellRailWord(id, status, { project = null, counts = null, solder = null } = {}) {
  if (!project || !status) return ''
  const t = status.text || ''
  const done = t === '[✓]'
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`
  switch (id) {
    // the right column (stageStatus text) already carries the state mark (1✕, 3!, [✓], 40%); the word adds what
    // the mark does not say: how many pins, what is left, what happened
    case 'plan': {
      const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
      const total = c.ok + c.caution + c.blocked + c.unchecked
      return total ? n(total, 'pin', 'pins') : 'no pins'
    }
    case 'calc': return done ? `${(project.calcs || []).length} saved` : 'none yet'
    case 'wire': return done ? n((project.circuits || []).length, 'circuit', 'circuits') : 'none yet'
    case 'solder': {
      if (status.tone === 'warn') return 'outdated'
      if (!solder?.total) return 'no plan'
      return done ? 'all done' : `${solder.total - solder.done} to go`
    }
    case 'flash': return t === 'FAIL' ? 'failed' : done ? 'flashed' : t === 'BUILT' ? 'built' : 'not built'
    case 'debug': return t === 'PANIC' ? 'to fix' : done ? 'fixed' : 'no crash'
    default: return ''
  }
}

/** HUD figures as words: PINS ✓ 4 ok ! 0 ✕ 1 blocked (+ ⊗/◇ module danger/caution when > 0;
 *  with > 2 counts the ok count hides, only the worst keeps its word),
 *  SOLDER 3/6, BUILD word → {pins: {items, label}, solder: {text, label}, build: {word, tone, label}}; label = full
 *  sentence for aria-label/title (the narrow HUD shows symbol + number). */
export function shellKpis(counts, solder, build, mods = null) {
  const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
  const items = [
    { key: 'ok', symbol: '✓', n: c.ok, word: 'ok', tone: 'ok' },
    { key: 'caution', symbol: '!', n: c.caution, word: 'caution', tone: c.caution ? 'warn' : 'dim' },
    { key: 'blocked', symbol: '✕', n: c.blocked, word: 'blocked', tone: c.blocked ? 'bad' : 'dim' }
  ]
  if (c.unchecked) items.push({ key: 'unchecked', symbol: '?', n: c.unchecked, word: 'unchecked', tone: 'dim' })
  if (mods?.danger) items.push({ key: 'mod-danger', symbol: '⊗', n: mods.danger, word: mods.dangerWord || 'module danger', tone: 'bad' })
  if (mods?.caution) items.push({ key: 'mod-caution', symbol: '◇', n: mods.caution, word: mods.cautionWord || 'module caution', tone: 'warn' })
  // a zero count stays as symbol + number (quiet); only counts that matter spend the room for their word
  for (const it of items) it.quiet = it.n === 0
  const pinsLabel = `Pins: ${items.map(i => `${i.n} ${i.word}`).join(', ')}`
  // HUD room with module findings and > 2 counts: ok count hidden, only the worst keeps its word (label keeps all)
  const loud = items.filter(i => !i.quiet)
  const worst = loud.find(i => i.tone === 'bad') || loud.find(i => i.tone === 'warn')
  if ((mods?.danger || mods?.caution) && loud.length > 2) {
    for (const it of loud) if (it !== worst) { it.word = ''; it.quiet ||= it.key === 'ok' }
    if (worst?.key === 'mod-danger') worst.word = 'module danger'
    else if (worst?.key === 'mod-caution') worst.word = 'module caution'
  }
  const s = solder || { done: 0, total: 0 }
  const solderText = s.total ? `${s.done}/${s.total}` : '—'
  const solderLabel = s.total ? `Solder: ${s.done} of ${s.total} steps done` : 'Solder: no plan yet'
  const b = build || { tone: 'faint', text: '—' }
  const word = b.text === 'OK' ? 'built' : b.text === 'FAIL' ? 'failed' : 'not built'
  const tone = b.text === 'OK' ? 'ok' : b.text === 'FAIL' ? 'bad' : 'dim'
  const ram = typeof b.ram === 'number' && Number.isFinite(b.ram) ? b.ram : null
  const buildLabel = `Build: ${word}${ram !== null ? `, RAM ${Math.round(ram * 10) / 10} %` : ''}`
  return { pins: { items, label: pinsLabel }, solder: { text: solderText, label: solderLabel }, build: { word, tone, ram, label: buildLabel } }
}
