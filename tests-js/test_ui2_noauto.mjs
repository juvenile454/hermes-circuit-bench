// Nothing opens a port on its own. The product bundle runs against a fake ctx (real fixtures as REST
// answers, a real ESP port in the list, the project detected on that real port): register, load, ports events,
// polling ticks, panic events and a reload never call POST /serial/open, /board/detect or /board/flash and never
// read a real port's tail. Detect and the monitor start only from the click handlers.
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
    .replace("import * as sdk from '@hermes/plugin-sdk'", `const sdk = globalThis.__cbSdk`)
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'", 'const useState = 0, useEffect = 0, useMemo = 0, useRef = 0, useCallback = 0')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = () => null, jsxs = () => null, Fragment = 0')
    + '\nexport const __t = { loadBench, pollTick, loadSerial, CB, $ports, $serial, $project, $monitor, onProjectUpdated, selectPort, $flow }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}

function fakeSdk() {
  const atom = v => {
    let cur = v
    const subs = new Set()
    return { get: () => cur, set: n => { cur = n; for (const s of subs) s(n) }, subscribe: fn => { subs.add(fn); return () => subs.delete(fn) } }
  }
  const nav = []
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', THEMES_AREA: 'themes',
    TRANSCRIPT_DIRECTIVE_AREA: 'directives', STATUSBAR_AREAS: { right: 'statusBar.right' }, PANES_AREA: 'panes',
    host: { navigate: p => nav.push(p), openWorkspace: () => nav.push('workspace'), notify: () => {} }, nav }
}

function fakeCtx(project, portsList) {
  const calls = []
  const handlers = new Map()
  const intervals = []
  const regs = []
  const answer = (method, path) => {
    if (path === '/health') return FX.health
    if (path === '/projects') return FX['projects.list']
    if (path.startsWith('/projects/')) return { ...clone(FX['project.laser-trigger']), result: { project, rev: project.rev } }
    if (path === '/ports') return { ...clone(FX.ports), result: { ports: portsList } }
    if (path.startsWith('/boards/')) return FX['board.esp32-s3-devkitc-1']
    if (path === '/pins/check') return FX['pins.check']
    if (path.startsWith('/serial/tail')) return FX['serial.lines']
    if (path === '/crash/decode') return FX['crash.decode']
    if (path.startsWith('/pins/info')) return FX['pins.info']
    return { ok: false, action: 'x', summary: 'no', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: { code: 'not_found', message: 'no' } }
  }
  const ctx = {
    calls, handlers, intervals, regs, sockets: [],
    rest: async (path, opts = {}) => { calls.push(`${opts.method || 'GET'} ${path}`); return clone(answer(opts.method || 'GET', path)) },
    socket: (path, fn) => { ctx.sockets.push(path); return () => {} },
    onEvent: (type, fn) => { handlers.set(type, fn); return () => {} },
    onDispose: () => {}, setInterval: (fn, ms) => { intervals.push(fn); return () => {} }, setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); return () => clearTimeout(t) },
    storage: { get: (k, d) => d, set: () => {} }, registerMany: rs => { regs.push(...rs); return () => {} }, register: r => { regs.push(r); return () => {} },
    registerSettingsPage: p => { regs.push({ id: 'settings', area: 'settings', data: p }); return () => {} }, os: {}
  }
  return ctx
}

const tick = () => new Promise(r => setTimeout(r, 30))
const FORBIDDEN = /^(POST \/serial\/open|POST \/board\/(detect|flash|build)|POST \/serial\/close)/

test('register + load + events + polling: no port is opened, detected or flashed, no real port is read', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const project = clone(FX['project.laser-trigger'].result.project)
  project.board.detected = { ...project.board.detected, port: '/dev/ttyACM0', simulated: false } // the real board
  const portsList = clone(FX.ports.result.ports) // /dev/ttyACM0 (ESP) + sim://
  const ctx = fakeCtx(project, portsList)
  mod.default.register(ctx)
  const t = mod.__t
  await t.loadBench()
  await tick()
  for (const ev of ['board.changed', 'panic.detected', 'job.updated', 'project.updated']) {
    ctx.handlers.get(`plugin.circuit-bench.${ev}`)?.({ payload: { port: '/dev/ttyACM0', state: 'linked', id: project.id, rev: project.rev + 1, job_id: 'j-0001-abcdef', by: 'agent' } })
  }
  t.CB.mounts = 1
  t.CB.lastEventAt = 0
  for (const fn of ctx.intervals) await fn()
  await tick()
  t.selectPort('/dev/ttyACM0') // choosing a port in the list is not an action
  await t.loadSerial({ fresh: true })
  await tick()
  assert.deepEqual(ctx.calls.filter(c => FORBIDDEN.test(c)), [])
  assert.deepEqual(ctx.calls.filter(c => /serial\/tail\?port=%2Fdev/.test(c)), [], 'a real port tail is never read')
  assert.deepEqual(ctx.sockets, [], 'no serial stream without a click')
  assert.equal(t.$monitor.get().status, 'closed')
  assert.equal(t.$serial.get().note, 'real-port')
  assert.ok(ctx.calls.includes('GET /ports'))
  // palette: Detect/Build only open station 05 and mark the button
  const pal = ctx.regs.filter(r => r.area === 'palette').map(r => r.data)
  assert.deepEqual(pal.map(p => p.label), ['Open Bench', 'Open serial monitor', 'New bench project', 'Manage bench projects', 'Load demo project', 'Detect board', 'Build firmware', 'Run bench doctor'])
  const before = ctx.calls.length
  pal.find(p => p.label === 'Detect board').run()
  pal.find(p => p.label === 'Build firmware').run()
  await tick()
  assert.deepEqual(ctx.calls.slice(before).filter(c => FORBIDDEN.test(c)), [])
  assert.equal(t.$flow.get().focus, 'build')
  assert.ok(ctx.regs.some(r => r.area === 'directives' && r.data.name === 'bench'))
  // the sidebar row carries the full name, so it is found next to other plugins
  assert.deepEqual(ctx.regs.find(r => r.area === 'nav')?.data, { path: '/bench', label: 'Circuit Bench', codicon: 'circuit-board' })
  assert.ok(ctx.regs.some(r => r.id === 'settings'))
  assert.ok(!ctx.regs.some(r => r.id === 'media-schematic'), 'no TOOL_MEDIA_RENDERER_AREA in this SDK: not registered')
})

test('sim board: buffered lines are read (GET /serial/tail), still nothing is opened', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const project = clone(FX['project.laser-trigger'].result.project) // detected on sim://
  const ctx = fakeCtx(project, clone(FX.ports.result.ports))
  mod.default.register(ctx)
  await mod.__t.loadBench()
  await tick()
  assert.ok(ctx.calls.some(c => c.startsWith('GET /serial/tail?port=sim%3A%2F%2Fesp32s3-n16r8')))
  assert.deepEqual(ctx.calls.filter(c => FORBIDDEN.test(c)), [])
  assert.deepEqual(ctx.sockets, [])
})
