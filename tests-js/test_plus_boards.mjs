// DevKit layouts ESP32-DevKitC V4 (J2/J3, 2×19) and ESP32-C3-DevKitM-1 (J1/J3, 2×15) next to the
// S3-DevKitC-1 (J1/J3, 2×22). DEVKITS/CHIPS mirror data/boards, the module drawing comes from the layout, and the
// product bundle's BoardView renders every layout fixture (data-cb anchors) through a tiny element renderer; the PLAN
// DevKit choice only offers existing layouts and a chip choice switches to the chip's default DevKit.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { CHIPS, DEVKITS, devkitInfo, devkitTitle, boardModule, pinView, chipInfo, variantInfo } from '../desktop-src/lib/pins.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const FXDIR = join(ROOT, 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(FXDIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FXDIR, f), 'utf8'))]))
const BOARDS_DIR = join(ROOT, 'circuit_bench', 'data', 'boards')
const BOARDS = readdirSync(BOARDS_DIR).filter(f => f.endsWith('.json')).sort().map(f => JSON.parse(readFileSync(join(BOARDS_DIR, f), 'utf8')))
const clone = x => JSON.parse(JSON.stringify(x))
const tick = () => new Promise(r => setTimeout(r, 30))
// every layout in data/boards (S2-DevKitC-1, C6-DevKitC-1, C6-DevKitM-1, WT32-ETH01 included); `headers` are
// the top header ids of the left and right side (WT32: PROG + IO on both sides, shared ids)
const EXPECT = {
  'esp32-s3-devkitc-1': { headers: ['J1', 'J3'], len: 22, module: 'WROOM-1', buttons: ['BOOT', 'RST'] },
  'esp32-devkitc-v4': { headers: ['J2', 'J3'], len: 19, module: 'WROOM-32E', buttons: ['EN', 'BOOT'] },
  'esp32-c3-devkitm-1': { headers: ['J1', 'J3'], len: 15, module: 'C3-MINI-1', buttons: ['BOOT', 'RST'] },
  'esp32-s2-devkitc-1': { headers: ['J1', 'J3'], len: 22, module: 'S2-SOLO-2', buttons: ['RST', 'BOOT'] },
  'esp32-c6-devkitc-1': { headers: ['J1', 'J3'], len: 16, module: 'C6-WROOM-1', buttons: ['BOOT', 'RST'] },
  'esp32-c6-devkitm-1': { headers: ['J1', 'J3'], len: 15, module: 'C6-MINI-1', buttons: ['BOOT', 'RST'] },
  'wt32-eth01': { headers: ['PROG', 'PROG'], len: 13, module: 'WT32-S1', buttons: [] }
}
/** Pins of one side in data order, each with its header id (a header id may appear on both sides). */
const sidePins = (b, side) => b.headers.filter(h => h.side === side).flatMap(h => h.pins.map(p => ({ ...p, header: h.id })))

// ------------------------------------------------------------------------------------------------ data mirrors

test('DEVKITS mirror data/boards; every chip has its default DevKit', () => {
  assert.deepEqual(DEVKITS.map(d => d.id).sort(), BOARDS.map(b => b.id))
  for (const b of BOARDS) {
    const d = devkitInfo(b.id)
    assert.deepEqual([d.chip, d.title, d.revision], [b.chip, b.title, b.revision], b.id)
    assert.deepEqual([d.module, d.variant], [b.module?.name ?? null, b.module?.variant ?? null], b.id)
    // the chip's default DevKit is one of its layouts (ESP32: DevKitC V4, the WT32-ETH01 is chosen explicitly)
    assert.equal(devkitInfo(chipInfo(b.chip).devkit)?.chip, b.chip, b.id)
    assert.ok(FX[`board.${b.id}`], `fixture board.${b.id}.json`)
    assert.equal(FX[`board.${b.id}`].result.id, b.id)
  }
  for (const c of CHIPS) assert.equal(devkitInfo(c.devkit)?.chip, c.id, c.id)
  assert.equal(devkitTitle(devkitInfo('esp32-devkitc-v4')), 'ESP32-DevKitC V4')
  assert.equal(Object.keys(EXPECT).length, BOARDS.length)
})

