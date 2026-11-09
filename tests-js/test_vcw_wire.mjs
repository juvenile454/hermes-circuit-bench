// Station 03 WIRE with grouped blocks and the module block, station
// 04 SOLDER for the module part kinds. A block is offered only when the backend names it (without names: the four base
// blocks, selectors [data-cb=seg-block] [data-cb-opt=…] unchanged); the module block picks a module part of the
// project; the part kinds of modspec.KINDS have a height class in rules.json and an own pictogram.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { parseQuantity } from '../desktop-src/lib/units.js'
import { WIRE_BLOCKS, WIRE_EXTRA_BLOCKS, wireBlock, wireBlockNames, wireBlockList, wireBlockOf, wireGroups, wireModuleParts, buildWireParams, wireForm } from '../desktop-src/lib/wire.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const clone = x => JSON.parse(JSON.stringify(x))
const LASER = fx('project.laser-trigger').result.project
const MODS = fx('project.modules-demo').result.project
const BASE = ['npn_low_side', 'led', 'button_pullup', 'divider']
const ALL = [...BASE, 'module', 'level_shifter']
// the answer of POST /schematic without a block (routes/workshop.py: \"block is required\", hint lists the blocks)
const HINT_ENV = { ok: false, action: 'schematic.render', error: { code: 'invalid_args', message: 'block is required', hint: `blocks: ${ALL.join(', ')}` }, result: null }

