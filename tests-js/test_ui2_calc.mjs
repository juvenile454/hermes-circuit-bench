// Calculator input parser (desktop-src/lib/units.js, mirror of bench_core/units.py) and the calculator
// model of station 02 (lib/calc.js): request bodies, result view, project ops (add_calc + add_parts).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseQuantity, parseRaw } from '../desktop-src/lib/units.js'
import { CALC_DEFS, calcDef, buildCalcBody, calcView, calcOps, nextRef, nextCalcId, initialForm } from '../desktop-src/lib/calc.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const project = fx('project.laser-trigger').result.project

test('quantities: SI prefixes, units, RKM codes (same grammar as bench_core/units.py)', () => {
  const ok = (t, u, v) => {
    const q = parseQuantity(t, u)
    assert.equal(q.ok, true, `${t}: ${q.error}`)
    assert.ok(Math.abs(q.value - v) <= Math.abs(v) * 1e-12, `${t} → ${q.value}, want ${v}`)
  }
  ok('4k7', 'Ω', 4700); ok('4.7 kΩ', 'Ω', 4700); ok('4.7k', 'Ω', 4700); ok('10mA', 'A', 0.01); ok('3V3', 'V', 3.3)
  ok('100nF', 'F', 1e-7); ok('2.2e-6', 'F', 2.2e-6); ok('1R5', 'Ω', 1.5); ok('R47', 'Ω', 0.47); ok('2u2', 'F', 2.2e-6)
  ok('2.2 µF', 'F', 2.2e-6); ok('1M', 'Ω', 1e6); ok('1 ohm', 'Ω', 1); ok('13 mA', 'A', 0.013); ok('3.3', 'V', 3.3); ok('100', '', 100)
  ok('10K', 'Ω', 10000); ok('.5', 'V', 0.5); ok('-2', 'V', -2)
  assert.deepEqual(parseRaw('3V3'), [3.3, 'V'])
  assert.deepEqual(parseRaw('4.7e3'), [4700, null])
})

test('quantities: errors name the problem; decimal comma refused; wrong unit refused', () => {
  const bad = (t, u, re) => {
    const q = parseQuantity(t, u)
    assert.equal(q.ok, false, t)
    assert.match(q.error, re, t)
    assert.ok(q.hint)
  }
  bad('4,7k', 'Ω', /decimal comma/)
  bad('10 mV', 'A', /expected a value in A, got V/)
  bad('abc', 'V', /cannot read/)
  bad('3V3 A', 'V', /code 3V3 is in V, not A/)
  bad('3 Vx', 'V', /unknown unit/)
  bad('10 mA', '', /plain number/)
  bad('1R5V', 'Ω', /code 1R5 is in Ω/)
  assert.deepEqual(parseQuantity('   ', 'V').empty, true)
  assert.match(parseQuantity('4,7k', 'Ω').hint, /decimal point/)
})

test('calculator definitions mirror calc.PARAMS names; bodies carry the typed text, errors per field', () => {
  // at least the six basic calculators, first and in this fixed order; more may follow
  assert.deepEqual(CALC_DEFS.map(d => d.type).slice(0, 6), ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo'])
  const led = calcDef('led')
  const good = buildCalcBody(led, initialForm(led), parseQuantity)
  assert.deepEqual(good, { ok: true, body: { v_supply: '3.3', v_f: '2.0', i_f: '10mA', series: 'E12' }, errors: {} })
  const badForm = { v_supply: '3,3', v_f: '', i_f: '10 mV', series: 'E99' }
  const b = buildCalcBody(led, badForm, parseQuantity)
  assert.equal(b.ok, false)
  assert.deepEqual(Object.keys(b.errors).sort(), ['i_f', 'series', 'v_f', 'v_supply'])
  assert.equal(b.errors.v_f, 'required')
  // optional empty fields are left out (backend defaults apply)
  const div = calcDef('divider')
  assert.equal('adc_range' in buildCalcBody(div, initialForm(div), parseQuantity).body, false)
  // stored project calc fills the form from its SI inputs
  assert.equal(initialForm(calcDef('npn'), project.calcs[0]).r_base, '1k')
  assert.equal(initialForm(calcDef('npn'), project.calcs[0]).i_load, '13mA')
})

test('result view: headline, E-series value and deviation (LED), rows with units', () => {
  const v = calcView(calcDef('led'), fx('calc.led'))
  assert.equal(v.ok, true)
  assert.equal(v.main.display, '150 Ω')
  assert.equal(v.exact.display, '130 Ω')
  assert.equal(v.deviation.display, '15.4 %')
  assert.equal(v.series, 'E12')
  assert.deepEqual(v.rows.map(r => r.q.display), ['130 Ω', '8.67 mA', '11.3 mW', '22.5 mW'])
  assert.match(v.formula, /R = \(V_supply − V_f\) \/ I_f/)
  assert.equal(v.steps.length, 5)
  const n = calcView(calcDef('npn'), fx('calc.npn'))
  assert.equal(n.main.display, '2.53 mA')
  assert.equal(n.hfe.part, '2N2222A')
  assert.equal(calcView(calcDef('i2c_pullup'), fx('calc.i2c_pullup')).main.display, '3.30 kΩ')
  assert.equal(calcView(calcDef('divider'), fx('calc.divider')).main.display, '2.10 V')
  assert.equal(calcView(calcDef('led'), { ok: false, error: { code: 'invalid_args' } }).ok, false)
})

test('Add to project: add_calc with SI inputs + parts with the next free refs', () => {
  assert.equal(nextRef(project.parts, 'R'), 'R5')
  assert.equal(nextRef(project.parts, 'LED'), 'LED1')
  assert.equal(nextCalcId(project, 'npn'), 'npn-2')
  assert.equal(nextCalcId(project, 'divider'), 'div-2')
  assert.equal(nextCalcId(project, 'led'), 'led-1')
  const { id, ops, parts } = calcOps('led', fx('calc.led'), project)
  assert.equal(id, 'led-1')
  assert.equal(ops[0].op, 'add_calc')
  assert.deepEqual(ops[0].calc.inputs, { v_supply: 3.3, v_f: 2, i_f: 0.01 })
  assert.equal(ops[0].calc.result.r_chosen.display, '150 Ω')
  assert.equal('steps' in ops[0].calc.result, false)
  assert.deepEqual(ops[0].calc.sources, ['iec-60063', 'rule-of-thumb'])
  assert.deepEqual(parts, [{ ref: 'R5', kind: 'resistor', value: '150 Ω', from_calc: 'led-1' }, { ref: 'LED1', kind: 'led', value: 'LED', from_calc: 'led-1' }])
  const i2c = calcOps('i2c_pullup', fx('calc.i2c_pullup'), project)
  assert.deepEqual(i2c.parts.map(p => `${p.ref} ${p.value}`), ['R5 3.3 kΩ', 'R6 3.3 kΩ'])
  const npn = calcOps('npn', fx('calc.npn'), project)
  assert.deepEqual(npn.parts.map(p => `${p.ref} ${p.value}`), ['R5 1 kΩ', 'R6 10 kΩ', 'Q2 2N2222A'])
  assert.ok(JSON.stringify(ops).length < 16000)
})
