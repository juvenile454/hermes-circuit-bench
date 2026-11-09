// Station 04 SOLDER as rendered (product bundle, a recording jsx, fake hooks, no DOM). One progress
// formula ("2/5 done · now C1", no "next" while a step is open), the open step with pictogram, hint lines and the
// button "Mark done (N)", polarity tags only where the step carries a sourced polarity hint, done steps fold to one
// line and open again with the full action (nothing cut, no ellipsis rule left), key n still marks the current step,
// the plan source lists every part with the current refs marked and says why a button is disabled.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { solderArtPolarity } from '../desktop-src/lib/art-parts.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const clone = x => JSON.parse(JSON.stringify(x))
const PROJECT = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project

// useState answers from a queue (tests force a folded step open), else the initial value
const HOOKS = { queue: [] }
globalThis.__cbHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [globalThis.__cbHooks.queue.length ? globalThis.__cbHooks.queue.shift() : (typeof i === "function" ? i() : i), () => {}], ' +
      'useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v === undefined ? null : v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { StationSolder, SolderStepCard, CB, $project, $solderPlan, CB_CSS, CB_CSS_PARTS }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

function fakeSdk() {
  const atom = v => {
    let cur = v
    const subs = new Set()
    return { get: () => cur, set: n => { cur = n; for (const s of subs) s(n) }, subscribe: fn => { subs.add(fn); return () => subs.delete(fn) } }
  }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette',
    host: { navigate: () => {}, openWorkspace: () => {}, notify: () => {} } }
}

