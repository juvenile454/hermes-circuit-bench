// Bench for the chips and boards ESP32-S2, ESP32-C6, the nine S3 variants and WT32-ETH01.
// Mirrors CHIPS/DEVKITS ↔ circuit_bench/data, module variant per board (module.variant, no variants[].boards,
// WT32-S1 = variant unknown), pinView for nc/signal, boardModule/boardPorts/boardWarnings, and the product bundle
// (BoardView, board warnings in PLAN and inspector, PLAN toolbar, new-project dialog) through a tiny element renderer.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import {
  CHIPS, DEVKITS, chipInfo, variantInfo, devkitInfo, devkitsOf, resolveDevkit, defaultVariant, boardModule, boardPorts,
  boardWarnings, warningMeta, variantGroups, variantTitle, pinView, headerIds, headerGpios
} from '../desktop-src/lib/pins.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const readDir = dir => readdirSync(dir).filter(f => f.endsWith('.json')).sort().map(f => JSON.parse(readFileSync(join(dir, f), 'utf8')))
const PINS = readDir(join(ROOT, 'circuit_bench', 'data', 'pins'))
const BOARDS = readDir(join(ROOT, 'circuit_bench', 'data', 'boards'))
const FXDIR = join(ROOT, 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(FXDIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FXDIR, f), 'utf8'))]))
const lay = id => FX[`board.${id}`].result
const clone = x => JSON.parse(JSON.stringify(x))
const tick = () => new Promise(r => setTimeout(r, 30))

// ------------------------------------------------------------------------------------------------ data mirrors

test('CHIPS mirror data/pins: every chip, variants in data order with label, PSRAM, flash, module; no board filter', () => {
  assert.deepEqual(CHIPS.map(c => c.id).sort(), PINS.map(d => d.chip).sort())
  for (const d of PINS) {
    const c = chipInfo(d.chip)
    assert.equal(c.label, d.title)
    assert.deepEqual(c.variants.map(v => [v.id, v.label, v.psram, v.flash_mb, v.psram_mb]),
      d.variants.map(v => [v.id, v.label, v.psram ?? null, v.flash_mb ?? null, v.psram_mb ?? null]), d.chip)
    // `module` only where the variant is a whole module (ESP32, C6); the S3 ordering codes keep the WROOM-1 drawing
    for (const v of c.variants) if (v.module) assert.equal(v.module, d.variants.find(x => x.id === v.id).module, `${d.chip} ${v.id}`)
    // no variants[].boards, so the Bench filters nothing by board
    assert.ok(d.variants.every(v => v.boards === undefined), `${d.chip}: variants[].boards appeared, the Bench must filter by board`)
  }
  assert.deepEqual(chipInfo('esp32s2').variants, [])
  assert.deepEqual(chipInfo('esp32c6').variants.map(v => v.id), ['mini-1', 'wroom-1'])
  assert.equal(chipInfo('esp32s3').variants.length, 9)
  assert.equal(chipInfo('esp32s3').variants.at(-1).id, 'n16r8')
  assert.ok(chipInfo('esp32s3').variants.every(v => !v.module))
})

test('DEVKITS mirror data/boards (chip, title, revision, module, module.variant); default DevKits per chip', () => {
  assert.deepEqual(DEVKITS.map(d => d.id).sort(), BOARDS.map(b => b.id).sort())
  for (const b of BOARDS) {
    const d = devkitInfo(b.id)
    assert.deepEqual([d.chip, d.title, d.revision, d.module, d.variant],
      [b.chip, b.title, b.revision, b.module?.name ?? null, b.module?.variant ?? null], b.id)
    if (b.module?.variant != null) assert.ok(variantInfo(b.chip, b.module.variant), `${b.id}: module.variant ${b.module.variant} is a variant of ${b.chip}`)
  }
  // grouped by chip in CHIPS order (the PLAN DevKit row reads chip by chip)
  const order = CHIPS.map(c => c.id)
  const idx = DEVKITS.map(d => order.indexOf(d.chip))
  assert.deepEqual(idx, [...idx].sort((a, b) => a - b))
  assert.deepEqual(Object.fromEntries(CHIPS.map(c => [c.id, c.devkit])), {
    esp32: 'esp32-devkitc-v4', esp32s2: 'esp32-s2-devkitc-1', esp32s3: 'esp32-s3-devkitc-1', esp32c3: 'esp32-c3-devkitm-1', esp32c6: 'esp32-c6-devkitc-1'
  })
  assert.deepEqual(devkitsOf('esp32').map(d => d.id), ['esp32-devkitc-v4', 'wt32-eth01'])
  assert.deepEqual(devkitsOf('esp32c6').map(d => d.id), ['esp32-c6-devkitc-1', 'esp32-c6-devkitm-1'])
  assert.equal(resolveDevkit('esp32', 'wt32-eth01'), 'wt32-eth01')
  assert.equal(resolveDevkit('esp32', 'esp32-c6-devkitc-1'), 'esp32-devkitc-v4')
  assert.equal(resolveDevkit('esp32s2', null), 'esp32-s2-devkitc-1')
})

