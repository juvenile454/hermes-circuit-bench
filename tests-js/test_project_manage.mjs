// Project manager: the HUD project pill opens a list; open switches the project and drops the station
// results of the previous one (calculator answers, drawn schematic, solder preview, finished jobs); delete goes through
// DELETE /projects/{id} and opens the next project. A new project shows no example circuit (WIRE starts empty) and the
// calculators carry no laser default. Runs the product bundle against a fake ctx and the fixture backend.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'
import { WIRE_BLOCKS } from '../desktop-src/lib/wire.js'
import { CALC_DEFS } from '../desktop-src/lib/calc.js'
import { createFixtureBackend } from '../desktop-src/lib/fixtures.js'
import { formatStamp } from '../desktop-src/lib/format.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const clone = x => JSON.parse(JSON.stringify(x))

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", `const sdk = globalThis.__cbSdk`)
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'", 'const useState = 0, useEffect = 0, useMemo = 0, useRef = 0, useCallback = 0')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = () => null, jsxs = () => null, Fragment = 0')
    + '\nexport const __t = { loadBench, openProject, removeProject, refreshProjects, onProjectUpdated, CB, $project, $bench, $calcs, $wire, $solderPlan, $nav, $jobs, $detect, $jobNote }\n'
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

function store() {
  // two projects in the fixture backend: the demo and an empty one
  const projects = new Map()
  const demo = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project
  const empty = { ...clone(demo), id: 's3-empty', title: 'S3 empty', rev: 1, simulated: false, assignments: [], parts: [], calcs: [], circuits: [],
    solder: { steps: [], done: [] }, firmware: { dir: null, env: null, last_build: null, last_flash: null }, debug: { last_panic: null }, notes: [] }
  projects.set(demo.id, demo)
  projects.set(empty.id, empty)
  const listOf = () => [...projects.values()].map(p => ({ id: p.id, title: p.title, chip: p.board.chip, variant: p.board.variant,
    devkit: p.board.devkit, rev: p.rev, updated: p.updated, simulated: p.simulated }))
  return { projects, listOf }
}

function fakeCtx(st) {
  const calls = []
  const handlers = new Map()
  const env = (action, result, ok = true, error = null) => ({ ok, action, summary: ok ? 'ok' : error.message, result, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error })
  const ctx = {
    calls, handlers,
    rest: async (path, opts = {}) => {
      const m = opts.method || 'GET'
      calls.push(`${m} ${path}`)
      if (path === '/health') return env('health', { version: '0.1.0' })
      if (path === '/projects' && m === 'GET') return env('project.list', { projects: st.listOf() })
      const pm = path.match(/^\/projects\/([a-z0-9-]+)$/)
      if (pm && m === 'GET') return st.projects.has(pm[1]) ? env('project.get', { project: clone(st.projects.get(pm[1])), rev: st.projects.get(pm[1]).rev })
        : env('project.get', null, false, { code: 'project_not_found', message: `no ${pm[1]}` })
      if (pm && m === 'DELETE') {
        if (!st.projects.has(pm[1])) return env('project.delete', null, false, { code: 'project_not_found', message: `no ${pm[1]}` })
        const p = st.projects.get(pm[1])
        st.projects.delete(pm[1])
        return { ...env('project.delete', { id: p.id, title: p.title, trash: `/data/trash/${p.id}-x` }), summary: `Moved bench project '${p.id}' to the trash.` }
      }
      if (path === '/ports') return env('board.ports', { ports: [] })
      if (path.startsWith('/boards/')) return env('board.layout', null, false, { code: 'unknown_board', message: 'none in this test' })
      if (path === '/pins/check') return env('pins.check', { pins: [] })
      if (path.startsWith('/serial/tail')) return env('serial.tail', { port: null, state: 'closed', lines: [], panic: null, next_seq: 1 })
      return env('x', null, false, { code: 'not_found', message: `${m} ${path}` })
    },
    socket: () => () => {}, onEvent: (type, fn) => { handlers.set(type, fn); return () => {} },
    onDispose: () => {}, setInterval: () => () => {}, setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); return () => clearTimeout(t) },
    storage: { get: (k, d) => d, set: () => {} }, registerMany: () => () => {}, register: () => () => {}, registerSettingsPage: () => () => {}, os: {}
  }
  return ctx
}

