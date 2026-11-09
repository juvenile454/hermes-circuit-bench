// Register bank (PC/EXCCAUSE/EXCVADDR highlighted and labelled), frame ↔ log coupling (a frame's PC
// marks the address in the raw Backtrace line), ELF check line with its reason, Fix with Hermes as an agent button
// (never danger) at both places, one panic anchor in the station head, cards in reading order, "N new lines" in the
// console toolbar. Rendered from the real fixtures (crash.decode.json, serial.lines.json, project.laser-trigger).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { registerBank, logMarkRanges, splitMarked, elfCheck, panicCardData, KEY_REGISTERS } from '../desktop-src/lib/crash.js'
import { logView, mergeLines, emptyBuffer } from '../desktop-src/lib/seq.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const decode = fx('crash.decode')
const project = fx('project.laser-trigger').result.project
const tail = fx('serial.lines').result
const buf = mergeLines(emptyBuffer(), tail.lines, { epoch: tail.epoch })
const lineText = re => buf.lines.find(l => l.k === 'line' && re.test(l.text)).text

// ─── pure helpers ──────────────────────────────────────────────────────

test('register bank (xtensa fixture): PC, EXCCAUSE, EXCVADDR labelled; cause carries the decoder reason; dump keeps log order', () => {
  const b = registerBank(decode.result)
  assert.equal(b.arch, 'xtensa')
  assert.deepEqual(b.key.map(r => [r.k, r.v, r.label]), [['PC', '0x420019e4', 'program counter'], ['EXCCAUSE', '0x0000001d', 'exception cause'],
    ['EXCVADDR', '0x0000000c', 'accessed address']])
  assert.equal(b.key.find(r => r.k === 'EXCCAUSE').note, 'StoreProhibited')
  assert.equal(b.key.find(r => r.k === 'PC').note, null)
  assert.deepEqual(b.all.map(r => r.k), Object.keys(decode.result.registers))
  assert.deepEqual(b.all.filter(r => r.key).map(r => r.k), ['PC', 'EXCCAUSE', 'EXCVADDR'])
})

test('register bank (riscv, synthetic): MEPC, MCAUSE, MTVAL; no note unless a cpu exception; nothing without registers', () => {
  const b = registerBank({ arch: 'riscv', kind: 'cpu_exception', reason: 'Store access fault',
    registers: { MEPC: '0x4200a0b2', RA: '0x4200a0a0', MSTATUS: '0x00001881', MCAUSE: '0x00000007', MTVAL: '0x00000000' } })
  assert.deepEqual(b.key.map(r => r.k), ['MEPC', 'MCAUSE', 'MTVAL'])
  assert.equal(b.key[1].note, 'Store access fault')
  assert.equal(registerBank({ arch: 'riscv', kind: 'abort', reason: 'abort()', registers: { MEPC: '0x1', MCAUSE: '0x2' } }).key[1].note, null)
  assert.equal(registerBank({ registers: {} }), null)
  assert.equal(registerBank(null), null)
  assert.deepEqual(Object.keys(KEY_REGISTERS), ['xtensa', 'riscv'])
})

test('frame ↔ log: each frame PC marks exactly its address in the raw Backtrace line, nothing elsewhere', () => {
  const bt = lineText(/^Backtrace:/)
  for (const f of decode.result.frames) {
    const r = logMarkRanges(bt, { kind: 'pc', value: f.pc })
    assert.equal(r.length, 1, f.pc)
    assert.equal(bt.slice(r[0][0], r[0][1]), f.pc)
  }
  // the register PC (0x420019e4) is not a backtrace address: no mark, and the UI does not invent why they differ
  assert.deepEqual(logMarkRanges(bt, { kind: 'pc', value: decode.result.registers.PC }), [])
  // a PC is never matched outside a Backtrace line or as a prefix of a longer number
  assert.deepEqual(logMarkRanges(lineText(/^PC\s*:/), { kind: 'pc', value: '0x420019e4' }), [])
  assert.deepEqual(logMarkRanges('Backtrace: 0x420019e10:0x3fcebf20', { kind: 'pc', value: '0x420019e1' }), [])
  assert.deepEqual(logMarkRanges('Backtrace: 0X420019E1:0x3fcebf20', { kind: 'pc', value: '0x420019e1' }), [[11, 21]])
})

