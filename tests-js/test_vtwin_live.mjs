// The live twin only shows store events (fixture sequences): lit port from the port kind, pulse only while
// the flash job runs, panic stamp, TX only while serial lines arrive; reduced motion leaves only static states.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { jobProgress } from '../desktop-src/lib/flash.js'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
// lib files share one scope in the bundle: concatenate the four the twin layer needs into one test module
const libSrc = ['art.js', 'board-geom.js', 'pins.js', 'art-board.js'].map(f => readFileSync(join(SRC, 'lib', f), 'utf8')).join('\n')
const { twinPortRef, twinFlashState, twinSerialTrack, artBoardTwin, TWIN_RX_WINDOW_MS, boardGeom, boardArtModel, chipInfo, variantInfo } =
  await import(`data:text/javascript;base64,${Buffer.from(libSrc).toString('base64')}`)
const FXDIR = join(SRC, 'fixtures')
const FX = Object.fromEntries(readdirSync(FXDIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FXDIR, f), 'utf8'))]))
const LAYOUTS = Object.fromEntries(Object.entries(FX).filter(([k]) => k.startsWith('board.')).map(([, v]) => [v.result.id, v.result]))
// the bundle's own port-kind table (lib/flash.js FLASH_PORT_USB is module-private; read it, never copy it)
const KIND_MAP = Function(`return ${/const FLASH_PORT_USB = (\{[\s\S]*?\})\n/.exec(readFileSync(join(SRC, 'lib', 'flash.js'), 'utf8'))[1]}`)()
const PORTS = FX.ports.result.ports
const JTAG = PORTS.find(p => p.kind === 'usb_serial_jtag')
const SIM = PORTS.find(p => p.simulated)
const s3 = LAYOUTS['esp32-s3-devkitc-1']
const modelOf = layout => boardArtModel({ layout, chip: chipInfo(layout.chip), variant: variantInfo(layout.chip, layout.module?.variant ?? null) })

test('lit port: only a real port whose kind leads to exactly one drawn usb port', () => {
  assert.equal(twinPortRef(JTAG, modelOf(s3), KIND_MAP), 'USB')
  assert.equal(twinPortRef({ ...JTAG, kind: 'cp210x' }, modelOf(s3), KIND_MAP), 'UART')
  assert.equal(twinPortRef(SIM, modelOf(s3), KIND_MAP), null)
  assert.equal(twinPortRef({ ...JTAG, kind: 'unknown' }, modelOf(s3), KIND_MAP), null)
  assert.equal(twinPortRef({ ...JTAG, kind: 'constructor' }, modelOf(s3), KIND_MAP), null)
  assert.equal(twinPortRef(null, modelOf(s3), KIND_MAP), null)
  // C3-DevKitM-1: only a UART bridge; a JTAG port has nowhere to arrive
  assert.equal(twinPortRef(JTAG, modelOf(LAYOUTS['esp32-c3-devkitm-1']), KIND_MAP), null)
  assert.equal(twinPortRef({ ...JTAG, kind: 'ch340' }, modelOf(LAYOUTS['esp32-c3-devkitm-1']), KIND_MAP), 'UART')
  // WT32-ETH01: no usb at all
  assert.equal(twinPortRef({ ...JTAG, kind: 'ch340' }, modelOf(LAYOUTS['wt32-eth01']), KIND_MAP), null)
})

