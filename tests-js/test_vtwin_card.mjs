// The chat card (view pins) with the compact board model, legend and key figures in words; several cards
// in one chat never share an SVG id.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const FXDIR = join(ROOT, 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(FXDIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FXDIR, f), 'utf8'))]))
const MAPS = JSON.parse(readFileSync(join(ROOT, 'tests-js', 'fixtures', 'ui1-pins-maps.json'), 'utf8'))
const project = FX['project.laser-trigger'].result.project
const s3 = FX['board.esp32-s3-devkitc-1'].result

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
    + '\nexport const __t = { BenchDirectiveInner, DIRECTIVE_BOARDS, DIRECTIVE_MAPS, DIRECTIVE_CACHE, $project }\n'
  const { __t: t } = await import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
  t.DIRECTIVE_BOARDS.set(s3.id, s3)
  t.DIRECTIVE_CACHE.set(project.id, { env: { ok: true, result: { project } }, at: Date.now() + 1e9 })
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
const svgsOf = tree => { const out = []; walk(tree, n => { if (n.props.dangerouslySetInnerHTML) out.push(n.props.dangerouslySetInnerHTML.__html) }); return out }
const card = (t, view = 'pins') => render(t.BenchDirectiveInner({ a: { project: project.id, view, station: view === 'pins' ? 'plan' : 'debug', title: 'PIN MAP' }, sessionId: null }))

test('pins card: compact board model under the old data-cb, key figures in words, legend, one primary button', async () => {
  const t = await loadBundle()
  t.DIRECTIVE_MAPS.set(JSON.stringify(['esp32s3', 'n16r8', true, s3.id]), MAPS['pins.map/esp32s3/n16r8/wifi-on'])
  const tree = card(t)
  const [model] = byCb(tree, 'directive-mini-pins')
  assert.ok(model, 'directive-mini-pins stays on the new model')
  assert.equal(model.props['data-cb-board'], s3.id)
  const [svg] = svgsOf([model])
  assert.match(svg, /^<svg[^>]*data-cb-mode="compact"/)
  // the drawing carries no text (it scales in the narrow card); the 5 project pins are assigned pads
  assert.doesNotMatch(svg, /<text/)
  assert.equal((svg.match(/data-cb-art-state="assigned"/g) || []).length, 5)
  // the map gives the unassigned pins their state (free / caution / blocked), not "not checked"
  assert.ok((svg.match(/data-cb-art-state="free"/g) || []).length > 5)
  assert.ok((svg.match(/data-cb-art-state="blocked"/g) || []).length >= 1)
  // the model is one image with its sentence
  const img = []
  walk([model], n => { if (n.props.role === 'img') img.push(n) })
  assert.equal(img.length, 1)
  assert.match(img[0].props['aria-label'], /LASER on GPIO14 \(ok\)/)
  // key figures: symbol + number + word, the sentence in aria-label (HUD format, lib/art-shell.js shellKpis)
  const [hl] = byCb(tree, 'directive-headline')
  assert.equal(hl.props['aria-label'], '5 pins assigned: 5 ok, 0 caution, 0 blocked')
  assert.equal(textOf(hl), '5 assigned✓5ok!0caution✕0blocked')
  assert.doesNotMatch(textOf(hl), /5✓ 0! 0✕/)
  // legend with the model's glyphs
  const [legend] = byCb(tree, 'directive-legend')
  assert.ok(legend)
  const items = []
  walk([legend], n => { if (n.props['data-cb-legend']) items.push(n.props['data-cb-legend']) })
  assert.deepEqual(items, ['assigned', 'free', 'caution', 'blocked', 'power', 'ground'])
  // the assignments beside the model with glyph + role + IO + header position + word
  const [rows] = byCb(tree, 'directive-rows')
  assert.match(textOf(rows), /LASERIO14J1-20outok/)
  assert.match(textOf(rows), /BUTTONIO2J3-5in · pull-upok/)
  // the dashed frames on the strips in words, the module facts from the variant (N16R8: octal PSRAM, IO35–37 on the header)
  const facts = textOf(byCb(tree, 'directive-board-facts')[0])
  assert.match(facts, /reservedOCTAL PSRAM IO35–37USB IO19\/20/)
  // the words carry the frame's tone: blocked octal pins with the map → bad
  const res = []
  walk(byCb(tree, 'directive-board-facts'), n => { if (/cb-dres--/.test(n.props.className || '')) res.push(n.props.className) })
  assert.deepEqual(res, ['cb-dres cb-dres--bad', 'cb-dres cb-dres--warn'])
  assert.equal((svg.match(/class="cb-art-bracket"/g) || []).length, 2)
  assert.match(facts, /moduleWROOM-1 · N16R816 MB flash8 MB octal PSRAM/)
  // exactly one button, and it is primary (no ghost/agent modifier)
  const buttons = []
  walk(tree, n => { if (n.type === 'button') buttons.push(n) })
  assert.equal(buttons.length, 1)
  assert.equal(buttons[0].props['data-cb'], 'directive-open')
  assert.equal(buttons[0].props.className, 'cb-btn cb-btn--sm')
  // SIM badge and the audit root
  assert.equal(byCb(tree, 'directive-sim').length, 1)
  const [root] = byCb(tree, 'directive-card')
  assert.equal(root.props['data-cb-audit-root'], 'directive')
  // never data-cb-state on the art or the legend (the e2e counts [data-cb-state] under the bench root)
  assert.doesNotMatch(svg, /data-cb-state=/)
})

test('two cards in one chat: own id prefixes, every url(#…) resolves inside its own SVG', async () => {
  const t = await loadBundle()
  const a = svgsOf(byCb(card(t), 'directive-mini-pins'))[0]
  const b = svgsOf(byCb(card(t), 'directive-mini-pins'))[0]
  const ids = s => [...s.matchAll(/ id="([^"]+)"/g)].map(m => m[1])
  const refs = s => [...s.matchAll(/url\(#([^)]+)\)/g)].map(m => m[1])
  assert.ok(ids(a).length > 3, 'defs present')
  assert.ok(ids(a).every(id => id.startsWith('cb-chat-')))
  assert.equal(new Set([...ids(a), ...ids(b)]).size, ids(a).length + ids(b).length, 'no id shared between the cards')
  for (const s of [a, b]) for (const r of refs(s)) assert.ok(ids(s).includes(r), `unresolved ${r}`)
})

test('without the map the pins are drawn unchecked; without a layout the list stands alone', async () => {
  const t = await loadBundle()
  const svg = svgsOf(byCb(card(t), 'directive-mini-pins'))[0]
  assert.equal((svg.match(/data-cb-art-state="assigned"/g) || []).length, 5)
  assert.equal((svg.match(/data-cb-art-state="free"/g) || []).length, 0)
  t.DIRECTIVE_BOARDS.delete(s3.id)
  const tree = card(t)
  assert.equal(byCb(tree, 'directive-mini-pins').length, 0)
  assert.equal(byCb(tree, 'directive-legend').length, 0)
  assert.equal(byCb(tree, 'directive-headline').length, 1)
  assert.match(textOf(byCb(tree, 'directive-rows')[0]), /VBATIO1/)
})

test('other views keep their headline text (test_ui2_directive summaries)', async () => {
  const t = await loadBundle()
  const tree = card(t, 'crash')
  assert.equal(textOf(byCb(tree, 'directive-headline')[0]), 'PANIC CAUGHT')
  assert.equal(byCb(tree, 'directive-mini-pins').length, 0)
})
