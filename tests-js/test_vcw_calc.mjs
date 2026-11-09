// Station 02 CALC with the register of GET /calc. The six basic cards
// stay the default group `basics` with their selectors; further register groups show generic cards (inputs from the
// params with their unit, the answer from the envelope alone: quantities, steps, checks, warnings, sources). The meta
// data of the new calculators is synthetic here (the fixtures are recorded from the backend).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { parseQuantity } from '../desktop-src/lib/units.js'
import { CALC_DEFS, calcGenericDef, calcGroups, calcResultRows, calcView, buildCalcBody, calcOps, calcParamLabel, calcPlainText, initialForm } from '../desktop-src/lib/calc.js'
import { calcMetaOf } from '../desktop-src/lib/modules.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const clone = x => JSON.parse(JSON.stringify(x))
const PROJECT = fx('project.laser-trigger').result.project

// synthetic register entries in the GET /calc shape (calckit.meta())
const INA = { kind: 'ina_shunt', title: 'INA219/INA226 shunt and calibration', group: 'power', summary: 'Shunt, current LSB and calibration register for an INA219 or INA226.',
  params: [{ name: 'part', unit: 'str', required: true, default: 'INA219' }, { name: 'r_shunt', unit: 'Ω', required: true, default: 0.1 },
    { name: 'i_max', unit: 'A', required: true, default: null }, { name: 'v_bus', unit: 'V', required: false, default: 12 },
    { name: 'n_avg', unit: 'int', required: false, default: 1 }, { name: 't_ambient', unit: '°C', required: false, default: 25 },
    { name: 'b_value', unit: 'K', required: false, default: 3977 }, { name: 'span', unit: 'range', required: false, default: [0, 3.3] }] }
const NTC = { kind: 'ntc', title: 'NTC thermistor divider', group: 'sensing', summary: 'Divider voltage over a temperature range.', params: [{ name: 'r25', unit: 'Ω', required: true, default: 10000 }] }
// the basics of the recorded register plus the two synthetic entries (independent of the family calculators)
const BASIC_ENV = (() => {
  const env = clone(fx('calc.meta'))
  env.result.calculators = env.result.calculators.filter(c => CALC_DEFS.some(d => d.type === c.kind))
  return env
})()
const META_ENV = (() => {
  const env = clone(BASIC_ENV)
  env.result.calculators.push(INA, NTC)
  return env
})()
const INA_ENV = {
  ok: true, action: 'calc.ina_shunt', summary: 'INA219: current LSB 100 µA, CAL 4096.',
  result: { inputs: { r_shunt: { value: 0.1, unit: 'Ω', display: '100 mΩ' } }, part: 'INA219', current_lsb: { value: 1e-4, unit: 'A', display: '100 µA' },
    cal: { value: 4096, unit: '', display: '4096' }, v_shunt_max: { value: 0.32, unit: 'V', display: '320 mV' }, nested: { a: 1 },
    steps: [{ name: 'Current_LSB', expr: 'I_max / 2^15', value: { value: 1e-4, unit: 'A', display: '100 µA' } }] },
  checks: [{ id: 'calc.ina_shunt.pga_range', status: 'failed', detail: '320 mV is above the 40 mV range' }],
  warnings: [{ code: 'shunt_power', severity: 'caution', message: 'Shunt dissipates 1 W at I_max.' }],
  assumptions: [{ key: 'pga', value: '±40 mV', reason: 'default gain' }],
  sources: [{ id: 'ti-ina219', title: 'TI INA219 datasheet', url: 'https://www.ti.com/lit/ds/symlink/ina219.pdf', retrieved: '2026-11-08' }]
}

test('labels from param names: one-letter symbols upper case', () => {
  assert.equal(calcParamLabel('v_in'), 'V in')
  assert.equal(calcParamLabel('r_shunt'), 'R shunt')
  assert.equal(calcParamLabel('current_lsb'), 'Current lsb')
  assert.equal(calcParamLabel(''), '')
})

