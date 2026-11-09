// The Bench's notice zone and the locked Flash button.
// Pure parts (flashGate, the fixture route of the flash gate) and the product bundle with a recording jsx and fake hooks (no DOM):
// notices (tone, role, at most three, ok fades / errors stay, station change), the gate under the Flash button
// (refusal message + hint from the backend, nothing computed), detection warnings as warning lines.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { flashGate } from '../desktop-src/lib/flash.js'
import { createFixtureBackend } from '../desktop-src/lib/fixtures.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const FIX = join(ROOT, 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(FIX).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FIX, f), 'utf8'))]))
const clone = x => JSON.parse(JSON.stringify(x))

test('flashGate only reads the answer: ready, locked with message and hint, unknown otherwise', () => {
  assert.deepEqual(flashGate(FX['flash.check.ok']), { state: 'ready', code: null, message: null, hint: null })
  const off = flashGate(FX['flash.check.flash_disabled'])
  assert.equal(off.state, 'locked')
  assert.equal(off.code, 'flash_disabled')
  assert.equal(off.message, FX['flash.check.flash_disabled'].result.refusal.message)
  assert.equal(off.hint, FX['flash.check.flash_disabled'].result.refusal.hint)
  assert.equal(flashGate(FX['flash.check.chip_mismatch']).code, 'chip_mismatch')
  for (const env of [null, undefined, {}, { ok: false, error: { code: 'network_error' }, result: null }, { ok: true, result: {} }]) {
    assert.equal(flashGate(env).state, 'unknown')
  }
})

test('the three flash.check fixtures are board.flash_check envelopes of the fixture project', () => {
  for (const n of ['ok', 'flash_disabled', 'chip_mismatch']) {
    const env = FX[`flash.check.${n}`]
    assert.equal(env.ok, true, n)
    assert.equal(env.action, 'board.flash_check', n)
    assert.equal(typeof env.result.ready, 'boolean', n)
  }
  assert.match(FX['flash.check.chip_mismatch'].result.refusal.message, /project laser-trigger is set to esp32s2/)
})

test('fixture route C5: sim board ready, a real port refused (allow_flash off), chip changed in PLAN → chip_mismatch', async () => {
  const b = createFixtureBackend(clone(FX), { delayMs: 0 })
  const get = q => b.handle('GET', `/board/flash/check?${q}`)
  assert.equal((await get('project=laser-trigger')).result.ready, true)
  assert.equal((await get('project=laser-trigger&port=sim%3A%2F%2Fesp32s3-n16r8')).result.ready, true)
  assert.equal((await get('project=laser-trigger&port=%2Fdev%2FttyACM0')).result.refusal.code, 'flash_disabled')
  assert.equal((await get('project=nope')).error.code, 'project_not_found')
  const p = b.projects.get('laser-trigger')
  const env = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: p.rev, ops: [{ op: 'set_board', chip: 'esp32s2', variant: null, devkit: 'esp32-s2-devkitc-1', wifi: true }] })
  assert.equal(env.ok, true)
  assert.equal((await get('project=laser-trigger')).result.refusal.code, 'chip_mismatch')
  // another chip has no recorded answer: an honest fixture error, never a made-up refusal
  const p2 = b.projects.get('laser-trigger')
  await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: p2.rev, ops: [{ op: 'set_board', chip: 'esp32c6', variant: 'wroom-1', devkit: 'esp32-c6-devkitc-1', wifi: true }] })
  assert.equal((await get('project=laser-trigger')).error.code, 'fixture_missing')
})