test('layout fixtures: header ids and lengths as in data/boards', () => {
  for (const b of BOARDS) {
    const lay = FX[`board.${b.id}`].result
    const e = EXPECT[b.id]
    assert.deepEqual([lay.left[0].header, lay.right[0].header], e.headers, b.id)
    assert.deepEqual([lay.left.length, lay.right.length], [e.len, e.len], b.id)
    assert.deepEqual(lay.left.map(p => [p.header, p.label]), sidePins(b, 'left').map(p => [p.header, p.label]), b.id)
    assert.deepEqual(lay.right.map(p => [p.header, p.label]), sidePins(b, 'right').map(p => [p.header, p.label]), b.id)
  }
})

test('boardModule: module name, flash and buttons from the layout; the S3 keeps WROOM-1 + variant', () => {
  const dk = boardModule(FX['board.esp32-devkitc-v4'].result, null)
  assert.deepEqual(dk, { name: 'WROOM-32E', flash_mb: 4, antenna: 'PCB ANTENNA', buttons: ['EN', 'BOOT'] })
  const c3 = boardModule(FX['board.esp32-c3-devkitm-1'].result, null)
  assert.deepEqual(c3, { name: 'C3-MINI-1', flash_mb: 4, antenna: 'PCB ANTENNA', buttons: ['BOOT', 'RST'] })
  const s3 = boardModule(FX['board.esp32-s3-devkitc-1'].result, variantInfo('esp32s3', 'n16r8'))
  assert.deepEqual(s3, { name: 'WROOM-1', flash_mb: 16, antenna: 'PCB ANTENNA', buttons: ['BOOT', 'RST'] })
  // an ESP32 variant is a whole module and replaces the DevKitC V4 standard module
  const wrover = boardModule(FX['board.esp32-devkitc-v4'].result, variantInfo('esp32', 'wrover-e'))
  assert.deepEqual(wrover, { name: 'WROVER-E', flash_mb: 8, antenna: 'PCB ANTENNA', buttons: ['EN', 'BOOT'] })
  assert.equal(boardModule(FX['board.esp32-devkitc-v4'].result, variantInfo('esp32', 'wroom-32e')).name, 'WROOM-32E')
  assert.equal(boardModule(null, null).flash_mb, null)
})

test('pinView: "IO34" labels read like "34"; named pins keep the GPIO as tag; EN is the reset pin', () => {
  const lay = FX['board.esp32-devkitc-v4'].result
  const hp = (side, n) => lay[side].find(p => p.n === n)
  const base = gpio => ({ pin: gpio, verdict: 'ok', reasons: [] })
  const io34 = pinView(hp('left', 5), null, base(34), lay.onboard)
  assert.deepEqual([io34.name, io34.tag, io34.state, io34.gpio], ['IO34', '', 'free', 34])
  const vp = pinView(hp('left', 3), null, base(36), lay.onboard)
  assert.deepEqual([vp.name, vp.tag], ['VP', '36'])
  const en = pinView(hp('left', 2), null, null)
  assert.deepEqual([en.state, en.name, en.gpio], ['reset', 'EN', null])
  const clk = pinView(hp('right', 19), null, { pin: 6, verdict: 'blocked', reasons: [{ rule_id: 'esp32.spi_flash', severity: 'blocked', message: 'flash' }] })
  assert.deepEqual([clk.state, clk.name, clk.tag], ['bad', 'CLK', 'FLASH · 6'])
  const c3 = FX['board.esp32-c3-devkitm-1'].result
  const led = pinView(c3.right.find(p => p.n === 6), null, { pin: 8, verdict: 'caution', reasons: [{ rule_id: 'onboard', severity: 'caution', message: 'RGB LED' }] }, c3.onboard)
  assert.deepEqual([led.name, led.tag, led.state], ['IO8', 'RGB LED', 'warn'])
})

// ------------------------------------------------------------------------------------------------ rendering