test('generic definition: every register unit gets a field kind (quantity, °C, number, text); defaults as input text', () => {
  const def = calcGenericDef(calcMetaOf(META_ENV).find(c => c.kind === 'ina_shunt'))
  assert.equal(def.generic, true)
  assert.equal(def.type, 'ina_shunt')
  assert.equal(def.short, 'IS')
  assert.deepEqual(['rtd', 'opto', 'current_sense', 'led_strip'].map(k => calcGenericDef({ kind: k }).short), ['RTD', 'OPTO', 'CS', 'LS'])
  const f = Object.fromEntries(def.fields.map(x => [x.name, x]))
  assert.deepEqual([f.part.text, f.part.def], [true, 'INA219'])
  assert.deepEqual([f.r_shunt.unit, f.r_shunt.def, f.r_shunt.required], ['Ω', '100m', true])
  assert.deepEqual([f.i_max.unit, f.i_max.def], ['A', ''])
  assert.deepEqual([f.v_bus.unit, f.v_bus.def], ['V', '12'])
  assert.deepEqual([f.n_avg.unit, f.n_avg.def], ['', '1'])
  assert.deepEqual([f.t_ambient.temp, f.t_ambient.suffix], [true, '°C'])
  assert.deepEqual([f.b_value.unit, f.b_value.suffix], ['', 'K'], 'K is a suffix: the parser would read K as kilo')
  assert.deepEqual([f.span.text, f.span.def], [true, ''], 'a non-scalar default is left to the backend')
  // every unit the register allows (calckit.PARAM_UNITS) maps to one field kind
  const py = readFileSync(join(ROOT, 'circuit_bench', 'bench_core', 'calckit.py'), 'utf8')
  const units = [...(/PARAM_UNITS: frozenset\[str\] = frozenset\(\{([^}]*)\}\)/.exec(py)[1]).matchAll(/"([^"]*)"/g)].map(m => m[1])
  assert.ok(units.length >= 13, units.join(','))
  for (const unit of units) {
    const [fd] = calcGenericDef({ kind: 'x_y', params: [{ name: 'a', unit, required: false, default: null }] }).fields
    const kinds = [fd.unit !== undefined && !fd.suffix, Boolean(fd.temp), fd.unit === '' && Boolean(fd.suffix), Boolean(fd.text)].filter(Boolean)
    assert.ok(kinds.length >= 1, `unit ${JSON.stringify(unit)}`)
  }
})

test('generic body: typed text sent, required checked, plain numbers refuse a unit', () => {
  const def = calcGenericDef(INA)
  const form = initialForm(def)
  let b = buildCalcBody(def, form, parseQuantity)
  assert.equal(b.ok, false)
  assert.equal(b.errors.i_max, 'required')
  b = buildCalcBody(def, { ...form, i_max: '3.2A', n_avg: '4' }, parseQuantity)
  assert.equal(b.ok, true, JSON.stringify(b.errors))
  assert.deepEqual(b.body, { part: 'INA219', r_shunt: '100m', i_max: '3.2A', v_bus: '12', n_avg: '4', t_ambient: '25', b_value: '3977' })
  b = buildCalcBody(def, { ...form, i_max: '3.2A', n_avg: '4mA' }, parseQuantity)
  assert.match(b.errors.n_avg, /plain number/)
  // kelvin: "3977K" is 3977 kelvin, never kilo; the typed text goes to the backend
  b = buildCalcBody(def, { ...form, i_max: '1', b_value: '3977K' }, parseQuantity)
  assert.equal(b.ok, true, JSON.stringify(b.errors))
  assert.equal(b.body.b_value, '3977K')
  assert.equal(calcPlainText(def.fields.find(f => f.name === 'b_value'), '3977 K'), '3977')
  assert.match(buildCalcBody(def, { ...form, i_max: '1', b_value: '3977mV' }, parseQuantity).errors.b_value, /plain number/)
})

test('generic result: first quantity is the headline, the rest are rows (answer order), steps kept', () => {
  const def = calcGenericDef(INA)
  const v = calcView(def, INA_ENV)
  assert.equal(v.ok, true)
  assert.equal(v.mainLabel, 'Part')
  assert.equal(v.main.display, 'INA219')
  assert.deepEqual(v.rows.map(r => [r.label, r.q.display]), [['Current lsb', '100 µA'], ['Cal', '4096'], ['V shunt max', '320 mV']])
  assert.equal(v.steps.length, 1)
  // result.main names the headline when the calculator sets it
  const w = calcView(def, { ...INA_ENV, result: { ...INA_ENV.result, main: 'cal' } })
  assert.deepEqual([w.mainLabel, w.main.display, w.rows.map(r => r.k)], ['Cal', '4096', ['part', 'current_lsb', 'v_shunt_max']])
  assert.deepEqual(calcResultRows({ inputs: {}, steps: [], formula: 'a', x: { display: '' }, y: null, z: { a: 1 }, l: [1], t: true, long: 'x'.repeat(40) }), [],
    'inputs, steps, empty displays, null, objects, lists, booleans and long texts left out')
  assert.deepEqual(calcResultRows({ cal: 4096, hex: '0x1000' }).map(r => [r.label, r.q.display]), [['Cal', '4096'], ['Hex', '0x1000']], 'plain numbers (registers, codes) shown')
  // an ok answer without quantities still shows its checks (dash headline); an error never shows a value
  assert.equal(calcView(def, { ok: true, result: {} }).main.display, '—')
  assert.equal(calcView(def, { ok: false, result: null }).ok, false)
})