test('variant filter / default per board: module.variant, none on the WT32-S1, chip default without module data', () => {
  for (const b of BOARDS) {
    const want = !chipInfo(b.chip).variants.length ? null
      : b.module ? (b.module.variant ?? null) : chipInfo(b.chip).variants.at(-1).id
    assert.equal(defaultVariant(b.chip, b.id), want, b.id)
  }
  assert.equal(defaultVariant('esp32', 'wt32-eth01'), null)
  assert.equal(defaultVariant('esp32', 'esp32-devkitc-v4'), 'wroom-32e')
  assert.equal(defaultVariant('esp32c6', 'esp32-c6-devkitm-1'), 'mini-1')
  assert.equal(defaultVariant('esp32c6', 'esp32-c6-devkitc-1'), 'wroom-1')
  assert.equal(defaultVariant('esp32s3', 'esp32-s3-devkitc-1'), 'n16r8')
  assert.equal(defaultVariant('esp32s3'), 'n16r8')
  assert.equal(defaultVariant('esp32s2', 'esp32-s2-devkitc-1'), null)
  // a DevKit of another chip is ignored (chip default)
  assert.equal(defaultVariant('esp32', 'esp32-c6-devkitm-1'), 'wroom-32e')
})

test('S3 module choice: nine variants grouped by PSRAM kind none / quad / octal; titles never print "null"', () => {
  assert.deepEqual(variantGroups('esp32s3').map(g => [g.psram, g.label, g.variants.map(v => v.id)]), [
    [null, 'no PSRAM', ['n4', 'n8', 'n16']], ['quad', 'quad PSRAM', ['n4r2', 'n8r2', 'n16r2']], ['octal', 'octal PSRAM', ['n4r8', 'n8r8', 'n16r8']]])
  assert.deepEqual(variantGroups('esp32').map(g => [g.psram, g.variants.map(v => v.id)]), [[null, ['wroom-32e']], ['spi', ['wrover-e']]])
  assert.deepEqual(variantGroups('esp32s2'), [])
  assert.equal(variantTitle(variantInfo('esp32s3', 'n16r2')), '16 MB flash, 2 MB PSRAM (quad)')
  assert.equal(variantTitle(variantInfo('esp32s3', 'n4')), '4 MB flash, no PSRAM')
  assert.equal(variantTitle(variantInfo('esp32c6', 'mini-1')), 'ESP32-C6-MINI-1, no PSRAM')
  for (const c of CHIPS) for (const v of c.variants) assert.doesNotMatch(variantTitle(v), /null|undefined/)
})

// ------------------------------------------------------------------------------------------------ pure presentation

test('pinView for nc and signal: plain pins with symbol and word, not selectable', () => {
  const c6 = lay('esp32-c6-devkitc-1')
  const nc = pinView(c6.left.find(p => p.n === 16), null, null, c6.onboard)
  assert.deepEqual([nc.state, nc.name, nc.symbol, nc.gpio], ['nc', 'NC', '∅', null])
  assert.match(nc.tag, /∅ unwired/)
  assert.match(nc.title, /not connected/)
  const wt = lay('wt32-eth01')
  const link = pinView(wt.left.find(p => p.label === 'LINK'), null, null, wt.onboard)
  assert.deepEqual([link.state, link.name, link.symbol, link.gpio], ['signal', 'LINK', '~', null])
  assert.match(link.tag, /~ signal/)
  assert.match(link.title, /board signal, not a GPIO/)
  // nc / signal never enter the board map (only kind gpio)
  assert.ok(!headerGpios(wt).includes(null))
  assert.deepEqual(headerGpios(wt).sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 12, 14, 15, 17, 32, 33, 35, 36, 39])
})

