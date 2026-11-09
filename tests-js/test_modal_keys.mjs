// The Bench modal handles Escape and Tab only for its own root (or when the focus is lost to <body>): keys of the
// app around it (chat composer: Escape cancels a turn, Tab moves on) pass untouched. Runs the product bundle with
// fake hooks and a small fake DOM, no browser.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from '../scripts/build-desktop.mjs'

const HOOKS = { refs: [], effects: [] }
globalThis.__cbModalHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbModalSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = i => [typeof i === "function" ? i() : i, () => {}], ' +
      'useEffect = f => { globalThis.__cbModalHooks.effects.push(f) }, useMemo = f => f(), ' +
      'useRef = v => { const r = { current: v === undefined ? null : v }; globalThis.__cbModalHooks.refs.push(r); return r }, useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (type, props, key) => ({ type, props, key }), jsxs = jsx, Fragment = "F"')
    + '\nexport const __t = { Modal }\n'
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

// ─── fake DOM: enough for Modal (parentNode, classList, contains, focus, querySelector(All)) ──────────────────────

function fakeDocument() {
  const listeners = []
  const doc = {
    activeElement: null,
    addEventListener: (type, fn) => listeners.push({ type, fn }),
    removeEventListener: (type, fn) => { const i = listeners.findIndex(l => l.type === type && l.fn === fn); if (i >= 0) listeners.splice(i, 1) },
    keydown(key, target, { shiftKey = false } = {}) {
      const e = { key, target, shiftKey, prevented: false, stopped: false, preventDefault() { this.prevented = true }, stopPropagation() { this.stopped = true } }
      for (const l of [...listeners]) if (l.type === 'keydown') l.fn(e)
      return e
    },
    listeners
  }
  const el = (tag, { cls = [], parent = null, focusable = false } = {}) => {
    const node = {
      tagName: tag.toUpperCase(), parentNode: parent, kids: [], isConnected: true, tabIndex: focusable ? 0 : -1, focusable,
      classList: { contains: c => cls.includes(c) },
      contains(n) { for (let x = n; x; x = x.parentNode) if (x === node) return true; return false },
      all() { return node.kids.flatMap(k => [k, ...k.all()]) },
      querySelectorAll() { return node.all().filter(k => k.focusable) },
      querySelector(sel) { return /input/.test(sel) ? node.all().find(k => ['INPUT', 'SELECT', 'TEXTAREA'].includes(k.tagName)) || null : null },
      getClientRects: () => [{}],
      focus() { doc.activeElement = node },
      matches: () => false, hasAttribute: () => false, setAttribute: () => {}
    }
    if (parent) parent.kids.push(node)
    return node
  }
  doc.body = el('body')
  return { doc, el }
}

let mod
async function openModal() {
  if (!mod) { globalThis.__cbModalSdk = fakeSdk(); mod = await loadBundle() }
  const { doc, el } = fakeDocument()
  // app markup around the Bench: a chat composer outside, the Bench root with the dialog inside
  const app = el('div', { parent: doc.body })
  const composer = el('textarea', { parent: app, focusable: true })
  const root = el('div', { parent: app, cls: ['cb-root'] })
  const station = el('button', { parent: root, focusable: true })
  const dialog = el('div', { parent: root, cls: ['cb-modal'] })
  const first = el('button', { parent: dialog, focusable: true })
  const last = el('button', { parent: dialog, focusable: true })
  globalThis.document = doc
  HOOKS.refs = []
  HOOKS.effects = []
  let closed = 0
  mod.__t.Modal({ title: 'Test dialog', onClose: () => { closed++ }, children: [] })
  HOOKS.refs[0].current = dialog // the dialog ref (first useRef in Modal)
  const cleanup = HOOKS.effects.map(f => f())
  assert.equal(doc.activeElement, first, 'the dialog takes the focus when it opens')
  return { doc, composer, station, dialog, first, last, closed: () => closed, cleanup }
}

test('Escape in the chat composer passes untouched; the dialog stays open', async () => {
  const m = await openModal()
  m.composer.focus()
  const e = m.doc.keydown('Escape', m.composer)
  assert.equal(e.prevented, false, 'no preventDefault on an app key')
  assert.equal(e.stopped, false, 'no stopPropagation on an app key')
  assert.equal(m.closed(), 0, 'the dialog stays open')
})

test('Escape inside the dialog closes it', async () => {
  const m = await openModal()
  const e = m.doc.keydown('Escape', m.first)
  assert.equal(e.prevented, true)
  assert.equal(m.closed(), 1)
})

test('Tab from the chat composer is no focus trap', async () => {
  const m = await openModal()
  m.composer.focus()
  const e = m.doc.keydown('Tab', m.composer)
  assert.equal(e.prevented, false)
  assert.equal(m.doc.activeElement, m.composer, 'the focus stays where the app put it')
})

test('focus lost to <body>: Tab jumps into the dialog, Escape closes it', async () => {
  const m = await openModal()
  m.doc.activeElement = m.doc.body
  const tab = m.doc.keydown('Tab', m.doc.body)
  assert.equal(tab.prevented, true)
  assert.equal(m.doc.activeElement, m.first)
  m.doc.activeElement = null
  assert.equal(m.doc.keydown('Escape', m.doc.body).prevented, true)
  assert.equal(m.closed(), 1)
})

test('inside the own root the focus trap still cycles and pulls stray focus back', async () => {
  const m = await openModal()
  m.last.focus()
  const wrap = m.doc.keydown('Tab', m.last)
  assert.equal(wrap.prevented, true)
  assert.equal(m.doc.activeElement, m.first, 'Tab on the last element wraps to the first')
  m.doc.keydown('Tab', m.first, { shiftKey: true })
  assert.equal(m.doc.activeElement, m.last, 'Shift+Tab on the first wraps to the last')
  // a click elsewhere in the Bench moved the focus out of the dialog: the next Tab brings it back
  m.station.focus()
  m.doc.keydown('Tab', m.station)
  assert.equal(m.doc.activeElement, m.first)
})

test('closing removes the document listener', async () => {
  const m = await openModal()
  assert.equal(m.doc.listeners.filter(l => l.type === 'keydown').length, 1)
  for (const c of m.cleanup) if (typeof c === 'function') c()
  assert.equal(m.doc.listeners.filter(l => l.type === 'keydown').length, 0)
})
