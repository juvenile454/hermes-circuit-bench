// REST error mapping (desktop-src/lib/api.js) and the development fixture backend (lib/fixtures.js).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseRestError, isEnvelope, errorEnvelope, asEnvelope, query, isOffline } from '../desktop-src/lib/api.js'
import { createFixtureBackend, mapKey } from '../desktop-src/lib/fixtures.js'
import { elfCheck, shortFunction } from '../desktop-src/lib/crash.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIR = join(ROOT, 'desktop-src', 'fixtures')
const FIXTURES = Object.fromEntries(readdirSync(DIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(DIR, f), 'utf8'))]))
const MAPS = JSON.parse(readFileSync(join(ROOT, 'tests-js', 'fixtures', 'ui1-pins-maps.json'), 'utf8'))
delete MAPS._generated_by
const backend = () => createFixtureBackend({ ...FIXTURES, ...MAPS }, { delayMs: 0 })

test('ctx.rest errors become envelopes, never throws', () => {
  const conflict = errorEnvelope('project.update', 'project_conflict', 'rev 12, not 11', 'reload', null)
  const e409 = Object.assign(new Error(`409: ${JSON.stringify({ ...conflict, http: undefined })}`), { statusCode: 409 })
  const r409 = parseRestError(e409, 'project.update')
  assert.equal(r409.error.code, 'project_conflict')
  assert.equal(r409.http, 409)
  const r404 = parseRestError(new Error('404: {"detail":"Not Found"}'), 'health')
  assert.deepEqual([r404.ok, r404.error.code, r404.http], [false, 'backend_unavailable', 404])
  assert.ok(isOffline(r404))
  assert.equal(parseRestError(new Error('401: {"detail":"Unauthorized"}')).error.code, 'unauthorized')
  assert.match(parseRestError(new Error('500: boom')).error.message, /Backend error 500: boom/)
  assert.equal(parseRestError(new Error('socket hang up')).error.code, 'network_error')
  assert.equal(parseRestError(new Error('Hermes desktop bridge unavailable')).error.code, 'network_error')
  assert.equal(parseRestError('weird').error.code, 'network_error')
  assert.ok(isOffline(parseRestError(new Error('ECONNREFUSED'))))
  assert.ok(!isOffline(r409))
  for (const env of [r409, r404]) assert.ok(isEnvelope(env))
  assert.equal(asEnvelope({ hello: 1 }, 'x').error.code, 'bad_response')
  assert.equal(asEnvelope(FIXTURES.health, 'x'), FIXTURES.health)
})

test('query strings', () => {
  assert.equal(query({ port: 'sim://esp32s3-n16r8', after: 0, x: null, y: undefined, z: '' }), '?port=sim%3A%2F%2Fesp32s3-n16r8&after=0')
  assert.equal(query({}), '')
  assert.equal(query({ wifi: true }), '?wifi=true')
})

test('fixture backend: project read, assign (rev +1, verdict from the map), conflict, unassign', async () => {
  const b = backend()
  const got = await b.handle('GET', '/projects/laser-trigger')
  const rev = FIXTURES['project.laser-trigger'].result.project.rev
  assert.equal(got.result.project.rev, rev)
  const env = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: rev, ops: [{ op: 'assign', role: 'BUTTON', mode: 'in_pullup', pin: 35 }] })
  assert.equal(env.ok, true)
  assert.equal(env.result.rev, rev + 1)
  assert.deepEqual(env.result.changed, ['assignments'])
  const button = env.result.project.assignments.find(a => a.role === 'BUTTON')
  assert.deepEqual([button.pin, button.verdict, button.updated_by], [35, 'blocked', 'ui'])
  const stale = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: rev, ops: [{ op: 'unassign', role: 'BUTTON' }] })
  assert.deepEqual([stale.ok, stale.error.code, stale.http, stale.result.rev], [false, 'project_conflict', 409, rev + 1])
  const un = await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: rev + 1, ops: [{ op: 'unassign', role: 'BUTTON' }], by: 'agent' })
  assert.equal(un.result.project.assignments.some(a => a.role === 'BUTTON'), false)
  assert.equal((await b.handle('GET', '/projects/nope')).error.code, 'project_not_found')
  assert.equal((await b.handle('PATCH', '/projects/laser-trigger', { expected_rev: rev + 2, ops: [{ op: 'explode' }] })).error.code, 'invalid_args')
})