test('register ↔ log: "NAME : value" in the dump line; PC never matches inside EXCVADDR or a longer name', () => {
  const pcLine = lineText(/^PC\s*:/)
  const r = logMarkRanges(pcLine, { kind: 'reg', name: 'PC', value: '0x420019e4' })
  assert.equal(r.length, 1)
  assert.equal(pcLine.slice(...r[0]), 'PC      : 0x420019e4')
  const ex = lineText(/^EXCVADDR/)
  assert.equal(ex.slice(...logMarkRanges(ex, { kind: 'reg', name: 'EXCVADDR', value: '0x0000000c' })[0]), 'EXCVADDR: 0x0000000c')
  assert.deepEqual(logMarkRanges(ex, { kind: 'reg', name: 'ADDR', value: '0x0000000c' }), [])
  assert.deepEqual(logMarkRanges(pcLine, { kind: 'reg', name: 'PC', value: '0x00000000' }), [])
  assert.deepEqual(logMarkRanges(pcLine, { kind: 'reg', name: 'P(C', value: '0x420019e4' }), [])
  assert.deepEqual(splitMarked('ab12cd', [[2, 4]]), [{ t: 'ab', mark: false }, { t: '12', mark: true }, { t: 'cd', mark: false }])
  assert.deepEqual(splitMarked('x', []), [{ t: 'x', mark: false }])
})

test('elf check: word and reason for its own line; a skipped check is never shown as passed', () => {
  const e = elfCheck(decode)
  assert.deepEqual([e.status, e.word, e.reason], ['skipped', 'skipped', 'simulated build, no ELF'])
  assert.equal(elfCheck({ checks: [{ id: 'crash.elf_match', status: 'failed' }], result: {} }).word, 'mismatch')
  assert.equal(elfCheck({ checks: [{ id: 'crash.elf_match', status: 'passed', detail: 'sha d106… matches' }], result: {} }).reason, 'sha d106… matches')
})