test('flash job sequence (fixtures): running → pulse dots on the trace port → module; done → solid trace, no dots', () => {
  const g = boardGeom({ layout: s3, mode: 'compact' })
  const model = modelOf(s3)
  const seq = [null, FX['job.build.running'].result && { ...FX['job.build.running'].result, kind: 'flash' }, FX['job.flash.done'].result]
  const states = seq.map(j => twinFlashState(jobProgress(j)))
  assert.deepEqual(states, [null, 'running', 'done'])
  assert.equal(twinFlashState(jobProgress({ state: 'failed' })), 'failed')
  const idle = artBoardTwin(model, g, { prefix: 'f1', port: 'USB', flash: null })
  const run = artBoardTwin(model, g, { prefix: 'f1', port: 'USB', flash: 'running' })
  const done = artBoardTwin(model, g, { prefix: 'f1', port: 'USB', flash: 'done' })
  const failed = artBoardTwin(model, g, { prefix: 'f1', port: 'USB', flash: 'failed' })
  assert.doesNotMatch(idle.svg, /cb-twin-trace|cb-twin-dot/)
  assert.equal((run.svg.match(/class="cb-twin-dot /g) || []).length, 4)
  assert.match(run.svg, /class="cb-twin-trace"/)
  assert.doesNotMatch(done.svg, /cb-twin-dot/)
  assert.match(done.svg, /class="cb-twin-trace"[^>]*stroke="var\(--cb-ok\)"/)
  assert.doesNotMatch(failed.svg, /cb-twin-trace|cb-twin-dot/)
  // the lit port is drawn live; without a port no trace and nothing lit, even while the job runs
  assert.equal((idle.svg.match(/class="cb-art-live"/g) || []).length, 1)
  const sim = artBoardTwin(model, g, { prefix: 'f2', port: null, flash: 'running' })
  assert.doesNotMatch(sim.svg, /cb-twin-trace|cb-twin-dot|cb-art-live/)
  assert.equal(sim.port, null)
  // the trace runs from the port body to the module edge (board coordinates inside the turned group)
  const d = /class="cb-twin-trace" d="([^"]+)"/.exec(run.svg)[1]
  const pts = [...d.matchAll(/[ML]([\d.]+) ([\d.]+)/g)].map(m => [Number(m[1]), Number(m[2])])
  assert.equal(pts.length, 4)
  assert.ok(pts[0][1] > pts[3][1], 'from the bottom edge up to the module')
})

test('turned view: antenna right, module centre in view percent for the DOM stamp; ids carry the prefix', () => {
  const g = boardGeom({ layout: s3, mode: 'compact' })
  const t = artBoardTwin(modelOf(s3), g, { prefix: 'debug-7' })
  assert.deepEqual(t.view, [g.height, g.bodyW])
  assert.match(t.svg, /^<svg[^>]*viewBox="0 0 [\d.]+ [\d.]+"[^>]*data-cb-turn="true"/)
  assert.ok(t.module.x > 50 && t.module.x < 100, `module right of centre: ${t.module.x}`)
  assert.ok(t.module.y > 20 && t.module.y < 80)
  const ids = [...t.svg.matchAll(/ id="([^"]+)"/g)].map(m => m[1])
  assert.ok(ids.length && ids.every(id => id.startsWith('cb-debug-7-')))
  const flat = artBoardTwin(modelOf(s3), g, { prefix: 'p', turn: false })
  assert.deepEqual(flat.view, [g.bodyW, g.height])
})

test('serial activity: only lines that arrive after the first look light TX, for a window from their arrival', () => {
  const lines = FX['serial.lines'].result.lines
  const buf = n => ({ lastSeq: lines[n - 1].seq, epoch: 'e1' })
  let st = twinSerialTrack(null, buf(40), 1000)
  assert.equal(st.active, false, 'the backlog already in the buffer never lights')
  st = twinSerialTrack(st, buf(40), 1200)
  assert.equal(st.active, false)
  st = twinSerialTrack(st, buf(41), 1300)
  assert.equal(st.active, true)
  assert.equal(st.until, 1300 + TWIN_RX_WINDOW_MS)
  st = twinSerialTrack(st, buf(41), 1300 + TWIN_RX_WINDOW_MS - 1)
  assert.equal(st.active, true)
  st = twinSerialTrack(st, buf(41), 1300 + TWIN_RX_WINDOW_MS + 1)
  assert.equal(st.active, false, 'no new line: dark again')
  // a new epoch (backend restart) with lines counts as arrival; a closed monitor (null buffer) never lights
  st = twinSerialTrack(st, { lastSeq: 3, epoch: 'e2' }, 5000)
  assert.equal(st.active, true)
  assert.equal(twinSerialTrack(twinSerialTrack(null, null, 0), null, 10).active, false)
})

test('motion budget: the pulse is opacity only, ≤ 600 ms, only under no-preference; reduced motion keeps static dots', () => {
  const css = readFileSync(join(SRC, '14-styles-board.js'), 'utf8')
  const kf = /@keyframes cb-twin-pulse\{([^\n]+)\}\n/.exec(css)[1]
  assert.doesNotMatch(kf, /(?<![a-z-])(top|left|width|height|stroke|fill|background)\s*:/)
  assert.match(kf, /opacity/)
  const anim = /\.cb-twin-dot\{opacity:0;animation:cb-twin-pulse ([\d.]+)s linear infinite\}/.exec(css)
  assert.ok(anim && Number(anim[1]) <= 0.6)
  const block = css.slice(css.indexOf('@media (prefers-reduced-motion:no-preference){\n  .cb-root .cb-twin-dot'))
  assert.ok(block.indexOf('animation:cb-twin-pulse') < block.indexOf('\n}'), 'the animation lives only inside no-preference')
  assert.match(css, /\.cb-root \.cb-twin-dot\{opacity:\.85\}/, 'static dots outside the media query')
})

// ── the twins as the stations mount them (bundle, fake SDK atoms): store events in, marks out ─────────────────────
function fakeSdk() {
  const atom = v => { let cur = v; const subs = new Set(); return { get: () => cur, set: n => { cur = n; for (const s of subs) s(n) }, subscribe: fn => { subs.add(fn); return () => subs.delete(fn) } } }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', THEMES_AREA: 'themes',
    TRANSCRIPT_DIRECTIVE_AREA: 'directives', STATUSBAR_AREAS: { right: 'statusBar.right' }, PANES_AREA: 'panes', host: {} }
}
async function loadBundle() {
  globalThis.__cbSdk = fakeSdk()
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = v => [typeof v === "function" ? v() : v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { FlashTwin, DebugTwin, DIRECTIVE_BOARDS, $project, $ports, $jobs, $flow, $monitor, $serial }\n'
  const { __t: t } = await import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
  t.DIRECTIVE_BOARDS.set(s3.id, s3)
  return t
}
function render(node) {
  if (node === null || node === undefined || node === false || node === true) return []
  if (Array.isArray(node)) return node.flatMap(render)
  if (typeof node !== 'object') return [String(node)]
  if (typeof node.type === 'function') return render(node.type(node.props))
  if (node.type === '#fragment') return render(node.props.children)
  const { children, ...props } = node.props || {}
  return [{ type: node.type, props, children: render(children) }]
}
function walk(tree, fn) { for (const n of tree) { if (typeof n === 'string') continue; fn(n); walk(n.children, fn) } }
const byCb = (tree, cb) => { const out = []; walk(tree, n => { if (n.props['data-cb'] === cb) out.push(n) }); return out }
const textOf = n => (typeof n === 'string' ? n : n.children.map(textOf).join(''))

test('FlashTwin: port from the flow, flash state from the job atom, stamp after the job; sim lights nothing', async () => {
  const t = await loadBundle()
  const project = structuredClone(FX['project.laser-trigger'].result.project)
  t.$project.set(project)
  t.$ports.set({ status: 'ready', ports: PORTS })
  t.$flow.set({ ...t.$flow.get(), port: JTAG.device })
  let tree = render(t.FlashTwin({ project }))
  let [m] = byCb(tree, 'flash-twin-model')
  assert.equal(m.props['data-cb-port-lit'], 'USB')
  assert.equal(m.props['data-cb-flash'], undefined)
  assert.equal(byCb(tree, 'flash-twin-model-stamp').length, 0)
  assert.match(textOf(byCb(tree, 'flash-twin-port')[0]), /\/dev\/ttyACM0on the USB port/)
  // the job flashes the detected board (sim in the demo project): no lit port, no trace, the stamp says it
  t.$jobs.set({ detect: null, build: null, flash: { state: 'running', progress: 0.3 } })
  tree = render(t.FlashTwin({ project }));
  [m] = byCb(tree, 'flash-twin-model')
  assert.equal(m.props['data-cb-flash'], 'running')
  assert.equal(m.props['data-cb-port-lit'], undefined)
  assert.match(textOf(byCb(tree, 'flash-twin-model-stamp')[0]), /FLASHING/)
  // a real detected port: the pulse runs on its trace
  project.board.detected = { ...project.board.detected, port: JTAG.device, simulated: false }
  tree = render(t.FlashTwin({ project }));
  [m] = byCb(tree, 'flash-twin-model')
  assert.equal(m.props['data-cb-port-lit'], 'USB')
  let svg = null
  walk([m], n => { if (n.props.dangerouslySetInnerHTML) svg = n.props.dangerouslySetInnerHTML.__html })
  assert.equal((svg.match(/class="cb-twin-dot /g) || []).length, 4)
  t.$jobs.set({ detect: null, build: null, flash: FX['job.flash.done'].result })
  tree = render(t.FlashTwin({ project }))
  assert.match(textOf(byCb(tree, 'flash-twin-model-stamp')[0]), /✓ FLASHED/)
  walk(byCb(tree, 'flash-twin-model'), n => { if (n.props.dangerouslySetInnerHTML) svg = n.props.dangerouslySetInnerHTML.__html })
  assert.doesNotMatch(svg, /cb-twin-dot/)
})

test('DebugTwin: panic stamp while the stored panic is current; TX dark while the monitor is closed', async () => {
  const t = await loadBundle()
  const project = structuredClone(FX['project.laser-trigger'].result.project)
  t.$project.set(project)
  t.$ports.set({ status: 'ready', ports: PORTS })
  let tree = render(t.DebugTwin({ project }))
  const [root] = byCb(tree, 'debug-twin')
  assert.equal(root.props['data-cb-panic'], 'true')
  assert.equal(textOf(byCb(tree, 'debug-twin-model-stamp')[0]), 'PANIC')
  assert.equal(byCb(tree, 'twin-tx')[0].props['data-cb-on'], 'false')
  assert.equal(byCb(tree, 'twin-rx')[0].props['data-cb-on'], 'false')
  // flashed after the panic: the panic is no longer current, the stamp goes
  project.firmware.last_flash.at = '2026-11-09T20:20:00Z'
  tree = render(t.DebugTwin({ project }))
  assert.equal(byCb(tree, 'debug-twin-model-stamp').length, 0)
  assert.equal(byCb(tree, 'debug-twin')[0].props['data-cb-panic'], 'false')
})
