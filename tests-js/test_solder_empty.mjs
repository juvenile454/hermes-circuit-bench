// Station 04 SOLDER without a plan (product bundle, a recording jsx, fake hooks, no DOM): the empty text names
// the button that plans from the project parts and says that a plan made in the chat shows up here; without parts
// it points at 02 CALC and the CSV import that the plan source panel really has.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const clone = x => JSON.parse(JSON.stringify(x))
const PROJECT = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSolderSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [typeof i === "function" ? i() : i, () => {}], ' +
      'useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v === undefined ? null : v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { StationSolder, CB, $project, $solderPlan }\n'
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
const norm = s => s.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim()

let mod
async function render(parts) {
  if (!mod) { globalThis.__cbSolderSdk = fakeSdk(); mod = await loadBundle() }
  const p = clone(PROJECT)
  p.parts = parts
  p.solder = { steps: [], done: [] }
  mod.__t.CB.api = new Proxy({}, { get: () => async () => ({ ok: false, error: { code: 'stub', message: 'stub' }, result: null }) })
  mod.__t.$project.set(p)
  mod.__t.$solderPlan.set({ status: 'idle', env: null })
  return expand(mod.__t.StationSolder({ project: p }))
}

test('no plan, parts listed: press "Plan from project parts"; a plan made by Hermes shows up here too', async () => {
  const n = PROJECT.parts.length
  assert.ok(n > 1)
  const tree = await render(clone(PROJECT.parts))
  const box = byCb(tree, 'solder-empty')
  assert.equal(box.length, 1)
  assert.equal(norm(text(find(box, (q, node) => node.type === 'p'))),
    `Press Plan from project parts to order the ${n} parts. A plan Hermes makes with this project also shows up here.`)
  const btn = byCb(box, 'solder-plan-parts')
  assert.equal(norm(text(btn)), 'Plan from project parts', 'the text names the real button')
  assert.equal(btn[0].props.disabled, false)
})

test('no plan, one part: the text reads "order the part"', async () => {
  const tree = await render(clone(PROJECT.parts).slice(0, 1))
  const said = norm(text(find(byCb(tree, 'solder-empty'), (q, node) => node.type === 'p')))
  assert.equal(said, 'Press Plan from project parts to order the part. A plan Hermes makes with this project also shows up here.')
})

test('no plan, no parts: 02 CALC or the CSV import of the plan source panel; nothing about pasting on the right', async () => {
  const tree = await render([])
  const box = byCb(tree, 'solder-empty')
  const said = norm(text(find(box, (q, node) => node.type === 'p')))
  assert.equal(said, 'Add parts in 02 CALC, or open import bom (csv) in the plan source panel.')
  assert.ok(!/paste a BOM on the right/.test(said))
  assert.equal(byCb(box, 'solder-plan-parts')[0].props.disabled, true)
  // the words of the text exist in the inspector next to it
  const insp = find(tree, q => q['data-cb'] === 'insp')
  assert.match(text(insp), /\/\/ plan source/)
  assert.ok(find(insp, (q, node) => node.type === 'summary' && /import bom \(csv\)/.test(text(node))).length === 1)
})