test('card data: "extra" interpretation leaves out what the decoder summary already says', () => {
  const d = panicCardData(decode, project.debug.last_panic, tail.panic)
  assert.deepEqual(d.extra.map(x => x.code), ['store_prohibited'])
  assert.equal(d.bank.key.length, 3)
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

const HOOKS = { slots: [], i: 0, effects: [] }
globalThis.__cbVdHooks = HOOKS

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const __H = globalThis.__cbVdHooks; const useState = v => { const k = __H.i++; if (!(k in __H.slots)) __H.slots[k] = typeof v === "function" ? v() : v;'
      + ' return [__H.slots[k], n => { __H.slots[k] = typeof n === "function" ? n(__H.slots[k]) : n }] }, useEffect = f => { __H.effects.push(f) }, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { PanicCard, PanicAnalysis, StationDebug, LogLines, Console, Btn, $panic, $serial, $logMark, $ui, $flow, setLogMark, CB }\n'
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
function walk(tree, fn) { for (const n of tree) { if (typeof n === 'string') continue; fn(n); walk(n.children, fn) } }
const textOf = n => (typeof n === 'string' ? n : n.children.map(textOf).join(''))
const find = (tree, pred) => { const out = []; walk(tree, n => { if (pred(n)) out.push(n) }); return out }
const byCb = (tree, cb) => find(tree, n => n.props['data-cb'] === cb)
const hasClass = (n, c) => String(n.props.className || '').split(/\s+/).includes(c)

async function setup() {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const t = mod.__t
  t.$panic.set({ status: 'ok', env: decode, key: project.debug.last_panic.log_ref, summary: decode.summary, flashAt: null })
  return t
}
const fresh = fn => { HOOKS.slots = []; HOOKS.i = 0; HOOKS.effects = []; return render(fn()) }

test('06 DEBUG: one panic anchor in the head; the analysis does not repeat the stamp; cards in reading order without numbers', async () => {
  const t = await setup()
  const tree = fresh(() => t.StationDebug({ project }))
  const anchors = byCb(tree, 'panic-anchor')
  assert.equal(anchors.length, 1)
  assert.equal(textOf(byCb(tree, 'panic-anchor-stamp')[0]), 'PANIC · StoreProhibited · core 1')
  assert.match(textOf(anchors[0]), /write_sensor_buffer\(…\).*main\.cpp:44/)
  const stamps = find(tree, n => hasClass(n, 'cb-stamp'))
  assert.equal(stamps.length, 1, 'exactly one stamp on the station')
  assert.doesNotMatch(textOf(byCb(tree, 'panic-analysis')[0]), /PANIC CAUGHT/)
  // DOM order = reading order; with a panic the analysis leads; no card numbers
  const grid = find(tree, n => hasClass(n, 'cb-debuggrid'))[0]
  assert.equal(grid.props['data-cb-panic'], 'true')
  assert.deepEqual(grid.children.map(c => c.props['data-cb']), ['panic-analysis', 'monitor', 'fix-loop'])
  assert.equal(find(tree, n => hasClass(n, 'cb-secn')).length, 0)
  assert.equal(byCb(tree, 'station-debug')[0].props['data-cb-audit-root'], 'station')
})

test('panic analysis: key registers highlighted with labels; full dump with the key cells marked; ELF line with reason', async () => {
  const t = await setup()
  const tree = fresh(() => t.PanicAnalysis({ project }))
  const regs = byCb(tree, 'panic-regs')[0]
  const keys = find([regs], n => hasClass(n, 'cb-regkey'))
  assert.deepEqual(keys.map(k => k.props['data-cb']), ['reg-PC', 'reg-EXCCAUSE', 'reg-EXCVADDR'])
  assert.match(textOf(keys[0]), /PC.*program counter.*0x420019e4/)
  assert.match(textOf(keys[1]), /EXCCAUSE.*exception cause.*0x0000001d.*= StoreProhibited/)
  assert.match(textOf(keys[2]), /EXCVADDR.*accessed address.*0x0000000c/)
  const cells = find([regs], n => hasClass(n, 'cb-regcell'))
  assert.equal(cells.length, Object.keys(decode.result.registers).length)
  assert.deepEqual(cells.filter(c => hasClass(c, 'cb-regcell--key')).map(c => textOf(c.children[0])), ['PC', 'EXCCAUSE', 'EXCVADDR'])
  const elf = byCb(tree, 'elf-check')
  assert.equal(elf.length, 1)
  assert.equal(elf[0].type, 'div', 'own line, not a chip in the header')
  assert.equal(elf[0].props['data-cb-status'], 'skipped')
  assert.match(textOf(elf[0]), /^elf check○ skipped· simulated build, no ELF$/)
  assert.ok(!/cb-dim|cb-faint/.test(elf[0].props.className))
  // decoder summary first, the interpretation only with what it adds; no PC-difference explanation invented
  assert.equal(textOf(byCb(tree, 'panic-summary')[0]), decode.summary)
  assert.deepEqual(byCb(tree, 'panic-interp')[0].children.map(textOf), [decode.result.interpretation[0].text])
  assert.doesNotMatch(textOf(tree[0]), /differ|return address|PC - 3|pc-3/i)
})

test('frame ↔ log coupling: hovering/focusing a frame or register sets the log mark, leaving clears it; #0 stressed', async () => {
  const t = await setup()
  const tree = fresh(() => t.PanicAnalysis({ project }))
  const rows = decode.result.frames.map(f => byCb(tree, `panic-frame-${f.i}`)[0])
  assert.ok(hasClass(rows[0], 'cb-frow--top'))
  assert.ok(rows.slice(1).every(r => !hasClass(r, 'cb-frow--top')))
  rows[1].props.onMouseEnter()
  assert.deepEqual(t.$logMark.get(), { kind: 'pc', value: '0x42001a01' })
  rows[1].props.onMouseLeave()
  assert.equal(t.$logMark.get(), null)
  rows[2].props.onFocus()
  assert.equal(t.$logMark.get().value, '0x42001a45')
  rows[2].props.onBlur()
  byCb(tree, 'reg-EXCVADDR')[0].props.onMouseEnter()
  assert.deepEqual(t.$logMark.get(), { kind: 'reg', name: 'EXCVADDR', value: '0x0000000c' })
  t.setLogMark(null)
  assert.equal(rows[0].props.tabIndex, 0)
})

test('log: the mark renders as <mark> on the frame address in the panic block only', async () => {
  const t = await setup()
  const view = logView(buf.lines)
  const props = { view, showTs: true, live: tail.panic.seq, panicSeq: tail.panic.seq, lastSeq: tail.next_seq - 1, stream: 's', episode: null, jumpReq: null }
  const plain = fresh(() => t.LogLines(props))
  assert.equal(byCb(plain, 'log-mark').length, 0)
  const tree = fresh(() => t.LogLines({ ...props, mark: { kind: 'pc', value: '0x42001a01' } }))
  const marks = byCb(tree, 'log-mark')
  assert.equal(marks.length, 1)
  assert.equal(textOf(marks[0]), '0x42001a01')
  assert.equal(marks[0].type, 'mark')
  assert.match(byCb(tree, 'log')[0].props['data-cb-mark'], /^pc::0x42001a01$/)
  const line = find(tree, n => hasClass(n, 'cb-line') && textOf(n).includes('Backtrace:'))[0]
  assert.match(textOf(line), /Backtrace: 0x420019e1:0x3fcebf20 0x42001a01:0x3fcebf40/, 'text unchanged around the mark')
  // no follow pill over the log any more: the count goes up to the toolbar
  assert.equal(byCb(tree, 'log-follow').length, 0)
})

test('Fix with Hermes: agent button (never danger) at both places, data-cb names unchanged', async () => {
  const t = await setup()
  const kinds = []
  const origBtn = t.Btn
  for (const [tree, cb] of [[fresh(() => t.PanicAnalysis({ project })), 'fix-with-hermes-main'], [fresh(() => t.PanicCard({ project })), 'fix-with-hermes']]) {
    const b = byCb(tree, cb)
    assert.equal(b.length, 1, cb)
    assert.ok(hasClass(b[0], 'cb-btn--agent'), `${cb}: ${b[0].props.className}`)
    assert.ok(!/danger/.test(b[0].props.className), cb)
    assert.match(textOf(b[0]), /Fix with Hermes/)
    kinds.push(cb)
  }
  assert.equal(typeof origBtn, 'function')
  assert.deepEqual(kinds, ['fix-with-hermes-main', 'fix-with-hermes'])
  const src = readFileSync(join(ROOT, 'desktop-src', '45-station-debug.js'), 'utf8') + readFileSync(join(ROOT, 'desktop-src', '30-ui-panic.js'), 'utf8')
  assert.doesNotMatch(src, /kind:\s*'danger'/)
})

test('console card: ELF chip, frames couple to the log as well; audit roots on console and panic card', async () => {
  const t = await setup()
  const tree = fresh(() => t.PanicCard({ project }))
  const card = byCb(tree, 'panic-card')[0]
  assert.equal(card.props['data-cb-audit-root'], 'panic')
  assert.equal(textOf(byCb(tree, 'elf-check')[0]), '○ elf skipped') // the SIM tag beside it says why
  byCb(tree, 'panic-card-frame-0')[0].props.onMouseEnter()
  assert.equal(t.$logMark.get().value, '0x420019e1')
  t.setLogMark(null)
})
