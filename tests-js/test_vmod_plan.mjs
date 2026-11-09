// Module helpers of lib/modules.js (pin links, assign preset, proposed conn,
// addresses, F texts, required parts → calc) and the PLAN components rendered with a stub h(): catalog dialog,
// module detail, module rows in the assignment table, the bus card. Real fixtures (shape, not texts) plus synthetic
// edge cases; no app markup, own data-cb hooks only.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  modPinLinks, modAssignInit, modSuggestConn, modAddressChoices, modRefFindings, modFText, modEvidence, modRequireCalc,
  modRequireText, modFindings, modulesResult, moduleInstances, modKeep, modCategories, modHidden, modWarningWord, MOD_SIGNAL_MODES, modCategoryLabel
} from '../desktop-src/lib/modules.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const FX = Object.fromEntries(readdirSync(join(SRC, 'fixtures')).filter(f => f.endsWith('.json'))
  .map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(SRC, 'fixtures', f), 'utf8'))]))
const clone = x => JSON.parse(JSON.stringify(x))
const BME = (() => { const r = FX['modules.info.bme280'].result; return r.module ?? r })()
const DEMO = FX['project.modules-demo'].result.project
const CHECK = FX['pins.check.modules-demo']

test('vocabulary mirrors modspec.py (signal → modes); categories come from the catalog, not a fixed list', () => {
  const py = readFileSync(join(ROOT, 'circuit_bench', 'bench_core', 'modspec.py'), 'utf8')
  const cats = [...py.slice(py.indexOf('CATEGORIES'), py.indexOf('SUPPLY_KEYS')).matchAll(/"([a-z0-9_.]+)"/g)].map(m => m[1])
  const got = modCategories(FX['modules.list'].result, 'zz.extra')
  assert.ok(got.length > 3 && got.every(c => cats.includes(c) || c === 'zz.extra'), got.join(','))
  assert.deepEqual(got, [...got].sort())
  assert.deepEqual(modCategories({ categories: ['b', 'a'], items: [{ category: 'x' }] }), ['a', 'b'])
  const block = py.slice(py.indexOf('SIGNAL_MODES'), py.indexOf('SIGNAL_DIRECTION'))
  for (const m of block.matchAll(/"([a-z0-9_]+)": \(([^)]*)\)/g)) {
    const modes = [...m[2].matchAll(/"([a-z0-9_]+)"/g)].map(x => x[1])
    assert.deepEqual(MOD_SIGNAL_MODES[m[1]] || [], modes, m[1])
  }
  assert.equal(modCategoryLabel('sensor.environment'), 'sensor · environment')
})

test('pin links: linked / bus / open; assign preset takes the free bus role or <ref>_<pin>', () => {
  const [u1] = moduleInstances(DEMO)
  const linked = modPinLinks(u1, BME, DEMO.assignments)
  assert.ok(linked.length >= 2 && linked.every(l => l.state === 'linked'), JSON.stringify(linked))
  const fresh = { ref: 'U3', module: 'bme280', conn: {} }
  const links = modPinLinks(fresh, BME, DEMO.assignments.slice(0, 1)) // only SDA assigned
  const sda = links.find(l => l.signal === 'i2c_sda')
  const scl = links.find(l => l.signal === 'i2c_scl')
  assert.equal(sda.state, 'bus')
  assert.equal(scl.state, 'open')
  assert.deepEqual(modAssignInit(fresh, scl, DEMO.assignments.slice(0, 1)), { role: 'SCL', mode: 'i2c_scl', pin: null, net: 'SCL0', link: { ref: 'U3', pin: scl.pin } })
  // role taken → own role and net
  const pre = modAssignInit(fresh, scl, [{ role: 'SCL', mode: 'out', pin: 4 }])
  assert.equal(pre.role, `U3_${scl.pin}`)
  assert.equal(pre.net, pre.role)
  assert.deepEqual(modPinLinks(fresh, null, []), [])
})