test('boardModule / boardPorts for the WT32: WT32-S1, 4 MB, no antenna invented, no buttons, RJ45 instead of USB', () => {
  const wt = lay('wt32-eth01')
  assert.deepEqual(boardModule(wt, null), { name: 'WT32-S1', flash_mb: 4, antenna: null, buttons: [] })
  // a chosen ESP32 variant only changes the rules; the unknown WT32-S1 keeps its name and flash
  assert.deepEqual(boardModule(wt, variantInfo('esp32', 'wrover-e')), { name: 'WT32-S1', flash_mb: 4, antenna: null, buttons: [] })
  assert.deepEqual(boardPorts(wt).map(p => [p.label, p.kind, p.connector]), [['LAN', 'rj45', true]])
  assert.match(boardPorts(wt)[0].title, /RJ45/)
  assert.deepEqual(headerIds(wt.left), ['PROG', 'IO'])
  assert.deepEqual(headerIds(wt.right), ['PROG', 'IO'])
  // the other new boards
  assert.deepEqual(boardModule(lay('esp32-s2-devkitc-1'), null), { name: 'S2-SOLO-2', flash_mb: 8, antenna: 'PCB ANTENNA', buttons: ['RST', 'BOOT'] })
  assert.deepEqual(boardPorts(lay('esp32-s2-devkitc-1')).map(p => [p.label, p.kind, p.connector]), [['USB', 'usb_otg', false], ['UART', 'usb_uart_bridge', false]])
  assert.match(boardPorts(lay('esp32-s2-devkitc-1'))[0].title, /OTG \(drawing only\) · GPIO19\/20/)
  const c6 = lay('esp32-c6-devkitc-1')
  assert.deepEqual(boardModule(c6, variantInfo('esp32c6', 'wroom-1')), { name: 'C6-WROOM-1', flash_mb: 8, antenna: 'PCB ANTENNA', buttons: ['BOOT', 'RST'] })
  assert.deepEqual(boardModule(c6, variantInfo('esp32c6', 'mini-1')).flash_mb, null, 'flash of another module is not the layout\'s')
  assert.deepEqual(boardModule(lay('esp32-c6-devkitm-1'), variantInfo('esp32c6', 'mini-1')), { name: 'C6-MINI-1', flash_mb: 4, antenna: 'PCB ANTENNA', buttons: ['BOOT', 'RST'] })
  // a layout without the buttons field keeps BOOT/RST (S3-DevKitC-1 v1.1)
  assert.deepEqual(boardModule(lay('esp32-s3-devkitc-1'), null).buttons, ['BOOT', 'RST'])
})

test('boardWarnings: WT32 danger first with symbol and word; other boards none', () => {
  const ws = boardWarnings(lay('wt32-eth01'))
  assert.deepEqual(ws.map(w => [w.id, w.severity, w.tone, w.symbol, w.word]), [
    ['wt32.power_exclusive', 'danger', 'bad', '⚠', 'DANGER'], ['wt32.supply_current', 'caution', 'warn', '!', 'CAUTION']])
  assert.equal(ws[0].message, 'Feed either 3V3 or 5V, never both.')
  assert.deepEqual(boardWarnings({ warnings: [{ id: 'a', severity: 'info', message: 'i' }, { id: 'b', severity: 'danger', message: 'd' }] }).map(w => w.id), ['b', 'a'])
  assert.deepEqual(warningMeta('info'), { tone: 'dim', symbol: 'i', word: 'NOTE' })
  for (const b of BOARDS) if (b.id !== 'wt32-eth01') assert.deepEqual(boardWarnings(lay(b.id)), [], b.id)
})

