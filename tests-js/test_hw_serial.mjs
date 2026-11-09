// Hardware test findings on a real ESP32-S3 in a reboot loop (~75 serial lines/s, one panic per boot): the Bench froze
// because every line re-rendered it, and every repeated panic was decoded again (after a rebuild against the wrong
// ELF). Pure helpers from desktop-src/lib/serial.js.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { coalescer, panicNeedsDecode, renderWindow, panicCurrent } from '../desktop-src/lib/serial.js'
import { emptyBuffer, mergeLines } from '../desktop-src/lib/seq.js'
import * as SERIAL from '../desktop-src/lib/serial.js'

function fakeTimers() {
  let now = 0
  let id = 0
  const due = new Map()
  return {
    setTimeout(fn, ms) { due.set(++id, [now + ms, fn]); return id },
    clearTimeout(t) { due.delete(t) },
    advance(ms) {
      now += ms
      for (const [k, [at, fn]] of [...due].sort((a, b) => a[1][0] - b[1][0])) if (at <= now) { due.delete(k); fn() }
    },
    count: () => due.size
  }
}

test('coalescer: a burst of 75 updates applies once with the newest value', () => {
  const t = fakeTimers()
  const seen = []
  const c = coalescer(t, 150, v => seen.push(v))
  for (let i = 1; i <= 75; i++) c.push(i)
  assert.equal(t.count(), 1)
  assert.deepEqual(seen, [])
  t.advance(150)
  assert.deepEqual(seen, [75])
  for (let s = 0; s < 1000; s += 13) { c.push(`x${s}`); t.advance(13) } // one second of a steady stream
  assert.ok(seen.length >= 6 && seen.length <= 8, `applies per second: ${seen.length - 1}`)
})

test('coalescer: cancel drops the pending value, flush applies it at once', () => {
  const t = fakeTimers()
  const seen = []
  const c = coalescer(t, 150, v => seen.push(v))
  c.push('a')
  c.cancel()
  t.advance(500)
  assert.deepEqual(seen, [])
  assert.equal(c.pending(), false)
  c.push('b')
  c.flush()
  assert.deepEqual(seen, ['b'])
  assert.equal(t.count(), 0)
})

test('panicNeedsDecode: a reboot loop decodes once per flash', () => {
  const pn = (ref, summary = 'StoreProhibited · core 1') => ({ log_ref: ref, summary })
  const decoded = { status: 'ready', key: 'panic-1.log', summary: 'StoreProhibited · core 1', flashAt: 'F1' }
  assert.equal(panicNeedsDecode({ status: 'idle', key: null }, pn('panic-1.log'), 'F1'), true)
  assert.equal(panicNeedsDecode(decoded, pn('panic-1.log'), 'F1'), false) // the same announcement
  assert.equal(panicNeedsDecode(decoded, pn('panic-2.log'), 'F1'), false) // the next boot, same crash
  assert.equal(panicNeedsDecode({ ...decoded, status: 'loading' }, pn('panic-3.log'), 'F1'), false)
  assert.equal(panicNeedsDecode(decoded, pn('panic-4.log', 'LoadProhibited · core 1'), 'F1'), true) // another crash
  assert.equal(panicNeedsDecode(decoded, pn('panic-5.log'), 'F2'), true) // a new flash
  assert.equal(panicNeedsDecode({ ...decoded, status: 'error' }, pn('panic-6.log'), 'F1'), true) // retry after an error
  assert.equal(panicNeedsDecode(decoded, { log_ref: null }, 'F1'), false)
})

test('renderWindow: the newest rows, extended back to a held panic block', () => {
  const view = Array.from({ length: 2000 }, (_, i) => (i === 300 ? { k: 'panic', seq: 301, lines: [] } : { k: 'line', seq: i + 1 }))
  assert.equal(renderWindow(view, null, 800).length, 800)
  assert.equal(renderWindow(view, null, 800)[0].seq, 1201)
  const held = renderWindow(view, 301, 800)
  assert.equal(held[0].k, 'panic')
  assert.equal(held.length, 1700)
  assert.equal(renderWindow(view, 9999, 800).length, 800) // a hold that is gone: the newest rows
  const small = view.slice(0, 10)
  assert.equal(renderWindow(small, null, 800), small)
  assert.deepEqual(renderWindow(null), [])
})