test('proposed conn: bus nets, fixed rail inside the supply range, GND, address select per map', () => {
  const c76 = modSuggestConn(BME, DEMO.assignments, '0x76')
  const sigOf = n => BME.pins.find(p => p.name === n)?.signal
  const sel = BME.interfaces.find(i => i.select)?.select
  for (const [pin, net] of Object.entries(c76)) {
    assert.ok(net, pin)
    if (sigOf(pin) === 'gnd') assert.equal(net, 'GND')
    if (sigOf(pin) === 'i2c_sda') assert.equal(net, 'SDA0')
  }
  assert.ok(!Object.keys(c76).some(p => BME.pins.find(x => x.name === p)?.tie), 'tied pins stay out')
  if (sel) {
    assert.equal(c76[sel.pin], 'GND')
    const c77 = modSuggestConn(BME, DEMO.assignments, '0x77')
    assert.notEqual(c77[sel.pin], 'GND')
  }
  // a supply range that excludes 3.3 V gets no rail
  const low = clone(BME)
  for (const s of Object.values(low.supplies)) { s.min = { value: 1.6, unit: 'V' }; s.max = { value: 1.95, unit: 'V' } }
  assert.ok(!Object.values(modSuggestConn(low, [], null)).includes('3V3'))
})

test('addresses, findings per ref, F texts, evidence, required parts → calc', () => {
  const a = modAddressChoices(BME)
  assert.ok(a.list.length >= 1 && a.list.every(x => /^0x[0-7][0-9a-f]$/.test(x)))
  assert.ok(a.def === null || a.list.includes(a.def))
  assert.deepEqual(modAddressChoices(null), { list: [], def: null })
  const f = modFindings(CHECK)
  const byRef = modRefFindings(f.warnings)
  for (const w of f.warnings) for (const r of w.refs || []) assert.ok(byRef[r])
  assert.equal(modFText({ value: 3.6, unit: 'V' }), '3.6 V')
  assert.equal(modFText({ rel: 0.8, of: 'VDDIO' }), '0.8 × VDDIO')
  assert.equal(modFText({ rel_offset: 0.3, of: 'VDDIO', unit: 'V' }), 'VDDIO + 0.3 V')
  assert.equal(modFText({ value: true }), 'yes')
  assert.equal(modFText(null), '—')
  assert.equal(modEvidence({ page: 8, evidence: 'x' }), 'p. 8 · “x”')
  assert.equal(modEvidence(null), '')
  const pull = (BME.requires || []).find(r => /pull/.test(r.code))
  if (pull) assert.equal(modRequireCalc(pull, BME), 'i2c_pullup')
  assert.equal(modRequireCalc({ code: 'decoupling', pins: ['VDD'] }, BME), null)
  assert.match(modRequireText({ code: 'pullup', kind: 'resistor', pins: ['SDA', 'SCL'], to: 'VDD' }), /pullup · resistor · SDA, SCL → VDD/)
  assert.equal(modKeep('1.43 mA · 3.3 V'), '1.43\u00a0mA · 3.3\u00a0V')
})

// --- components with a stub h() -------------------------------------------------------------------------------------
const strip = f => readFileSync(join(SRC, f), 'utf8').replace(/^(\s*)export\s+(?=(const|let|function|class|async)\b)/gm, '$1')
async function load(extra = '') {
  const code = [strip('lib/modules.js'),
    'const h = (t, p, ...c) => ({ t, p: p || {}, c })',
    'let STATE = {}; const sdk = { useValue: a => a.get(), atom: v => { let x = v; return { get: () => x, set: n => { x = n } } } }',
    'const useState = v => [v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v })',
    'const Label = () => null, Btn = () => null, Modal = p => ({ t: "Modal", p, c: [p.children] }), SourceLine = () => null',
    'const $project = sdk.atom(null), $check = sdk.atom({ env: null })',
    'const CB = { api: {} }; const patchAtom = () => null, $ui = sdk.atom({}); const CALLS = []; const composeDraft = t => CALLS.push(["draft", t]), patchOps = o => CALLS.push(["patch", o])',
    'const goStation = s => CALLS.push(["go", s]), ownRoot = () => null, unassignRole = () => null, selectPin = () => null, removePartsFromProject = r => CALLS.push(["remove", r])',
    strip('27-modules.js'), strip('30-ui-bus.js'), strip('47-dialog-modules.js'), extra,
    'export { BusCard, ModulesDialog, ModuleDetail, BusRequires, ModTags, CALLS, $project, $check, $modInfo, $modCatalog }'].join('\n')
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
}
/** Expand function components (stub render) and collect nodes. */
function render(node, out = []) {
  if (node == null || typeof node !== 'object') return out
  if (Array.isArray(node)) { for (const n of node) render(n, out); return out }
  if (typeof node.t === 'function') return render(node.t({ ...node.p, children: node.c }), out)
  out.push(node)
  render(node.c, out)
  return out
}
const texts = nodes => nodes.flatMap(n => n.c.filter(c => typeof c === 'string' || typeof c === 'number')).join(' | ')