function fakeSdk() {
  const atom = v => {
    let cur = v
    const subs = new Set()
    return { get: () => cur, set: n => { cur = n; for (const s of subs) s(n) }, subscribe: fn => { subs.add(fn); return () => subs.delete(fn) } }
  }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', THEMES_AREA: 'themes',
    TRANSCRIPT_DIRECTIVE_AREA: 'directives', STATUSBAR_AREAS: { right: 'statusBar.right' }, PANES_AREA: 'panes',
    host: { navigate: () => {}, openWorkspace: () => {}, notify: () => {} } }
}

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = v => [typeof v === "function" ? v() : v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { BoardView, PlanToolbar, CB, $view, $board, $project, setWhatIf, loadBoard, runChecks, entrySources }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

/** Expand function components into a tree of host elements {type, props, children[]} (strings for text). */
function render(node) {
  if (node === null || node === undefined || node === false || node === true) return []
  if (Array.isArray(node)) return node.flatMap(render)
  if (typeof node !== 'object') return [String(node)]
  if (typeof node.type === 'function') return render(node.type(node.props))
  if (node.type === '#fragment') return render(node.props.children)
  const { children, ...props } = node.props
  return [{ type: node.type, props, children: render(children) }]
}

function walk(tree, fn) {
  for (const n of tree) {
    if (typeof n === 'string') continue
    fn(n)
    walk(n.children, fn)
  }
}

const textOf = n => (typeof n === 'string' ? n : n.children.map(textOf).join(''))
const byCb = (tree, cb) => {
  const out = []
  walk(tree, n => { if (n.props['data-cb'] === cb) out.push(n) })
  return out
}

function fakeCtx() {
  const calls = []
  const bodies = []
  const ctx = {
    calls,
    bodies,
    rest: async (path, opts = {}) => {
      calls.push(`${opts.method || 'GET'} ${path}`)
      if (opts.body !== undefined) bodies.push({ path, body: clone(opts.body) })
      const m = /^\/boards\/([a-z0-9-]+)$/.exec(path)
      if (m && FX[`board.${m[1]}`]) return clone(FX[`board.${m[1]}`])
      if (path === '/pins/check') return clone(FX['pins.check'])
      if (path === '/health') return clone(FX.health)
      return { ok: false, action: 'x', summary: 'no', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: { code: 'not_found', message: 'no' } }
    },
    socket: () => () => {}, onEvent: () => () => {}, onDispose: () => {}, setInterval: () => () => {},
    setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); return () => clearTimeout(t) },
    storage: { get: (k, d) => d, set: () => {} }, registerMany: () => () => {}, register: () => () => {},
    registerSettingsPage: () => () => {}, os: {}
  }
  return ctx
}

test('BoardView renders all layouts with their data-cb anchors (pins, headers, module, buttons)', async () => {
  globalThis.__cbSdk = fakeSdk()
  const { __t: t } = await loadBundle()
  for (const b of BOARDS) {
    const layout = FX[`board.${b.id}`].result
    const e = EXPECT[b.id]
    const tree = render(t.BoardView({ layoutState: { status: 'ready', id: b.id, layout }, mapState: { status: 'idle', env: null }, rows: [],
      board: { chip: b.chip, variant: null, wifi: true, devkit: b.id }, selected: null, suggestPins: [], onSelect: () => {} }))
    const [board] = byCb(tree, 'board')
    assert.ok(board, `${b.id}: no data-cb=board`)
    assert.equal(board.props['data-cb-board'], b.id)
    const hdrs = []
    walk([board], n => { if (n.props.className === 'cb-board-hdr cb-label') hdrs.push(textOf(n)) })
    assert.deepEqual(hdrs, e.headers, b.id)
    for (const side of ['left', 'right']) {
      const want = sidePins(b, side)
      const [col] = byCb(tree, `header-${side}`)
      const pins = []
      walk([col], n => { if (n.props.className === 'cb-pin') pins.push(n) })
      assert.equal(pins.length, e.len, `${b.id} ${side}`)
      assert.deepEqual(pins.map(p => p.props['data-cb']), want.map(p => (p.kind === 'gpio' ? `pin-${p.gpio}` : `pin-${p.header}-${p.n}`)))
      // GPIO pins are buttons (selectable), power/ground/reset/nc/signal are plain
      assert.deepEqual(pins.map(p => p.type), want.map(p => (p.kind === 'gpio' ? 'button' : 'div')))
      assert.ok(pins.every(p => p.props['data-cb-state'] !== undefined))
    }
    assert.equal(textOf(byCb(tree, 'board-module-name')[0]), e.module, b.id)
    assert.deepEqual(byCb(tree, 'board-buttons')[0].children.map(textOf), e.buttons.map(x => `[${x}]`))
    assert.equal(byCb(tree, 'psram-bracket').length, 0)
  }
  // the S3 N16R8 still gets its octal PSRAM bracket; the other boards never do
  const s3 = FX['board.esp32-s3-devkitc-1'].result
  const tree = render(t.BoardView({ layoutState: { status: 'ready', id: s3.id, layout: s3 }, mapState: { status: 'idle', env: null }, rows: [],
    board: { chip: 'esp32s3', variant: 'n16r8', wifi: true, devkit: s3.id }, selected: null, suggestPins: [], onSelect: () => {} }))
  assert.equal(byCb(tree, 'psram-bracket').length, 1)
  // no layout for a chip: the empty state names every existing layout
  const none = render(t.BoardView({ layoutState: { status: 'none' }, mapState: { status: 'idle' }, rows: [], board: { chip: 'esp32c6' }, selected: null, suggestPins: [], onSelect: () => {} }))
  assert.ok(textOf(byCb(none, 'board-none')[0]).includes(DEVKITS.map(devkitTitle).join(', ')))
  assert.match(textOf(byCb(none, 'board-none')[0]), /ESP32-S3-DevKitC-1 v1\.1/)
})

