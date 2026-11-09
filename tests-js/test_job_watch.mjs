// Job watch (GET /jobs/{id} polling): a failed poll is retried every 2 s, at most 30 times in a row; after that the
// job card says the contact is lost and no timer is left. job_not_found still ends the watch at once. Runs the
// product bundle against a fake ctx whose timers the test fires by hand.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from '../scripts/build-desktop.mjs'

async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbJobSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'", 'const useState = 0, useEffect = 0, useMemo = 0, useRef = 0, useCallback = 0')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = () => null, jsxs = () => null, Fragment = 0')
    + '\nexport const __t = { watchJob, createApi, CB, $jobs, $jobNote, $detect, JOB_WATCH }\n'
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

const envOf = result => ({ ok: true, action: 'job.get', summary: 'ok', result, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: null })

/** Fake ctx: GET /jobs/{id} answers from `script` (an Error is thrown like a dropped connection); timers are queued. */
function fakeCtx(script) {
  const timers = []
  const ctx = {
    timers, jobCalls: 0,
    rest: async path => {
      if (path.startsWith('/jobs/')) {
        ctx.jobCalls++
        const next = script.shift()
        if (next instanceof Error) throw next
        return next
      }
      if (path === '/ports') return envOf({ ports: [] })
      return { ok: false, action: 'x', summary: 'stub', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false, error: { code: 'stub', message: 'stub' } }
    },
    setTimeout: (fn, ms) => {
      const t = { fn, ms, cleared: false }
      timers.push(t)
      return () => { t.cleared = true }
    },
    setInterval: () => () => {},
    storage: { get: (k, d) => d, set: () => {} }
  }
  return ctx
}

const settle = () => new Promise(r => setTimeout(r, 5))

let mod
async function setup(script) {
  if (!mod) { globalThis.__cbJobSdk = fakeSdk(); mod = await loadBundle() }
  const t = mod.__t
  const ctx = fakeCtx(script)
  t.CB.ctx = ctx
  t.CB.api = t.createApi(ctx)
  t.$jobs.set({ detect: null, build: { job_id: 'job-b1', kind: 'build', state: 'running', progress: null, started: 1 }, flash: null })
  t.$jobNote.set({ detect: null, build: null, flash: null, example: null })
  return { t, ctx }
}

/** Fire the one pending timer, wait for the poll to finish; returns its delay. */
async function fire(ctx) {
  const open = ctx.timers.filter(x => !x.cleared && !x.fired)
  assert.equal(open.length, 1, `one pending timer expected, got ${open.length}`)
  open[0].fired = true
  await open[0].fn()
  await settle()
  return open[0].ms
}

const pending = ctx => ctx.timers.filter(x => !x.cleared && !x.fired).length

test('two failed polls, then running, then done: the job ends as done', async () => {
  const lost = new Error('fetch failed')
  const { t, ctx } = await setup([lost, lost,
    envOf({ job_id: 'job-b1', kind: 'build', state: 'running', progress: null, started: 1 }),
    envOf({ job_id: 'job-b1', kind: 'build', state: 'done', progress: 1, started: 1, result: { ok: true, action: 'board.build', result: {} } })])
  t.watchJob('job-b1', 'build')
  assert.equal(await fire(ctx), 250, 'first poll right away')
  assert.equal(await fire(ctx), 2000, 'retry after 2 s')
  assert.equal(t.$jobs.get().build.state, 'running', 'still running while the contact is down')
  assert.equal(await fire(ctx), 2000, 'second retry after 2 s')
  assert.equal(t.$jobs.get().build.state, 'running')
  assert.equal(await fire(ctx), 700, 'back to the normal poll interval')
  assert.equal(t.$jobs.get().build.state, 'done')
  assert.equal(pending(ctx), 0, 'no timer after done')
  assert.equal(t.$jobNote.get().build, null, 'no note on success')
  assert.equal(ctx.jobCalls, 4)
})

test('31 failed polls in a row: the note says the contact is lost, no further timer', async () => {
  const script = Array.from({ length: 31 }, () => new Error('fetch failed'))
  const { t, ctx } = await setup(script)
  t.watchJob('job-b1', 'build')
  assert.equal(await fire(ctx), 250)
  for (let i = 0; i < 30; i++) {
    assert.equal(t.$jobNote.get().build, null, `no note yet after ${i + 1} failures`)
    assert.equal(await fire(ctx), 2000)
  }
  assert.equal(ctx.jobCalls, 31)
  assert.equal(pending(ctx), 0, 'the watch stopped')
  assert.equal(t.$jobNote.get().build?.message, 'Lost contact with the job. Reload the Bench.')
  assert.equal(t.$jobNote.get().build?.hint, null)
  assert.equal(t.JOB_WATCH.build, null)
})

test('a backend error answer counts like a dropped connection; job_not_found ends at once', async () => {
  const busy = { ok: false, action: 'job.get', summary: 'busy', result: null, checks: [], warnings: [], assumptions: [], sources: [], simulated: false,
    error: { code: 'backend_error', message: 'Backend error 503' } }
  const gone = { ...busy, summary: 'gone', error: { code: 'job_not_found', message: 'no job' } }
  const { t, ctx } = await setup([busy, gone])
  t.watchJob('job-b1', 'build')
  await fire(ctx)
  assert.equal(await fire(ctx), 2000)
  assert.equal(pending(ctx), 0, 'job_not_found: no retry')
  assert.equal(t.$jobs.get().build, null)
  assert.equal(t.$jobNote.get().build?.code, 'job_not_found')
})
