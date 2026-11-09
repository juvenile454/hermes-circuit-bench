// Mini schematics of the six calculators (lib/art-calc.js) and the result model of the cards (lib/calc.js
// calcBands, calcChips, calcSteps, calcFormulaLines). Every drawn value is a `display` text of the fixture answer; a
// missing field drops its part without an error; no NaN anywhere; the SVG passes the sanitizeSvg list.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { CALC_DEFS, calcDef, calcBands, calcChips, calcSteps, calcFormulaLines, calcView, calcCheckTone, valueTone } from '../desktop-src/lib/calc.js'
import { sanitizeSvg } from '../desktop-src/lib/wire.js'

// lib files share one scope in the bundle; the SVG helpers (artEl, artEsc, artNum) live in art.js (one
// set of helpers), so the test module concatenates the files like the build does
const __libSrc = ['art.js', 'art-calc.js'].map(f => readFileSync(new URL(`../desktop-src/lib/${f}`, import.meta.url), 'utf8')).join('\n')
const __lib = await import(`data:text/javascript;base64,${Buffer.from(__libSrc).toString('base64')}`)
const { calcArt, calcArtDisp, CALC_ART_W } = __lib

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
// a schematic is required for the six basic calculators only; further
// calculators may come without one (generic cards)
const BASIC = ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo']
const TYPES = CALC_DEFS.map(d => d.type).filter(t => BASIC.includes(t))
const clone = x => JSON.parse(JSON.stringify(x))
const unesc = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
/** Text content of the <text> elements (tspans joined). */
const texts = svg => [...svg.matchAll(/<text\b[^>]*>(.*?)<\/text>/g)].map(m => unesc(m[1].replace(/<[^>]+>/g, '')))

// what each schematic must carry from its fixture (display texts or plain strings of the answer)
const EXPECT = {
  led: r => [r.inputs.v_supply.display, r.r_chosen.display, r.i_actual.display, r.inputs.v_f.display],
  npn: r => [r.inputs.v_drive.display, r.inputs.r_base.display, r.inputs.r_pulldown.display, r.inputs.i_load.display, r.i_b.display, r.forced_beta.display, r.inputs.part],
  divider: r => [r.inputs.v_in_max.display, r.inputs.r1.display, r.inputs.r2.display, r.v_out_max.display, r.i_div.display, r.r_source.display],
  i2c_pullup: r => [r.inputs.v_dd.display, r.suggested.display, r.inputs.c_bus.display, r.suggested_t_r.display],
  mosfet: r => [r.inputs.v_supply.display, r.inputs.gate_v.display, r.inputs.r_gate.display, r.inputs.r_pulldown.display, r.inputs.i_load.display, r.v_gs.display, r.p_loss.display, r.v_ds_on.display, r.inputs.part],
  ldo: r => [r.inputs.v_in.display, r.inputs.v_out.display, r.inputs.i_load.display, r.p_total.display, r.efficiency.display, r.inputs.part]
}

