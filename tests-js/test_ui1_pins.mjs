// Pin presentation (desktop-src/lib/pins.js): state → class/symbol/text, merge, map, chips vs data.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CHIPS, MODES, verdictMeta, pinView, mergeAssignments, countVerdicts, mapAssignments, headerGpios, mapByGpio, validateAssign,
  splitHeader, ruleTag, mainReason, suggestionChips, chipInfo, variantInfo, modeLabel, modeShort, devkitInfo
} from '../desktop-src/lib/pins.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const layout = fx('board.esp32-s3-devkitc-1').result
const project = fx('project.laser-trigger').result.project
const check = fx('pins.check').result
const maps = JSON.parse(readFileSync(join(ROOT, 'tests-js', 'fixtures', 'ui1-pins-maps.json'), 'utf8'))
const map = maps['pins.map/esp32s3/n16r8/wifi-on'].result

test('verdictMeta: never colour only — symbol and word for every state', () => {
  assert.deepEqual(verdictMeta('ok'), { tone: 'ok', symbol: '✓', text: 'ok', stamp: 'OK' })
  assert.equal(verdictMeta('caution').symbol, '!')
  assert.equal(verdictMeta('blocked').stamp, 'BLOCKED')
  assert.equal(verdictMeta('blocked').tone, 'bad')
  assert.equal(verdictMeta(undefined).text, 'not checked')
  assert.equal(verdictMeta('weird').tone, 'none')
})

test('pinView: power, ground, reset, free, caution, blocked, assigned, unchecked', () => {
  const byGpio = mapByGpio(map)
  const hp = (side, n) => layout[side].find(p => p.n === n)
  assert.equal(pinView(hp('left', 1), null, null).state, 'power')
  assert.equal(pinView(hp('left', 22), null, null).name, 'GND')
  assert.equal(pinView(hp('left', 3), null, null).state, 'reset')
  const io4 = pinView(hp('left', 4), null, byGpio.get(4), layout.onboard)
  assert.equal(io4.state, 'free')
  assert.equal(io4.name, 'IO4')
  const io3 = pinView(hp('left', 13), null, byGpio.get(3), layout.onboard)
  assert.deepEqual([io3.state, io3.tag, io3.symbol], ['warn', 'STRAP', '!'])
  const tx = pinView(hp('right', 2), null, byGpio.get(43), layout.onboard)
  assert.deepEqual([tx.state, tx.name, tx.tag], ['warn', 'TX', 'UART0 · 43'])
  const io35 = pinView(hp('right', 13), null, byGpio.get(35), layout.onboard)
  assert.deepEqual([io35.state, io35.tag, io35.symbol], ['bad', 'PSRAM', '✕'])
  const io38 = pinView(hp('right', 10), null, byGpio.get(38), layout.onboard)
  assert.equal(io38.tag, 'RGB LED')
  const used = pinView(hp('left', 20), { role: 'LASER', mode: 'out', verdict: 'ok' }, byGpio.get(14))
  assert.deepEqual([used.state, used.tag, used.tone], ['used', 'LASER', 'active'])
  const usedBad = pinView(hp('right', 13), { role: 'BUTTON', mode: 'in_pullup', verdict: 'blocked' }, byGpio.get(35))
  assert.deepEqual([usedBad.state, usedBad.tag], ['used-bad', 'BUTTON ✕'])
  assert.equal(pinView(hp('left', 4), null, null).state, 'unchecked')
  assert.match(pinView(hp('left', 4), null, null).title, /not checked/)
})

test('mergeAssignments uses a check entry only when role, pin and mode match', () => {
  const rows = mergeAssignments(project.assignments, check.pins)
  const button = rows.find(r => r.role === 'BUTTON')
  // project: BUTTON on GPIO2 (ok, stored); fixture check: BUTTON on GPIO35 → foreign, ignored
  assert.equal(button.pin, 2)
  assert.equal(button.verdict, 'ok')
  assert.equal(button.checked, false)
  const laser = rows.find(r => r.role === 'LASER')
  assert.equal(laser.checked, true)
  assert.equal(laser.header, 'J1-20')
  const moved = mergeAssignments(project.assignments.map(a => (a.role === 'BUTTON' ? { ...a, pin: 35 } : a)), check.pins)
  const b2 = moved.find(r => r.role === 'BUTTON')
  assert.deepEqual([b2.verdict, b2.checked, b2.alternatives], ['blocked', true, [2, 4, 5]])
  assert.deepEqual(countVerdicts(moved), { ok: 4, caution: 0, blocked: 1, unchecked: 0 })
  assert.deepEqual(mergeAssignments(undefined, null), [])
})