test('fixture backend stores calculations, parts and circuits (CALC/WIRE "Add to project"); a pasted BOM has no fixture', async () => {
  const b = createFixtureBackend(clone(FX), { delayMs: 0 })
  const rev = b.projects.get('laser-trigger').rev
  const env = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: rev, ops: [
    { op: 'add_calc', calc: { id: 'led-1', type: 'led', inputs: {}, result: {}, assumptions: [], sources: [] } },
    { op: 'add_parts', parts: [{ ref: 'R9', kind: 'resistor', value: '82 Ω', from_calc: 'led-1' }] },
    { op: 'add_circuit', circuit: { id: 'led', block: 'led_resistor', params: {} } }] })
  assert.equal(env.ok, true, env.error?.message)
  assert.deepEqual(env.result.changed, ['calcs', 'parts', 'circuits'])
  const p = b.projects.get('laser-trigger')
  assert.ok(p.calcs.some(c => c.id === 'led-1') && p.parts.some(x => x.ref === 'R9') && p.circuits.some(c => c.id === 'led'))
  const dup = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: p.rev, ops: [{ op: 'add_circuit', circuit: { id: 'led', block: 'x', params: {} } }] })
  assert.equal(dup.error.code, 'invalid_args')
  assert.equal((await b.handle('POST', '/solder/plan', { project: 'laser-trigger' })).ok, true)
  assert.equal((await b.handle('POST', '/solder/plan', { project: 'laser-trigger', bom: 'ref,value\nR1,1k' })).error.code, 'fixture_missing')
})

// ─── product bundle (recording jsx, fake hooks) ────────────────────────────────────────────

const HOOKS = { queue: [], effects: [] }
globalThis.__cbHuiHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbHuiSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [globalThis.__cbHuiHooks.queue.length ? globalThis.__cbHuiHooks.queue.shift() : (typeof i === "function" ? i() : i), () => {}], ' +
      'useEffect = f => { globalThis.__cbHuiHooks.effects.push(f) }, useMemo = f => f(), useRef = v => ({ current: v === undefined ? null : v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { NoticeZone, setNotice, dropNotices, goStation, patchOps, FlashCard, DetectResult, refreshFlashCheck, applyVariant, CB, $notices, $project, $flashCheck, $flow, $detect, $nav, $ui }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

function fakeSdk() {
  const atom = v => {
    let cur = v
    return { get: () => cur, set: n => { cur = n }, subscribe: () => () => {} }
  }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette',
    host: { navigate: () => {}, openWorkspace: () => {}, notify: () => {} } }
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

let mod
async function T() {
  if (!mod) { globalThis.__cbHuiSdk = fakeSdk(); mod = await loadBundle() }
  return mod.__t
}

test('notices: symbol + word per tone, status for ok, alert for errors, at most three, same text once', async () => {
  const t = await T()
  t.$notices.set([])
  t.setNotice('led-1 saved.', 'ok')
  t.setNotice('The change was not saved.', 'bad')
  t.setNotice('reloaded the project, try again', 'warn')
  let tree = expand(t.NoticeZone({ list: t.$notices.get() }))
  const items = find(tree, p => typeof p['data-cb-notice'] === 'number')
  assert.deepEqual(items.map(n => [n.props.role, n.props['data-cb']]), [['status', 'notice-ok'], ['alert', 'notice-bad'], ['alert', 'notice-warn']])
  assert.match(text(items[0]), /^✓ok/)
  assert.match(text(items[1]), /^✕error/)
  assert.match(text(items[2]), /^!warning/)
  // a fourth notice pushes out the fading one first, errors stay
  t.setNotice('Circuit led saved to the project.', 'ok')
  t.setNotice('Board saved to the project.', 'ok')
  assert.deepEqual(t.$notices.get().map(n => n.tone), ['bad', 'warn', 'ok'])
  t.setNotice('Board saved to the project.', 'ok')
  assert.equal(t.$notices.get().length, 3)
  // ✕ removes exactly that notice
  tree = expand(t.NoticeZone({ list: t.$notices.get() }))
  const x = byCb(tree, 'notice-dismiss')[0]
  x.props.onClick()
  assert.deepEqual(t.$notices.get().map(n => n.tone), ['warn', 'ok'])
})

