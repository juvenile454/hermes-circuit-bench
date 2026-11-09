// Panic card data from the real crash.decode fixture, freshness of the stored panic, Fix-with-Hermes input.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { panicCardData, projectPanicCurrent, splitTopFrame, elfCheck } from '../desktop-src/lib/crash.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const decode = fx('crash.decode')
const project = fx('project.laser-trigger').result.project
const serialPanic = fx('serial.lines').result.panic

test('card data from crash.decode.json: reason, core, frames (#0 = write_sensor_buffer main.cpp:44), interpretation', () => {
  const d = panicCardData(decode, project.debug.last_panic, serialPanic)
  assert.equal(d.title, 'StoreProhibited · core 1')
  assert.equal(d.decoded, true)
  assert.equal(d.simulated, true)
  assert.equal(d.frames.length, decode.result.frames.length)
  assert.deepEqual([d.top.short, d.top.file, d.top.line], ['write_sensor_buffer(…)', 'src/main.cpp', 44])
  assert.deepEqual(d.frames.slice(0, 3).map(f => `${f.base}:${f.line}`), ['main.cpp:44', 'main.cpp:49', 'main.cpp:74'])
  assert.deepEqual(d.registers.map(r => r.k), ['PC', 'EXCCAUSE', 'EXCVADDR'])
  assert.equal(d.registers.find(r => r.k === 'EXCVADDR').v, '0x0000000c')
  assert.equal(d.interpretation.at(-1).code, 'null_pointer')
  assert.equal(d.elf.status, 'skipped') // sim build: no ELF, never "passed"
  assert.equal(d.logRef, serialPanic.log_ref)
})

test('without a decode: stored panic or the serial summary still give a card', () => {
  const fromProject = panicCardData(null, project.debug.last_panic, null)
  assert.equal(fromProject.title, 'StoreProhibited · core 1')
  assert.equal(fromProject.decoded, false)
  assert.equal(fromProject.top.short, 'write_sensor_buffer(…)')
  assert.equal(fromProject.top.line, 44)
  const fromSerial = panicCardData(null, null, serialPanic)
  assert.equal(fromSerial.title, 'StoreProhibited · core 1')
  assert.equal(fromSerial.frames.length, 0)
  assert.equal(panicCardData(null, null, null), null)
  assert.equal(panicCardData({ ok: false, error: { code: 'decode_failed' } }, null, null), null)
  assert.deepEqual(splitTopFrame('setup() (src/main.cpp:74)'), { fn: 'setup()', file: 'src/main.cpp', line: 74 })
  assert.deepEqual(splitTopFrame('loopTask'), { fn: 'loopTask', file: null, line: null })
})

test('stored panic is current until a successful flash after it', () => {
  assert.equal(projectPanicCurrent(project), true) // fixture: panic and flash at the same second
  const p = structuredClone(project)
  p.firmware.last_flash.at = '2026-11-09T20:16:00Z'
  assert.equal(projectPanicCurrent(p), false)
  p.debug.last_panic.at = '2026-11-09T20:17:00Z'
  assert.equal(projectPanicCurrent(p), true)
  p.firmware.last_flash = { ...p.firmware.last_flash, ok: false, at: '2026-11-09T20:18:00Z' }
  assert.equal(projectPanicCurrent(p), true) // a failed flash does not replace the firmware
  assert.equal(projectPanicCurrent({ debug: {} }), false)
})

test('elf check: a mismatch is red, a missing ELF is "skipped", never "passed"', () => {
  assert.equal(elfCheck({ checks: [{ id: 'crash.elf_match', status: 'failed' }], result: {} }).tone, 'bad')
  assert.equal(elfCheck({ checks: [], result: { elf_match: null } }).status, 'skipped')
  assert.equal(elfCheck({ checks: [{ id: 'crash.elf_match', status: 'passed', detail: 'ok' }], result: {} }).symbol, '✓')
})