test('board map: every header GPIO once, mode "in", 36 on the S3-DevKitC-1', () => {
  const gp = headerGpios(layout)
  assert.equal(gp.length, 36)
  assert.equal(new Set(gp).size, 36)
  const a = mapAssignments(layout)
  assert.ok(a.every(x => x.mode === 'in' && /^IO\d+$/.test(x.role)))
  assert.equal(map.pins.length, 36)
  assert.equal(mapByGpio(map).get(35).verdict, 'blocked')
})

test('CHIPS mirror circuit_bench/data/pins and data/boards', () => {
  const pinsDir = join(ROOT, 'circuit_bench', 'data', 'pins')
  const chips = readdirSync(pinsDir).filter(f => f.endsWith('.json')).map(f => JSON.parse(readFileSync(join(pinsDir, f), 'utf8')))
  assert.deepEqual(CHIPS.map(c => c.id).sort(), chips.map(c => c.chip).sort())
  for (const data of chips) {
    const ui = chipInfo(data.chip)
    assert.equal(ui.label, data.title)
    assert.deepEqual(ui.variants.map(v => [v.id, v.label, v.psram, v.flash_mb]), data.variants.map(v => [v.id, v.label, v.psram ?? null, v.flash_mb]))
  }
  const boardsDir = join(ROOT, 'circuit_bench', 'data', 'boards')
  for (const f of readdirSync(boardsDir).filter(x => x.endsWith('.json'))) {
    const b = JSON.parse(readFileSync(join(boardsDir, f), 'utf8'))
    // every layout is offered for its chip; the chip's default DevKit is one of its layouts (the ESP32 has
    // the DevKitC V4 and the WT32-ETH01, the default stays the DevKitC V4)
    assert.equal(devkitInfo(b.id)?.chip, b.chip, `DevKit ${b.id}`)
    assert.equal(devkitInfo(chipInfo(b.chip).devkit)?.chip, b.chip, `default DevKit of ${b.chip}`)
  }
  assert.equal(chipInfo('esp32').devkit, 'esp32-devkitc-v4')
  assert.equal(variantInfo('esp32s3', 'n16r8').psram, 'octal')
})

test('modes, roles and the assign form', () => {
  const contract = ['out', 'in', 'in_pullup', 'in_pulldown', 'adc', 'pwm', 'i2c_sda', 'i2c_scl', 'spi_sck', 'spi_mosi', 'spi_miso', 'spi_cs', 'uart_tx', 'uart_rx', 'touch']
  assert.deepEqual(MODES.map(m => m[0]), contract) // the assignment modes of the contract
  assert.equal(modeLabel('in_pullup'), 'in · pull-up')
  // the assignments table shows one word of ≤ 8 characters (64 px column) so nothing is cut at 1440 × 900
  for (const [m] of MODES) assert.ok([...modeShort(m)].length <= 8, m)
  assert.equal(modeShort('i2c_sda'), 'i²c sda')
  assert.equal(modeShort('in_pullup'), 'pullup')
  assert.deepEqual(validateAssign({ role: 'BUTTON', mode: 'in_pullup', pin: 2, net: 'BTN' }), [])
  assert.deepEqual(validateAssign({ role: 'button', mode: 'in_pullup', pin: 2 }).map(e => e.field), ['role'])
  assert.deepEqual(validateAssign({ role: 'X', mode: 'nope', pin: 99, net: 'a b' }).map(e => e.field), ['mode', 'pin', 'net'])
  assert.equal(validateAssign({ role: 'A'.repeat(25), mode: 'out', pin: 1 }).length, 1)
})

test('header, rule tags, reasons, suggestions', () => {
  assert.deepEqual(splitHeader('J3-13'), { header: 'J3', n: 13 })
  assert.equal(splitHeader('nope'), null)
  assert.equal(ruleTag('s3.octal_psram'), 'PSRAM')
  assert.equal(ruleTag('esp32.input_only'), 'IN ONLY')
  assert.equal(ruleTag('x.something_new'), 'SOMETHIN')
  assert.equal(mainReason({ reasons: [{ severity: 'info', rule_id: 'a' }, { severity: 'blocked', rule_id: 'b' }] }).rule_id, 'b')
  assert.equal(mainReason({}), null)
  assert.deepEqual(suggestionChips(fx('pins.suggest').result, 'BUTTON').map(s => s.gpio), [2, 4, 5])
  assert.deepEqual(suggestionChips(fx('pins.suggest').result, 'NOPE'), [])
})
