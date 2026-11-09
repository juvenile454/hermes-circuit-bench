// Desktop contract of the module support. The API functions of 20-api.js build
// the right routes and bodies; the fixture backend (lib/fixtures.js) answers /modules, /modules/{id}, /calc and the
// ops add_module/connect/set_rails (clean errors when a fixture is missing); lib/modules.js helpers. Synthetic data
// here; the real fixtures (generated from the backend) are checked too as soon as they exist.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createFixtureBackend } from '../desktop-src/lib/fixtures.js'
import {
  moduleInstances, partGroups, modNextRef, modInstanceLabel, modAddress, modAddresses, modSupply, modVolts, modAmps,
  modInterfaces, modWarningMeta, modStatusMeta, modFindings, modulesResult, modRails, addModuleOp, connectOp, setRailsOp,
  modConnProblems, modCheckExtras, calcMetaOf, MOD_BASIC_CALCS, MOD_OPS, MOD_WARNING_WORDS
} from '../desktop-src/lib/modules.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const DIR = join(SRC, 'fixtures')
const FIXTURES = Object.fromEntries(readdirSync(DIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(DIR, f), 'utf8'))]))
const clone = x => JSON.parse(JSON.stringify(x))
const env = (action, result, extra = {}) => ({ ok: true, action, summary: `${action} (synthetic)`, result, checks: [], warnings: [], assumptions: [],
  sources: [], simulated: false, error: null, ...extra })

// --- synthetic fixtures (shapes of the module API and engine contract) ------------------------------------------------
const LIST = env('modules.list', { total: 3, items: [
  { id: 'bme280', title: 'BME280 humidity, pressure and temperature sensor', category: 'sensor.environment', kind: 'module', interfaces: ['i2c', 'spi'], addresses: ['0x76', '0x77'], supply: '1.71–3.6 V', class: 'A' },
  { id: 'ssd1306', title: 'SSD1306 OLED controller', category: 'display.oled', kind: 'module', interfaces: ['i2c'], addresses: ['0x3c', '0x3d'], supply: '1.65–3.3 V', class: 'A' },
  { id: 'ds3231', title: 'DS3231 RTC', category: 'rtc', kind: 'module', interfaces: ['i2c'], addresses: ['0x68'], supply: '2.3–5.5 V', class: 'A' }] })
const INFO = env('modules.info', { id: 'bme280', title: 'BME280 humidity, pressure and temperature sensor', category: 'sensor.environment', kind: 'module',
  pins: [{ name: 'SDA', signal: 'i2c_sda' }, { name: 'SCL', signal: 'i2c_scl' }, { name: 'SDO', signal: 'addr_select' }, { name: 'VDD', signal: 'supply' }, { name: 'GND', signal: 'gnd' }],
  interfaces: [{ type: 'i2c', addresses: { value: ['0x76', '0x77'] }, default: '0x76' }],
  supplies: { VDD: { min: { value: 1.71, unit: 'V' }, max: { value: 3.6, unit: 'V' } } } })
const META = env('calc.list', { calculators: [
  { kind: 'ina_shunt', title: 'INA219/INA226 shunt', group: 'sensing', summary: 'calibration', params: [{ name: 'r_shunt', unit: 'Ω', required: true, default: null }] },
  ...['ldo', 'mosfet', 'i2c_pullup', 'divider', 'npn', 'led'].map(k => ({ kind: k, title: k, group: 'basics', summary: '', params: [] }))] })