// ------------------------------------------------------------------------------------------------ bundle rendering

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

/** useState with real slots (reset the index before each render), so a dialog can be driven through its handlers. */
const HOOKS = { slots: [], i: 0 }
globalThis.__cbHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const __H = globalThis.__cbHooks; const useState = v => { const k = __H.i++; if (!(k in __H.slots)) __H.slots[k] = typeof v === "function" ? v() : v;'
      + ' return [__H.slots[k], n => { __H.slots[k] = typeof n === "function" ? n(__H.slots[k]) : n }] }, useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { BoardView, BoardWarnings, PlanToolbar, StationPlan, NewProjectDialog, CB, $view, $board, $project, setWhatIf, loadBoard, viewBoard, isWhatIf }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

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
const byType = (tree, type) => {
  const out = []
  walk(tree, n => { if (n.type === type) out.push(n) })
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
      if (path === '/projects' && opts.method === 'POST') return { ok: false, action: 'project.create', summary: 'test', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: { code: 'invalid_args', message: 'test stop' } }
      return { ok: false, action: 'x', summary: 'no', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: { code: 'not_found', message: 'no' } }
    },
    socket: () => () => {}, onEvent: () => () => {}, onDispose: () => {}, setInterval: () => () => {},
    setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); return () => clearTimeout(t) },
    storage: { get: (k, d) => d, set: () => {} }, registerMany: () => () => {}, register: () => () => {},
    registerSettingsPage: () => () => {}, os: {}
  }
  return ctx
}

const boardTree = (t, id, variant = null) => {
  const layout = lay(id)
  return render(t.BoardView({ layoutState: { status: 'ready', id, layout }, mapState: { status: 'idle', env: null }, rows: [],
    board: { chip: layout.chip, variant, wifi: true, devkit: id }, selected: null, suggestPins: [], onSelect: () => {} }))
}

test('BoardView WT32-ETH01: PROG and IO on both sides, LINK as signal, RJ45 LAN, no buttons, WT32-S1, variant unknown', async () => {
  globalThis.__cbSdk = fakeSdk()
  const { __t: t } = await loadBundle()
  const tree = boardTree(t, 'wt32-eth01')
  const [board] = byCb(tree, 'board')
  assert.equal(board.props['data-cb-board'], 'wt32-eth01')
  for (const side of ['left', 'right']) {
    const [col] = byCb(tree, `header-${side}`)
    assert.deepEqual(byCb([col], 'header-sep').map(textOf), ['IO'], side)
    const pins = []
    walk([col], n => { if (n.props.className === 'cb-pin') pins.push(n) })
    assert.equal(pins.length, 13)
  }
  const link = byCb(tree, 'pin-IO-10')[0]
  assert.deepEqual([link.type, link.props['data-cb-state']], ['div', 'signal'])
  assert.match(textOf(link), /~ signal.*LINK/)
  assert.equal(byCb(tree, 'pin-0')[0].type, 'button', 'IO0 (PROG-6) is a GPIO')
  assert.equal(textOf(byCb(tree, 'board-module-name')[0]), 'WT32-S1')
  assert.deepEqual(byCb(tree, 'board-buttons')[0].children, [])
  assert.equal(byCb(tree, 'board-antenna').length, 0, 'antenna: null draws no antenna')
  const ports = byCb(tree, 'board-ports')[0].children
  assert.deepEqual(ports.map(p => p.props['data-cb-port']), ['rj45'])
  assert.match(textOf(ports[0]), /LAN/)
  assert.equal(byCb(tree, 'board-variant-unknown').length, 1)
  // a chosen variant removes the unknown note; WROVER-E shows its PSRAM reservation, the module stays WT32-S1
  const wrover = boardTree(t, 'wt32-eth01', 'wrover-e')
  assert.equal(byCb(wrover, 'board-variant-unknown').length, 0)
  assert.equal(byCb(wrover, 'board-reserve').length, 1)
  assert.equal(textOf(byCb(wrover, 'board-module-name')[0]), 'WT32-S1')
})