const tick = () => new Promise(r => setTimeout(r, 20))

test('switching projects drops the previous project\'s station results; delete opens the next project', async () => {
  globalThis.__cbSdk = fakeSdk()
  const mod = await loadBundle()
  const st = store()
  const ctx = fakeCtx(st)
  mod.default.register(ctx)
  const t = mod.__t
  await t.loadBench({ projectId: 'laser-trigger' })
  await tick()
  assert.equal(t.$project.get().id, 'laser-trigger')
  assert.deepEqual(t.$bench.get().projects.map(p => p.id).sort(), ['laser-trigger', 's3-empty'])
  // station results of the demo (as if the user had calculated and drawn there)
  t.$calcs.set({ npn: { status: 'ready', env: { ok: true }, body: {} } })
  t.$wire.set({ status: 'ready', key: 'k', env: { ok: true, result: { svg: '<svg/>' } }, circuit: 'laser' })
  t.$solderPlan.set({ status: 'ready', env: { ok: true } })
  // finished jobs of the demo: their log, detect result and notes belong to it
  t.$jobs.set({ detect: { job_id: 'd1', kind: 'detect', state: 'done' }, build: { job_id: 'b1', kind: 'build', state: 'done' },
    flash: { job_id: 'f1', kind: 'flash', state: 'failed' } })
  t.$detect.set({ status: 'ready', port: 'sim://esp32s3', env: { ok: true } })
  t.$jobNote.set({ detect: null, build: { code: 'build_failed', message: 'x' }, flash: { code: 'flash_failed', message: 'y' }, example: { code: 'z', message: 'z' } })
  await t.openProject('s3-empty')
  await tick()
  assert.equal(t.$project.get().id, 's3-empty')
  assert.equal(t.$nav.get().project, 's3-empty')
  assert.deepEqual(t.$calcs.get(), {}, 'no calculator answer of the demo')
  assert.equal(t.$wire.get().env, null, 'no schematic of the demo')
  assert.equal(t.$solderPlan.get().env, null)
  assert.deepEqual(t.$jobs.get(), { detect: null, build: null, flash: null }, 'no finished job of the demo')
  assert.deepEqual(t.$detect.get(), { status: 'idle', port: null, env: null })
  assert.deepEqual(t.$jobNote.get(), { detect: null, build: null, flash: null, example: null })
  // open the current one again: nothing reloads
  const before = ctx.calls.length
  assert.equal(await t.openProject('s3-empty'), null)
  assert.equal(ctx.calls.length, before)
  // running jobs survive a project change (finished ones go); a running detect keeps its state
  const running = { detect: { job_id: 'd2', kind: 'detect', state: 'running' }, build: { job_id: 'b2', kind: 'build', state: 'queued' },
    flash: { job_id: 'f2', kind: 'flash', state: 'done' } }
  t.$jobs.set(clone(running))
  t.$detect.set({ status: 'running', port: 'sim://esp32s3', env: null })
  t.$jobNote.set({ detect: null, build: { code: 'x', message: 'x' }, flash: null, example: null })
  // delete the open project: DELETE, the list shrinks, the next project opens
  const del = await t.removeProject('s3-empty')
  assert.equal(del.ok, true)
  assert.ok(ctx.calls.includes('DELETE /projects/s3-empty'))
  await tick()
  assert.deepEqual(t.$bench.get().projects.map(p => p.id), ['laser-trigger'])
  assert.equal(t.$project.get()?.id, 'laser-trigger')
  assert.deepEqual(t.$jobs.get(), { ...running, flash: null })
  assert.equal(t.$detect.get().status, 'running')
  assert.deepEqual(t.$jobNote.get(), { detect: null, build: null, flash: null, example: null })
  // an unknown project: the error comes back, nothing else changes
  const bad = await t.removeProject('nope')
  assert.equal(bad.ok, false)
  assert.equal(t.$project.get()?.id, 'laser-trigger')
  // deleted elsewhere (agent, second window): the event drops it, the bench falls back to the empty state
  st.projects.delete('laser-trigger')
  t.onProjectUpdated({ id: 'laser-trigger', rev: 1, changed: ['deleted'], by: 'ui' })
  await tick()
  assert.equal(t.$project.get(), null)
  assert.equal(t.$bench.get().phase, 'empty')
})