test('notices: ok fades after 3 s (the zone schedules it), errors stay; a station change drops confirmations only', async () => {
  const t = await T()
  t.$notices.set([])
  const timers = []
  t.CB.ctx = { setTimeout: (fn, ms) => { timers.push({ fn, ms }); return () => {} } }
  t.setNotice('led-1 saved.', 'ok')
  t.setNotice('No solder plan fixture.', 'bad')
  HOOKS.effects = []
  t.NoticeZone({ list: t.$notices.get() })
  HOOKS.effects.forEach(f => f())
  assert.equal(timers.length, 1)
  assert.ok(timers[0].ms > 2900 && timers[0].ms <= 3000, String(timers[0].ms))
  // not due yet: nothing goes
  timers[0].fn()
  assert.equal(t.$notices.get().length, 2)
  t.$notices.set(t.$notices.get().map(n => ({ ...n, at: n.at - 3100 })))
  timers[0].fn()
  assert.deepEqual(t.$notices.get().map(n => n.tone), ['bad'])
  // only errors left: no timer
  HOOKS.effects = []; timers.length = 0
  t.NoticeZone({ list: t.$notices.get() })
  HOOKS.effects.forEach(f => f())
  assert.equal(timers.length, 0)
  t.setNotice('led-1 saved.', 'ok')
  t.goStation('wire')
  assert.deepEqual(t.$notices.get().map(n => n.tone), ['bad'])
})

test('patchOps: a conflict reloads and says "reloaded the project, try again"; an error stays as an alert', async () => {
  const t = await T()
  t.$notices.set([])
  const p = { id: 'laser-trigger', rev: 3, board: {}, assignments: [] }
  t.$project.set(p)
  t.CB.api = new Proxy({
    patchProject: async () => ({ ok: false, error: { code: 'project_conflict', message: 'rev' }, result: null }),
    project: async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null })
  }, { get: (o, k) => k in o ? o[k] : async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  await t.patchOps([{ op: 'note', text: 'x' }])
  assert.ok(t.$notices.get().some(n => n.tone === 'warn' && /reloaded the project, try again/.test(n.text)), JSON.stringify(t.$notices.get()))
})

test('FLASH: a refusal locks the button and shows message and hint under it; ready and unknown do not lock', async () => {
  const t = await T()
  const p = clone(FX['project.laser-trigger'].result.project)
  t.$project.set(p)
  const card = () => expand(t.FlashCard({ project: p, n: '4', primary: true }))
  for (const [name, code] of [['flash.check.flash_disabled', 'flash_disabled'], ['flash.check.chip_mismatch', 'chip_mismatch']]) {
    t.$flashCheck.set({ project: p.id, port: null, env: FX[name] })
    const tree = card()
    const btn = byCb(tree, 'flash-start')[0]
    assert.equal(btn.props.disabled, true, code)
    assert.equal(btn.props['data-cb-gate'], 'locked')
    assert.equal(btn.props['aria-describedby'], 'cb-flash-gate')
    assert.match(text(btn), /locked/)
    const note = byCb(tree, 'flash-gate')[0]
    assert.equal(note.props['data-cb-code'], code)
    assert.equal(text(byCb(note, 'flash-gate-msg')), FX[name].result.refusal.message)
    assert.equal(text(byCb(note, 'flash-gate-hint')), FX[name].result.refusal.hint)
    assert.equal(byCb(note, 'agent-settings-link').length, code === 'flash_disabled' ? 1 : 0)
  }
  for (const env of [FX['flash.check.ok'], null, { ok: false, error: { code: 'network_error', message: 'x' }, result: null }]) {
    t.$flashCheck.set({ project: p.id, port: null, env })
    const tree = card()
    assert.equal(byCb(tree, 'flash-start')[0].props.disabled, false)
    assert.equal(byCb(tree, 'flash-gate').length, 0)
  }
  // an answer for another project never locks this one
  t.$flashCheck.set({ project: 'other', port: null, env: FX['flash.check.flash_disabled'] })
  assert.equal(byCb(card(), 'flash-start')[0].props.disabled, false)
})