const DEMO = (() => {
  const p = clone(FIXTURES['project.laser-trigger'].result.project)
  Object.assign(p, { id: 'modules-demo', title: 'Modules demo', rev: 3 })
  p.parts = [{ ref: 'U2', kind: 'module', value: 'SSD1306', module: 'ssd1306', address: '0x3c', conn: { SDA: 'SDA0' } },
    { ref: 'R1', kind: 'resistor', value: '4.7 kΩ', conn: { 1: 'SDA0', 2: '3V3' } },
    { ref: 'U1', kind: 'module', value: 'BME280', module: 'bme280', address: '0x76' }]
  p.assignments = [{ role: 'SDA', mode: 'i2c_sda', pin: 8, net: 'SDA0', verdict: 'ok', rule_ids: [] }, { role: 'SCL', mode: 'i2c_scl', pin: 9, net: 'SCL0', verdict: 'ok', rule_ids: [] }]
  return env('project.get', { project: p, rev: p.rev })
})()
const MODCHECK = env('pins.check', { chip: 'esp32s3', variant: 'n16r8', wifi: true, devkit: 'esp32-s3-devkitc-1', counts: { ok: 2, caution: 0, blocked: 0 },
  pins: DEMO.result.project.assignments.map(a => ({ role: a.role, mode: a.mode, pin: a.pin })),
  modules: { buses: [{ id: 'i2c:SDA0', type: 'i2c', gpios: { SDA: 8, SCL: 9 }, segments: [{ id: 'main', devices: [{ ref: 'U1', module: 'bme280', address: '0x76' }, { ref: 'U3', module: 'ds3231', address: '0x68' }] }], f_max_hz: 400000 }],
    rails: [{ net: '3V3', volts: 3.3, i_typ: 0.012, i_max: 0.045, i_peak: 0.205, limit: 0.5, limit_source: 'user' }, { net: '5V', volts: 5, i_typ: 0.001, i_max: 0.002, i_peak: null, limit: null, limit_source: null }],
    counts: { modules: 3, findings: 3, shown: 3 } } }, {
  checks: [{ id: 'pins.gpio', status: 'passed', detail: '' }, { id: 'modules.address_conflict', status: 'failed', detail: '0x68 twice' }, { id: 'modules.supply_range', status: 'passed', detail: '' }],
  warnings: [{ code: 'board_note', severity: 'info', message: 'not a module warning' },
    { code: 'mod_env_bmp_vs_bme', severity: 'info', message: 'BMP280 boards look the same' },
    { code: 'mod_level_out', severity: 'caution', message: 'U3 drives 5 V logic' },
    { code: 'mod_address_conflict', severity: 'danger', message: '0x68: U3 and U4' }] })

const SYN = { 'modules.list': LIST, 'modules.info.bme280': INFO, 'calc.meta': META, 'project.modules-demo': DEMO, 'pins.check.modules-demo': MODCHECK }
const backend = (extra = SYN) => createFixtureBackend({ ...FIXTURES, ...extra }, { delayMs: 0 })