test('BusCard: devices with addresses, findings as symbol + word, rails without limit never full, one agent button', async () => {
  const m = await load()
  m.$project.set(DEMO)
  m.$modInfo.set({ bme280: { status: 'ready', env: FX['modules.info.bme280'] } })
  const mods = modulesResult(CHECK)
  const card = m.BusCard({ modules: mods, findings: { ...modFindings(CHECK), sources: CHECK.sources } })
  assert.equal(card.p['data-cb'], 'insp-buses')
  const nodes = render(card)
  const all = JSON.stringify(card)
  for (const b of mods.buses) for (const s of b.segments) for (const d of s.devices) assert.ok(all.includes(d.ref))
  const f = nodes.filter(n => n.p['data-cb'] === 'mod-finding')
  assert.equal(f.length, modFindings(CHECK).warnings.length)
  for (const n of f) {
    const [det] = n.c
    const [sum, body] = det.c
    assert.equal(det.t, 'details')
    const [sym, line] = sum.c
    assert.ok(sym.c[0] && line.c[0].c[0], 'symbol and word in the one-line summary')
    assert.match(line.c[1].c[0], /U\d/, 'refs in the summary')
    assert.ok(body.c[0].length > 20, 'message folded below')
  }
  // passed / not checked folded, readable family names, no double entry for a shown finding
  const passed = nodes.find(n => n.p['data-cb'] === 'mod-passed')
  const words = render(passed).map(n => n.c).flat().filter(x => typeof x === 'string').join(' ')
  assert.match(words, /BME680 SDO float \(environment\)/)
  assert.match(words, /DS3231 VIH \(RTC\)/)
  const open = render(nodes.find(n => n.p['data-cb'] === 'mod-open')).map(n => n.c).flat().filter(x => typeof x === 'string').join(' ')
  assert.ok(!/BMP vs BME/.test(open), 'info finding shown once, not again as not checked')
  for (const r of nodes.filter(n => n.p['data-cb'] === 'mod-rail')) {
    const meter = render(r).find(n => /cb-mod-meter/.test(n.p.className || ''))
    const rail = mods.rails.find(x => x.net === r.p['data-cb-net'])
    if (rail.limit == null) { assert.match(meter.p.className, /--none/); assert.equal(meter.c[0], null) }
  }
  // required parts → calc link for the pull-up
  const req = render(m.BusRequires({ refs: ['bme280'], checks: modFindings(CHECK).checks }))
  if ((BME.requires || []).some(r => /pull/.test(r.code))) assert.ok(req.some(n => n.p['data-cb'] === 'mod-calc-i2c_pullup'))
  // at most one agent button, and it only fills the composer
  const asks = render(card).filter(n => n.p['data-cb'] === 'mod-ask')
  assert.ok(asks.length <= 1)
})

test('BusCard: limit known → bar with fraction, symbol + word; over the limit stays capped at 100 %', async () => {
  const m = await load()
  const mods = clone(modulesResult(CHECK))
  mods.rails = [{ net: '3V3', volts: 3.3, i_typ: 0.1, i_max: 0.3, i_peak: 0.6, limit: 0.5, limit_source: 'user' }]
  const nodes = render(m.BusCard({ modules: mods, findings: modFindings(CHECK) }))
  const meter = nodes.find(n => /cb-mod-meter/.test(n.p.className || ''))
  assert.match(meter.p.className, /--bad/)
  assert.equal(meter.c[0].p.style.width, '100%')
  assert.match(meter.p['aria-label'], /over limit/)
  assert.ok(texts(nodes).includes('⊗ 120 % · over limit'), texts(nodes))
})

