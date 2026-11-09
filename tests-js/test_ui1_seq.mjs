// Serial line buffer (desktop-src/lib/seq.js): seq merge, duplicates, gaps, epoch reset.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { emptyBuffer, mergeLines, gapsOf, lineClass, bufferText } from '../desktop-src/lib/seq.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const tail = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'serial.lines.json'), 'utf8')).result
const line = (seq, text = `l${seq}`) => ({ t: 'line', seq, ts: '00:00:00.000', text })

test('in-order lines are appended, duplicates dropped (reconnect resends ≤ 200 lines)', () => {
  let b = mergeLines(emptyBuffer(), [line(1), line(2), line(3)])
  b = mergeLines(b, [line(2), line(3), line(4)])
  assert.deepEqual(b.lines.map(l => l.seq), [1, 2, 3, 4])
  assert.equal(b.dropped, 2)
  assert.equal(b.lastSeq, 4)
})

test('a jump in seq leaves a gap marker', () => {
  const b = mergeLines(emptyBuffer(), [line(10), line(11), line(15)])
  assert.deepEqual(gapsOf(b), [{ from: 12, to: 14 }])
  assert.deepEqual(b.lines.map(l => l.k), ['line', 'line', 'gap', 'line'])
  assert.match(bufferText(b), /3 line\(s\) missed \(seq 12–14\)/)
})

test('first batch may start anywhere (tail after reconnect) without a gap', () => {
  const b = mergeLines(emptyBuffer(), [line(813), line(814)])
  assert.deepEqual(gapsOf(b), [])
})

test('a new epoch resets duplicate detection (backend restart: seq starts at 1 again)', () => {
  let b = mergeLines(emptyBuffer(), [{ t: 'state', port: 'sim://x', state: 'open', epoch: 'a' }, line(1), line(2), line(3)])
  b = mergeLines(b, [{ t: 'state', port: 'sim://x', state: 'open', epoch: 'b' }, line(1), line(2)])
  assert.deepEqual(b.lines.map(l => l.k), ['line', 'line', 'line', 'epoch', 'line', 'line'])
  assert.equal(b.epoch, 'b')
  assert.equal(b.lastSeq, 2)
  // the same epoch again changes nothing; polling passes the epoch as an option
  const c = mergeLines(b, [line(2), line(3)], { epoch: 'b' })
  assert.deepEqual(c.lines.slice(-2).map(l => l.seq), [2, 3])
})

test('panic message is kept, state recorded, junk ignored, limit enforced', () => {
  let b = mergeLines(emptyBuffer(), [{ t: 'state', port: 'p', state: 'open' }, ...tail.lines, tail.panic, null, { t: 'line', seq: 0 }, 'x'])
  assert.equal(b.panic.log_ref, tail.panic.log_ref)
  assert.equal(b.panic.seq, tail.panic.seq)
  assert.equal(b.state.state, 'open')
  assert.equal(b.lines.length, tail.lines.length)
  b = mergeLines(b, tail.lines)
  assert.equal(b.lines.length, tail.lines.length) // second poll of the same tail: nothing new
  const many = Array.from({ length: 50 }, (_, i) => line(i + 1))
  assert.equal(mergeLines(emptyBuffer(), many, { limit: 20 }).lines.length, 20)
  const input = emptyBuffer()
  mergeLines(input, [line(1)])
  assert.equal(input.lines.length, 0) // pure: input untouched
})

test('line highlighting classes', () => {
  assert.equal(lineClass("Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled."), 'panic')
  assert.equal(lineClass('Backtrace: 0x42001d67:0x3fcebd70'), 'bt')
  assert.equal(lineClass('EXCCAUSE: 0x0000001d  EXCVADDR: 0x0000000c'), 'bt')
  assert.equal(lineClass('ESP-ROM:esp32s3-20210327'), 'rom')
  assert.equal(lineClass('[laser-trigger] boot, laser off'), 'hl')
  assert.equal(lineClass('Rebooting...'), '')
})
