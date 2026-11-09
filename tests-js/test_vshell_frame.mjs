// Frame of the Bench. lib/art-shell.js (station symbols, rail words, HUD key
// figures as words), the source rules of the frame (audit roots, data-cb-sim, SIM badge never hidden by a container
// query, the HUD sim pill without an outer frame) and the button kinds: kind 'agent' for every Hermes action, kind
// 'danger' only on destructive actions (positive list over ALL desktop-src files).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { shellStationShapes, shellRailWord, shellKpis } from '../desktop-src/lib/art-shell.js'
import { STATIONS } from '../desktop-src/lib/stages.js'
import { build } from '../scripts/build-desktop.mjs'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src')
const read = f => readFileSync(join(SRC, f), 'utf8')
const ALL = [...readdirSync(SRC).filter(f => f.endsWith('.js')), ...readdirSync(join(SRC, 'lib')).filter(f => f.endsWith('.js')).map(f => `lib/${f}`)]
const product = build({ withFixtures: false })

// ─── lib/art-shell.js ───────────────────────────────────────────────────

test('every station has its own symbol; no forbidden SVG parts; unknown id draws nothing', () => {
  const seen = new Set()
  for (const s of STATIONS) {
    const shapes = shellStationShapes(s.id)
    assert.ok(shapes.length >= 1, s.id)
    for (const [tag, attrs] of shapes) {
      assert.ok(['path', 'rect', 'circle'].includes(tag), `${s.id}: ${tag}`)
      for (const k of Object.keys(attrs)) assert.ok(!/^on|href/i.test(k), `${s.id}: ${k}`)
      if (attrs.stroke) assert.equal(attrs.stroke, 'currentColor')
    }
    seen.add(JSON.stringify(shapes))
  }
  assert.equal(seen.size, STATIONS.length, 'symbols are distinct')
  assert.deepEqual(shellStationShapes('nope'), [])
  assert.equal(JSON.stringify(shellStationShapes('plan')), JSON.stringify(shellStationShapes('plan')), 'deterministic')
})

test('rail words: short, a word per state, no word without a project', () => {
  const project = { calcs: [{}, {}], circuits: [{}] }
  const cases = [
    ['plan', { text: '[!]', tone: 'bad' }, { counts: { ok: 2, caution: 0, blocked: 1, unchecked: 0 } }, '3 pins'],
    ['plan', { text: '[!]', tone: 'warn' }, { counts: { ok: 2, caution: 3, blocked: 0, unchecked: 0 } }, '5 pins'],
    ['plan', { text: '[✓]', tone: 'ok' }, { counts: { ok: 1, caution: 0, blocked: 0, unchecked: 0 } }, '1 pin'],
    ['plan', { text: '[ ]', tone: 'faint' }, { counts: { ok: 0, caution: 0, blocked: 0, unchecked: 0 } }, 'no pins'],
    ['calc', { text: '[✓]' }, {}, '2 saved'],
    ['calc', { text: '[ ]' }, {}, 'none yet'],
    ['wire', { text: '[✓]' }, {}, '1 circuit'],
    ['solder', { text: '[✓]' }, { solder: { done: 6, total: 6 } }, 'all done'],
    ['solder', { text: '[ ]' }, { solder: { done: 2, total: 6 } }, '4 to go'],
    ['solder', { text: '[ ]' }, { solder: { done: 0, total: 0 } }, 'no plan'],
    ['solder', { text: '[!]', tone: 'warn' }, { solder: { done: 1, total: 6 } }, 'outdated'],
    ['flash', { text: 'FAIL' }, {}, 'failed'],
    ['flash', { text: 'BUILT' }, {}, 'built'],
    ['flash', { text: '[✓]' }, {}, 'flashed'],
    ['flash', { text: '[ ]' }, {}, 'not built'],
    ['debug', { text: 'PANIC' }, {}, 'to fix'], // shorter, "unresolved" was cut beside PANIC
    ['debug', { text: '[✓]' }, {}, 'fixed'],
    ['debug', { text: '[ ]' }, {}, 'no crash']
  ]
  for (const [id, st, extra, want] of cases) {
    const got = shellRailWord(id, st, { project, ...extra })
    assert.equal(got, want, `${id} ${st.text}`)
    assert.ok(got.length <= 10, `${id}: "${got}" fits the rail`)
  }
  assert.equal(shellRailWord('plan', { text: '[✓]' }, { project: null }), '')
  assert.equal(shellRailWord('plan', null, { project }), '')
})