test('BusCard: 3 findings then show all, hidden findings as words, +N devices, partial rails, required-parts tone', async () => {
  const m = await load()
  const mods = clone(modulesResult(CHECK))
  const w = { code: 'mod_required_parts', severity: 'caution', message: 'U3 (mpu6050) decoupling missing on REGOUT, see p. 12', refs: ['U3'] }
  const env = clone(CHECK)
  env.warnings.push(w, { ...w, code: 'mod_bus_speed', severity: 'info' }, { ...w, code: 'mod_level_in', severity: 'info' })
  mods.counts = { ...mods.counts, findings: 7, shown: 5, hidden: ['mod_display_sh1106_vs_ssd1306 U4', 'mod_address_select U1,U3'] }
  mods.buses[0].segments[0].more = 2
  mods.buses.push({ id: 'spi:SCK0', type: 'spi', gpios: { SCK: 12 }, segments: [], more: 3 })
  const f = modFindings(env)
  const nodes = render(m.BusCard({ modules: mods, findings: f }))
  const list = nodes.find(n => n.p['data-cb'] === 'mod-findings')
  assert.equal(list.c[0].length, 3, 'three findings on top')
  assert.ok(nodes.some(n => n.p['data-cb'] === 'mod-all'))
  const all = texts(nodes)
  assert.match(all, /show all 6/)
  assert.match(all, /hidden: SH1106 vs SSD1306 \(display\) U4 · address select U1 U3/)
  assert.ok(!/mod_/.test(all.replace(/data-cb/g, '')), all)
  const devs = nodes.filter(n => n.p['data-cb'] === 'mod-devices').map(n => n.c.join(''))
  assert.match(devs[0], /· \+2 devices$/)
  assert.equal(devs[1], '+3 devices')
  assert.match(texts(nodes), /typ\u00a0≥\u00a0/)
  assert.match(texts(nodes), /\? partial: U3 has no data/)
  assert.deepEqual(modHidden(['mod_bus_speed U2,U3']), ['bus speed U2 U3'])
  assert.equal(modWarningWord('modules.env.bmp_vs_bme'), 'BMP vs BME (environment)')
  // required parts: the strongest warning of the rule (caution), not the check status
  m.$modInfo.set({ mpu6050: { status: 'ready', env: FX['modules.info.mpu6050'] } })
  const req = render(m.BusRequires({ refs: ['mpu6050'], checks: [{ id: 'modules.required_parts', status: 'failed', tone: 'bad' }], warns: f.warnings }))
  const raw = JSON.stringify(m.BusRequires({ refs: ['mpu6050'], checks: [{ id: 'modules.required_parts', status: 'failed', tone: 'bad' }], warns: f.warnings }))
  if (req.length) assert.match(raw, /cb-mod-t-warn"\},"c":\["◇ caution"\]/, raw.slice(0, 400))
})

test('ModulesDialog: catalog rows with interface, address, supply and class tags; detail with add box', async () => {
  const m = await load()
  m.$project.set(DEMO)
  m.$modCatalog.set({ status: 'ready', key: JSON.stringify(['', '', '']), env: FX['modules.list'] })
  const dlg = m.ModulesDialog({ init: null, onClose: () => {} })
  const nodes = render(dlg)
  const rows = nodes.filter(n => n.p['data-cb'] === 'module-row')
  assert.equal(rows.length, FX['modules.list'].result.items.length)
  const tags = render(m.ModTags({ m: FX['modules.list'].result.items[0] })).filter(n => n.p.className?.startsWith('cb-mod-tag'))
  assert.ok(tags.length >= 3, JSON.stringify(tags))
  assert.ok(tags.some(t => /class /.test(t.c.join(''))))
  const det = render(m.ModuleDetail({ id: 'bme280', project: DEMO, st: { status: 'ready', env: FX['modules.info.bme280'] }, onClose: () => {}, box: { current: null } }))
  for (const hook of ['module-pins', 'module-add', 'modules-connect']) assert.ok(det.some(n => n.p['data-cb'] === hook), hook)
  assert.ok(det.some(n => n.p['data-cb'] === 'modules-address'))
  const conn = det.find(n => n.p['data-cb'] === 'modules-conn')
  assert.match(conn.c.join(''), /→/)
  // categories from the loaded entries
  const opts = nodes.filter(n => n.t === 'option').map(n => n.p.value).filter(Boolean)
  assert.deepEqual(opts, modCategories(FX['modules.list'].result))
  // init.ref opens the instance view: conn, address, remove; no add box
  m.$modInfo.set({ bme280: { status: 'ready', env: FX['modules.info.bme280'] } })
  const dlg2 = m.ModulesDialog({ init: { ref: 'u1', address: '0x76' }, onClose: () => {} })
  assert.match(dlg2.p.title, /^U1 · /)
  const byRef = render(dlg2)
  assert.ok(byRef.some(n => n.p['data-cb'] === 'module-detail'))
  assert.ok(byRef.some(n => n.p['data-cb'] === 'module-instance'))
  assert.ok(!byRef.some(n => n.p['data-cb'] === 'module-add' || n.p['data-cb'] === 'modules-add'), 'no add box in the instance view')
  assert.match(JSON.stringify(byRef), /"data-cb":"module-remove"/) // Btn is a stub: look at its props
  assert.match(JSON.stringify(byRef), /0x76/)
  assert.match(JSON.stringify(byRef), /→SDA0/)
})

test('ModulesDialog: load more when the catalog holds more than loaded; Escape from a list detail goes back', async () => {
  const m = await load()
  m.$project.set(DEMO)
  const env = clone(FX['modules.list'])
  env.result.total = env.result.items.length + 25
  m.$modCatalog.set({ status: 'ready', key: JSON.stringify(['', '', '']), env, cats: ['zz.more'] })
  const nodes = render(m.ModulesDialog({ init: null, onClose: () => {} }))
  assert.ok(nodes.some(n => n.p['data-cb'] === 'modules-more' || n.p?.['data-cb'] === 'modules-more') || JSON.stringify(nodes).includes('Load more (25 left)'))
  assert.ok(nodes.some(n => n.t === 'option' && n.p.value === 'zz.more'), 'categories seen earlier stay selectable')
  const src = readFileSync(join(SRC, '47-dialog-modules.js'), 'utf8')
  assert.match(src, /onClose: listed \? \(\) => setPick\(null\) : onClose/)
  assert.match(src, /ArrowDown: 1, ArrowUp: -1/)
})

test('PLAN wiring: Add module entry, BusPanel in the inspector, module rows open the preset assign dialog', () => {
  const plan = readFileSync(join(SRC, '40-station-plan.js'), 'utf8')
  assert.match(plan, /'data-cb': 'add-module'[^\n]*\n?[^\n]*openModules\(\)/)
  assert.match(plan, /h\(BusPanel, null\)/)
  const assign = readFileSync(join(SRC, '30-ui-assign.js'), 'utf8')
  assert.match(assign, /onAssign\(modAssignInit\(inst, l, assigns\)\)/)
  assert.match(assign, /h\('button', \{ type: 'button', className: 'cb-mod-grpbtn[^']*', 'data-cb': 'mod-group-open'/) // keyboard: a button in the row head
  const css = readFileSync(join(SRC, '19-styles-modules.js'), 'utf8')
  for (const c of ['nw', 'dcol', 'search', 'cat', 'rail', 'grpbtn', 'fd']) assert.match(css, new RegExp(`\\.cb-mod-${c}[{,.>\\s]`), c)
  assert.match(assign, /startsWith\('mod_'\)/) // module findings only in the bus card (one alarm source)
  for (const f of ['30-ui-bus.js', '47-dialog-modules.js', '30-ui-assign.js', '19-styles-modules.js']) {
    const s = readFileSync(join(SRC, f), 'utf8').replace(/\$\{[^}]*\}/g, '')
    assert.ok(!/querySelector(All)?\((['"`])[^'"`]*\.(?!cb-)[a-z]/.test(s), `${f}: own selectors only`)
  }
})