test('FLASH: refreshFlashCheck asks for the selected port, else the detected one, and keeps only the newest answer', async () => {
  const t = await T()
  const p = clone(FX['project.laser-trigger'].result.project)
  t.$project.set(p)
  const asked = []
  t.CB.api = { flashCheck: async (id, port) => { asked.push([id, port]); return FX['flash.check.ok'] } }
  t.$flow.set({ port: null, focus: null, at: 0 })
  await t.refreshFlashCheck()
  t.$flow.set({ port: '/dev/ttyACM0', focus: null, at: 0 })
  await t.refreshFlashCheck()
  assert.deepEqual(asked, [['laser-trigger', 'sim://esp32s3-n16r8'], ['laser-trigger', '/dev/ttyACM0']])
  assert.equal(t.$flashCheck.get().port, '/dev/ttyACM0')
})

test('FLASH: the detection\'s caution/danger warnings are warning lines (symbol + word), info stays out', async () => {
  const t = await T()
  const p = clone(FX['project.laser-trigger'].result.project)
  const det = p.board.detected
  t.$detect.set({ status: 'ready', port: det.port, env: { ok: true, result: det, warnings: [
    { code: 'no_auto_reset', severity: 'caution', message: '/dev/ttyACM0: hold BOOT', source_ids: [] },
    { code: 'board_identity', severity: 'danger', message: 'wrong MAC', source_ids: [] },
    { code: 'board_reset', severity: 'info', message: 'esptool reset the board', source_ids: [] }] } })
  const tree = expand(t.DetectResult({ project: p }))
  const lines = find(tree, q => typeof q['data-cb'] === 'string' && q['data-cb'].startsWith('detect-warning-'))
  assert.deepEqual(lines.map(l => [l.props['data-cb'], l.props['data-cb-severity']]), [['detect-warning-no_auto_reset', 'caution'], ['detect-warning-board_identity', 'danger']])
  assert.match(text(lines[0]), /^!caution\/dev\/ttyACM0: hold BOOT$/)
  assert.match(text(lines[1]), /^✕dangerwrong MAC$/)
})

test('FLASH: a real board\'s unverified guess "n16r8?" matches project n16r8; "Use" sends set_board without "?"', async () => {
  const t = await T()
  const p = clone(FX['project.laser-trigger'].result.project)
  assert.equal(p.board.variant, 'n16r8')
  t.$project.set(p)
  const det = { ...p.board.detected, port: '/dev/ttyACM0', simulated: false, variant_suggestion: 'n16r8?' }
  t.$detect.set({ status: 'ready', port: det.port, env: { ok: true, result: det, warnings: [] } })
  let tree = expand(t.DetectResult({ project: p }))
  assert.equal(byCb(tree, 'variant-differs').length, 0, 'no mismatch line for the same bare variant')
  const ok = byCb(tree, 'variant-matches')
  assert.equal(ok.length, 1)
  assert.equal(ok[0].props['data-cb-unverified'], 'true')
  assert.match(text(ok[0]), /^✓ module variant N16R8 matches the project \(unverified/)
  assert.doesNotMatch(text(tree), /N16R8\?/)
  // a different guess: the button and the dialog carry the bare id, set_board gets the bare id
  t.$detect.set({ status: 'ready', port: det.port, env: { ok: true, result: { ...det, variant_suggestion: 'n8r2?' }, warnings: [] } })
  tree = expand(t.DetectResult({ project: p }))
  const diff = byCb(tree, 'variant-differs')
  assert.equal(diff.length, 1)
  assert.match(text(diff[0]), /Detected N8R2 \(unverified\), the project says N16R8\./)
  const take = byCb(tree, 'variant-take')[0]
  assert.equal(text(take), 'Use N8R2')
  take.props.onClick()
  assert.equal(t.$ui.get().modal.variant, 'n8r2')
  const sent = []
  t.CB.api = { patchProject: async (id, rev, ops) => { sent.push(ops); return { ok: false, error: { code: 'stub', message: 'stub' }, result: null } } }
  await t.applyVariant('n8r2?')
  assert.deepEqual(sent.map(ops => ops.map(o => [o.op, o.variant])), [[['set_board', 'n8r2']]])
})