test('fixture backend: pins.check returns the real fixture for its own request, composes otherwise', async () => {
  const b = backend()
  const fx = FIXTURES['pins.check'].result
  const exact = await b.handle('POST', '/pins/check', { chip: 'esp32s3', variant: 'n16r8', wifi: true, devkit: 'esp32-s3-devkitc-1',
    assignments: fx.pins.map(p => ({ role: p.role, mode: p.mode, pin: p.pin })) })
  assert.deepEqual(exact, FIXTURES['pins.check'])
  const composed = await b.handle('POST', '/pins/check', { chip: 'esp32s3', variant: 'n8', wifi: true, devkit: 'esp32-s3-devkitc-1',
    assignments: [{ role: 'BUTTON', mode: 'in_pullup', pin: 35 }] })
  assert.equal(composed.result.pins[0].verdict, 'ok') // N8 has no octal PSRAM
  assert.equal(composed.assumptions[0].value, 'composed')
  const missing = await b.handle('POST', '/pins/check', { chip: 'esp32', assignments: [{ role: 'A', mode: 'out', pin: 4 }] })
  assert.equal(missing.error.code, 'fixture_missing')
  assert.ok(MAPS[mapKey('esp32s3', 'n16r8', true)])
})

test('fixture backend: suggest, info, ports, serial tail, jobs, unknown routes', async () => {
  const b = backend()
  const sug = await b.handle('POST', '/pins/suggest', { chip: 'esp32s3', variant: 'n16r8', wifi: true, requests: [{ role: 'BUTTON', mode: 'in_pullup', requested: 35 }], taken: [1, 8, 9, 14] })
  assert.deepEqual(sug.result.requests[0].suggestions.map(s => s.gpio), [2, 4, 5])
  const sug2 = await b.handle('POST', '/pins/suggest', { chip: 'esp32s3', variant: 'n16r8', wifi: true, requests: [{ role: 'LED', mode: 'out', requested: 3 }], taken: [1, 2, 4] })
  assert.deepEqual(sug2.result.requests[0].suggestions.map(s => s.gpio), [5, 6, 7])
  assert.equal((await b.handle('GET', '/pins/info?chip=esp32s3&pin=35&variant=n16r8')).result.gpio, 35)
  const info4 = await b.handle('GET', '/pins/info?chip=esp32s3&pin=4&variant=n16r8')
  assert.equal(info4.result.header, 'J1-4')
  assert.equal((await b.handle('GET', '/ports')).result.ports.length, 2)
  const all = FIXTURES['serial.lines'].result.lines.map(l => l.seq)
  const after = all[all.length - 4]
  const t = await b.handle('GET', `/serial/tail?port=sim%3A%2F%2Fesp32s3-n16r8&after=${after}`)
  assert.deepEqual(t.result.lines.map(l => l.seq), all.filter(s => s > after))
  assert.equal(t.result.epoch, FIXTURES['serial.lines'].result.epoch)
  assert.equal((await b.handle('GET', '/serial/tail?port=%2Fdev%2FttyACM0&after=0')).result.state, 'closed')
  const jobId = FIXTURES['job.build.done'].result.job_id
  assert.equal((await b.handle('GET', `/jobs/${jobId}`)).result.state, 'done') // done wins over running for the same id
  assert.equal((await b.handle('GET', '/jobs/j-9999-000000')).ok, false)
  assert.equal((await b.handle('GET', '/boards/esp32-s3-devkitc-1')).result.id, 'esp32-s3-devkitc-1')
  assert.equal((await b.handle('DELETE', '/boards/esp32-s3-devkitc-1')).error.code, 'fixture_missing')
  const demo = await b.handle('POST', '/projects/demo')
  assert.deepEqual([demo.ok, demo.action, demo.result.id, demo.simulated], [true, 'sim.demo', 'laser-trigger', true]) // short form (sim.demo.json)
})

test('crash decode: ELF check is shown as skipped, not passed, when there is no ELF (sim build)', () => {
  const env = FIXTURES['crash.decode']
  assert.equal(env.result.elf_match, null)
  assert.deepEqual([elfCheck(env).status, elfCheck(env).text], ['skipped', 'elf check skipped'])
  assert.equal(elfCheck({ ok: true, result: { elf_match: true }, checks: [] }).text, 'elf match')
  assert.equal(elfCheck({ ok: true, result: { elf_match: false }, checks: [] }).tone, 'bad')
  assert.equal(elfCheck({ ok: true, result: { elf_match: null }, checks: [{ id: 'crash.elf_match', status: 'passed' }] }).status, 'passed')
  assert.equal(elfCheck(null).status, 'skipped')
})

test('frame signatures are compacted for the narrow panic card (full text stays in the tooltip)', () => {
  const frames = FIXTURES['crash.decode'].result.frames
  assert.equal(shortFunction(frames[0].function), 'write_sensor_buffer(…)')
  assert.equal(shortFunction('sample_sensor()'), 'sample_sensor()')
  assert.equal(shortFunction('loopTask(void*)'), 'loopTask(…)')
  assert.equal(shortFunction('Foo::bar(int) const'), 'Foo::bar(…) const')
  assert.equal(shortFunction('??'), '??')
  assert.equal(shortFunction(''), '??')
})