test('HUD key figures as words: symbol + number + word, full sentence as label, build as a word', () => {
  const k = shellKpis({ ok: 4, caution: 0, blocked: 1, unchecked: 0 }, { done: 3, total: 6 }, { tone: 'ok', text: 'OK', ram: 12.34 })
  assert.deepEqual(k.pins.items.map(i => `${i.symbol} ${i.n} ${i.word}`), ['✓ 4 ok', '! 0 caution', '✕ 1 blocked'])
  assert.deepEqual(k.pins.items.map(i => i.tone), ['ok', 'dim', 'bad'], 'zero counts are quiet, not coloured')
  assert.deepEqual(k.pins.items.map(i => i.quiet), [false, true, false], 'zero counts drop their word in the HUD')
  assert.equal(k.pins.label, 'Pins: 4 ok, 0 caution, 1 blocked')
  assert.equal(k.solder.text, '3/6')
  assert.equal(k.solder.label, 'Solder: 3 of 6 steps done')
  assert.equal(k.build.word, 'built')
  assert.equal(k.build.label, 'Build: built, RAM 12.3 %')
  const u = shellKpis({ ok: 0, caution: 0, blocked: 0, unchecked: 2 }, { done: 0, total: 0 }, { tone: 'bad', text: 'FAIL' })
  assert.equal(u.pins.items.at(-1).word, 'unchecked')
  assert.equal(u.solder.text, '—')
  assert.equal(u.build.word, 'failed')
  assert.equal(u.build.tone, 'bad')
  assert.equal(shellKpis(null, null, null).build.word, 'not built')
  assert.equal(shellKpis(null, null, { text: 'OK', ram: NaN }).build.ram, null)
})

// ─── frame sources ──────────────────────────────────────────────────────

test('audit roots: hud, rail and bench carry data-cb-audit-root; the bench root carries data-cb-sim from the project', () => {
  assert.match(read('30-ui-hud.js'), /'data-cb': 'hud', 'data-cb-audit-root': 'hud'/)
  assert.match(read('30-ui-rail.js'), /'data-cb': 'rail', 'data-cb-audit-root': 'rail'/)
  const bench = read('30-ui-bench.js')
  assert.match(bench, /'data-cb': 'bench-root', 'data-cb-audit-root': 'bench'/)
  assert.match(bench, /'data-cb-sim': project \? \(project\.simulated \? 'true' : 'false'\) : undefined/)
  // the inspector root is the station aside [data-cb=insp] (fallback of the audit); an explicit root of that name may
  // only sit on that aside itself (CALC, SOLDER), never on a part inside it
  const all = (product.match(/'data-cb-audit-root': 'inspector'/g) || []).length
  const onAside = (product.match(/'data-cb': 'insp', 'data-cb-audit-root': 'inspector'/g) || []).length
  assert.equal(all, onAside)
})

test('HUD: the sim link is the SIM badge without an outer pill frame; no override for it in the kit styles', () => {
  const hud = read('30-ui-hud.js')
  assert.ok(!hud.includes('cb-pill--sim'), 'no pill class on the sim link')
  assert.match(hud, /className: 'cb-hudsim', 'data-cb': 'hud-link'/)
  assert.match(hud, /h\(SimBadge, \{ dataCb: 'sim-banner-hud' \}\)/)
  assert.ok(!/cb-pill--sim/.test(read('13-styles-kit.js')))
  assert.ok(!/cb-pill--sim/.test(read('12-styles.js')))
})