/** Expand function components (fake hooks) into a tree of host elements. */
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
async function setup(doneN, { env = null } = {}) {
  if (!mod) { globalThis.__cbSdk = fakeSdk(); mod = await loadBundle() }
  const p = clone(PROJECT)
  p.solder.done = p.solder.steps.slice(0, doneN).map(s => s.id)
  const calls = []
  const api = { solderStep: async (id, stepId, done) => { calls.push([id, stepId, done]); return { ok: true, result: { project: p } } } }
  // every other call (the pin check after applyProject …) answers "not here"
  mod.__t.CB.api = new Proxy(api, { get: (o, k) => k in o ? o[k] : async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  mod.__t.$project.set(p)
  mod.__t.$solderPlan.set({ status: env ? 'ready' : 'idle', env })
  HOOKS.queue = []
  const tree = expand(mod.__t.StationSolder({ project: p }))
  return { p, calls, tree }
}

test('one progress formula in the head: "2/5 done · now C1"; all done → "5/5 done · ✓ all steps done"', async () => {
  const { tree } = await setup(2)
  assert.equal(norm(text(byCb(tree, 'solder-formula'))), '2/5 done · now C1')
  assert.ok(!/next/i.test(text(byCb(tree, 'solder-progress'))), 'no "next" while a step is open')
  assert.equal(byCb(tree, 'solder-progress').length, 1)
  const four = await setup(0)
  assert.equal(norm(text(byCb(four.tree, 'solder-formula'))), '0/5 done · now R1 · R2 · R3 · R4')
  const all = await setup(5)
  assert.equal(norm(text(byCb(all.tree, 'solder-formula'))), '5/5 done · ✓ all steps done')
  assert.equal(find(all.tree, p => p['aria-current'] === 'step').length, 0)
  assert.equal(byCb(all.tree, 'solder-mark-done').length, 0)
})

test('the open step: pictogram, kind in the head, hint lines with symbol + category + sources, one "Mark done (N)"', async () => {
  const { tree, p } = await setup(2)
  const cur = find(tree, q => q['aria-current'] === 'step')
  assert.equal(cur.length, 1)
  assert.equal(cur[0].props['data-cb'], 'step-3')
  assert.match(text(find(cur[0], q => q.className === 'cb-step-head')), /electrolytic/, 'E2E catalog reads the kind from .cb-step-head')
  assert.equal(byCb(cur[0], 'step-pic-3').length, 1)
  assert.match(byCb(cur[0], 'step-pic-3')[0].props.dangerouslySetInnerHTML.__html, /data-cb-art="electrolytic"[^>]*data-cb-polarity="minus-stripe"/)
  const btn = byCb(tree, 'solder-mark-done')
  assert.equal(btn.length, 1, 'only on the current step')
  assert.equal(norm(text(btn)), 'Mark done (N)')
  assert.equal(btn[0].props['aria-keyshortcuts'], 'n')
  const rows = find(cur[0], q => q['data-cb-hint-kind'])
  assert.deepEqual(rows.map(r => [r.props['data-cb-hint-kind'], r.props['data-cb-severity']]), p.solder.steps[2].hints.map(x => [
    x.code === 'polarity' ? 'polarity' : x.code === 'heat_sensitive' ? 'heat' : 'tip', x.severity]))
  const danger = rows[0]
  assert.equal(text(find(danger, q => q.className === 'cb-shint-sym')), '✕')
  assert.match(text(find(danger, q => q.className === 'cb-shint-cat')), /danger: polarity/)
  assert.equal(text(byCb(danger, 'hint-src')), 'src ›nichicon-al-guidelines·nichicon-al-technical-notes·rubycon-zlj-spec') // separators + CSS gap
  // with the plan answer loaded the sources carry their titles and open their URL
  const withSrc = await setup(2, { env: { ok: true, sources: [{ id: 'solder-rubycon-zlj-spec', title: 'Rubycon, Spec sheet', url: 'https://example.invalid/r.pdf', retrieved: '2026-11-06' }] } })
  const src = byCb(find(withSrc.tree, q => q['aria-current'] === 'step'), 'hint-src')[0]
  assert.ok(find(src, (q, n) => n.type === 'button' && /Rubycon/.test(text(n))).length === 1)
})

test('polarity tags only where the step carries a sourced polarity hint (C1 stripe, Q1 pinout: datasheet)', async () => {
  const { tree, p } = await setup(0)
  const tags = byCb(tree, 'step-polarity')
  const expected = p.solder.steps.filter(s => solderArtPolarity(s)).map(s => solderArtPolarity(s).mark)
  assert.deepEqual(tags.map(t => t.props['data-cb-mark']), expected)
  assert.deepEqual(expected, ['pinout-datasheet', 'minus-stripe'])
  assert.match(norm(text(tags[0])), /pinout: datasheet/)
  // no pin letters anywhere for the transistor
  const q1 = byCb(tree, 'step-pic-2')[0].props.dangerouslySetInnerHTML.__html
  assert.ok(!/<text|>[EBC]</.test(q1))
  // the hint gone → the tag is gone
  const p2 = clone(p)
  p2.solder.steps[2].hints = p2.solder.steps[2].hints.filter(x => x.code !== 'polarity')
  HOOKS.queue = []
  const t2 = expand(mod.__t.StationSolder({ project: p2 }))
  assert.deepEqual(byCb(t2, 'step-polarity').map(t => t.props['data-cb-mark']), ['pinout-datasheet'])
  assert.ok(!/data-cb-polarity/.test(byCb(t2, 'step-pic-3')[0].props.dangerouslySetInnerHTML.__html))
})

test('done steps fold to one line (refs, ✓ done, details ▾) and open with the full action and hints', async () => {
  const { tree, p } = await setup(3)
  for (const n of [1, 2, 3]) {
    const card = byCb(tree, `step-${n}`)[0]
    assert.match(card.props.className, /cb-step--done/)
    assert.equal(find(card, q => q.className === 'cb-step-act').length, 0, 'folded: no cut text, the action is not shown')
    assert.match(norm(text(card)), new RegExp(p.solder.steps[n - 1].refs.join(' · ')))
    const more = byCb(card, `step-expand-${n}`)[0]
    assert.equal(more.props['aria-expanded'], 'false')
  }
  // open: the same card with open = true shows the whole action, unchanged
  const s = p.solder.steps[0]
  HOOKS.queue = [true]
  const open = expand(mod.__t.SolderStepCard({ step: s, done: true, current: false, onToggle: () => {}, onMark: () => {}, busy: false, parts: p.parts, sources: [] }))
  assert.equal(byCb(open, 'step-expand-1')[0].props['aria-expanded'], 'true')
  assert.equal(norm(text(find(open, q => q.className === 'cb-step-act'))), norm(s.action))
  assert.equal(find(open, q => q['data-cb-hint-kind']).length, s.hints.length)
  // later steps are dimmed and have no button
  const later = byCb(tree, 'step-5')[0]
  assert.match(later.props.className, /cb-step--todo/)
  assert.equal(byCb(later, 'solder-mark-done').length, 0)
})

test('no ellipsis left on step texts: the last rule for done actions wraps, the solder styles never cut', async () => {
  await setup(0)
  const css = mod.__t.CB_CSS + mod.__t.CB_CSS_PARTS.join('')
  const own = readFileSync(join(ROOT, 'desktop-src', '16-styles-solder.js'), 'utf8')
  const ownCss = own.replace(/^\s*\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')
  assert.ok(!/ellipsis/.test(ownCss), 'no ellipsis rule in 16-styles-solder.js')
  for (const m of ownCss.matchAll(/\{([^{}]*)\}/g)) assert.ok(!(/nowrap/.test(m[1]) && /overflow:hidden/.test(m[1])), `cutting rule: ${m[1]}`)
  const decl = (sel, prop) => {
    let last = null
    for (const m of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!m[1].split(',').map(x => x.trim()).includes(sel)) continue
      for (const d of m[2].split(';')) { const [k, v] = d.split(':').map(x => x?.trim()); if (k === prop) last = v }
    }
    return last
  }
  assert.equal(decl('.cb-root .cb-step--done .cb-step-act', 'text-overflow'), 'clip')
  assert.equal(decl('.cb-root .cb-step--done .cb-step-act', 'white-space'), 'normal')
  assert.equal(decl('.cb-root .cb-step--done .cb-step-act', 'overflow'), 'visible')
  assert.equal(decl('.cb-root .cb-solder-why', 'white-space'), 'normal')
})

test('key n marks the current step done (not from inputs, not with modifiers); the button does the same', async () => {
  const { tree, calls, p } = await setup(2)
  const main = byCb(tree, 'station-solder')[0]
  assert.equal(main.props['data-cb-audit-root'], 'station')
  const ev = (key, extra = {}) => ({ key, target: { tagName: 'MAIN' }, preventDefault: () => {}, ...extra })
  main.props.onKeyDown(ev('n'))
  await new Promise(r => setTimeout(r, 5))
  assert.deepEqual(calls, [[p.id, p.solder.steps[2].id, true]])
  main.props.onKeyDown(ev('n', { target: { tagName: 'TEXTAREA' } }))
  main.props.onKeyDown(ev('n', { ctrlKey: true }))
  main.props.onKeyDown(ev('x'))
  await new Promise(r => setTimeout(r, 5))
  assert.equal(calls.length, 1)
  await byCb(tree, 'solder-mark-done')[0].props.onClick()
  assert.deepEqual(calls[1], [p.id, p.solder.steps[2].id, true])
})

test('plan source: every part with its step, the current refs marked NOW, reasons for disabled buttons, CSV folded', async () => {
  const { tree, p } = await setup(2)
  const aside = byCb(tree, 'insp')[0]
  assert.equal(aside.props['data-cb-audit-root'], 'inspector')
  const rows = find(aside, q => /^part-/.test(q['data-cb'] || ''))
  // every part once, in solder order (step 01 R1–R4, 02 Q1, 03 C1 …)
  assert.deepEqual(rows.map(r => r.props['data-cb']), ['R1', 'R2', 'R3', 'R4', 'Q1', 'C1', 'SW1', 'J2'].map(r => `part-${r}`))
  assert.deepEqual(rows.map(r => r.props['data-cb']).sort(), p.parts.map(x => `part-${x.ref}`).sort())
  const st = Object.fromEntries(rows.map(r => [r.props['data-cb'].slice(5), r.props['data-cb-state']]))
  assert.deepEqual(st, { R1: 'done', R2: 'done', Q1: 'done', R3: 'done', R4: 'done', C1: 'now', SW1: 'todo', J2: 'todo' })
  const now = rows.find(r => r.props['data-cb-state'] === 'now')
  assert.equal(now.props['aria-current'], 'true')
  assert.match(text(now), /03 current step/, 'the step number stays, the state is said (frame + ● + words)')
  const box = byCb(aside, 'solder-csv-box')[0]
  assert.equal(box.type, 'details')
  assert.equal(byCb(box, 'solder-plan-csv')[0].props.disabled, true)
  assert.match(text(byCb(box, 'solder-csv-why')), /paste a BOM first/)
  assert.equal(byCb(aside, 'solder-replan')[0].props.disabled, false)
  assert.equal(byCb(aside, 'solder-replan-why').length, 0)
  // no parts: the reason is visible
  const empty = clone(p)
  empty.parts = []
  HOOKS.queue = []
  const t2 = expand(mod.__t.StationSolder({ project: empty }))
  assert.match(text(byCb(t2, 'solder-replan-why')), /no parts in the project yet/)
})

test('height strip: one silhouette per step in solder order, the current one marked (rule of thumb)', async () => {
  const { tree, p } = await setup(2)
  const strip = byCb(tree, 'solder-heights')[0]
  assert.match(text(strip), /rule of thumb/)
  const cells = find(strip, q => /^height-/.test(q['data-cb'] || ''))
  assert.deepEqual(cells.map(c => c.props['data-cb-state']), ['done', 'done', 'now', 'todo', 'todo'])
  assert.deepEqual(cells.map(c => c.props['data-cb']), p.solder.steps.map(s => `height-${s.n}`))
})
