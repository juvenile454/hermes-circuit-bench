// Frame polish: one panic strip outside 06 DEBUG with the selectors the smoke reads, console tools in their own
// group, one rail status grammar that keeps the stageStatus text in the DOM, no endless blinking, the generic USB jack
// without a form claim, the twin pad of the chat card's hover coupling, source labels that keep enumerations.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { shellRailMark, shellMarkShapes } from '../desktop-src/lib/art-shell.js'
import { stageStatus } from '../desktop-src/lib/stages.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const read = f => readFileSync(join(SRC, f), 'utf8')
const fx = name => JSON.parse(readFileSync(join(SRC, 'fixtures', `${name}.json`), 'utf8'))
const decode = fx('crash.decode')
const project = fx('project.laser-trigger').result.project

// ─── rail grammar (lib/art-shell.js) ───────────────────────────────────

test('rail mark: every stageStatus text maps to glyph + number; the code keeps the original text', () => {
  const cases = {
    '1✕': ['blocked', '1', '✕'], '3!': ['caution', '3', '!'], '!': ['caution', '', '!'], '[✓]': ['done', '', '[✓]'], '[ ]': ['todo', '', '[ ]'],
    '40%': ['progress', '40%', ''], PANIC: ['panic', 'PANIC', ''], FAIL: ['blocked', '', 'FAIL'], BUILT: ['built', '', 'BUILT'], '': ['', '', '']
  }
  for (const [text, [glyph, num, code]] of Object.entries(cases)) {
    const m = shellRailMark(text)
    assert.deepEqual([m.glyph, m.num, m.code], [glyph, num, code], text)
    // the DOM text of .cb-s (num + code, as the E2E reads it with textContent) is the stageStatus text again
    assert.equal(`${m.num}${m.code}`.replace(/^(\d+)(✕|!)$/, '$1$2'), text, text)
  }
  assert.equal(shellRailMark('40%').pct, 40)
  // every station of the fixture project has a mark
  const s = stageStatus(project, { ok: 4, caution: 0, blocked: 1, unchecked: 0 }, null)
  for (const st of Object.values(s)) assert.ok(shellRailMark(st.text).glyph || !st.text, st.text)
})

test('rail mark shapes: progress ring grows with pct, panic is a word only, unknown draws nothing', () => {
  assert.equal(shellMarkShapes('progress', 0).length, 1)
  assert.match(JSON.stringify(shellMarkShapes('progress', 40)), /A5 5 0 0 1/)
  assert.match(JSON.stringify(shellMarkShapes('progress', 75)), /A5 5 0 1 1/)
  assert.equal(shellMarkShapes('progress', 100).length, 2)
  assert.deepEqual(shellMarkShapes('panic'), [])
  assert.deepEqual(shellMarkShapes('nope'), [])
  assert.equal(shellMarkShapes('done').length, 2)
})

// ─── motion budget ─────────────────────────────────────────────────────

test('no endless blinking: rail alert, ok dots and the card stamp are static or finite; the title cursor blinks 3×', () => {
  const css = read('12-styles.js') + read('19-styles-debug.js')
  const rule = sel => (css.match(new RegExp(`${sel.replace(/[.[\]=()]/g, m => `\\${m}`)}\\{[^}]*\\}`)) || [''])[0]
  assert.doesNotMatch(rule('.cb-root .cb-stage[data-cb-alert=true] .cb-s'), /animation/)
  assert.doesNotMatch(rule('.cb-root .cb-dot--ok'), /animation/)
  assert.match(rule('.cb-root .cb-alarm .cb-stamp'), /animation:cb-pulse \.6s ease-in-out 1\}/)
  assert.match(css, /animation:cb-blink 1s steps\(2\) 3\}/)
})

// ─── generic USB jack ──────────────────────────────────────────────────

test('generic USB jack: metal shell with shadow and a plain opening, marked schematic, no dashes', async () => {
  const { artPort } = await import(`data:text/javascript;base64,${Buffer.from(read('lib/art.js')).toString('base64')}`)
  const g = artPort('generic_usb', 0, 0, { prefix: 'p' })
  assert.match(g, /data-cb-schematic="true"/)
  assert.match(g, /filter="url\(#cb-p-shadow\)"/)
  assert.doesNotMatch(g, /dasharray/)
  assert.match(g, /fill="var\(--cb-cavity\)"/)
})