test('Add to project for a generic kind: add_calc only (no invented parts)', () => {
  const { id, ops, parts } = calcOps('ina_shunt', INA_ENV, PROJECT)
  assert.equal(id, 'ina_shunt-1')
  assert.deepEqual(ops.map(o => o.op), ['add_calc'])
  assert.equal(parts.length, 0)
  assert.equal(ops[0].calc.type, 'ina_shunt')
  assert.equal(ops[0].calc.inputs.r_shunt, 0.1)
  assert.deepEqual(ops[0].calc.sources, ['ti-ina219'])
})

test('groups: basics first with the six cards (also without GET /calc), then register groups with calculators only', () => {
  assert.deepEqual(calcGroups([], []).map(g => [g.id, g.defs.map(d => d.type)]), [['basics', CALC_DEFS.map(d => d.type)]])
  assert.deepEqual(calcGroups(calcMetaOf(BASIC_ENV), BASIC_ENV.result.groups).map(g => g.id), ['basics'], 'only the basics: no group pick')
  // the recorded register (family calculators merged): basics = the six own cards, every other kind once as a generic card
  const metaFx = fx('calc.meta')
  const real = calcGroups(calcMetaOf(metaFx), metaFx.result.groups)
  assert.equal(real[0].id, 'basics')
  assert.deepEqual(real[0].defs.map(d => [d.type, Boolean(d.generic)]), CALC_DEFS.map(d => [d.type, false]))
  const extra = metaFx.result.calculators.filter(c => !CALC_DEFS.some(d => d.type === c.kind))
  assert.deepEqual(real.slice(1).flatMap(g => g.defs.map(d => d.type)).sort(), extra.map(c => c.kind).sort())
  assert.ok(real.slice(1).every(g => g.defs.every(d => d.generic && d.group === g.id)))
  for (const g of real.slice(1)) assert.ok(metaFx.result.groups.includes(g.id), g.id)
  const g = calcGroups(calcMetaOf(META_ENV), META_ENV.result.groups)
  assert.deepEqual(g.map(x => x.id), ['basics', 'power', 'sensing'])
  assert.deepEqual(g[1].defs.map(d => [d.type, d.generic]), [['ina_shunt', true]])
  // a new kind in basics joins the basics after the six; an unknown group still shows (after the known ones)
  const more = calcGroups(calcMetaOf({ ok: true, result: { calculators: [...META_ENV.result.calculators, { kind: 'opto', group: 'basics', params: [] }, { kind: 'zz', group: 'misc', params: [] }] } }), ['basics', 'power'])
  assert.deepEqual(more[0].defs.map(d => d.type), [...CALC_DEFS.map(d => d.type), 'opto'])
  assert.deepEqual(more.map(x => x.id), ['basics', 'power', 'sensing', 'misc'])
})

// ─── rendered station (product bundle, recording jsx, fake hooks) ─────────────────────────────────────────────
const HOOKS = { queue: [] }
globalThis.__cbHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [globalThis.__cbHooks.queue.length ? globalThis.__cbHooks.queue.shift() : (typeof i === "function" ? i() : i), () => {}], ' +
      'useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v === undefined ? null : v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { StationCalc, CB, $project, $calcs, $calcMeta, CB_CSS_PARTS }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}
function fakeSdk() {
  const atom = v => {
    let cur = v
    return { get: () => cur, set: n => { cur = n }, subscribe: () => () => {} }
  }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', host: { navigate: () => {}, notify: () => {} } }
}
function expand(node) {
  if (node === null || node === undefined || typeof node !== 'object') return node
  if (Array.isArray(node)) return node.map(expand)
  if (typeof node.type === 'function') return expand(node.type(node.props || {}))
  const kids = node.props?.children
  return { ...node, props: { ...node.props, children: kids === undefined ? undefined : expand(kids) } }
}
function find(node, pred, out = []) {
  if (Array.isArray(node)) { for (const n of node) find(n, pred, out); return out }
  if (!node || typeof node !== 'object') return out
  if (pred(node.props || {}, node)) out.push(node)
  find(node.props?.children, pred, out)
  return out
}
const byCb = (tree, v) => find(tree, p => p['data-cb'] === v)
function text(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(text).join('')
  return text(node.props?.children)
}
const norm = s => s.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim()

