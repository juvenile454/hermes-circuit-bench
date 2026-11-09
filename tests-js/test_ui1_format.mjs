// Units and display formatting (desktop-src/lib/format.js).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatSI, formatQty, formatPct, formatFraction, formatDuration, formatClock, shortHash, cellBar, nbspUnits, clip } from '../desktop-src/lib/format.js'

test('formatSI picks the SI prefix and keeps 3 significant digits', () => {
  assert.equal(formatSI(0.00253, 'A'), '2.53 mA')
  assert.equal(formatSI(4700, 'Ω'), '4.7 kΩ')
  assert.equal(formatSI(100000, 'Ω'), '100 kΩ')
  assert.equal(formatSI(1e-5, 'F'), '10 µF')
  assert.equal(formatSI(3.3, 'V'), '3.3 V')
  assert.equal(formatSI(0, 'A'), '0 A')
  assert.equal(formatSI(-0.013, 'A'), '-13 mA')
  assert.equal(formatSI(999.9, 'Ω'), '1 kΩ')
  assert.equal(formatSI(NaN, 'V'), '—')
  assert.equal(formatSI(1.5e6, 'Hz'), '1.5 MHz')
})

test('formatQty prefers the contract display text', () => {
  assert.equal(formatQty({ value: 0.00253, unit: 'A', display: '2.53 mA' }), '2.53 mA')
  assert.equal(formatQty({ value: 0.0026, unit: 'A' }), '2.6 mA')
  assert.equal(formatQty(null), '—')
  assert.equal(formatQty(5.14), '5.14')
})

test('percent, fraction, duration', () => {
  assert.equal(formatPct(5.6), '5.6 %')
  assert.equal(formatPct(7.94, 1), '7.9 %')
  assert.equal(formatPct(undefined), '—')
  assert.equal(formatFraction(0.42), '42 %')
  assert.equal(formatFraction(1.7), '100 %')
  assert.equal(formatDuration(3.91), '3.9 s')
  assert.equal(formatDuration(42.4), '42 s')
  assert.equal(formatDuration(125), '2:05 min')
  assert.equal(formatDuration(-1), '—')
})

test('clock, hash, bar, clip', () => {
  assert.equal(formatClock('2026-11-06T21:41:07Z', { utc: true }), '21:41:07')
  assert.equal(formatClock('nonsense'), '—')
  assert.equal(shortHash('3f9a5c0d21e8b47a6c13', 8), '3f9a5c0d…')
  assert.equal(shortHash(''), '—')
  assert.equal(cellBar(2, 5, 10), '▰▰▱▱▱')
  assert.equal(cellBar(7, 11, 8), '▰▰▰▰▰▱▱▱')
  assert.equal(cellBar(0, 0), '')
  assert.equal(clip('abcdef', 4), 'abc…')
})

test('nbspUnits keeps a value and its unit on one line', () => {
  const s = nbspUnits('R1 (1 kΩ), C1 (10 µF) at 3.3 V, 42 % and 5 cm, 2 items')
  assert.equal(s, 'R1 (1\u00a0kΩ), C1 (10\u00a0µF) at 3.3\u00a0V, 42\u00a0% and 5 cm, 2 items')
})
