// Net classes, hover coupling net ↔ row and part ↔ row, the fitted plan's
// smallest scale, the SVG attributes of the regenerated fixture, the styles per data-kind / data-net.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  WIRE_RAILS, WIRE_GROUND, wireNetClass, wiringRows, svgRefs, svgViewBox, sanitizeSvg, wireHl, wireHlHas,
  wireHoverTarget, wireRowOn, wireRowHl, wireWarnings, wireHlKey
} from '../desktop-src/lib/wire.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = p => readFileSync(join(ROOT, p), 'utf8')
const fixture = JSON.parse(read('desktop-src/fixtures/schematic.npn.json'))
const sch = fixture.result

/** Children of the flat backend SVG: [{tag, attrs, text}] (the SVG has one level below the root). */
function svgChildren(svg) {
  const body = svg.replace(/^<svg\b[^>]*>/, '').replace(/<\/svg>\s*$/, '')
  const out = []
  for (const m of body.matchAll(/<([a-z]+)\b([^>]*?)(\/>|>([^<]*)<\/\1>)/g)) {
    const attrs = Object.fromEntries([...m[2].matchAll(/([a-zA-Z:-]+)=(["'])(.*?)\2/g)].map(a => [a[1], a[3]]))
    out.push({ tag: m[1], attrs, text: m[4] ?? null })
  }
  return out
}
const els = svgChildren(sch.svg)

test('rails and ground mirror bench_core/wiring.py; net classes', () => {
  const py = read('circuit_bench/bench_core/wiring.py')
  assert.match(py, new RegExp(`^RAILS = \\(${WIRE_RAILS.map(r => `"${r}"`).join(', ')}\\)$`, 'm'))
  assert.match(py, new RegExp(`^GROUND = "${WIRE_GROUND}"$`, 'm'))
  assert.deepEqual(['5V', '3V3', 'GND', 'LASER_EN', 'VIN'].map(wireNetClass), ['power', 'power', 'ground', 'signal', 'signal'])
  assert.deepEqual(wiringRows(sch.wiring).map(r => r.netClass), ['signal', 'signal', 'signal', 'signal', 'power', 'ground', 'ground'])
})

test('fixture SVG (regenerated from the backend): every element has its role, nets and refs, stays safe', () => {
  assert.equal(sanitizeSvg(sch.svg).ok, true)
  assert.ok(els.length > 20, els.length)
  const kinds = new Set(['wire', 'body', 'pin', 'label', 'port', 'junction'])
  const nets = new Set(sch.nets.map(n => n.name))
  for (const e of els) {
    assert.ok(kinds.has(e.attrs['data-kind']), JSON.stringify(e))
    if (['wire', 'port', 'junction'].includes(e.attrs['data-kind'])) assert.ok(nets.has(e.attrs['data-net']), JSON.stringify(e))
    if (e.attrs['data-kind'] === 'body') assert.match(e.attrs['data-ref'], /^[A-Z]+\d+$/)
  }
  // every net is drawn, so a hovered row always lights something in the plan
  assert.deepEqual(new Set(els.filter(e => e.attrs['data-kind'] === 'wire' || e.attrs['data-kind'] === 'port').map(e => e.attrs['data-net'])), nets)
  assert.deepEqual(svgRefs(sch.svg), ['R1', 'R2', 'Q1', 'J2'])
  assert.deepEqual(svgRefs('<svg><rect data-ref="R7"/><rect data-ref=\'Q2\'/></svg>'), ['R7', 'Q2'])
  // net labels at the port and the header pins of the rails
  const texts = els.filter(e => e.tag === 'text').map(e => e.text)
  for (const t of ['LASER_EN', 'J1-20 · IO14', '+5 V', 'J1-21 · 5V', 'J1-22 · G']) assert.ok(texts.includes(t), t)
})

test('fit: the plan never goes below scale 1, so the smallest text (font-size 10) stays ≥ 10 px', () => {
  const vb = svgViewBox(sch.svg)
  assert.deepEqual(vb, { x: -101, y: -178, w: 414, h: 314 })
  const sizes = els.filter(e => e.tag === 'text').map(e => Number(e.attrs['font-size']))
  assert.equal(Math.min(...sizes), 10)
  assert.equal(svgViewBox('<svg viewBox="0 0 0 5"></svg>'), null)
  assert.equal(svgViewBox('<svg></svg>'), null)
  const src = read('desktop-src/42-station-wire.js')
  // minimum size = viewBox in px (scale ≥ 1), the stage grows with it instead of shrinking the plan
  assert.match(src, /minWidth: `\$\{vb\.w\}px`, minHeight: `\$\{vb\.h\}px`/)
  assert.match(src, /className: 'cb-svgstage', style: vb \? \{ minHeight: `\$\{vb\.h\}px` \}/)
})

test('hover coupling net ↔ row and part ↔ row (both directions)', () => {
  const rows = wiringRows(sch.wiring)
  const on = hl => rows.filter(r => wireRowOn(hl, r)).map(r => r.i)
  const lit = hl => els.filter(e => wireHlHas(hl, { ref: e.attrs['data-ref'], net: e.attrs['data-net'], pin: e.attrs['data-pin'] }))
  // plan → table: a wire of LASER_BASE lights both LASER_BASE rows; the part R2 lights its rows
  const node = (attrs, parent = null) => ({ attrs, parentNode: parent, getAttribute: k => attrs[k] ?? null })
  const stop = node({})
  const wire = els.find(e => e.attrs['data-kind'] === 'wire' && e.attrs['data-net'] === 'LASER_BASE')
  assert.deepEqual(wireHoverTarget(node(wire.attrs, stop), stop), { refs: [], net: 'LASER_BASE' })
  assert.deepEqual(on(wireHoverTarget(node(wire.attrs, stop), stop)), [1, 2])
  assert.deepEqual(on(wireHl(['R2'])), [2, 5])
  assert.deepEqual(on(wireHl([], 'GND')), [5, 6])
  // a pin marker belongs to its part, a net label to its net, nothing under the pointer → no highlight
  assert.deepEqual(wireHoverTarget(node({ 'data-pin': 'Q1.B' }, stop), stop), { refs: ['Q1'], net: null })
  const label = els.find(e => e.text === 'J1-21 · 5V')
  assert.deepEqual(wireHoverTarget(node(label.attrs, stop), stop), { refs: [], net: '5V' })
  assert.equal(wireHoverTarget(node({}, stop), stop), null)
  // table → plan: row 1 (R1.2 → Q1.B, LASER_BASE) lights the net's wires and junction and both parts with their pins
  const hl = wireRowHl(rows[1], sch.parts)
  assert.deepEqual(hl, { refs: ['R1', 'Q1'], net: 'LASER_BASE' })
  const l = lit(hl)
  assert.ok(l.some(e => e.attrs['data-kind'] === 'wire' && e.attrs['data-net'] === 'LASER_BASE'))
  assert.ok(l.some(e => e.attrs['data-kind'] === 'junction'))
  assert.ok(l.some(e => e.tag === 'rect' && e.attrs['data-ref'] === 'Q1'))
  assert.ok(l.some(e => e.attrs['data-pin'] === 'Q1.B'))
  assert.ok(!l.some(e => e.attrs['data-ref'] === 'R2' || e.attrs['data-net'] === 'GND'))
  // the board header J1 of row 0 is no part: only R1 and the net LASER_EN
  assert.deepEqual(wireRowHl(rows[0], sch.parts), { refs: ['R1'], net: 'LASER_EN' })
  assert.equal(wireHl([], 'bad net!'), null)
  assert.equal(wireHlHas(null, { ref: 'R1' }), false)
})

test('warnings: danger/caution as cards under the parts, info stays in the list; the text is unchanged', () => {
  const w = wireWarnings(fixture.warnings)
  assert.deepEqual(w.cards.map(x => x.code), ['laser_safety'])
  assert.equal(w.cards[0].message, 'Laser modules can damage eyes. Never look into the beam.')
  assert.deepEqual(w.notes.map(x => x.code), ['transistor_pinout'])
  const src = read('desktop-src/42-station-wire.js')
  const parts = src.indexOf("'data-cb': 'wire-parts'")
  const card = src.indexOf("'data-cb': 'wire-warning'")
  assert.ok(parts > 0 && card > parts, 'warning card after the parts')
  assert.match(src, /h\('p', \{ className: 'cb-wwarn-t' \}, w\.message\)/)
})

test('Save SVG sits in the plan header, not in the block toolbar', () => {
  const src = read('desktop-src/42-station-wire.js')
  const toolbar = src.slice(src.indexOf("h('div', { className: 'cb-toolbar' }"), src.indexOf("env && !env.ok"))
  assert.ok(!toolbar.includes('wire-save'))
  assert.match(src, /actions: h\(Btn, \{ kind: 'quiet', size: 'sm', 'data-cb': 'wire-save'/)
  assert.match(src, /className: 'cb-svghead'[\s\S]*actions \? h\('span', \{ className: 'cb-svghead-act' \}, actions\)/)
})

test('styles: stroke widths per data-kind, net colours per data-net, active on hover; no own colour values', () => {
  const css = read('desktop-src/15-styles-wire.js')
  assert.match(css, /\[data-kind=wire\]\{stroke-width:1\.5px\}/)
  assert.match(css, /\.cb-root \.cb-svg svg \[data-kind=body\],\.cb-root \.cb-svg svg \[data-kind=port\]\{stroke-width:2px\}/)
  assert.match(css, /vector-effect:non-scaling-stroke/)
  for (const r of WIRE_RAILS) assert.ok(css.includes(`[data-net="${r}"]`), r)
  assert.match(css, new RegExp(`\\[data-net=${WIRE_GROUND}\\]\\{color:var\\(--cb-fg-dim\\)\\}`))
  assert.match(css, /\[data-net="5V"\]\{color:var\(--cb-power-text\)\}/)
  assert.match(css, /\[data-cb-on=true\]\{color:var\(--cb-active-text\)\}/)
  assert.ok(!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(css), 'only --cb-* tokens')
  // the pulse runs only without reduced motion
  assert.match(css, /@media \(prefers-reduced-motion:no-preference\)\{\s*\.cb-root \.cb-svg svg \[data-kind=wire\]\[data-cb-on=true\]\{animation:cb-wire-pulse/)
})

test('highlight marks survive re-renders: one {__html} object per SVG, marks after every commit, equal highlights keep state', () => {
  // React 19 writes innerHTML again for a new dangerouslySetInnerHTML object, which drops the data-cb-on marks
  const src = read('desktop-src/42-station-wire.js')
  assert.match(src, /const html = useMemo\(\(\) => \(\{ __html: safe\.ok \? safe\.svg : '' \}\), \[safe\.ok \? safe\.svg : ''\]\)/)
  assert.match(src, /dangerouslySetInnerHTML: html \}/)
  assert.match(src, /el\.removeAttribute\('data-cb-on'\)\n    \}\n  \}\)/, 'the marking effect has no dependency list')
  assert.match(src, /setHlRaw\(prev => wireHlKey\(prev\) === wireHlKey\(next\) \? prev : next\)/)
  assert.equal(wireHlKey(null), '')
  assert.equal(wireHlKey(wireHl(['R1', 'Q1'], 'LASER_BASE')), 'R1,Q1|LASER_BASE')
  assert.equal(wireHlKey(wireHl(['R1'])), wireHlKey({ refs: ['R1'], net: null }))
})
