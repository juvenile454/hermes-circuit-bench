// The MOSFET and LDO cards of station 02 (lib/calc.js): fields mirror calc.PARAMS, the temperature input,
// request bodies, the result view from the real-answer fixtures, a result without a headline value, project ops.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseQuantity } from '../desktop-src/lib/units.js'
import { CALC_DEFS, calcDef, buildCalcBody, calcView, calcOps, nextCalcId, initialForm, parseTempC, worstCheck } from '../desktop-src/lib/calc.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const project = fx('project.laser-trigger').result.project

// calc_power.PARAMS (bench_core/calc_power.py): names in order
const PARAMS = {
  mosfet: ['i_load', 'v_supply', 'gate_v', 'part', 'r_gate', 'r_pulldown', 'r_ds_on', 't_ambient'],
  ldo: ['v_in', 'v_out', 'i_load', 'part', 't_ambient']
}

test('the new cards follow calc.PARAMS; required fields as in the backend', () => {
  // the six basic calculators come first in a fixed order (MOSFET, LDO at 5 and 6); more may follow
  assert.deepEqual(CALC_DEFS.map(d => d.type).slice(0, 6), ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo'])
  for (const [type, names] of Object.entries(PARAMS)) {
    const def = calcDef(type)
    assert.deepEqual(def.fields.map(f => f.name), names, type)
    assert.ok(def.title && def.short && def.main && def.rows.length >= 4, type)
  }
  assert.deepEqual(calcDef('mosfet').fields.filter(f => f.required).map(f => f.name), ['i_load', 'v_supply'])
  assert.deepEqual(calcDef('ldo').fields.filter(f => f.required).map(f => f.name), ['v_in', 'v_out', 'i_load'])
  // the backend file still lists these names (no silent rename)
  const py = readFileSync(join(ROOT, 'circuit_bench', 'bench_core', 'calc_power.py'), 'utf8')
  for (const names of Object.values(PARAMS)) for (const n of names) assert.match(py, new RegExp(`\\("${n}", `), n)
})

test('temperature input: °C forms, range, errors', () => {
  for (const t of ['25', '25 °C', '25°C', '25C', '-10', '40 degC', '+5']) assert.equal(parseTempC(t).ok, true, t)
  assert.equal(parseTempC('25 °C').value, 25)
  assert.equal(parseTempC('-10').value, -10)
  assert.equal(parseTempC('').empty, true)
  assert.match(parseTempC('200').error, /between -60 and 150/)
  assert.match(parseTempC('25 K').error, /°C/)
  assert.match(parseTempC('2,5').error, /°C/)
})

test('request bodies: defaults are valid, typed text is sent, errors per field', () => {
  const m = calcDef('mosfet')
  const good = buildCalcBody(m, initialForm(m), parseQuantity)
  assert.deepEqual(good, { ok: true, errors: {},
    body: { i_load: '2A', v_supply: '12', gate_v: '3V3', part: 'AO3400A', r_gate: '100', r_pulldown: '100k', t_ambient: '25' } })
  assert.equal('r_ds_on' in good.body, false) // optional and empty: the backend default applies
  const bad = buildCalcBody(m, { ...initialForm(m), i_load: '2V', v_supply: '', t_ambient: 'hot', r_ds_on: '4,7m' }, parseQuantity)
  assert.equal(bad.ok, false)
  assert.deepEqual(Object.keys(bad.errors).sort(), ['i_load', 'r_ds_on', 't_ambient', 'v_supply'])
  assert.equal(bad.errors.v_supply, 'required')
  const l = calcDef('ldo')
  assert.deepEqual(buildCalcBody(l, initialForm(l), parseQuantity).body,
    { v_in: '5', v_out: '3V3', i_load: '500mA', part: 'AMS1117-3.3', t_ambient: '25' })
  // a stored calc (SI numbers) fills the form again, the temperature without a unit
  const stored = { inputs: { v_in: 5, v_out: 3.3, i_load: 0.5, part: 'AMS1117-3.3', t_ambient: 40 } }
  assert.deepEqual(initialForm(l, stored), { v_in: '5', v_out: '3.3', i_load: '500mA', part: 'AMS1117-3.3', t_ambient: '40' })
  assert.equal(buildCalcBody(l, initialForm(l, stored), parseQuantity).ok, true)
})

test('result view from the real answers (fixtures)', () => {
  const m = calcView(calcDef('mosfet'), fx('calc.mosfet'))
  assert.equal(m.ok, true)
  assert.equal(m.mainLabel, 'P conduction')
  assert.equal(m.main.display, '192 mW')
  assert.deepEqual(m.rows.map(r => `${r.label}=${r.q.display}`),
    ['R DS(on)=48.0 mΩ', 'V drop=96.0 mV', 'T junction=49.0 °C', 'V GS=3.297 V', 'I gate peak=33.0 mA'])
  assert.match(m.formula, /P = I_load² · R_DS\(on\)/)
  assert.equal(worstCheck(fx('calc.mosfet').checks), 'passed')
  const l = calcView(calcDef('ldo'), fx('calc.ldo'))
  assert.equal(l.mainLabel, 'P regulator')
  assert.equal(l.main.display, '905 mW')
  assert.deepEqual(l.rows.map(r => `${r.label}=${r.q.display}`),
    ['T junction=106 °C', 'Efficiency=64.6 %', 'P load=850 mW', 'P quiescent=55.0 mW', 'V in − V out=1.70 V'])
  assert.ok(fx('calc.ldo').sources.some(s => s.id === 'ds-esp32-s3-wroom-1-power'))
  assert.ok(fx('calc.ldo').warnings.some(w => w.code === 'esp32s3_supply'))
})

test('a result without a headline value still shows (failed logic-level check stays visible)', () => {
  const env = JSON.parse(JSON.stringify(fx('calc.mosfet')))
  env.result.p_loss = null; env.result.r_ds_on = null; env.result.v_ds_on = null; env.result.t_j = null
  env.checks[0] = { id: 'calc.mosfet.logic_level', status: 'failed', detail: 'IRLZ44N specifies R_DS(on) only from V_GS 4.00 V' }
  const v = calcView(calcDef('mosfet'), env)
  assert.equal(v.ok, true)
  assert.equal(v.main.display, '—')
  assert.deepEqual(v.rows.map(r => r.label), ['V GS', 'I gate peak'])
  assert.equal(worstCheck(env.checks), 'failed')
  assert.equal(calcView(calcDef('mosfet'), { ok: false, error: { code: 'invalid_args' } }).ok, false)
  // the older cards keep their rule: no headline value, no result block
  assert.equal(calcView(calcDef('led'), { ok: true, result: { r_chosen: null } }).ok, false)
})

test('Add to project: ids and parts for MOSFET and LDO', () => {
  assert.equal(nextCalcId(project, 'mosfet'), 'mosfet-1')
  assert.equal(nextCalcId(project, 'ldo'), 'ldo-1')
  const m = calcOps('mosfet', fx('calc.mosfet'), project)
  assert.equal(m.ops[0].op, 'add_calc')
  assert.equal(m.ops[0].calc.inputs.i_load, 2)
  assert.equal(m.ops[0].calc.inputs.t_ambient, 25)
  assert.deepEqual(m.ops[0].calc.sources, ['rule-of-thumb', 'ds-esp32-s3-wroom-1-power', 'aos-ao3400a'])
  assert.deepEqual(m.parts.map(p => `${p.ref} ${p.kind} ${p.value}`), ['R5 resistor 100 Ω', 'R6 resistor 100 kΩ', 'Q2 transistor AO3400A'])
  const l = calcOps('ldo', fx('calc.ldo'), project)
  assert.deepEqual(l.parts.map(p => `${p.ref} ${p.kind} ${p.value}`), ['U1 ic AMS1117-3.3'])
  assert.equal('steps' in l.ops[0].calc.result, false)
  assert.ok(JSON.stringify(m.ops).length < 16000 && JSON.stringify(l.ops).length < 16000)
})