let mod
async function render({ meta = null, group = null, calcs = {} } = {}) {
  if (!mod) { globalThis.__cbSdk = fakeSdk(); mod = await loadBundle() }
  mod.__t.CB.api = new Proxy({}, { get: () => async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  const p = clone(PROJECT)
  mod.__t.$project.set(p)
  mod.__t.$calcs.set(calcs)
  mod.__t.$calcMeta.set(meta ? { status: 'ready', env: meta, list: calcMetaOf(meta) } : { status: 'idle', env: null, list: [] })
  HOOKS.queue = group ? [group] : []
  return expand(mod.__t.StationCalc({ project: p }))
}

test('station: basics is the default group with the six cards and their selectors; no group pick without more groups', async () => {
  for (const meta of [null, BASIC_ENV, fx('calc.meta')]) {
    const tree = await render({ meta })
    assert.equal(byCb(tree, 'seg-calc-group').length, meta === fx('calc.meta') || (meta && meta.result.calculators.length > 6) ? 1 : 0)
    assert.equal(byCb(tree, 'calc-grid')[0].props['data-cb-group'], 'basics')
    for (const d of CALC_DEFS) {
      assert.equal(byCb(tree, `calc-${d.type}`).length, 1, d.type)
      assert.equal(byCb(tree, `calc-run-${d.type}`).length, 1, d.type)
      assert.equal(byCb(tree, `calc-add-${d.type}`).length, 1, d.type)
    }
    assert.equal(find(tree, p => p['data-cb-generic'] === 'true').length, 0)
  }
})

test('station with more groups: group pick with counts, basics default, a generic card per calculator of the group', async () => {
  let tree = await render({ meta: META_ENV })
  const seg = byCb(tree, 'seg-calc-group')
  assert.equal(seg.length, 1)
  const opts = find(seg, p => p['data-cb-opt'])
  assert.deepEqual(opts.map(o => [o.props['data-cb-opt'], norm(text(o)), o.props['aria-pressed']]),
    [['basics', 'basics · 6', 'true'], ['power', 'power · 1', 'false'], ['sensing', 'sensing · 1', 'false']])
  assert.equal(byCb(tree, 'calc-led').length, 1)
  tree = await render({ meta: META_ENV, group: 'power' })
  assert.equal(byCb(tree, 'calc-grid')[0].props['data-cb-group'], 'power')
  assert.equal(byCb(tree, 'calc-led').length, 0)
  const card = byCb(tree, 'calc-ina_shunt')[0]
  assert.equal(card.props['data-cb-generic'], 'true')
  assert.equal(byCb(card, 'calc-art-ina_shunt').length, 0, 'no schematic on a generic card')
  assert.match(norm(text(byCb(card, 'calc-sum-ina_shunt'))), /^Shunt, current LSB/)
  // inputs with their unit in the field; idle state and the source foot as on the basic cards
  assert.deepEqual(find(card, p => typeof p['data-cb'] === 'string' && p['data-cb'].startsWith('in-ina_shunt-')).map(n => n.props['data-cb']),
    INA.params.map(x => `in-ina_shunt-${x.name}`))
  assert.match(norm(text(card)), /Ω/)
  assert.equal(byCb(card, 'calc-idle-ina_shunt').length, 1)
  assert.match(norm(text(byCb(card, 'calc-src'))), /src ›/)
})

test('generic card with an answer: headline in the tone of the worst check, rows, chips, warning, steps, sources', async () => {
  const tree = await render({ meta: META_ENV, group: 'power', calcs: { ina_shunt: { status: 'ready', env: INA_ENV } } })
  const card = byCb(tree, 'calc-ina_shunt')[0]
  const big = byCb(card, 'calc-value-ina_shunt')[0]
  assert.equal(big.props['data-cb-check'], 'failed')
  assert.match(big.props.className, /cb-bad/)
  const t = norm(text(card))
  assert.match(t, /✕ 1 of 1 failed/, 'state as symbol + words, never colour alone')
  assert.match(t, /Current lsb100 µA/)
  assert.match(t, /V shunt max320 mV/)
  assert.match(t, /pga range/)
  assert.match(t, /! caution/)
  assert.match(norm(text(byCb(card, 'calc-steps-ina_shunt'))), /Current_LSB/)
  assert.match(norm(text(byCb(card, 'calc-src'))), /INA219/)
  assert.equal(byCb(card, 'calc-add-ina_shunt')[0].props.disabled, false)
})

test('styles: the summary line is ≥ 11 px and uses tokens only', async () => {
  if (!mod) await render()
  const css = mod.__t.CB_CSS_PARTS.join("\n")
  const rule = /\.cb-root \.cb-calc-sum\{([^}]*)\}/.exec(css)
  assert.ok(rule, 'cb-calc-sum rule')
  assert.match(rule[1], /font-size:11px/)
  assert.ok(!/#[0-9a-f]{3,8}\b/i.test(rule[1]))
})
