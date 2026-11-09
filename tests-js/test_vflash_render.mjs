// The station pieces as rendered by the product bundle (stub hooks, function components expanded to a
// plain tree): flash dialog (hash groups, bars, words, focus/confirm unchanged), flash map only with result.images,
// port symbol only for the detected real port, phase word in the job line.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIR = join(ROOT, 'desktop-src', 'fixtures')
const FX = Object.fromEntries(readdirSync(DIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(DIR, f), 'utf8'))]))
const clone = x => JSON.parse(JSON.stringify(x))

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbVfSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = v => [typeof v === "function" ? v() : v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v ?? null }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = (t, p, k) => ({ t, p, k }), jsxs = jsx, Fragment = "frag"')
    + '\nexport const __t = { FlashDialog, FlashMap, PortList, JobLine, BuildCard, FlashCard, CB, $project, $jobs, $board, $flow }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

function fakeSdk() {
  const atom = v => {
    let cur = v
    return { get: () => cur, set: n => { cur = n }, subscribe: () => () => {} }
  }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', THEMES_AREA: 'themes',
    TRANSCRIPT_DIRECTIVE_AREA: 'directives', STATUSBAR_AREAS: { right: 'statusBar.right' }, PANES_AREA: 'panes', host: {} }
}

/** Expand function components; return the host tree {t, p, kids}. */
function expand(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return null
  if (typeof node !== 'object') return String(node)
  if (Array.isArray(node)) return node.map(expand).filter(x => x !== null)
  if (typeof node.t === 'function') return expand(node.t(node.p || {}))
  const kids = node.p?.children === undefined ? [] : [].concat(node.p.children).map(expand).flat().filter(x => x !== null)
  return { t: node.t, p: node.p || {}, kids }
}
const all = (n, pred, out = []) => {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out }
  if (n && typeof n === 'object') { if (pred(n)) out.push(n); n.kids.forEach(x => all(x, pred, out)) }
  return out
}
const text = n => Array.isArray(n) ? n.map(text).join('') : typeof n === 'string' ? n : n ? n.kids.map(text).join('') : ''
const byCb = (tree, v) => all(tree, n => n.p['data-cb'] === v)

globalThis.__cbVfSdk = fakeSdk()
const M = await loadBundle()
const T = M.__t
const project = clone(FX['project.laser-trigger'].result.project)
T.$project.set(project)
T.CB.ctx = { os: { writeClipboard: async () => true }, setTimeout: () => () => {} }

test('dialog: target, hash in eight groups (contiguous text), RAM/flash bars, checks in words, buttons unchanged', () => {
  const confirm = { port: project.board.detected.port, mac: project.board.detected.mac, elf_sha256: project.firmware.last_build.elf_sha256 }
  const tree = expand(T.FlashDialog({ confirm, onClose: () => {} }))
  const hash = byCb(tree, 'flash-hash')[0]
  assert.equal(hash.kids.length, 8)
  assert.equal(text(hash), confirm.elf_sha256) // no spaces in the text: search and e2e find any prefix
  assert.equal(byCb(tree, 'flash-hash-copy').length, 1)
  const bars = all(tree, n => n.p.role === 'progressbar')
  assert.deepEqual(bars.map(b => [b.p['aria-label'], b.p['aria-valuenow']]), [['RAM used', 6], ['Flash used', 9]])
  assert.match(text(byCb(tree, 'flash-mem')[0]), /5\.9\s*%.*8\.5\s*%/)
  const checks = ['port', 'mac', 'elf'].map(id => byCb(tree, `flash-check-${id}`)[0])
  assert.ok(checks.every(c => c.p['data-cb-state'] === 'match' && /match/.test(text(c))))
  assert.ok(!/= detection|= last build/.test(text(tree)))
  assert.equal(byCb(tree, 'flash-cancel').length, 1)
  const confirmBtn = byCb(tree, 'flash-confirm')[0]
  assert.match(text(confirmBtn), /Flash simulated board/)
  assert.ok(text(tree).includes('SIMULATED') && text(tree).includes('aa:bb:cc:dd:ee:ff') && text(tree).includes('sim://esp32s3-n16r8'))
})