/** CSS rules with display:none inside @container blocks of a style file → the selectors */
function hiddenInContainers(css) {
  const out = []
  const re = /@container[^{]*\{((?:[^{}]*\{[^{}]*\})*)[^{}]*\}/g
  for (const m of css.matchAll(re)) {
    for (const r of m[1].matchAll(/([^{}]+)\{([^{}]*)\}/g)) if (/display:\s*none/.test(r[2])) out.push(...r[1].split(',').map(s => s.trim()))
  }
  return out
}

test('SIMULATED stays visible in narrow containers: no container query hides the badge or its word', () => {
  // self-check of the parser: it finds a hidden badge inside a container block
  assert.deepEqual(hiddenInContainers('@container x (max-width:9px){.cb-root .a{color:red}.cb-root .cb-simban{display:none}}'), ['.cb-root .cb-simban'])
  for (const f of ['11-styles-ui2.js', '12-styles.js', '13-styles-kit.js']) {
    const sels = hiddenInContainers(read(f))
    const bad = sels.filter(s => /\.cb-simban(?!-[wl])\b|\.cb-simbadge(?!-s)\b|sim-banner|sim-badge/.test(s) && !/\.cb-simban-w|\.cb-simbadge-s/.test(s))
    assert.deepEqual(bad, [], f)
  }
  // the console's narrow rule only drops the word BOARD (12-styles.js, container cbcons < 760 px)
  assert.match(read('12-styles.js'), /@container cbcons \(max-width:760px\)\{\.cb-root \.cb-tabs \.cb-meta > \.cb-simban \.cb-simban-w\{display:none\}/)
})

test('the project list marks simulated projects with the SIM badge (not a plain tag)', () => {
  const d = read('46-dialogs.js')
  assert.match(d, /p\.simulated \? h\(SimBadge, \{ compact: true, dataCb: 'sim-badge-project' \}\) : null,\s*h\('span', \{ className: 'cb-ellip'/)
  assert.ok(!/'SIM'\)/.test(d))
})

// ─── button kinds ───────────────────────────────────────────────────────

/** Every Btn call with its kind and data-cb in a source file. */
function btnCalls(src) {
  const out = []
  for (const m of src.matchAll(/h\(Btn, \{([^}]*)\}/g)) {
    const kind = /kind: '([a-z]+)'/.exec(m[1])?.[1] || 'primary'
    const cb = /'data-cb': '([a-z0-9-]+)'/.exec(m[1])?.[1] || null
    out.push({ kind, cb, body: m[1] })
  }
  return out
}

// destructive actions: the only places kind 'danger' may stand
const DANGER_OK = new Set(['project-delete-confirm', 'part-remove-confirm'])
// Hermes actions in 30-ui-panic.js and 45-station-debug.js that may still be kind 'danger'. The set is empty: every
// Fix with Hermes button is kind 'agent'.
const DANGER_PENDING_V_DEBUG = new Set() // empty: Fix with Hermes is kind 'agent'
// actions that hand a draft to Hermes (composeDraft) — these must be kind 'agent'
const AGENT_REQUIRED = ['ask-hermes', 'ask-create']

test('kind danger only on destructive actions (positive list over all desktop-src files)', () => {
  const found = []
  for (const f of ALL) {
    const src = read(f)
    for (const b of btnCalls(src)) if (b.kind === 'danger') found.push({ f, cb: b.cb })
    // no hand-made danger buttons beside Btn
    if (!/^1[0-9]-styles/.test(f)) assert.ok(!/['"`][^'"`]*cb-btn--danger/.test(src), `${f}: cb-btn--danger outside Btn`)
  }
  const bad = found.filter(x => !DANGER_OK.has(x.cb) && !DANGER_PENDING_V_DEBUG.has(x.cb))
  assert.deepEqual(bad, [], 'kind danger outside the positive list')
  for (const cb of DANGER_OK) assert.ok(found.some(x => x.cb === cb), `${cb} still destructive and still danger`)
})

test('Hermes actions are kind agent', () => {
  const calls = ALL.flatMap(f => btnCalls(read(f)).map(b => ({ f, ...b })))
  for (const cb of AGENT_REQUIRED) {
    const c = calls.filter(x => x.cb === cb)
    assert.ok(c.length >= 1, cb)
    for (const x of c) assert.equal(x.kind, 'agent', `${x.f}: ${cb}`)
  }
  // every Btn that drafts into the composer is an agent action (or one of the pending ones above)
  for (const f of ALL) {
    for (const b of btnCalls(read(f))) {
      if (/composeDraft\(/.test(b.body) && !DANGER_PENDING_V_DEBUG.has(b.cb)) assert.equal(b.kind, 'agent', `${f}: ${b.cb}`)
    }
  }
})

test('one scale: buttons 24 / 28 / 32 px, icon buttons 24 px', () => {
  const css = read('12-styles.js')
  assert.match(css, /\.cb-root \.cb-btn\{[^}]*height:28px/)
  assert.match(css, /\.cb-root \.cb-btn--sm\{height:24px/)
  assert.match(css, /\.cb-root \.cb-btn--lg\{height:32px/)
  assert.match(css, /\.cb-root \.cb-iconbtn\{[^}]*height:24px/)
})

test('assignment table: fixed layout with a column per field (no horizontal scroll in the inspector)', () => {
  assert.match(read('30-ui-assign.js'), /className: 'cb-table cb-table--assign'/)
  assert.match(read('30-ui-assign.js'), /h\('colgroup'/)
  assert.match(read('13-styles-kit.js'), /\.cb-root \.cb-table--assign\{table-layout:fixed\}/)
})

test('inspector: alternatives as chips under "use instead", source in the card foot', () => {
  const s = read('30-ui-inspector.js')
  assert.match(s, /'data-cb': 'alternatives'/)
  assert.match(s, /className: 'cb-chipbtn cb-altchip',\s*'data-cb': `alt-\$\{a\}`/)
  assert.match(s, /use instead/)
  assert.match(s, /className: 'cb-card-foot' \}, h\(SourceLine/)
  // order: verdict → why → way out → functions
  const at = k => s.indexOf(k)
  assert.ok(at("'data-cb': 'verdict-stamp'") < at("'data-cb': 'inspector-why'"))
  assert.ok(at("'data-cb': 'inspector-why'") < at("'data-cb': 'insp-way'"))
  assert.ok(at("'data-cb': 'insp-way'") < at("'data-cb': 'pin-functions'"))
})