test('panicCurrent: a real reboot loop keeps the panic, an outside reset ends it (real-board banners)', () => {
  const L = (seq, text) => ({ t: 'line', seq, ts: '15:00:00.000', text })
  let b = mergeLines(emptyBuffer(), [L(1, "Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled."),
    L(2, 'Rebooting...'), { t: 'panic', seq: 1, summary: 'StoreProhibited · core 1', log_ref: 'panic-1.log' }])
  assert.equal(panicCurrent(b), true)
  b = mergeLines(b, [L(3, 'ESP-ROM:esp32s3-20210327')])
  assert.equal(panicCurrent(b), true) // the banner has just begun
  b = mergeLines(b, [L(4, 'Build:Mar 27 2021'), L(5, 'rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)'),
    L(6, 'Saved PC:0x420243b2'), L(7, '[laser-trigger] boot, laser off')])
  assert.equal(panicCurrent(b), true) // the panic's own reboot: the loop goes on
  const flashed = mergeLines(b, [L(8, 'ESP-ROM:esp32s3-20210327'), L(9, 'Build:Mar 27 2021'),
    L(10, 'rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)'), L(11, '[laser-trigger] boot ok')])
  assert.equal(panicCurrent(flashed), false) // esptool reset after a flash
  const power = mergeLines(b, [L(8, 'rst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)')])
  assert.equal(panicCurrent(power), false)
  const wdt = mergeLines(b, [L(8, 'rst:0x7 (TG0WDT_SYS_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)')])
  assert.equal(panicCurrent(wdt), true)
})

test('serialPanicLive: a panic from before the last good flash is old firmware', () => {
  const { serialPanicLive, logRefTime } = SERIAL
  assert.equal(logRefTime('panic-20261106-150209.log'), Date.UTC(2026, 10, 6, 15, 2, 9))
  assert.ok(Number.isNaN(logRefTime('x.log')))
  const buf = mergeLines(emptyBuffer(), [{ t: 'line', seq: 1, ts: '', text: "Guru Meditation Error: Core  1 panic'ed (StoreProhibited)." },
    { t: 'panic', seq: 1, summary: 'StoreProhibited · core 1', log_ref: 'panic-20261106-150209.log' }])
  assert.equal(serialPanicLive(buf, null), true)
  assert.equal(serialPanicLive(buf, { firmware: { last_flash: { ok: true, at: '2026-11-06T15:03:58Z' } } }), false)
  assert.equal(serialPanicLive(buf, { firmware: { last_flash: { ok: true, at: '2026-11-06T15:00:00Z' } } }), true)
  assert.equal(serialPanicLive(buf, { firmware: { last_flash: { ok: false, at: '2026-11-06T15:03:58Z' } } }), true)
})

test('cleanRunAfter: application lines after the flash and no panic count as running', () => {
  const { cleanRunAfter } = SERIAL
  const L = (seq, text) => ({ t: 'line', seq, ts: '', text })
  let b = mergeLines(emptyBuffer(), [L(1, 'old'), L(2, 'ESP-ROM:esp32s3-20210327'), L(3, 'rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)'),
    L(4, 'entry 0x403b61f4'), L(5, '[laser-trigger] vbat 0.11 V, laser off'), L(6, '[laser-trigger] vbat 0.11 V, laser off')])
  assert.equal(cleanRunAfter(b, 1), null) // two app lines are not enough yet
  b = mergeLines(b, [L(7, '[laser-trigger] vbat 0.10 V, laser off')])
  assert.deepEqual(cleanRunAfter(b, 1).n, 3)
  assert.equal(cleanRunAfter(b, 1).last.seq, 7)
  const crashed = mergeLines(b, [L(8, "Guru Meditation Error: Core  1 panic'ed (StoreProhibited).")])
  assert.equal(cleanRunAfter(crashed, 1), null)
  assert.equal(cleanRunAfter(b, null), null)
})

test('real captures (tests/fixtures/real): the reboot loop keeps the panic, the boot after the flash ends it', async () => {
  const { readFileSync } = await import('node:fs')
  const dir = new URL('../tests/fixtures/real/', import.meta.url)
  const toMsgs = (text, from) => text.split('\n').map((t, i) => ({ t: 'line', seq: from + i, ts: '', text: t }))
  const loop = readFileSync(new URL('esp32s3-reboot-loop.log', dir), 'utf8')
  const msgs = toMsgs(loop, 1)
  const guru = msgs.find(m => /Guru Meditation/.test(m.text))
  let b = mergeLines(emptyBuffer(), [...msgs, { t: 'panic', seq: guru.seq, summary: 'StoreProhibited · core 1', log_ref: 'panic-20261106-140000.log' }])
  assert.equal(SERIAL.panicCurrent(b), true) // later boots in the capture are rst:0xc reboots of the same crash
  const after = readFileSync(new URL('esp32s3-after-flash.log', dir), 'utf8')
  b = mergeLines(b, toMsgs(after, b.lastSeq + 1))
  assert.equal(SERIAL.panicCurrent(b), false)
  assert.ok(SERIAL.cleanRunAfter(b, msgs.length))
})