test('a new project shows no example circuit and no laser defaults', () => {
  const wire = readFileSync(join(ROOT, 'desktop-src', '42-station-wire.js'), 'utf8')
  assert.match(wire, /useState\(circuits\[0\]\?\.block \|\| null\)/, 'WIRE starts without a block when the project has no circuit')
  assert.doesNotMatch(wire, /wire\.status === 'idle' && \(stored \|\| block\)/, 'nothing is drawn on its own without a stored circuit')
  assert.equal(WIRE_BLOCKS.find(b => b.block === 'npn_low_side').params.find(p => p.name === 'load').def, 'load')
  assert.equal(CALC_DEFS.find(c => c.type === 'npn').fields.find(f => f.name === 'load').def, 'other')
})

test('fixture backend: DELETE /projects/{id} removes it from the list', async () => {
  const fx = Object.fromEntries(readdirSync(join(ROOT, 'desktop-src', 'fixtures')).filter(f => f.endsWith('.json'))
    .map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', f), 'utf8'))]))
  const b = createFixtureBackend(fx, { delayMs: 0 })
  const before = (await b.handle('GET', '/projects')).result.projects.map(p => p.id)
  assert.ok(before.includes('laser-trigger'))
  const del = await b.handle('DELETE', '/projects/laser-trigger')
  assert.deepEqual([del.ok, del.action, del.result.id], [true, 'project.delete', 'laser-trigger'])
  assert.ok(!(await b.handle('GET', '/projects')).result.projects.some(p => p.id === 'laser-trigger'))
  assert.equal((await b.handle('DELETE', '/projects/laser-trigger')).error.code, 'project_not_found')
  assert.equal((await b.handle('POST', '/projects/demo')).result.id, 'laser-trigger') // the demo comes back
})

test('formatStamp', () => {
  assert.equal(formatStamp(null), '—')
  assert.match(formatStamp('2026-11-06T17:42:26Z'), /^2026-11-06 \d\d:42$/)
})

test('fixture backend: remove_parts drops parts by ref, unknown refs are refused', async () => {
  const fx = Object.fromEntries(readdirSync(join(ROOT, 'desktop-src', 'fixtures')).filter(f => f.endsWith('.json'))
    .map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', f), 'utf8'))]))
  const b = createFixtureBackend(fx, { delayMs: 0 })
  const p = (await b.handle('GET', '/projects/laser-trigger')).result.project
  const ref = p.parts[0].ref
  const ok = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: p.rev, ops: [{ op: 'remove_parts', refs: [ref.toLowerCase()] }] })
  assert.equal(ok.ok, true)
  assert.deepEqual(ok.result.changed, ['parts'])
  assert.ok(!ok.result.project.parts.some(x => x.ref === ref))
  assert.equal(ok.result.project.parts.length, p.parts.length - 1)
  const bad = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: ok.result.rev, ops: [{ op: 'remove_parts', refs: ['ZZ9'] }] })
  assert.equal(bad.error.code, 'invalid_args')
  const bundle = build({ withFixtures: false })
  assert.match(bundle, /op: 'remove_parts', refs/)
  assert.match(bundle, /'data-cb': 'part-remove'/)
})