/** 20-api.js evaluated like the bundle does it (lib files + the API file in one scope), ctx.rest recorded. */
async function loadApi(fixtures = null) {
  const strip = f => readFileSync(join(SRC, f), 'utf8').replace(/^(\s*)export\s+(?=(const|let|function|class|async)\b)/gm, '$1')
  const code = [strip('lib/api.js'), strip('lib/fixtures.js'), 'const CB_FIXTURES = globalThis.__CB_MOD_FX ?? null', strip('20-api.js'), 'export { createApi }'].join('\n')
  globalThis.__CB_MOD_FX = fixtures
  const mod = await import(`data:text/javascript;base64,${Buffer.from(`${code}\n// ${Math.random()}`).toString('base64')}`)
  return mod.createApi
}

test('API: modules/module/calcMeta/calc/patchProject build the module routes and bodies', async () => {
  const createApi = await loadApi(null)
  const calls = []
  const ctx = { rest: async (path, opts) => { calls.push([opts.method, path, opts.body]); return env('x', {}) } }
  const api = createApi(ctx)
  assert.equal(api.mode, 'live')
  await api.modules()
  await api.modules('bme 280', 'sensor.environment', 'i2c')
  await api.modules(null, null, 'spi', { limit: 20, offset: 0 })
  await api.module('bme280')
  await api.module('sht40', 'ad1b')
  await api.calcMeta()
  await api.calc('ina_shunt', { r_shunt: '0.1' })
  await api.patchProject('modules-demo', 3, [addModuleOp({ module: 'bme280', address: '0x76' }), connectOp('u1', { SDA: 'SDA0', SDO: null }), setRailsOp({ rails: { VMOT: 12 } })])
  assert.deepEqual(calls, [
    ['GET', '/modules', undefined],
    ['GET', '/modules?q=bme%20280&category=sensor.environment&interface=i2c', undefined],
    ['GET', '/modules?interface=spi&limit=20&offset=0', undefined],
    ['GET', '/modules/bme280', undefined],
    ['GET', '/modules/sht40?variant=ad1b', undefined],
    ['GET', '/calc', undefined],
    ['POST', '/calc/ina_shunt', { r_shunt: '0.1' }],
    ['PATCH', '/projects/modules-demo', { expected_rev: 3, ops: [{ op: 'add_module', module: 'bme280', address: '0x76' },
      { op: 'connect', ref: 'U1', conn: { SDA: 'SDA0', SDO: null } }, { op: 'set_rails', rails: { VMOT: 12 } }] }]
  ])
  // errors stay envelopes with the action of the route
  const bad = createApi({ rest: async () => { throw new Error('404: {"detail":"Not Found"}') } })
  const e = await bad.modules('x')
  assert.deepEqual([e.ok, e.action, e.error.code], [false, 'modules.list', 'backend_unavailable'])
  assert.equal((await bad.calcMeta()).action, 'calc.list')
  assert.equal((await bad.module('bme280')).action, 'modules.info')
})

test('API in fixture mode reaches the fixture backend (development build)', async () => {
  const createApi = await loadApi({ ...FIXTURES, ...SYN })
  const api = createApi({ storage: { get: () => true } })
  assert.equal(api.mode, 'fixtures')
  api.fixtures.reset()
  const list = await api.modules(null, 'display')
  assert.deepEqual(list.result.items.map(m => m.id), ['ssd1306'])
  assert.equal((await api.module('bme280')).result.id, 'bme280')
  assert.equal(calcMetaOf(await api.calcMeta())[0].kind, 'led')
})

test('fixture backend: GET /modules filters q/category/interface, limit/offset; GET /modules/{id}', async () => {
  const b = backend()
  const all = await b.handle('GET', '/modules')
  assert.equal(all.ok, true)
  assert.equal(all.result.total, 3)
  assert.deepEqual((await b.handle('GET', '/modules?q=OLED')).result.items.map(m => m.id), ['ssd1306'])
  assert.deepEqual((await b.handle('GET', '/modules?category=sensor')).result.items.map(m => m.id), ['bme280'])
  assert.deepEqual((await b.handle('GET', '/modules?interface=spi')).result.items.map(m => m.id), ['bme280'])
  const page = await b.handle('GET', '/modules?limit=1&offset=1')
  assert.deepEqual([page.result.total, page.result.items.map(m => m.id)], [3, ['ssd1306']])
  assert.equal((await b.handle('GET', '/modules/bme280?variant=x')).result.id, 'bme280')
  const noFile = await b.handle('GET', '/modules/ssd1306')
  assert.deepEqual([noFile.ok, noFile.error.code, noFile.http], [false, 'fixture_missing', 404])
  const unknown = await b.handle('GET', '/modules/nope')
  assert.deepEqual([unknown.error.code, unknown.http], ['invalid_args', 400])
  assert.match(unknown.error.hint, /bench_pins/)
})

test('fixture backend: GET /calc and POST /calc/{kind} generic; missing fixtures give clean errors', async () => {
  const b = backend()
  assert.equal((await b.handle('GET', '/calc')).action, 'calc.list')
  assert.equal((await b.handle('POST', '/calc/led', {})).ok, true)
  const none = await b.handle('POST', '/calc/ina_shunt', {})
  assert.deepEqual([none.ok, none.action, none.error.code, none.http], [false, 'calc.ina_shunt', 'fixture_missing', 404])
  assert.equal((await b.handle('POST', '/calc/meta', {})).error.code, 'fixture_missing', 'calc.meta is not a calculator')
  // without any module fixture: every new route answers fixture_missing, nothing throws
  const bareFx = Object.fromEntries(Object.entries(FIXTURES).filter(([k]) => !/^(modules\.|calc\.meta$|project\.modules-demo$|pins\.check\.modules-demo$)/.test(k)))
  const bare = createFixtureBackend(bareFx, { delayMs: 0 })
  for (const [m, p] of [['GET', '/modules'], ['GET', '/modules/bme280'], ['GET', '/calc'], ['POST', '/calc/buck']]) {
    const r = await bare.handle(m, p, {})
    assert.equal(r.ok, false, `${m} ${p}`)
    assert.ok(['fixture_missing', 'invalid_args'].includes(r.error.code), `${m} ${p}: ${r.error.code}`)
  }
  const add = await bare.handle('PATCH', '/projects/laser-trigger', { expected_rev: FIXTURES['project.laser-trigger'].result.project.rev, ops: [{ op: 'add_module', module: 'bme280' }] })
  assert.deepEqual([add.ok, add.error.code, add.http], [false, 'invalid_args', 400])
})

test('fixture backend: add_module (auto ref U<n>, kind, short value), connect (merge, null deletes), set_rails', async () => {
  const b = backend()
  const p0 = (await b.handle('GET', '/projects/modules-demo')).result.project
  const patch = async ops => b.handle('PATCH', '/projects/modules-demo', { expected_rev: b.projects.get('modules-demo').rev, ops })
  const r1 = await patch([{ op: 'add_module', module: 'ds3231', conn: { SDA: 'SDA0' } }, { op: 'add_module', module: 'BME280', address: '0x77', facts: { regulator: '3V3' } }])
  assert.equal(r1.ok, true, r1.summary)
  assert.equal(r1.result.rev, p0.rev + 1)
  assert.deepEqual(r1.result.changed, ['parts'])
  const added = r1.result.project.parts.slice(-2)
  // kind comes from the module info (the real ds3231 fixture says 'ic'; without it the synthetic default 'module')
  const ds = FIXTURES['modules.info.ds3231']?.result
  const dsKind = (ds?.module || ds)?.kind || 'module'
  assert.deepEqual(added, [{ ref: 'U3', kind: dsKind, value: 'DS3231', module: 'ds3231', conn: { SDA: 'SDA0' } },
    { ref: 'U4', kind: 'module', value: 'BME280', module: 'bme280', address: '0x77', facts: { regulator: '3V3' } }])
  const r2 = await patch([{ op: 'connect', ref: 'u4', conn: { SDA: 'SDA0', SCL: 'SCL0' } }, { op: 'connect', ref: 'U4', conn: { SCL: null } }])
  assert.deepEqual(r2.result.project.parts.find(x => x.ref === 'U4').conn, { SDA: 'SDA0' })
  const r3 = await patch([{ op: 'set_rails', rails: { VMOT: 12, '1V8': 1.8 }, rail_limits: { '3V3': 0.5 } }, { op: 'set_rails', rails: { '1V8': null } }])
  assert.deepEqual([r3.result.project.options.rails, r3.result.project.options.rail_limits], [{ VMOT: 12 }, { '3V3': 0.5 }])
  assert.deepEqual(r3.result.changed, ['options'])
  assert.equal(r3.result.project.options.wifi, p0.options.wifi, 'other options kept')
  // refusals: 400 invalid_args with a reason, the project unchanged
  const rev = b.projects.get('modules-demo').rev
  for (const [op, re] of [[{ op: 'add_module', module: 'nope' }, /unknown module/], [{ op: 'add_module', module: 'bme280', ref: 'U1' }, /U1 exists/],
    [{ op: 'add_module', module: 'bme280', address: '0x10' }, /no address 0x10/], [{ op: 'add_module', module: 'bme280', conn: { XX: 'N1' } }, /no pin XX/],
    [{ op: 'connect', ref: 'U9', conn: { SDA: 'X' } }, /no part U9/], [{ op: 'connect', ref: 'U1', conn: { SDA: 'bad net!' } }, /not a net name/],
    [{ op: 'set_rails', rails: { HV: 230 } }, /0–60 V/], [{ op: 'set_rails', rails: { '3V3': 3.0 } }, /fixed rail/], [{ op: 'set_rails' }, /rails or rail_limits/],
    [{ op: 'set_rails', rail_limits: { '3V3': 0 } }, /> 0 A/]]) {
    const r = await patch([op])
    assert.deepEqual([r.ok, r.error.code, r.http], [false, 'invalid_args', 400], JSON.stringify(op))
    assert.match(r.error.message, re)
  }
  assert.equal(b.projects.get('modules-demo').rev, rev)
  assert.equal((await patch([{ op: 'bogus' }])).http, 400, 'unknown ops stay refused')
})

test('fixture backend: pins.check of a project with modules answers the modules-demo fixture; others unchanged', async () => {
  const b = backend()
  const p = b.projects.get('modules-demo')
  const body = { chip: 'esp32s3', variant: 'n16r8', wifi: true, devkit: 'esp32-s3-devkitc-1', assignments: p.assignments.map(a => ({ role: a.role, mode: a.mode, pin: a.pin })), ...modCheckExtras(p) }
  const r = await b.handle('POST', '/pins/check', body)
  assert.ok(modulesResult(r), 'result.modules present')
  assert.equal((await b.handle('POST', '/pins/check', { project: 'modules-demo' })).result.modules.counts.modules, 3)
  const plain = await b.handle('POST', '/pins/check', clone({ ...FIXTURES['pins.check'].result, assignments: FIXTURES['pins.check'].result.pins }))
  assert.equal(plain.result.modules, undefined, 'no modules: the old answer')
  const withoutCheck = { ...FIXTURES, 'project.modules-demo': DEMO }
  delete withoutCheck['pins.check.modules-demo']
  const missing = await createFixtureBackend(withoutCheck, { delayMs: 0 }).handle('POST', '/pins/check', { project: 'modules-demo' })
  assert.equal(missing.error.code, 'fixture_missing')
  // the seeded module projects are listed after the recorded ones (fixture modules-stress)
  assert.deepEqual((await b.handle('GET', '/projects')).result.projects.map(x => x.id), ['laser-trigger', 'modules-demo', 'modules-stress'])
  const recordedOnly = { ...FIXTURES }
  delete recordedOnly['project.modules-demo']
  delete recordedOnly['project.modules-stress']
  assert.deepEqual((await createFixtureBackend(recordedOnly, { delayMs: 0 }).handle('GET', '/projects')).result.projects.map(x => x.id), ['laser-trigger'])
})

test('lib/modules.js: instances, groups, refs, labels, formatting', () => {
  const p = DEMO.result.project
  const inst = moduleInstances(p)
  assert.deepEqual(inst.map(i => i.ref), ['U1', 'U2'])
  assert.deepEqual(inst[1].conn, { SDA: 'SDA0' })
  assert.deepEqual(partGroups(p).others.map(x => x.ref), ['R1'])
  assert.deepEqual(moduleInstances(null), [])
  assert.deepEqual(moduleInstances({ parts: [{ ref: 'U10', module: 'a' }, { ref: 'U2', module: 'b' }] }).map(i => i.ref), ['U2', 'U10'])
  assert.equal(modNextRef(p.parts), 'U3')
  assert.equal(modNextRef([]), 'U1')
  assert.equal(modInstanceLabel(inst[0], INFO.result), 'U1 BME280 · I²C 0x76')
  assert.equal(modInstanceLabel({ ref: 'U5', module: 'x', value: 'X' }), 'U5 X')
  assert.equal(modAddress(0x3c), '0x3c')
  assert.equal(modAddress('0X3C'), '0x3c')
  assert.equal(modAddress('0x8'), '0x08')
  assert.equal(modAddresses(['0x76', '0x77'], '0x77'), '0x76 / •0x77')
  assert.equal(modAddresses({ value: [0x68] }), '0x68')
  assert.equal(modAddresses(null), '')
  assert.equal(modSupply('1.71–3.6 V'), '1.71–3.6 V')
  assert.equal(modSupply(INFO.result.supplies), 'VDD 1.71–3.6 V')
  assert.equal(modSupply({ min: 0.0018, max: 3.6 }), '1.8 mV–3.6 V')
  assert.equal(modSupply({ max: { value: 5.5, unit: 'V' } }), '≤ 5.5 V')
  assert.equal(modSupply(null), '—')
  assert.equal(modVolts(3.3), '3.3 V')
  assert.equal(modAmps(0.000714), '714 µA')
  assert.equal(modAmps(null), '—')
  assert.deepEqual(modInterfaces(['i2c', { type: 'spi' }, 'i2c', { type: 'onewire' }]), ['I²C', 'SPI', '1-Wire'])
})

test('lib/modules.js: warning code → symbol + word, findings sorted, rails', () => {
  assert.deepEqual(modWarningMeta({ code: 'mod_address_conflict', severity: 'danger' }), { symbol: '⊗', tone: 'bad', level: 'danger', severity: 'danger', word: 'address conflict' })
  assert.equal(modWarningMeta({ code: 'mod_level_out', severity: 'caution' }).symbol, '◇')
  assert.equal(modWarningMeta({ code: 'mod_prox_vl53_xshut', severity: 'caution' }).word, 'VL53 XSHUT (proximity)', 'family in words')
  assert.deepEqual(modWarningMeta({ code: 'mod_x', severity: 'weird' }).severity, 'info')
  assert.equal(modStatusMeta('passed').symbol, '✓')
  assert.equal(modStatusMeta('failed').word, 'failed')
  assert.equal(modStatusMeta('nope').word, 'not checked')
  for (const code of Object.keys(MOD_WARNING_WORDS)) assert.match(code, /^mod_[a-z_]+$/)
  const f = modFindings(MODCHECK)
  assert.deepEqual(f.warnings.map(w => w.code), ['mod_address_conflict', 'mod_level_out', 'mod_env_bmp_vs_bme'])
  assert.deepEqual(f.warnings.map(w => w.symbol), ['⊗', '◇', 'i'])
  assert.deepEqual(f.checks.map(c => [c.id, c.symbol]), [['modules.address_conflict', '✕'], ['modules.supply_range', '✓']])
  assert.deepEqual(modFindings({ ok: false }), { warnings: [], checks: [] })
  assert.equal(modulesResult(FIXTURES['pins.check']), null)
  assert.equal(modulesResult(null), null)
  const rails = modRails(MODCHECK)
  assert.deepEqual(rails[0], { net: '3V3', volts: '3.3 V', typ: '12 mA', max: '45 mA', peak: '205 mA', limit: '500 mA', limitSource: 'user', frac: 0.41 })
  assert.equal(rails[1].frac, null)
  assert.equal(rails[1].peak, '—')
  assert.deepEqual(modRails(FIXTURES['pins.check']), [])
})

test('lib/modules.js: op builders, conn checks, check extras, GET /calc parsing', () => {
  assert.deepEqual(MOD_OPS, ['add_module', 'connect', 'set_rails'])
  assert.deepEqual(addModuleOp({ module: ' bme280 ', ref: 'u7', address: 0x77, qty: 2, conn: {}, facts: {} }), { op: 'add_module', module: 'bme280', ref: 'U7', address: '0x77', qty: 2 })
  assert.throws(() => addModuleOp({}), /module id/)
  assert.throws(() => connectOp('U1', {}), /at least one pin/)
  assert.throws(() => setRailsOp({}), /rails or rail_limits/)
  assert.deepEqual(setRailsOp({ rail_limits: { '3V3': 0.5 } }), { op: 'set_rails', rail_limits: { '3V3': 0.5 } })
  assert.deepEqual(modConnProblems({ SDA: 'SDA0', SDO: null }), [])
  assert.equal(modConnProblems({ SDA: 'a b' }).length, 1)
  assert.equal(modConnProblems(Object.fromEntries(Array.from({ length: 49 }, (_, i) => [`P${i}`, 'N']))).length, 1)
  assert.deepEqual(modCheckExtras(FIXTURES['project.laser-trigger'].result.project), {}, 'no modules: the old pins.check body')
  const ex = modCheckExtras(DEMO.result.project)
  assert.equal(ex.parts.length, 3)
  assert.equal(ex.options.wifi, DEMO.result.project.options.wifi)
  const meta = calcMetaOf(META)
  assert.deepEqual(meta.map(c => c.kind), [...MOD_BASIC_CALCS, 'ina_shunt'], 'basics first in the fixed order, then the rest')
  assert.deepEqual(meta.at(-1).params, [{ name: 'r_shunt', unit: 'Ω', required: true, default: null }])
  assert.equal(meta.at(-1).basic, false)
  assert.deepEqual(calcMetaOf(env('calc.list', { calcs: [{ type: 'led', params: ['v_supply'] }] }))[0].params[0].name, 'v_supply')
  assert.deepEqual(calcMetaOf({ ok: false }), [])
  assert.deepEqual(calcMetaOf(env('calc.list', { other: 1 })), [])
})

test('real module fixtures (when generated) are envelopes the backend serves', async () => {
  const names = ['modules.list', 'calc.meta', 'pins.check.modules-demo', 'project.modules-demo'].filter(n => existsSync(join(DIR, `${n}.json`)))
  const b = createFixtureBackend(FIXTURES, { delayMs: 0 })
  if (names.includes('modules.list')) {
    const r = await b.handle('GET', '/modules')
    assert.equal(r.ok, true)
    assert.ok(Array.isArray(r.result.items) && r.result.total >= r.result.items.length)
    for (const m of r.result.items) for (const k of ['id', 'title', 'category', 'kind']) assert.ok(k in m, `${m.id}: ${k}`)
  }
  for (const f of readdirSync(DIR).filter(x => /^modules\.info\.[a-z0-9_]+\.json$/.test(x))) {
    const id = f.slice('modules.info.'.length, -5)
    assert.equal((await b.handle('GET', `/modules/${id}`)).ok, true, f)
  }
  if (names.includes('calc.meta')) assert.deepEqual(calcMetaOf(await b.handle('GET', '/calc')).slice(0, 6).map(c => c.kind), MOD_BASIC_CALCS)
  if (names.includes('project.modules-demo') && names.includes('pins.check.modules-demo')) {
    assert.ok(modulesResult(await b.handle('POST', '/pins/check', { project: 'modules-demo' })))
  }
})

test('desktop stubs: modal case, style part, components without module data render nothing', () => {
  const bench = readFileSync(join(SRC, '30-ui-bench.js'), 'utf8')
  assert.match(bench, /if \(t === 'modules'\) return h\(ModulesDialog, \{ init: modal\.init \?\? null, onClose: close \}\)/)
  const css = readFileSync(join(SRC, '19-styles-modules.js'), 'utf8')
  assert.equal((css.match(/CB_CSS_PARTS\.push\(/g) || []).length, 1)
  const classes = [...css.matchAll(/\.(cb-[a-z0-9-]+)/g)].map(m => m[1]).filter(c => c !== 'cb-root')
  assert.ok(classes.length && classes.every(c => c.startsWith('cb-mod-')), classes.join(','))
  assert.match(readFileSync(join(SRC, '47-dialog-modules.js'), 'utf8'), /function ModulesDialog\(\{ init = null, onClose \}\)/)
  assert.match(readFileSync(join(SRC, '30-ui-bus.js'), 'utf8'), /function BusCard\(\{ modules, findings = null \}\)/)
  assert.match(readFileSync(join(ROOT, 'scripts', 'build-desktop.mjs'), 'utf8'), /BUNDLE_BUDGET = 760_000/)
})

test('BusCard renders nothing without module data, a card with buses and findings', async () => {
  const strip = f => readFileSync(join(SRC, f), 'utf8').replace(/^(\s*)export\s+(?=(const|let|function|class|async)\b)/gm, '$1')
  const code = [strip('lib/modules.js'), 'const h = (t, p, ...c) => ({ t, p, c })', 'const Label = () => null', strip('30-ui-bus.js'), 'export { BusCard }'].join('\n')
  const { BusCard } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
  assert.equal(BusCard({ modules: null }), null)
  assert.equal(BusCard({ modules: { buses: [], rails: [], counts: { modules: 0 } } }), null)
  const card = BusCard({ modules: MODCHECK.result.modules, findings: modFindings(MODCHECK) })
  assert.equal(card.p['data-cb'], 'insp-buses')
  assert.ok(JSON.stringify(card).includes('U1 0x76 · U3 0x68'))
  assert.ok(JSON.stringify(card).includes('address conflict'))
})