test('PLAN: the DevKit choice offers only existing layouts; DevKit → chip and chip → default DevKit load the matching view', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  const ctx = fakeCtx()
  mod.default.register(ctx)
  assert.ok(t.CB.api, 'register sets the API client')
  t.$view.set({ ...t.$view.get(), chip: 'esp32s3', variant: 'n16r8', wifi: true, selected: null })
  const toolbar = () => render(t.PlanToolbar({ rows: [], view: t.$view.get(), suggesting: false }))
  // seven layouts → a dropdown grouped by chip (optgroups), the value is the shown DevKit
  const seg = tree => byCb(tree, 'seg-devkit')[0]
  const options = tree => seg(tree).children.flatMap(g => g.children)
  const opts = tree => options(tree).map(o => ({ id: o.props.value, pressed: o.props.value === seg(tree).props.value ? 'true' : 'false', label: textOf(o) }))
  const choose = (tree, id) => seg(tree).props.onChange({ target: { value: id } })
  let tree = toolbar()
  assert.equal(seg(tree).type, 'select')
  assert.deepEqual(opts(tree).map(o => o.id), DEVKITS.map(d => d.id))
  assert.deepEqual(opts(tree).filter(o => o.pressed === 'true').map(o => o.id), ['esp32-s3-devkitc-1'])
  assert.equal(byCb(tree, 'seg-variant').length, 1)
  // choose the DevKitC V4: chip ESP32, its layout is loaded
  choose(tree, 'esp32-devkitc-v4')
  await tick()
  assert.equal(t.$view.get().chip, 'esp32')
  assert.deepEqual([t.$board.get().status, t.$board.get().id, t.$board.get().layout?.left.length], ['ready', 'esp32-devkitc-v4', 19])
  assert.ok(ctx.calls.includes('GET /boards/esp32-devkitc-v4'))
  tree = toolbar()
  assert.deepEqual(opts(tree).filter(o => o.pressed === 'true').map(o => o.id), ['esp32-devkitc-v4'])
  // the ESP32 has module variants; the DevKitC V4 default is its standard module WROOM-32E
  const vopts = byCb(tree, 'seg-variant')[0].children.map(b => [b.props['data-cb-opt'], textOf(b), b.props['aria-pressed']])
  assert.deepEqual(vopts, [['wrover-e', 'WROVER-E', 'false'], ['wroom-32e', 'WROOM-32E', 'true']])
  assert.equal(t.$view.get().variant, 'wroom-32e')
  assert.equal(textOf(byCb(tree, 'group-module')[0]).startsWith('module'), true)
  // choose the chip ESP32-C3: its default DevKit follows
  byCb(tree, 'seg-chip')[0].children.find(b => b.props['data-cb-opt'] === 'esp32c3').props.onClick()
  await tick()
  assert.deepEqual([t.$view.get().chip, t.$board.get().id, t.$board.get().layout?.right.length], ['esp32c3', 'esp32-c3-devkitm-1', 15])
  assert.deepEqual(opts(toolbar()).filter(o => o.pressed === 'true').map(o => o.id), ['esp32-c3-devkitm-1'])
  // and back to the S3
  t.setWhatIf({ chip: 'esp32s3' })
  await tick()
  assert.deepEqual([t.$board.get().id, t.$board.get().layout?.left.length], ['esp32-s3-devkitc-1', 22])
  assert.deepEqual(ctx.calls.filter(c => /^(POST \/serial|POST \/board\/)/.test(c)), [])
})