test('block names from the backend: catalogue answer or the hint of a render without a block; else none', () => {
  assert.deepEqual(wireBlockNames(HINT_ENV), ALL)
  assert.deepEqual(wireBlockNames({ ok: true, result: { blocks: [{ block: 'led' }, 'module', { block: 'BAD name' }] } }), ['led', 'module'])
  assert.equal(wireBlockNames(fx('schematic.npn')), null, 'a drawn schematic (fixture backend) names no blocks')
  assert.equal(wireBlockNames({ ok: false, error: { code: 'stub', message: 'x' } }), null)
  assert.equal(wireBlockNames(null), null)
  // the route still builds its hint from the block catalogue (the format this reads)
  const py = readFileSync(join(ROOT, 'circuit_bench', 'dashboard', 'routes', 'workshop.py'), 'utf8')
  assert.match(py, /"block is required",\s*\n\s*f"blocks: \{', '\.join\(/)
})

test('offered blocks: base set without names; exactly the named ones with names (module with a part pick)', () => {
  assert.deepEqual(wireBlockList(null).map(b => b.block), BASE)
  const list = wireBlockList(ALL)
  assert.deepEqual(list.map(b => b.block), ALL)
  assert.equal(list.find(b => b.block === 'module').params[0].part, true)
  // only the names the backend knows: a backend without level_shifter never offers it
  assert.deepEqual(wireBlockList([...BASE, 'module']).map(b => b.block), [...BASE, 'module'])
  // the backend's parameter table wins for a block without a local form; an unknown block gets an empty form
  const remote = { ok: true, result: { blocks: [{ block: 'level_shifter', title: 'Level shifter', params: [{ name: 'r_pullup', type: 'ohm', default: 10000, required: false, doc: '' },
    { name: 'low', type: 'choice', default: '3V3', required: false, doc: '', choices: ['3V3'] }, { name: 'odd', type: 'weird', default: null, required: false, doc: '' }] }] } }
  const ls = wireBlockList(['level_shifter', 'relay'], remote)
  assert.deepEqual(ls[0].params.map(p => [p.name, p.unit || null, p.choice || null]), [['r_pullup', 'Ω', null], ['low', null, ['3V3']]])
  assert.deepEqual(ls[1], { block: 'relay', title: 'relay', params: [] })
  assert.equal(wireBlockOf({ block: 'x y' }), null)
  assert.equal(wireBlock('module').block, 'module', 'a stored module circuit finds its form')
})

test('groups: basic, modules, more; empty groups left out', () => {
  assert.deepEqual(wireGroups(wireBlockList(null)).map(g => g.id), ['basic'])
  assert.deepEqual(wireGroups(wireBlockList([...ALL, 'relay'])).map(g => [g.id, g.blocks.map(b => b.block)]),
    [['basic', BASE], ['modules', ['module', 'level_shifter']], ['more', ['relay']]])
})

test('module parts of the project (parts with a module field, by ref) and the part param', () => {
  const want = MODS.parts.filter(x => x.module).map(x => [x.ref, `${x.ref} ${x.value || x.module}`]).sort()
  assert.ok(want.length >= 2)
  assert.deepEqual(wireModuleParts(MODS).map(m => [m.ref, m.label]), want)
  assert.ok(wireModuleParts(MODS).every(m => !/^[RC]\d/.test(m.ref)), 'plain parts (R, C) are not module parts')
  assert.deepEqual(wireModuleParts(LASER), [])
  const p = clone(MODS)
  p.parts = [{ ref: 'U10', kind: 'module', value: 'SSD1306', module: 'ssd1306' }, { ref: 'U2', kind: 'ic', module: 'bme280' }, { ref: 'U3', kind: 'module', module: 'ds3231' }, { ref: 'R1', kind: 'resistor' }]
  assert.deepEqual(wireModuleParts(p).map(m => m.ref), ['U2', 'U3', 'U10'])
  const mod = WIRE_EXTRA_BLOCKS.find(b => b.block === 'module')
  assert.deepEqual(buildWireParams(mod, { part: 'U2' }, parseQuantity), { ok: true, params: { part: 'U2' }, errors: {} })
  assert.equal(buildWireParams(mod, { part: '' }, parseQuantity).errors.part, 'required')
  assert.match(buildWireParams(mod, { part: 'u2; x' }, parseQuantity).errors.part, /part ref/)
  assert.deepEqual(wireForm(mod, { part: 'U1' }), { part: 'U1' })
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
    + '\nexport const __t = { StationWire, StationSolder, CB, $project, $wire, $wireBlocks, $solderPlan, loadWireBlocks, CB_CSS_PARTS, SOLDER_ART_HEIGHT, SOLDER_ART_KINDS, solderArtPart, solderArtTop }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}
function fakeSdk() {
  const atom = v => { let cur = v; return { get: () => cur, set: n => { cur = n }, subscribe: () => () => {} } }
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
async function boot() {
  if (!mod) { globalThis.__cbSdk = fakeSdk(); mod = await loadBundle() }
  return mod
}
async function renderWire({ names = null, project = LASER, block = null } = {}) {
  await boot()
  mod.__t.CB.api = new Proxy({}, { get: () => async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  const p = clone(project)
  mod.__t.$project.set(p)
  mod.__t.$wire.set({ status: 'idle', key: null, env: null })
  mod.__t.$wireBlocks.set({ status: 'ready', names, env: null })
  // useState order in StationWire: blockId, circuitId, form, …
  HOOKS.queue = block ? [block, null, block === 'module' ? { part: wireModuleParts(p)[0]?.ref || '' } : {}] : []
  return expand(mod.__t.StationWire({ project: p }))
}
const opts = tree => find(byCb(tree, 'seg-block'), q => q['data-cb-opt']).map(o => o.props['data-cb-opt'])

test('loadWireBlocks asks once and keeps the names of the backend hint', async () => {
  await boot()
  const calls = []
  mod.__t.CB.api = { schematic: async body => { calls.push(body); return HINT_ENV } }
  mod.__t.$wireBlocks.set({ status: 'idle', names: null, env: null })
  await mod.__t.loadWireBlocks()
  await mod.__t.loadWireBlocks()
  assert.deepEqual(calls, [{}])
  assert.deepEqual(mod.__t.$wireBlocks.get().names, ALL)
  // a catalogue route, when the API has one, is preferred
  const cat = []
  mod.__t.CB.api = { schematicBlocks: async () => { cat.push(1); return { ok: true, result: { blocks: [{ block: 'led', params: [] }] } } }, schematic: async () => { throw new Error('not used') } }
  mod.__t.$wireBlocks.set({ status: 'idle', names: null, env: null })
  await mod.__t.loadWireBlocks()
  assert.deepEqual([cat.length, mod.__t.$wireBlocks.get().names], [1, ['led']])
})

test('without backend names: one plain control [data-cb=seg-block] with the four base blocks (selectors unchanged)', async () => {
  const tree = await renderWire({ names: null })
  const seg = byCb(tree, 'seg-block')
  assert.equal(seg.length, 1)
  assert.match(seg[0].props.className, /cb-seg\b/)
  assert.deepEqual(opts(tree), BASE)
  assert.equal(find(tree, q => q['data-cb-group']).length, 0)
})

test('with module blocks: grouped pick inside [data-cb=seg-block] (group word + control), data-cb-opt kept', async () => {
  const tree = await renderWire({ names: ALL })
  const seg = byCb(tree, 'seg-block')
  assert.equal(seg.length, 1)
  assert.deepEqual(opts(tree), ALL)
  const groups = find(seg, q => q['data-cb-group'])
  assert.deepEqual(groups.map(g => [g.props['data-cb-group'], norm(text(find(g, q => q.className === 'cb-wblocks-k')))]), [['basic', 'basic'], ['modules', 'modules']])
  assert.deepEqual(find(seg, q => q.role === 'group').map(g => g.props['aria-label']), ['Building block', 'Building block · basic', 'Building block · modules'])
})

test('module block: part pick from the project module parts; none → a sentence and “Add a module…”', async () => {
  let tree = await renderWire({ names: ALL, project: MODS, block: 'module' })
  const sel = byCb(tree, 'w-part')
  assert.equal(sel.length, 1)
  assert.deepEqual(find(sel, (q, n) => n.type === 'option').map(o => o.props.value), wireModuleParts(MODS).map(m => m.ref))
  assert.match(norm(text(byCb(tree, 'wire-params'))), /Module part.*BME280/)
  assert.equal(byCb(tree, 'wire-render').length, 1)
  assert.equal(byCb(tree, 'wire-no-module').length, 0)
  tree = await renderWire({ names: ALL, project: LASER, block: 'module' })
  assert.match(norm(text(byCb(tree, 'wire-no-module'))), /No module part in this project yet/)
  assert.equal(byCb(tree, 'wire-render').length, 0)
  assert.equal(byCb(tree, 'wire-add-module').length, 1)
  // picking the module block there clears the old drawing (nothing to draw) instead of keeping it
  const calls = []
  mod.__t.CB.api = new Proxy({}, { get: (o, k) => async (...a) => { calls.push(k); return { ok: false, error: { code: 'stub', message: 'stub' }, result: null } } })
  mod.__t.$wire.set({ status: 'ready', key: 'x', env: fx('schematic.npn'), circuit: null })
  HOOKS.queue = []
  const t3 = expand(mod.__t.StationWire({ project: clone(LASER) }))
  find(byCb(t3, 'seg-block'), q => q['data-cb-opt'] === 'module')[0].props.onClick()
  assert.equal(mod.__t.$wire.get().status, 'idle')
  assert.deepEqual(calls.filter(k => k === 'schematic'), [])
})

test('level_shifter without a parameter table: says the backend draws its defaults, Draw stays', async () => {
  const tree = await renderWire({ names: ALL, block: 'level_shifter' })
  assert.match(norm(text(byCb(tree, 'wire-params'))), /backend draws its defaults/)
  assert.equal(byCb(tree, 'wire-render').length, 1)
})

test('styles: the grouped pick wraps (never scrolls), group words ≥ 10 px, tokens only', async () => {
  await boot()
  const css = mod.__t.CB_CSS_PARTS.join('\n')
  assert.match(css, /\.cb-root \.cb-wblocks\{display:flex;flex-wrap:wrap/)
  assert.match(css, /\.cb-root \.cb-group--wblocks\{flex-wrap:wrap;min-width:0/)
  const k = /\.cb-root \.cb-wblocks-k\{([^}]*)\}/.exec(css)[1]
  assert.match(k, /font-size:10px/)
  assert.match(k, /color:var\(--cb-fg-dim\)/)
})

// ─── SOLDER: part kinds of module parts ─────────────────────────────────────────────────────────────────────
test('SOLDER: every modspec part kind (ic, module) has a height class in rules.json and an own pictogram; module stands tallest', async () => {
  await boot()
  const spec = readFileSync(join(ROOT, 'circuit_bench', 'bench_core', 'modspec.py'), 'utf8')
  const kinds = [...(/^KINDS: tuple\[str, \.\.\.\] = \(([^)]*)\)/m.exec(spec)[1]).matchAll(/"([a-z_]+)"/g)].map(m => m[1])
  assert.deepEqual(kinds, ['ic', 'module'])
  const rules = JSON.parse(readFileSync(join(ROOT, 'circuit_bench', 'data', 'solder', 'rules.json'), 'utf8'))
  for (const k of kinds) {
    const r = rules.kinds.find(x => x.kind === k)
    assert.ok(r, `rules.json has kind ${k}`)
    assert.equal(mod.__t.SOLDER_ART_HEIGHT[k], r.height_class, k)
    assert.ok(mod.__t.SOLDER_ART_KINDS.includes(k), `${k} has an own drawing`)
    assert.match(mod.__t.solderArtPart(k), new RegExp(`data-cb-art="${k}"`))
  }
  assert.ok(mod.__t.solderArtTop('module') < mod.__t.solderArtTop('ic'), 'module (tall) above ic (medium)')
  assert.equal(rules.kinds.find(x => x.kind === 'module').mechanical, true, 'module parts go last (mechanical)')
})

test('SOLDER: a plan with module parts shows their kind and height word in the strip', async () => {
  await boot()
  const p = clone(MODS)
  const steps = [{ id: 's1', n: 1, refs: ['U1', 'U2'], kind: 'ic', action: 'Solder the ICs U1, U2.', hints: [] },
    { id: 's2', n: 2, refs: ['U3'], kind: 'module', action: 'Solder the module U3.', hints: [] }]
  p.solder = { steps, done: [] }
  mod.__t.CB.api = new Proxy({}, { get: () => async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  mod.__t.$project.set(p)
  mod.__t.$solderPlan.set({ status: 'idle', env: null })
  HOOKS.queue = []
  const tree = expand(mod.__t.StationSolder({ project: p }))
  const strip = byCb(tree, 'solder-heights')
  assert.equal(strip.length, 1)
  assert.match(byCb(strip, 'height-1')[0].props.title, /ic · medium/)
  assert.match(byCb(strip, 'height-2')[0].props.title, /module · tall/)
})