test('dialog: without a clipboard door there is no copy button; a differing MAC reads "differs"', () => {
  const keep = T.CB.ctx
  T.CB.ctx = {}
  const confirm = { port: project.board.detected.port, mac: '11:22:33:44:55:66', elf_sha256: project.firmware.last_build.elf_sha256 }
  const tree = expand(T.FlashDialog({ confirm, onClose: () => {} }))
  T.CB.ctx = keep
  assert.equal(byCb(tree, 'flash-hash-copy').length, 0)
  const mac = byCb(tree, 'flash-check-mac')[0]
  assert.equal(mac.p['data-cb-state'], 'differs')
  assert.match(text(mac), /differs/)
})

test('flash map: drawn only for a done flash job with images; the simulated fixture job draws nothing', () => {
  assert.equal(expand(T.FlashMap({ job: FX['job.flash.done'].result })), null)
  const job = clone(FX['job.flash.done'].result)
  job.result.result.images = [{ offset: '0x0', name: 'bootloader.bin', sha256: 'b'.repeat(64) }, { offset: '0x8000', name: 'partitions.bin', sha256: 'c'.repeat(64) },
    { offset: '0xe000', name: 'boot_app0.bin', sha256: 'd'.repeat(64) }, { offset: '0x10000', name: 'firmware.bin', sha256: 'a'.repeat(64) }]
  const tree = expand(T.FlashMap({ job }))
  const rows = byCb(tree, 'flash-map-image')
  assert.deepEqual(rows.map(r => r.p['data-cb-offset']), ['0x0', '0x8000', '0xe000', '0x10000'])
  assert.match(text(rows[3]), /0x10000.*firmware\.bin/)
  assert.ok(!/bytes|KiB|size/i.test(text(tree)), 'no sizes on the map')
  const marks = all(tree, n => n.p['data-cb-offset'] && n.p.style?.left)
  assert.equal(marks.length, 4)
  assert.equal(marks[0].p.style.left, '0%')
  assert.equal(expand(T.FlashMap({ job: { ...job, state: 'running' } })), null)
})

test('port list: connector symbol (artPort) only on the detected real port; sim and undetected ports get none', () => {
  const ports = clone(FX.ports.result.ports)
  T.$board.set({ status: 'ready', id: 'esp32-s3-devkitc-1', layout: FX['board.esp32-s3-devkitc-1'].result, error: null, sources: [] })
  const flow = { port: 'sim://esp32s3-n16r8' }
  let tree = expand(T.PortList({ ports: { status: 'ready', ports }, project, flow, health: null }))
  assert.equal(byCb(tree, 'port-symbol').length, 0) // the project is detected on the sim port
  const onReal = clone(project)
  onReal.board.detected.port = '/dev/ttyACM0'
  tree = expand(T.PortList({ ports: { status: 'ready', ports }, project: onReal, flow, health: null }))
  const sym = byCb(tree, 'port-symbol')
  assert.equal(sym.length, 1)
  assert.equal(sym[0].p['data-cb-port'], 'generic_usb') // S3 "USB" port: the board data names no connector type
  assert.match(sym[0].p.dangerouslySetInnerHTML.__html, /data-cb-port="generic_usb"/)
  assert.ok(all(byCb(tree, 'port-real')[0], n => n.p['data-cb'] === 'port-symbol').length === 1)
  // descriptions wrap (no ellipsis class)
  assert.ok(all(tree, n => /cb-vf-portdesc/.test(n.p.className || '')).every(n => !/cb-ellip/.test(n.p.className)))
})

test('job line: phase word and percent while running, plain state when done', () => {
  const run = expand(T.JobLine({ kind: 'flash', job: { job_id: 'j-1', kind: 'flash', state: 'running', progress: 0.42, log_tail: ['Writing at 0x00010000 [====>   ] 42.0%'] } }))
  assert.equal(run.p['data-cb-phase'], 'writing')
  assert.match(text(run), /flash.*writing.*42 %/)
  assert.equal(all(run, n => n.p.role === 'progressbar')[0].p['aria-label'], 'flash progress · writing')
  const done = expand(T.JobLine({ kind: 'flash', job: FX['job.flash.done'].result }))
  assert.equal(done.p['data-cb-phase'], undefined)
  assert.match(text(done), /flash done/)
})