test('BoardView S2 / C6: nc pin with word, OTG port drawn, C6 module per variant, no unknown note for S2', async () => {
  globalThis.__cbSdk = fakeSdk()
  const { __t: t } = await loadBundle()
  const c6 = boardTree(t, 'esp32-c6-devkitc-1', 'wroom-1')
  const nc = byCb(c6, 'pin-J1-16')[0]
  assert.deepEqual([nc.type, nc.props['data-cb-state']], ['div', 'nc'])
  assert.match(textOf(nc), /∅ unwired.*not connected/)
  assert.equal(textOf(byCb(c6, 'board-module-name')[0]), 'C6-WROOM-1')
  assert.equal(byCb(c6, 'board-variant-unknown').length, 0)
  assert.equal(byCb(c6, 'header-sep').length, 0)
  assert.equal(textOf(byCb(boardTree(t, 'esp32-c6-devkitm-1', 'mini-1'), 'board-module-name')[0]), 'C6-MINI-1')
  const s2 = boardTree(t, 'esp32-s2-devkitc-1')
  assert.deepEqual(byCb(s2, 'board-ports')[0].children.map(p => p.props['data-cb-port']), ['usb_otg', 'usb_uart_bridge'])
  assert.equal(byCb(s2, 'board-variant-unknown').length, 0, 'the S2 has no module variants')
  assert.deepEqual(byCb(s2, 'board-buttons')[0].children.map(textOf), ['[RST]', '[BOOT]'])
})

test('board warnings: PLAN strip above the board and an inspector card, danger first, symbol + word + text', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  const ctx = fakeCtx()
  mod.default.register(ctx)
  t.$project.set({ id: 'w', rev: 1, title: 'w', board: { chip: 'esp32', module: null, variant: null, devkit: 'wt32-eth01', detected: null },
    options: { wifi: true }, assignments: [] })
  t.$view.set({ ...t.$view.get(), chip: 'esp32', variant: null, devkit: 'wt32-eth01', wifi: true, selected: null })
  await t.loadBoard('wt32-eth01')
  await tick()
  assert.equal(t.$board.get().id, 'wt32-eth01')
  const tree = render(t.StationPlan({ project: t.$project.get(), rows: [] }))
  const strip = byCb(tree, 'board-warnings')
  assert.equal(strip.length, 1)
  const card = byCb(tree, 'insp-board-warnings')
  assert.equal(card.length, 1)
  for (const scope of [strip[0], card[0]]) {
    const items = byCb([scope], 'board-warning')
    assert.deepEqual(items.map(i => i.props['data-cb-severity']), ['danger', 'caution'])
    assert.match(textOf(items[0]), /⚠ DANGER\s*Feed either 3V3 or 5V, never both\./)
    assert.match(textOf(items[1]), /! CAUTION\s*Use a supply that delivers at least 500 mA\./)
    assert.match(items[0].props.className, /cb-bwarn--bad/)
  }
  assert.match(textOf(card[0]), /board · WT32-ETH01 V1\.4/)
  // the inspector aside: board warnings first, then the inspector
  const [aside] = byCb(tree, 'insp')
  assert.equal(aside.children[0].props['data-cb'], 'insp-board-warnings')
  // legend names signal (LINK); no warning strip on a board without warnings
  assert.equal(byCb(tree, 'legend-signal').length, 1)
  assert.equal(byCb(tree, 'legend-nc').length, 0)
  t.setWhatIf({ chip: 'esp32', devkit: 'esp32-devkitc-v4' })
  await tick()
  const v4 = render(t.StationPlan({ project: t.$project.get(), rows: [] }))
  assert.equal(byCb(v4, 'board-warnings').length, 0)
  assert.equal(byCb(v4, 'insp-board-warnings').length, 0)
})

