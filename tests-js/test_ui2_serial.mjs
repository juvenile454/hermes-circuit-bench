// Live serial client (desktop-src/lib/serial.js): duplicates over seq, fallback to polling when the socket
// stays silent for 3 s (also a 1008 refusal: ctx.socket then never delivers), back to the stream, epoch reset,
// gap fill after `lagging`, panic freshness.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { emptyBuffer, mergeLines } from '../desktop-src/lib/seq.js'
import { createSerialClient, fillGaps, panicCurrent, lastLineMatching, streamPath, SOCKET_GRACE_MS, POLL_MS } from '../desktop-src/lib/serial.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const TAIL = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'serial.lines.json'), 'utf8')).result
const PORT = 'sim://esp32s3-n16r8'
const seq = { mergeLines, emptyBuffer }
const line = (n, text = `l${n}`) => ({ t: 'line', seq: n, ts: '00:00:00.000', text })

/** Fake clock: timers fire only on advance(). */
function fakeTimers() {
  let now = 0
  let id = 0
  const q = new Map()
  return {
    setTimeout(fn, ms) { const k = ++id; q.set(k, { at: now + ms, fn }); return k },
    clearTimeout(k) { q.delete(k) },
    async advance(ms) {
      const end = now + ms
      for (;;) {
        const next = [...q.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        now = next[1].at
        q.delete(next[0])
        await next[1].fn()
        await new Promise(r => setImmediate(r))
      }
      now = end
    },
    pending: () => q.size
  }
}

function fakeSocket() {
  const s = { path: null, fn: null, disposed: false }
  s.open = (path, fn) => { s.path = path; s.fn = fn; return () => { s.disposed = true } }
  s.send = msg => s.fn(msg)
  return s
}

function tailFrom(lines, extra = {}) {
  const calls = []
  const fn = async (port, after) => {
    calls.push(after)
    const ls = lines().filter(l => l.seq > (after || 0))
    return { ok: true, result: { port, state: 'open', lines: ls, panic: extra.panic?.() ?? null, epoch: extra.epoch?.() ?? 'e1', simulated: true, next_seq: (ls.at(-1)?.seq || 0) + 1 } }
  }
  fn.calls = calls
  return fn
}

test('stream path keeps the port in the query (never token/native_dial)', () => {
  assert.equal(streamPath(PORT), '/serial/stream?port=sim%3A%2F%2Fesp32s3-n16r8')
})

test('socket: state + snapshot + live lines, duplicates over seq dropped (reconnect resends ≤ 200 lines)', async () => {
  const t = fakeTimers()
  const sock = fakeSocket()
  const tail = tailFrom(() => [])
  const ups = []
  const c = createSerialClient({ port: PORT, socket: sock.open, tail, timers: t, seq, onUpdate: u => ups.push(u) })
  c.start()
  assert.equal(c.mode(), 'connecting')
  sock.send({ t: 'state', port: PORT, state: 'open', epoch: 'e1', simulated: true, next_seq: 4 })
  for (const l of [line(1), line(2), line(3)]) sock.send(l)
  // reconnect: the server sends state + the snapshot again
  sock.send({ t: 'state', port: PORT, state: 'open', epoch: 'e1' })
  for (const l of [line(2), line(3), line(4)]) sock.send(l)
  assert.equal(c.mode(), 'socket')
  assert.deepEqual(c.buffer().lines.map(l => l.seq), [1, 2, 3, 4])
  assert.equal(c.buffer().dropped, 2)
  await t.advance(SOCKET_GRACE_MS * 3)
  assert.equal(tail.calls.length, 0, 'no polling while the socket delivers')
  assert.equal(ups.at(-1).simulated, true)
  c.stop()
  assert.ok(sock.disposed)
})

test('silent socket (e.g. 1008, host isolation): polling GET /serial/tail after 3 s, with after=<last seq>', async () => {
  const t = fakeTimers()
  const sock = fakeSocket()
  let lines = TAIL.lines.slice(0, 10)
  const tail = tailFrom(() => lines)
  const c = createSerialClient({ port: PORT, socket: sock.open, tail, timers: t, seq })
  c.start()
  await t.advance(SOCKET_GRACE_MS - 1)
  assert.equal(tail.calls.length, 0)
  await t.advance(1)
  assert.equal(c.mode(), 'poll')
  assert.deepEqual(tail.calls, [0])
  assert.equal(c.buffer().lastSeq, 10)
  lines = TAIL.lines
  await t.advance(POLL_MS)
  assert.deepEqual(tail.calls, [0, 10])
  assert.equal(c.buffer().lines.filter(l => l.k === 'line').length, TAIL.lines.length)
  await t.advance(POLL_MS)
  assert.equal(tail.calls.at(-1), TAIL.lines.at(-1).seq)
  assert.equal(c.buffer().lines.filter(l => l.k === 'line').length, TAIL.lines.length, 'second poll of the same tail adds nothing')
  // the socket comes back: polling stops, its snapshot is deduplicated
  sock.send({ t: 'state', port: PORT, state: 'open', epoch: 'e1' })
  for (const l of TAIL.lines.slice(-5)) sock.send(l)
  assert.equal(c.mode(), 'socket')
  const n = tail.calls.length
  await t.advance(POLL_MS * 5)
  assert.equal(tail.calls.length, n)
  assert.equal(c.buffer().lines.filter(l => l.k === 'line').length, TAIL.lines.length)
  c.stop()
  assert.equal(t.pending(), 0)
})

test('no socket function (OAuth remote): polls at once', async () => {
  const t = fakeTimers()
  const tail = tailFrom(() => [line(1), line(2)])
  const c = createSerialClient({ port: PORT, socket: null, tail, timers: t, seq })
  c.start()
  await t.advance(0)
  assert.equal(c.mode(), 'poll')
  assert.equal(c.buffer().lastSeq, 2)
  c.stop()
})

test('polling across a backend restart: new epoch → read from seq 1 again, dedupe reset', async () => {
  const t = fakeTimers()
  let epoch = 'e1'
  let lines = [line(1), line(2), line(3)]
  const tail = tailFrom(() => lines, { epoch: () => epoch })
  const c = createSerialClient({ port: PORT, socket: null, tail, timers: t, seq })
  c.start()
  await t.advance(0)
  assert.equal(c.buffer().lastSeq, 3)
  epoch = 'e2'
  lines = [line(1, 'new boot'), line(2, 'again')]
  await t.advance(POLL_MS)
  assert.deepEqual(tail.calls.slice(-2), [3, 0])
  const b = c.buffer()
  assert.equal(b.epoch, 'e2')
  assert.deepEqual(b.lines.map(l => l.k), ['line', 'line', 'line', 'epoch', 'line', 'line'])
  assert.equal(b.lines.at(-1).text, 'again')
  c.stop()
})

test('lagging state / gap: the missing range is fetched from the tail and filled in place', async () => {
  const t = fakeTimers()
  const sock = fakeSocket()
  const all = Array.from({ length: 12 }, (_, i) => line(i + 1))
  const tail = tailFrom(() => all)
  const c = createSerialClient({ port: PORT, socket: sock.open, tail, timers: t, seq })
  c.start()
  sock.send({ t: 'state', port: PORT, state: 'open', epoch: 'e1' })
  for (const l of all.slice(0, 4)) sock.send(l)
  sock.send({ t: 'state', port: PORT, state: 'open', epoch: 'e1', detail: 'lagging: 5 messages dropped, reload the tail' })
  for (const l of all.slice(9)) sock.send(l)
  assert.ok(c.buffer().lines.some(l => l.k === 'gap'))
  await t.advance(400)
  assert.deepEqual(tail.calls, [4])
  assert.deepEqual(c.buffer().lines.map(l => l.k === 'line' ? l.seq : 'gap'), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
  c.stop()
})

test('fillGaps keeps unfilled parts of a gap', () => {
  const b = mergeLines(emptyBuffer(), [line(1), line(6)])
  const f = fillGaps(b, [line(3)])
  assert.deepEqual(f.lines.map(l => (l.k === 'gap' ? `g${l.from}-${l.to}` : l.seq)), [1, 'g2-2', 3, 'g4-5', 6])
  assert.equal(fillGaps(b, []), b)
})

test('panic freshness: current in a reboot loop, stale after a boot into new firmware', () => {
  let b = mergeLines(emptyBuffer(), [...TAIL.lines, TAIL.panic])
  assert.equal(panicCurrent(b), true)
  b = mergeLines(b, [line(77, 'ESP-ROM:esp32s3-20210327'), line(78, '[laser-trigger] boot, laser off'), line(79, '[laser-trigger] boot ok')])
  assert.equal(panicCurrent(b), false)
  assert.equal(lastLineMatching(b, /boot ok/).seq, 79)
  // the reboot loop announces the next panic: current again
  b = mergeLines(b, [line(80, "Guru Meditation Error: Core  1 panic'ed (StoreProhibited)"), { t: 'panic', seq: 80, summary: 'StoreProhibited · core 1', log_ref: 'panic-20261109-201501.log' }])
  assert.equal(panicCurrent(b), true)
  assert.equal(panicCurrent(emptyBuffer()), false)
})
