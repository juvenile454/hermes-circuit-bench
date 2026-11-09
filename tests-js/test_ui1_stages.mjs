// Directive attributes, stations and rail status.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseDirectiveAttrs, DIRECTIVE_VIEWS } from '../desktop-src/lib/directive.js'
import { STATIONS, VIEW_TO_STATION, stageStatus, hudFigures, solderProgress, panicKey, isStation, stationInfo } from '../desktop-src/lib/stages.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const project = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project

test('directive: valid attributes map view → station', () => {
  assert.deepEqual(parseDirectiveAttrs({ project: 'laser-trigger', view: 'pins' }), { project: 'laser-trigger', view: 'pins', station: 'plan', title: 'PIN MAP' })
  assert.deepEqual(parseDirectiveAttrs({ project: 'laser-trigger', view: 'crash' }).station, 'debug')
  assert.equal(parseDirectiveAttrs({ project: 'laser-trigger' }).view, 'pins')
  assert.equal(parseDirectiveAttrs({ project: 'a'.repeat(48), view: 'calc', extra: 'ignored' }).station, 'calc')
})

test('directive: garbage renders nothing', () => {
  for (const attrs of [null, undefined, 'x', [], {}, { project: '' }, { project: 'Laser' }, { project: 'a'.repeat(49) },
    { project: '../etc', view: 'pins' }, { project: 'laser-trigger', view: 'PINS' }, { project: 'laser-trigger', view: 'shell' },
    { project: 'laser-trigger', view: 5 }, { project: 7, view: 'pins' }, { project: 'laser trigger' }, { project: 'x<script>' }]) {
    assert.equal(parseDirectiveAttrs(attrs), null, JSON.stringify(attrs))
  }
})

test('stations and views follow the station contract', () => {
  assert.deepEqual(STATIONS.map(s => s.id), ['plan', 'calc', 'wire', 'solder', 'flash', 'debug'])
  assert.deepEqual(STATIONS.map(s => s.n), ['01', '02', '03', '04', '05', '06'])
  assert.deepEqual(Object.keys(VIEW_TO_STATION), DIRECTIVE_VIEWS)
  for (const v of DIRECTIVE_VIEWS) assert.equal(parseDirectiveAttrs({ project: 'p', view: v }).station, VIEW_TO_STATION[v])
  assert.ok(isStation('debug'))
  assert.ok(!isStation('shell'))
  assert.equal(stationInfo('nope').id, 'plan')
})

test('rail status from the demo project (fixture: real sim chain after detect, build, flash, panic)', () => {
  const s = stageStatus(project, { ok: 4, caution: 0, blocked: 1, unchecked: 0 }, null)
  assert.deepEqual(s.plan, { text: '1✕', tone: 'bad', alert: false })
  assert.equal(s.calc.text, '[✓]')
  assert.equal(s.wire.text, '[✓]')
  const sp = solderProgress(project)
  assert.deepEqual(s.solder, sp.done ? { text: `${Math.round((sp.done / sp.total) * 100)}%`, tone: 'active', alert: false } : { text: '0%', tone: 'faint', alert: false })
  const twoDone = { ...project, solder: { ...project.solder, done: project.solder.steps.slice(0, 2).map(x => x.id) } }
  assert.deepEqual(stageStatus(twoDone).solder, { text: '40%', tone: 'active', alert: false })
  assert.equal(s.flash.text, '[✓]')
  assert.deepEqual(s.debug, { text: 'PANIC', tone: 'bad', alert: true })
  assert.equal(stageStatus(project, null, panicKey(project)).debug.alert, false) // seen: stops blinking
  assert.equal(stageStatus(project, { ok: 0, caution: 2, blocked: 0, unchecked: 0 }).plan.text, '2!')
  assert.equal(stageStatus(null).plan.text, '')
  const fresh = { ...project, calcs: [], circuits: [], solder: { steps: [], done: [] }, firmware: {}, debug: {} }
  const f = stageStatus(fresh, { ok: 0, caution: 0, blocked: 0, unchecked: 0 })
  assert.deepEqual(Object.values(f).map(x => x.text), ['[ ]', '[ ]', '[ ]', '[ ]', '[ ]', '[ ]'])
})

test('HUD figures and solder progress', () => {
  assert.deepEqual(solderProgress(project), { done: project.solder.done.length, total: 5 })
  assert.deepEqual(solderProgress({ solder: { steps: [{ id: 'a' }], done: ['a', 'gone'] } }), { done: 1, total: 1 })
  const f = hudFigures(project, { ok: 5, caution: 0, blocked: 0, unchecked: 0 })
  const lb = project.firmware.last_build
  assert.deepEqual(f.build, { tone: 'ok', text: 'OK', ram: lb.ram_pct, flash: lb.flash_pct })
  assert.equal(hudFigures({}).build.text, '—')
  assert.equal(panicKey(project), `StoreProhibited@${project.debug.last_panic.at}`)
  assert.equal(panicKey({}), null)
})