test('PLAN toolbar: S3 dropdown 9 variants in 3 PSRAM groups; DevKit WT32 / V4 / C6 boards preselect module.variant', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  const ctx = fakeCtx()
  mod.default.register(ctx)
  t.$project.set({ id: 's', rev: 1, title: 's', board: { chip: 'esp32s3', module: null, variant: 'n16r8', devkit: 'esp32-s3-devkitc-1', detected: null },
    options: { wifi: true }, assignments: [] })
  t.$view.set({ ...t.$view.get(), chip: 'esp32s3', variant: 'n16r8', devkit: null, wifi: true, selected: null })
  const toolbar = () => render(t.PlanToolbar({ rows: [], view: t.$view.get(), suggesting: false }))
  let tree = toolbar()
  const [sel] = byCb(tree, 'seg-variant')
  assert.equal(sel.type, 'select')
  assert.equal(sel.props.value, 'n16r8')
  assert.match(sel.props.title, /N16R8: 16 MB flash, 8 MB PSRAM \(octal\)/)
  const groups = byType([sel], 'optgroup')
  assert.deepEqual(groups.map(g => [g.props.label, g.children.map(o => o.props.value)]), [
    ['no PSRAM', ['n4', 'n8', 'n16']], ['quad PSRAM', ['n4r2', 'n8r2', 'n16r2']], ['octal PSRAM', ['n4r8', 'n8r8', 'n16r8']]])
  assert.equal(byType([sel], 'option').length, 9)
  assert.deepEqual(byType([sel], 'option').map(o => [textOf(o), o.props.title]).slice(3, 4), [['N4R2', '4 MB flash, 2 MB PSRAM (quad)']])
  sel.props.onChange({ target: { value: 'n8r2' } })
  await tick()
  assert.equal(t.$view.get().variant, 'n8r2')
  // chip row offers the five chips; DevKit row the seven layouts
  assert.deepEqual(byCb(toolbar(), 'seg-chip')[0].children.map(b => b.props['data-cb-opt']), CHIPS.map(c => c.id))
  // DevKit dropdown grouped by chip (optgroup per chip, data order)
  const kitSel = () => byCb(toolbar(), 'seg-devkit')[0]
  assert.equal(kitSel().type, 'select')
  assert.deepEqual(kitSel().children.map(g => [g.props.label, g.children.map(o => o.props.value)]), [
    ['ESP32', ['esp32-devkitc-v4', 'wt32-eth01']], ['ESP32-S2', ['esp32-s2-devkitc-1']], ['ESP32-S3', ['esp32-s3-devkitc-1']],
    ['ESP32-C3', ['esp32-c3-devkitm-1']], ['ESP32-C6', ['esp32-c6-devkitc-1', 'esp32-c6-devkitm-1']]])
  const devkit = id => kitSel().props.onChange({ target: { value: id } })
  const pressed = () => [kitSel().props.value]
  // WT32-ETH01: chip ESP32, module variant unknown (nothing pressed), its layout loads, checks run with devkit wt32-eth01
  devkit('wt32-eth01')
  await tick()
  assert.deepEqual([t.$view.get().chip, t.$view.get().devkit, t.$view.get().variant], ['esp32', 'wt32-eth01', null])
  assert.deepEqual([t.$board.get().id, t.$board.get().layout?.left.length], ['wt32-eth01', 13])
  assert.deepEqual(pressed(), ['wt32-eth01'])
  tree = toolbar()
  assert.deepEqual(byCb(tree, 'seg-variant')[0].children.map(b => b.props['aria-pressed']), ['false', 'false'])
  assert.equal(t.viewBoard().devkit, 'wt32-eth01')
  // DevKitC V4: WROOM-32E (its module.variant); back to the WT32: empty again (module variant unknown)
  devkit('esp32-devkitc-v4')
  await tick()
  assert.deepEqual([t.$view.get().chip, t.$view.get().devkit, t.$view.get().variant, t.$board.get().id], ['esp32', 'esp32-devkitc-v4', 'wroom-32e', 'esp32-devkitc-v4'])
  devkit('wt32-eth01')
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant], ['wt32-eth01', null])
  // a variant the user chose on the WT32 stays on the WT32 and on the DevKitC V4 (no preset over a user choice)
  byCb(toolbar(), 'seg-variant')[0].children.find(b => b.props['data-cb-opt'] === 'wrover-e').props.onClick()
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant], ['wt32-eth01', 'wrover-e'])
  devkit('esp32-devkitc-v4')
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant], ['esp32-devkitc-v4', 'wrover-e'])
  // chip ESP32-C6: default DevKit C6-DevKitC-1 with WROOM-1; C6-DevKitM-1 with MINI-1 (presets, nothing chosen)
  byCb(toolbar(), 'seg-chip')[0].children.find(b => b.props['data-cb-opt'] === 'esp32c6').props.onClick()
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant, t.$board.get().id], ['esp32-c6-devkitc-1', 'wroom-1', 'esp32-c6-devkitc-1'])
  assert.equal(byCb(toolbar(), 'seg-variant')[0].type, 'div', 'two variants: segmented control')
  devkit('esp32-c6-devkitm-1')
  await tick()
  assert.deepEqual([t.$view.get().chip, t.$view.get().variant, t.$board.get().layout?.left.length], ['esp32c6', 'mini-1', 15])
  devkit('esp32-c6-devkitc-1')
  await tick()
  assert.equal(t.$view.get().variant, 'wroom-1')
  // user picks MINI-1 on the C6-DevKitC-1: switching boards keeps it
  byCb(toolbar(), 'seg-variant')[0].children.find(b => b.props['data-cb-opt'] === 'mini-1').props.onClick()
  await tick()
  devkit('esp32-c6-devkitm-1')
  await tick()
  devkit('esp32-c6-devkitc-1')
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant], ['esp32-c6-devkitc-1', 'mini-1'])
  devkit('esp32-c6-devkitm-1')
  await tick()
  // ESP32-S2: no module group, its DevKit
  byCb(toolbar(), 'seg-chip')[0].children.find(b => b.props['data-cb-opt'] === 'esp32s2').props.onClick()
  await tick()
  assert.deepEqual([t.viewBoard().devkit, t.viewBoard().variant, t.$board.get().layout?.left.length], ['esp32-s2-devkitc-1', null, 22])
  assert.equal(byCb(toolbar(), 'group-module').length, 0)
  // the map check carries the chosen DevKit
  const lastMap = ctx.bodies.filter(b => b.path === '/pins/check').at(-1).body
  assert.deepEqual([lastMap.chip, lastMap.devkit, lastMap.variant], ['esp32s2', 'esp32-s2-devkitc-1', null])
  assert.ok(ctx.bodies.some(b => b.path === '/pins/check' && b.body.devkit === 'wt32-eth01' && b.body.chip === 'esp32'))
  assert.deepEqual(ctx.calls.filter(c => /^(POST \/serial|POST \/board\/)/.test(c)), [])
})