test('a schematic per calculator with the values of its fixture (display texts only)', () => {
  assert.deepEqual(Object.keys(EXPECT), BASIC)
  assert.deepEqual(TYPES, BASIC, 'the six basic calculators are all defined')
  for (const t of TYPES) {
    const env = fx(`calc.${t}`)
    const a = calcArt(t, env, { tone: valueTone(env.checks) })
    assert.ok(a, t)
    assert.match(a.svg, /^<svg [^>]*width="288"/, t)
    assert.equal(sanitizeSvg(a.svg).ok, true, `${t}: ${sanitizeSvg(a.svg).reason}`)
    assert.ok(!/NaN|undefined|null|\[object/.test(a.svg), `${t}: no NaN/undefined in the SVG`)
    const all = texts(a.svg).join(' | ')
    for (const want of EXPECT[t](env.result)) assert.ok(all.includes(want), `${t}: ${want} in ${all}`)
    // nothing numeric the answer did not say: every value text of the drawing is one of the answer's texts
    const answer = JSON.stringify(env.result)
    for (const v of a.values) assert.ok(answer.includes(JSON.stringify(v).slice(1, -1)) || answer.includes(v.replace(/^load /, '')), `${t}: ${v} from the answer`)
    assert.match(a.label, /^Schematic: /)
    for (const k of a.shown) assert.ok(calcArtDisp(env.result[k]), `${t}: shown key ${k} has a display`)
  }
})

test('schematics are deterministic, escaped, colours only as tokens, text never below 10 px', () => {
  for (const t of TYPES) {
    const env = fx(`calc.${t}`)
    assert.equal(calcArt(t, env).svg, calcArt(t, clone(env)).svg, t)
    const a = calcArt(t, env)
    assert.ok(!/#[0-9a-f]{3,8}\b/i.test(a.svg.replace(/url\(#[^)]+\)/g, '')), `${t}: no fixed colour values`)
    for (const m of a.svg.matchAll(/font-size="([\d.]+)"/g)) assert.ok(Number(m[1]) >= 10, `${t}: font ${m[1]}`)
  }
  const env = fx('calc.npn')
  env.result.inputs.part = '<b>"&'
  env.result.inputs.load = '<script>'
  const svg = calcArt('npn', env).svg
  assert.ok(!svg.includes('<script>') && !svg.includes('<b>'))
  assert.ok(svg.includes('&lt;b&gt;&quot;&amp;') && svg.includes('load &lt;script&gt;'))
  assert.equal(sanitizeSvg(svg).ok, true)
})

test('labels stay inside the drawing (shifted, never cut); a label that cannot fit drops', () => {
  for (const t of TYPES) {
    const a = calcArt(t, fx(`calc.${t}`))
    for (const m of a.svg.matchAll(/<text x="([\d.-]+)"[^>]*>(.*?)<\/text>/g)) {
      const x = Number(m[1])
      const w = [...unesc(m[2].replace(/<[^>]+>/g, ''))].length * 0.6 * 11
      assert.ok(x >= 2 && x + w <= CALC_ART_W + 1, `${t}: ${m[2]} at ${x}`)
    }
  }
  const env = fx('calc.npn')
  env.result.inputs.part = 'X'.repeat(40)
  assert.ok(!texts(calcArt('npn', env).svg).some(s => s.includes('XXXX')), 'a 40-character part name does not fit and drops')
})

test('missing fields drop their labels without an error; before a result the circuit draws without values', () => {
  for (const t of TYPES) {
    const empty = calcArt(t, null)
    assert.ok(empty && sanitizeSvg(empty.svg).ok, t)
    assert.deepEqual(empty.values, [], `${t}: no values without an answer`)
    assert.deepEqual(empty.shown, [])
    assert.ok(!/\d/.test(texts(empty.svg).join('').replace(/R1|R2|V_DD|R_PD|R_B|R_G/g, '')), `${t}: no numbers before a result: ${texts(empty.svg)}`)
    // an answer with holes: every quantity without its display text
    const env = clone(fx(`calc.${t}`))
    const strip = o => { for (const [k, v] of Object.entries(o)) { if (v && typeof v === 'object') { if ('display' in v) delete v.display; strip(v) } } }
    strip(env.result)
    const a = calcArt(t, env)
    assert.ok(!/NaN|undefined/.test(a.svg), t)
    assert.deepEqual(a.shown, [], `${t}: nothing shown without display texts`)
    // a failed answer draws the bare circuit
    assert.deepEqual(calcArt(t, { ok: false, error: { code: 'invalid_args' } }).values, [])
    assert.equal(calcArt(t, { ok: true, result: 'garbage' }).values.length, 0)
  }
  assert.equal(calcArt('nope', fx('calc.led')), null)
})

test('result tone: the chosen value in the schematic carries the tone of the worst check, a failure never green', () => {
  const env = fx('calc.led')
  assert.match(calcArt('led', env, { tone: 'ok' }).svg, /fill="var\(--cb-ok-text\)"[^>]*>150 Ω/)
  const bad = clone(env)
  bad.checks[0].status = 'failed'
  const tone = valueTone(bad.checks)
  assert.equal(tone, 'bad')
  const svg = calcArt('led', bad, { tone }).svg
  assert.match(svg, /fill="var\(--cb-bad-text\)"[^>]*>150 Ω/)
  assert.ok(!svg.includes('--cb-ok'), 'no green in a failed result')
  assert.equal(calcCheckTone('failed'), 'bad')
  assert.equal(calcCheckTone('not_checked'), 'fg')
  assert.equal(calcCheckTone('passed'), 'ok')
})

test('LED bands: ruler exact → E12 with only r_exact, r_chosen, r_deviation; power meter labelled like the assumption', () => {
  const env = fx('calc.led')
  const [ruler, meter] = calcBands(calcDef('led'), env)
  assert.deepEqual(ruler, { kind: 'ruler', id: 'r', keys: ['r_exact', 'r_chosen', 'r_deviation'], from: { label: 'exact', display: '130 Ω' },
    to: { label: 'E12', display: '150 Ω' }, delta: '+15.4 %', down: false })
  assert.equal(meter.kind, 'meter')
  assert.equal(meter.value, '11.3 mW')
  assert.equal(meter.limit, '22.5 mW')
  assert.ok(Math.abs(meter.frac - 0.5) < 0.01, 'P_R is half the rating (drawing position only)')
  const a = env.assumptions.find(x => x.key === 'p_rating')
  assert.deepEqual(meter.note, { lead: 'rating =', value: a.value, reason: a.reason }, 'note verbatim from the assumption')
  // without the assumption no rule-of-thumb label is invented
  const noA = clone(env)
  noA.assumptions = noA.assumptions.filter(x => x.key !== 'p_rating')
  assert.equal(calcBands(calcDef('led'), noA)[1].note, null)
  // missing fields drop the band; a zero rating cannot be drawn (frac null, no NaN)
  const holes = clone(env)
  delete holes.result.r_exact
  holes.result.p_rating_min.value = 0
  const b = calcBands(calcDef('led'), holes)
  assert.deepEqual(b.map(x => x.kind), ['meter'])
  assert.equal(b[0].frac, null)
  const noVal = clone(env)
  delete noVal.result.p_r.value
  assert.equal(calcBands(calcDef('led'), noVal)[1].frac, null)
  assert.ok(!JSON.stringify(calcBands(calcDef('led'), noVal)).includes('NaN'))
})

test('thermal meters (LDO, MOSFET) and the I²C window come from the answer, tone from their check', () => {
  const ldo = calcBands(calcDef('ldo'), fx('calc.ldo'))
  assert.equal(ldo.length, 1)
  assert.equal(ldo[0].value, '106 °C')
  assert.equal(ldo[0].limit, '125 °C')
  assert.equal(ldo[0].start, '25.0 °C')
  assert.equal(ldo[0].tone, 'ok')
  assert.ok(ldo[0].frac > 0.8 && ldo[0].frac < 0.85)
  assert.equal(ldo[0].note.value, '90.0 °C/W')
  const hot = fx('calc.ldo')
  hot.checks.find(c => c.id === 'calc.ldo.t_j').status = 'failed'
  assert.equal(calcBands(calcDef('ldo'), hot)[0].tone, 'bad')
  const fet = calcBands(calcDef('mosfet'), fx('calc.mosfet'))
  assert.equal(fet[0].value, '49.0 °C')
  assert.equal(fet[0].limit, '150 °C')
  const noAmb = fx('calc.mosfet')
  delete noAmb.result.inputs.t_ambient
  assert.equal(calcBands(calcDef('mosfet'), noAmb)[0].frac, null)
  assert.equal(calcBands(calcDef('mosfet'), noAmb)[0].start, null)
  const noPart = fx('calc.mosfet')
  delete noPart.result.part
  assert.deepEqual(calcBands(calcDef('mosfet'), noPart), [])
  const [w] = calcBands(calcDef('i2c_pullup'), fx('calc.i2c_pullup'))
  assert.equal(w.kind, 'window')
  assert.deepEqual([w.min.display, w.mark, w.max.display], ['967 Ω', '3.30 kΩ', '11.8 kΩ'])
  assert.ok(w.frac > 0.4 && w.frac < 0.6, 'the geometric middle sits mid-window (log track)')
  assert.equal(w.tone, 'ok')
  for (const t of ['npn', 'divider']) assert.deepEqual(calcBands(calcDef(t), fx(`calc.${t}`)), [], `${t}: no band without a limit in the answer`)
  for (const t of TYPES) {
    assert.deepEqual(calcBands(calcDef(t), null), [])
    assert.deepEqual(calcBands(calcDef(t), { ok: false, error: {} }), [])
    assert.ok(!JSON.stringify(calcBands(calcDef(t), fx(`calc.${t}`))).includes('NaN'))
  }
})

test('check chips: symbol + name + word; failed never green; unknown status neutral', () => {
  const c = calcChips(fx('calc.divider').checks)
  assert.deepEqual(c, [{ id: 'calc.divider.adc_range', name: 'adc range', status: 'not_checked', word: 'not checked', sym: '?', tone: 'dim',
    detail: 'give adc_range ([min, max] in V, e.g. [0, 2.9]) to compare with the ADC input range' }])
  const fet = calcChips(fx('calc.mosfet').checks)
  assert.deepEqual(fet.map(x => `${x.sym} ${x.name} ${x.word}`), ['✓ logic level passed', '✓ v ds max passed', '✓ i d max passed', '✓ t j passed', '✓ gate network passed'])
  const mixed = calcChips([{ id: 'calc.x.a', status: 'failed', detail: 'no' }, { id: 'calc.x.b', status: 'weird' }, { status: 'skipped' }, null])
  assert.deepEqual(mixed.map(x => [x.sym, x.word, x.tone]), [['✕', 'failed', 'bad'], ['?', 'unknown', 'dim'], ['○', 'skipped', 'dim']])
  assert.ok(!mixed.some(x => x.status === 'failed' && x.tone === 'ok'))
  assert.deepEqual(calcChips(undefined), [])
})

test('formula drawer: one line per equation, steps as rows (name, expression, value) from steps[]', () => {
  const v = calcView(calcDef('led'), fx('calc.led'))
  assert.deepEqual(calcFormulaLines(v.formula), ['R = (V_supply − V_f) / I_f', 'I = (V_supply − V_f) / R_chosen', 'P_R = I² · R_chosen'])
  assert.deepEqual(calcSteps(v.steps)[0], { name: 'R', expr: '(3.30 V − 2.00 V) / 10.0 mA', value: '130 Ω' })
  assert.equal(calcSteps(v.steps).length, 5)
  assert.deepEqual(calcSteps([{ name: 'x' }, { expr: 'no name' }, null, { name: 'y', expr: 'a', value: { value: 1 } }]),
    [{ name: 'x', expr: '', value: '' }, { name: 'y', expr: 'a', value: '' }])
  assert.deepEqual(calcFormulaLines(null), [])
  for (const t of TYPES) assert.ok(calcSteps(fx(`calc.${t}`).result.steps).every(s => s.value && s.expr), t)
})

test('the station renders the schematic through the art library and keeps the E2E anchors', () => {
  const src = readFileSync(join(ROOT, 'desktop-src', '41-station-calc.js'), 'utf8')
  for (const anchor of ['calc-run-', 'calc-result-', 'calc-formula-', 'calc-add-', 'calc-value-', 'calc-art-', 'calc-assume-', 'calc-src', 'project-calcs', 'project-parts', 'part-remove']) {
    assert.ok(src.includes(anchor), anchor)
  }
  assert.match(src, /calcArt\(def\.type/)
  assert.match(src, /className: `cb-calc-big/)
  // the station computes nothing: no arithmetic on answer values in the card (positions come from lib/calc.js)
  assert.ok(!/\.value\s*[*/+-]\s*[\d.(]/.test(src.replace(/b\.frac \* 100/g, '')), 'no arithmetic on values')
  const css = readFileSync(join(ROOT, 'desktop-src', '17-styles-calc.js'), 'utf8')
  assert.equal((css.match(/CB_CSS_PARTS\.push\(/g) || []).length, 1)
  assert.ok(!/#[0-9a-f]{3,8}\b/i.test(css), 'tokens only')
})

test('unit in the field only when the typed text does not carry it; verdict counted from the checks', async () => {
  const { calcTypedUnit, calcVerdict } = await import('../desktop-src/lib/calc.js')
  assert.equal(calcTypedUnit('10mA', 'A'), true)
  assert.equal(calcTypedUnit('3V3', 'V'), true)
  assert.equal(calcTypedUnit('100pF', 'F'), true)
  assert.equal(calcTypedUnit('4k7', 'Ω'), false)
  assert.equal(calcTypedUnit('4k7 ohm', 'Ω'), true)
  assert.equal(calcTypedUnit('3.3', 'V'), false)
  assert.equal(calcTypedUnit('', 'A'), false)
  assert.deepEqual(calcVerdict(fx('calc.npn').checks), ['✓', 'all 3 passed', 'ok'])
  assert.deepEqual(calcVerdict(fx('calc.led').checks), ['✓', 'check passed', 'ok'])
  assert.deepEqual(calcVerdict(fx('calc.divider').checks), ['?', '1 of 1 not checked', 'dim'])
  assert.deepEqual(calcVerdict([{ status: 'passed' }, { status: 'failed' }, { status: 'skipped' }]), ['✕', '1 of 3 failed', 'bad'])
  assert.equal(calcVerdict([]), null)
  assert.equal(calcVerdict(undefined), null)
})

test('calculators beyond the six basics may come without a schematic (null), never with a broken one', () => {
  for (const t of CALC_DEFS.map(d => d.type).filter(x => !BASIC.includes(x))) {
    const a = calcArt(t, null)
    assert.ok(a === null || sanitizeSvg(a.svg).ok, `${t}: no schematic or a clean one`)
  }
  assert.equal(calcArt('ina_shunt', null), null, 'a calculator without art draws nothing (generic card)')
})
