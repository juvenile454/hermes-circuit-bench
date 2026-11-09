// Status words and feedback reach every user: the HUD link words without a board use fg-dim (≥ 4.5:1 on bg and
// panel), the copy buttons name their result (Copied / Copy failed), the notice zone is a polite live region from
// the start, and the console tabs point at the panel that shows their content. Product bundle, recording jsx,
// fake hooks, no DOM.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { contrastRatio } from '../desktop-src/lib/contrast.js'
import { PHOSPHOR } from '../desktop-src/lib/tokens.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const HOOKS = { queue: [] }
globalThis.__cbA11yHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbA11ySdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [globalThis.__cbA11yHooks.queue.length ? globalThis.__cbA11yHooks.queue.shift() : (typeof i === "function" ? i() : i), () => {}], ' +
      'useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v === undefined ? null : v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { linkState, FlashHash, Console, NoticeZone, CB, $ui, $jobs }\n'
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

let mod
async function T() {
  if (!mod) { globalThis.__cbA11ySdk = fakeSdk(); mod = await loadBundle() }
  HOOKS.queue = []
  mod.__t.CB.ctx = { os: { writeClipboard: async () => true }, setTimeout: () => () => {} }
  return mod.__t
}

test('HUD link words without a board are information: fg-dim, ≥ 4.5:1 on bg and panel', async () => {
  const t = await T()
  const quiet = [t.linkState({ status: 'error', ports: [] }), t.linkState({ status: 'idle', ports: [] }),
    t.linkState({ status: 'loading', ports: [] }), t.linkState({ status: 'ready', ports: [] })]
  assert.deepEqual(quiet.map(l => [l.kind, l.label, l.tone]),
    [['offline', 'OFFLINE', 'dim'], ['unknown', '…', 'dim'], ['unknown', '…', 'dim'], ['none', 'NO BOARD', 'dim']])
  // the HUD renders the tone as class cb-<tone>; cb-dim is fg-dim
  const hud = readFileSync(join(ROOT, 'desktop-src', '30-ui-hud.js'), 'utf8')
  assert.match(hud, /h\('span', \{ className: `cb-\$\{link\.tone\}` \}, link\.label\)/)
  const styles = readFileSync(join(ROOT, 'desktop-src', '12-styles.js'), 'utf8')
  assert.match(styles, /\.cb-root \.cb-dim\{color:var\(--cb-fg-dim\)\}/)
  for (const ground of ['bg', 'panel']) {
    const r = contrastRatio(PHOSPHOR['fg-dim'], PHOSPHOR[ground])
    assert.ok(r >= 4.5, `fg-dim on ${ground}: ${r.toFixed(2)}:1`)
    assert.ok(contrastRatio(PHOSPHOR['fg-faint'], PHOSPHOR[ground]) < 4.5, 'fg-faint is decoration only')
  }
})

test('copy buttons name their result: Copied / Copy failed (flash hash and console log)', async () => {
  const t = await T()
  const hash = 'ab'.repeat(32)
  const label = st => {
    HOOKS.queue = [st]
    return byCb(expand(t.FlashHash({ hash, label: 'elf sha256' })), 'flash-hash-copy')[0].props['aria-label']
  }
  assert.equal(label(null), 'Copy the elf sha256')
  assert.equal(label('ok'), 'Copied')
  assert.equal(label('fail'), 'Copy failed')

  t.$ui.set({ ...t.$ui.get(), tab: 'build' })
  t.$jobs.set({ detect: null, build: { job_id: 'job-b1', kind: 'build', state: 'done', log_tail: ['Compiling', 'SUCCESS'] }, flash: null })
  const consoleLabel = st => {
    HOOKS.queue = [null, st, 0] // jump, copied, newLines
    return byCb(expand(t.Console({ surface: 'pane', project: null })), 'console-copy')[0].props['aria-label']
  }
  assert.equal(consoleLabel(null), 'Copy log')
  assert.equal(consoleLabel('ok'), 'Copied')
  assert.equal(consoleLabel('fail'), 'Copy failed')
})

test('the notice zone is a polite live region before the first notice arrives', async () => {
  const t = await T()
  const empty = expand(t.NoticeZone({ list: [] }))
  assert.equal(byCb(empty, 'notices')[0].props['aria-live'], 'polite')
  const one = expand(t.NoticeZone({ list: [{ id: 'n1', text: 'Saved.', tone: 'ok', at: Date.now() }] }))
  assert.equal(byCb(one, 'notices')[0].props['aria-live'], 'polite')
})

test('console tabs: id + aria-controls, the content sits in a tabpanel labelled by the selected tab', async () => {
  const t = await T()
  t.$ui.set({ ...t.$ui.get(), tab: 'build' })
  t.$jobs.set({ detect: null, build: { job_id: 'job-b1', kind: 'build', state: 'done', log_tail: ['Compiling', 'SUCCESS'] }, flash: null })
  const tree = expand(t.Console({ surface: 'pane', project: null }))
  const tabs = find(tree, p => p.role === 'tab')
  assert.deepEqual(tabs.map(n => n.props['data-cb']), ['tab-serial', 'tab-build', 'tab-flash'])
  const ids = tabs.map(n => n.props.id)
  assert.ok(ids.every(Boolean) && new Set(ids).size === 3, ids.join(', '))
  const panels = find(tree, p => p.role === 'tabpanel')
  assert.equal(panels.length, 1)
  const panel = panels[0].props
  assert.ok(panel.id)
  for (const n of tabs) assert.equal(n.props['aria-controls'], panel.id)
  assert.equal(panel['aria-labelledby'], tabs.find(n => n.props['aria-selected'] === 'true').props.id)
  assert.equal(find(panels[0], p => p['data-cb'] === 'log').length, 1, 'the log is inside the panel')
  // a second console (pane beside the page) gets its own ids
  const other = expand(t.Console({ surface: 'pane', project: null }))
  const otherIds = find(other, p => p.role === 'tab').map(n => n.props.id)
  assert.ok(otherIds.every(id => !ids.includes(id)), 'ids are unique per console')
  // collapsed page console: no panel, so no aria-controls pointing nowhere
  const shut = expand(t.Console({ surface: 'page', project: null, mode: 'collapsed' }))
  assert.equal(find(shut, p => p.role === 'tabpanel').length, 0)
  assert.ok(find(shut, p => p.role === 'tab').every(n => n.props['aria-controls'] === undefined))
})