test('PLAN what-if: a project on the WT32 is not "what-if" in its own view; another DevKit of the same chip is', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  mod.default.register(fakeCtx())
  t.$project.set({ id: 'w', rev: 1, title: 'w', board: { chip: 'esp32', module: null, variant: null, devkit: 'wt32-eth01', detected: null }, options: { wifi: true }, assignments: [] })
  t.$view.set({ ...t.$view.get(), chip: 'esp32', variant: null, devkit: 'wt32-eth01', wifi: true })
  assert.equal(t.isWhatIf(), false)
  const toolbar = () => render(t.PlanToolbar({ rows: [], view: t.$view.get(), suggesting: false }))
  assert.equal(byCb(toolbar(), 'whatif').length, 0)
  t.setWhatIf({ devkit: 'esp32-devkitc-v4' })
  await tick()
  assert.equal(t.isWhatIf(), true)
  // the what-if line sits in the toolbar (compact); the project board is its title and screen-reader text
  const [w] = byCb(toolbar(), 'whatif')
  assert.match(textOf(w), /◇ WHAT-IF/)
  assert.equal(textOf(byCb([w], 'whatif-project')[0]), 'Project board: WT32-ETH01 V1.4, ESP32, Wi-Fi on.')
  assert.equal(byCb([w], 'whatif-apply').length, 1)
  assert.equal(byCb([w], 'whatif-reset').length, 1)
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant], ['esp32-devkitc-v4', 'wroom-32e'])
  // Reset: back to the project board, the module stays unknown
  byCb(toolbar(), 'whatif-reset')[0].props.onClick()
  await tick()
  assert.deepEqual([t.$view.get().devkit, t.$view.get().variant, t.isWhatIf()], ['wt32-eth01', null, false])
})