test('PLAN on the ESP32: MODULE choice WROOM-32E / WROVER-E steers pins.check and the board drawing', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  const ctx = fakeCtx()
  mod.default.register(ctx)
  // a project on the DevKitC V4 without a confirmed module, LED on GPIO16
  t.$project.set({ id: 'p', rev: 1, title: 'p', board: { chip: 'esp32', module: null, variant: null, devkit: 'esp32-devkitc-v4', detected: null },
    options: { wifi: true }, assignments: [{ role: 'LED', mode: 'out', pin: 16 }] })
  t.$view.set({ ...t.$view.get(), chip: 'esp32', variant: null, wifi: true, selected: null })
  await t.loadBoard('esp32-devkitc-v4')
  await tick()
  const lastCheck = () => ctx.bodies.filter(b => b.path === '/pins/check' && b.body.assignments.some(a => a.role === 'LED')).at(-1)?.body
  assert.deepEqual([lastCheck().chip, lastCheck().variant, lastCheck().devkit], ['esp32', null, 'esp32-devkitc-v4'])
  const toolbar = () => render(t.PlanToolbar({ rows: [], view: t.$view.get(), suggesting: false }))
  let seg = byCb(toolbar(), 'seg-variant')[0]
  assert.deepEqual(seg.children.map(b => b.props['aria-pressed']), ['false', 'false'], 'unknown module: nothing pressed')
  assert.deepEqual(seg.children.map(b => b.props.title), ['8 MB flash, 8 MB PSRAM', '4 MB flash, no PSRAM'])
  for (const [id, label, reserve] of [['wrover-e', 'WROVER-E', 1], ['wroom-32e', 'WROOM-32E', 0]]) {
    seg.children.find(b => b.props['data-cb-opt'] === id).props.onClick()
    await tick()
    assert.equal(t.$view.get().variant, id)
    assert.deepEqual([lastCheck().chip, lastCheck().variant], ['esp32', id])
    seg = byCb(toolbar(), 'seg-variant')[0]
    assert.deepEqual(seg.children.filter(b => b.props['aria-pressed'] === 'true').map(b => b.props['data-cb-opt']), [id])
    const layout = t.$board.get().layout
    const tree = render(t.BoardView({ layoutState: { status: 'ready', id: layout.id, layout }, mapState: { status: 'idle', env: null }, rows: [],
      board: { chip: 'esp32', variant: id, wifi: true, devkit: layout.id }, selected: null, suggestPins: [], onSelect: () => {} }))
    assert.equal(textOf(byCb(tree, 'board-module-name')[0]), label)
    assert.equal(byCb(tree, 'board-reserve').length, reserve, id)
    assert.equal(byCb(tree, 'psram-bracket').length, 0)
  }
  assert.deepEqual(ctx.calls.filter(c => /^(POST \/serial|POST \/board\/)/.test(c)), [])
})

test('inspector sources: a rule sourced from the DevKit guide is listed once (esp32.psram_16_17, c3.uart0)', async () => {
  globalThis.__cbSdk = fakeSdk()
  const { __t: t } = await loadBundle()
  const env = { sources: [{ id: 'idf-v6.1-gpio-esp32', title: 'IDF' }, { id: 'devkitc-esp32-v4', title: 'ESP32-DevKitC V4 User Guide' }] }
  assert.deepEqual(t.entrySources([env], ['devkitc-esp32-v4', 'devkitc-esp32-v4']).map(s => s.id), ['devkitc-esp32-v4'])
  assert.deepEqual(t.entrySources([env], ['idf-v6.1-gpio-esp32', 'devkitc-esp32-v4']).map(s => s.id), ['idf-v6.1-gpio-esp32', 'devkitc-esp32-v4'])
})