// ─── rendered (product bundle, fake SDK) ───────────────────────────────

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
  globalThis.__cbSdk = fakeSdk()
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = v => [typeof v === "function" ? v() : v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { ConsoleRow, PanicStrip, PanicCard, RailMark, sourceLabel, artBoardTwinPad, boardArtModel, boardGeom, chipInfo, variantInfo, $panic, $nav, $ui, $project }\n'
  return (await import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)).__t
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
function walk(tree, fn) { for (const n of tree) { if (typeof n === 'string') continue; fn(n); walk(n.children, fn) } }
const textOf = n => (typeof n === 'string' ? n : n.children.map(textOf).join(''))
const find = (tree, pred) => { const out = []; walk(tree, n => { if (pred(n)) out.push(n) }); return out }
const byCb = (tree, cb) => find(tree, n => n.props['data-cb'] === cb)

test('panic strip outside 06 DEBUG: one line, keeps data-cb=panic-card and .cb-panic-actions, Open Debug, no agent button', async () => {
  const t = await loadBundle()
  t.$panic.set({ status: 'ok', env: decode, key: project.debug.last_panic.log_ref, summary: decode.summary, flashAt: null })
  const strip = render(t.PanicStrip({ project }))
  const [card] = byCb(strip, 'panic-card')
  assert.ok(card, 'the smoke waits for [data-cb=panic-card] on PLAN')
  assert.equal(card.props['data-cb-form'], 'strip')
  assert.equal(card.props['data-cb-audit-root'], 'panic')
  assert.match(card.props['aria-label'], /^Panic: StoreProhibited · core 1 at main\.cpp:44$/)
  assert.equal(find(strip, n => String(n.props.className || '').split(' ').includes('cb-panic-actions')).length, 1)
  assert.equal(byCb(strip, 'panic-open-debug').length, 1)
  assert.equal(byCb(strip, 'fix-with-hermes').length, 0, 'the Hermes action lives in 06 DEBUG and in the serial pane card')
  assert.equal(find(strip, n => String(n.props.className || '').includes('cb-stamp')).length, 0, 'no stamp: one alarm source per screen')
  // the full card (serial pane) has no SIM tag of its own any more
  assert.equal(byCb(render(t.PanicCard({ project })), 'panic-sim').length, 0)
})

test('rail mark rendered: .cb-s text equals the stageStatus text (E2E reads it), glyph svg aria-hidden', async () => {
  const t = await loadBundle()
  for (const text of ['1✕', '[✓]', '40%', 'PANIC', '[ ]']) {
    const [s] = render(t.RailMark({ text, tone: 'ok' }))
    assert.equal(textOf(s), text, text)
    for (const svg of find([s], n => n.type === 'svg')) assert.equal(svg.props['aria-hidden'], 'true')
  }
})

test('source labels: enumerations are never cut after the first item', async () => {
  const t = await loadBundle()
  assert.equal(t.sourceLabel({ title: 'IEC 60063:2015 preferred number series E6, E12, E24 (values via Wikipedia, secondary source)' }),
    'IEC 60063:2015 preferred number series E6, E12, E24')
  assert.equal(t.sourceLabel({ title: 'NXP UM10204, I2C-bus specification and user manual, Rev. 7.0 (1 October 2021)' }), 'NXP UM10204')
  assert.equal(t.sourceLabel({ title: 'onsemi 2N2222A/D, Small Signal Switching Transistor NPN Silicon, Rev. 2 (November 2013)' }), 'onsemi 2N2222A/D')
})

test('twin pad: an assigned GPIO has a position inside the compact model; turned and upright agree', async () => {
  const t = await loadBundle()
  const layout = fx('board.esp32-s3-devkitc-1').result
  const b = project.board
  const model = t.boardArtModel({ layout, chip: t.chipInfo(b.chip), variant: t.variantInfo(b.chip, b.variant), base: new Map(), used: new Map() })
  const g = t.boardGeom({ layout, mode: 'compact' })
  for (const a of project.assignments) {
    const up = t.artBoardTwinPad(model, g, a.pin, false)
    const turned = t.artBoardTwinPad(model, g, a.pin, true)
    assert.ok(up && turned, `GPIO${a.pin}`)
    for (const v of [up.x, up.y, turned.x, turned.y]) assert.ok(v > 0 && v < 100, `GPIO${a.pin}: ${v}`)
    // turned by 90°: x(turned) = 100 − y(upright), y(turned) = x(upright)
    assert.ok(Math.abs(turned.x - (100 - up.y)) < 0.2 && Math.abs(turned.y - up.x) < 0.2, `GPIO${a.pin}`)
  }
  assert.equal(t.artBoardTwinPad(model, g, 999, true), null)
})

test('console bar: the tools (copy, pane, hide) sit in their own group after the meta', () => {
  const src = read('50-console.js')
  const meta = src.indexOf("className: 'cb-meta'")
  const tools = src.indexOf("className: 'cb-cons-tools'")
  assert.ok(meta > 0 && tools > meta)
  assert.match(read('12-styles.js'), /\.cb-root \.cb-cons-tools\{flex:none;/)
})