test('new-project dialog: chip → its boards, board → module.variant, WT32 = unknown, S3 module list grouped by PSRAM', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  const ctx = fakeCtx()
  mod.default.register(ctx)
  HOOKS.slots = []
  const draw = () => { HOOKS.i = 0; return render(t.NewProjectDialog({ onClose: () => {} })) }
  let tree = draw()
  const sel = (tr, cb) => byCb(tr, cb)[0]
  assert.equal(sel(tree, 'new-project-chip').props.value, 'esp32s3')
  assert.deepEqual(byType([sel(tree, 'new-project-devkit')], 'option').map(o => o.props.value), ['esp32-s3-devkitc-1'])
  assert.equal(sel(tree, 'new-project-variant').props.value, 'n16r8')
  assert.deepEqual(byType([sel(tree, 'new-project-variant')], 'optgroup').map(g => [g.props.label, g.children.length]), [['no PSRAM', 3], ['quad PSRAM', 3], ['octal PSRAM', 3]])
  sel(tree, 'new-project-chip').props.onChange({ target: { value: 'esp32' } })
  tree = draw()
  assert.deepEqual(byType([sel(tree, 'new-project-devkit')], 'option').map(o => o.props.value), ['esp32-devkitc-v4', 'wt32-eth01'])
  assert.deepEqual([sel(tree, 'new-project-devkit').props.value, sel(tree, 'new-project-variant').props.value], ['esp32-devkitc-v4', 'wroom-32e'])
  sel(tree, 'new-project-devkit').props.onChange({ target: { value: 'wt32-eth01' } })
  tree = draw()
  assert.equal(sel(tree, 'new-project-variant').props.value, '')
  assert.match(textOf(byType([sel(tree, 'new-project-variant')], 'option')[0]), /^WT32-S1 · variant not stated/)
  assert.match(textOf(tree[0]), /Board view: WT32-ETH01 V1\.4\./)
  sel(tree, 'new-project-id').props.onChange({ target: { value: 'eth-node' } })
  tree = draw()
  await sel(tree, 'new-project-submit').props.onClick()
  const body = ctx.bodies.find(b => b.path === '/projects')?.body
  assert.deepEqual(body, { id: 'eth-node', title: 'eth-node', chip: 'esp32', variant: null, devkit: 'wt32-eth01' })
  // ESP32-S2: its DevKit, no module select
  sel(tree, 'new-project-chip').props.onChange({ target: { value: 'esp32s2' } })
  tree = draw()
  assert.equal(byCb(tree, 'new-project-variant').length, 0)
  assert.equal(sel(tree, 'new-project-devkit').props.value, 'esp32-s2-devkitc-1')
  sel(tree, 'new-project-chip').props.onChange({ target: { value: 'esp32c6' } })
  tree = draw()
  assert.deepEqual([sel(tree, 'new-project-devkit').props.value, sel(tree, 'new-project-variant').props.value], ['esp32-c6-devkitc-1', 'wroom-1'])
  sel(tree, 'new-project-devkit').props.onChange({ target: { value: 'esp32-c6-devkitm-1' } })
  tree = draw()
  assert.equal(sel(tree, 'new-project-variant').props.value, 'mini-1')
  // a module the user chose is not overwritten by the next board's preset
  sel(tree, 'new-project-variant').props.onChange({ target: { value: 'wroom-1' } })
  tree = draw()
  sel(tree, 'new-project-devkit').props.onChange({ target: { value: 'esp32-c6-devkitc-1' } })
  tree = draw()
  sel(tree, 'new-project-devkit').props.onChange({ target: { value: 'esp32-c6-devkitm-1' } })
  tree = draw()
  assert.equal(sel(tree, 'new-project-variant').props.value, 'wroom-1')
  // a new chip starts again from its board's preset; WT32 after the V4 preset: empty
  sel(tree, 'new-project-chip').props.onChange({ target: { value: 'esp32' } })
  tree = draw()
  assert.equal(sel(tree, 'new-project-variant').props.value, 'wroom-32e')
  sel(tree, 'new-project-devkit').props.onChange({ target: { value: 'wt32-eth01' } })
  tree = draw()
  assert.equal(sel(tree, 'new-project-variant').props.value, '')
})
