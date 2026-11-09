// Pure UI parts: console state, empty console, log display model with folded blank runs and panic blocks, outdated
// solder plan and the real-board flash hint, value colour from the worst check, drafts without duplicates, ELF
// wording.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { consoleMode, serialEmptyState, panicCurrent } from '../desktop-src/lib/serial.js'
import { logView, panicBlocks, bufferText, lineClass } from '../desktop-src/lib/seq.js'
import { solderStale, flashSolderHint, stageStatus, solderProgress } from '../desktop-src/lib/stages.js'
import { worstCheck, valueTone } from '../desktop-src/lib/calc.js'
import { fixDraftText, elfCheck } from '../desktop-src/lib/crash.js'
import { findingText } from '../desktop-src/lib/pins.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const clone = x => JSON.parse(JSON.stringify(x))
const project = fx('project.laser-trigger').result.project
const serial = fx('serial.lines').result
const lines = serial.lines.map(l => ({ k: 'line', seq: l.seq, ts: l.ts, text: l.text }))

test('console state: one bar while no port is open; port, job, panic, pane, user choice win', () => {
  assert.equal(consoleMode({}), 'idle')
  assert.equal(consoleMode({ monitorOpen: true }), 'open')
  assert.equal(consoleMode({ serialOpen: true }), 'open')
  assert.equal(consoleMode({ jobRunning: true }), 'open')
  assert.equal(consoleMode({ panic: true }), 'open')
  assert.equal(consoleMode({ pinned: true }), 'open')
  assert.equal(consoleMode({ cons: 'collapsed', monitorOpen: true }), 'collapsed')
  assert.equal(consoleMode({ paneOpen: true, cons: 'collapsed' }), 'pane')
})

test('empty console: a sim port offers "Open monitor ›" on it, never a simulator that cannot be started', () => {
  const sim = serialEmptyState({ ports: [{ device: 'sim://esp32s3-n16r8', simulated: true }], serial: { port: 'sim://esp32s3-n16r8', status: 'closed' } })
  assert.deepEqual(sim, { kind: 'sim', text: 'Simulated board ready.', action: { label: 'Open monitor ›', port: 'sim://esp32s3-n16r8' } })
  assert.equal(serialEmptyState({ ports: [], serial: {} }).kind, 'none')
  assert.doesNotMatch(serialEmptyState({ ports: [], serial: {} }).text, /start the simulator/)
  const real = serialEmptyState({ ports: [{ device: '/dev/ttyACM0', simulated: false, likely_esp: true }], serial: { port: '/dev/ttyACM0', note: 'real-port' } })
  assert.equal(real.kind, 'real')
  assert.equal(real.action.port, null) // a real port is never opened from the console: 06 DEBUG, click there
  assert.equal(serialEmptyState({ backendDown: true }).kind, 'offline')
})

test('log display: blank runs fold to one, each panic is one block Guru … Rebooting, copy text unchanged', () => {
  const view = logView(lines)
  const flat = view.flatMap(e => (e.k === 'panic' ? e.lines : [e]))
  for (let i = 1; i < flat.length; i++) {
    assert.ok(String(flat[i].text).trim() || String(flat[i - 1].text).trim(), `two blank lines in a row at seq ${flat[i].seq}`)
  }
  assert.ok(flat.length < lines.length)
  const blocks = panicBlocks(view)
  assert.deepEqual(blocks.map(b => b.seq), [10, 34, 58])
  for (const e of view.filter(x => x.k === 'panic')) {
    assert.match(e.lines[0].text, /^Guru Meditation/)
    assert.match(e.lines[e.lines.length - 1].text, /^Rebooting\.\.\./)
    assert.ok(e.lines.some(l => /^Backtrace:/.test(l.text)))
  }
  assert.equal(blocks[blocks.length - 1].seq, serial.panic.seq) // the chip "▲ panic · seq N" points at the latest panic
  // the copy text keeps every line, blank ones included
  const buf = { lines, panic: serial.panic }
  assert.equal(bufferText(buf).split('\n').length, lines.length)
  assert.equal(lineClass('Saved PC:0x40377ab6'), 'rom')
})

test('log display: a block ends at the next boot banner when "Rebooting..." is missing; gaps end it too', () => {
  const ls = [
    { k: 'line', seq: 1, text: "Guru Meditation Error: Core  1 panic'ed (LoadProhibited). Exception was unhandled." },
    { k: 'line', seq: 2, text: '' }, { k: 'line', seq: 3, text: '' }, { k: 'line', seq: 4, text: 'Backtrace: 0x1:0x2' },
    { k: 'line', seq: 5, text: 'ESP-ROM:esp32s3-20210327' }, { k: 'line', seq: 6, text: 'ok' }
  ]
  const v = logView(ls)
  assert.equal(v[0].k, 'panic')
  assert.deepEqual(v[0].lines.map(l => l.seq), [1, 2, 4])
  assert.deepEqual(v.slice(1).map(e => e.seq), [5, 6])
  const g = logView([ls[0], { k: 'gap', from: 2, to: 9 }, { k: 'line', seq: 10, text: 'x' }])
  assert.deepEqual(g.map(e => e.k), ['panic', 'gap', 'line'])
})

test('log display: a panic followed by a boot with an outside reset (new firmware) is not current', () => {
  // hardware test: a bare "ESP-ROM:" line is only the start of the banner (its reset reason follows); the panic's own reboot
  // (rst:0xc) keeps it current; power-on or the esptool reset after a flash ends it (test_hw_serial.mjs)
  const rom = { k: 'line', seq: 77, text: 'ESP-ROM:esp32s3-20210327' }
  assert.equal(panicCurrent({ lines, panic: serial.panic }), true)
  assert.equal(panicCurrent({ lines: [...lines, rom], panic: serial.panic }), true)
  const fresh = [...lines, rom, { k: 'line', seq: 78, text: 'rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)' }]
  assert.equal(panicCurrent({ lines: fresh, panic: serial.panic }), false)
  const app = [...lines, rom, { k: 'line', seq: 78, text: '[laser-trigger] boot, laser off' }]
  assert.equal(panicCurrent({ lines: app, panic: serial.panic }), false)
})

test('solder plan outdated: parts added after planning are named, the step that gains a part reopens', () => {
  assert.deepEqual(solderStale(project), { stale: false, missing: [], gone: [], reopen: [] })
  const p = clone(project)
  p.parts.push({ ref: 'R5', kind: 'resistor', value: '82 Ω', from_calc: 'led-1' }, { ref: 'LED1', kind: 'led', value: 'LED', from_calc: 'led-1' })
  p.solder.done = [p.solder.steps[0].id, p.solder.steps[1].id]
  const st = solderStale(p)
  assert.equal(st.stale, true)
  assert.deepEqual(st.missing, ['R5', 'LED1'])
  assert.deepEqual(st.reopen.map(r => [r.n, r.gains]), [[1, ['R5']]]) // resistors gain R5; the transistor step keeps its mark
  const rail = stageStatus(p, { ok: 5, caution: 0, blocked: 0, unchecked: 0 }, null).solder
  assert.equal(rail.text, '!')
  assert.equal(rail.tone, 'warn')
  assert.match(rail.detail, /R5, LED1 not in the plan/)
  const gone = clone(project)
  gone.parts = gone.parts.filter(x => x.ref !== 'SW1')
  assert.deepEqual(solderStale(gone).gone, ['SW1'])
  // without a plan there is nothing to be outdated
  assert.equal(solderStale({ ...project, solder: { steps: [], done: [] } }).stale, false)
})

test('05 FLASH hint for a real board only: unfinished or outdated solder plan, never for sim', () => {
  const p = clone(project)
  p.solder.done = [p.solder.steps[0].id, p.solder.steps[1].id]
  assert.equal(flashSolderHint(p, 'sim://esp32s3-n16r8'), null)
  assert.equal(flashSolderHint(p, '/dev/ttyACM0'), 'solder 2/5 — board not finished?')
  p.solder.done = p.solder.steps.map(s => s.id)
  assert.equal(flashSolderHint(p, '/dev/ttyACM0'), null)
  p.parts.push({ ref: 'LED1', kind: 'led', value: 'LED' })
  assert.match(flashSolderHint(p, '/dev/ttyACM0'), /^solder plan outdated \(LED1 not in it\)/)
  assert.equal(flashSolderHint({ ...p, solder: { steps: [], done: [] } }, '/dev/ttyACM0'), null)
  assert.equal(solderProgress(p).total, 5)
})

test('result value takes the colour of its worst check', () => {
  assert.equal(valueTone(fx('calc.npn').checks), 'ok')
  assert.equal(valueTone([{ id: 'a', status: 'passed' }, { id: 'b', status: 'not_checked' }]), 'fg')
  assert.equal(valueTone([{ id: 'a', status: 'passed' }, { id: 'b', status: 'failed' }, { id: 'c', status: 'not_checked' }]), 'bad')
  assert.equal(valueTone([{ id: 'a', status: 'skipped' }]), 'fg')
  assert.equal(valueTone([]), 'fg')
  assert.equal(worstCheck(null), null)
})

test('fix draft: reason once, no repeated interpretation, firmware place as the agent reads it', () => {
  const decode = fx('crash.decode')
  const text = fixDraftText(project, decode)
  const prose = text.split('\n').filter(l => !/^#\d/.test(l)).join('\n')
  assert.equal((prose.match(/StoreProhibited/g) || []).length, 1, text)
  assert.equal((text.match(/NULL pointer/gi) || []).length, 1, text) // in the summary only, not again as interpretation
  assert.match(text, /Firmware: bench_project get → firmware\.dir \(PlatformIO env s3\)\./)
  assert.doesNotMatch(text, /\(\(|\)\)/)
  for (const must of ['laser-trigger', 'write_sensor_buffer', 'main.cpp:44', 'ask before flashing', '(simulated board)']) assert.ok(text.includes(must), must)
  // without a summary the reason line is built from the decode result
  const bare = fixDraftText(project, { result: { reason: 'LoadProhibited', core: 0, frames: [] } })
  assert.match(bare, /Panic: LoadProhibited on core 0\./)
})

test('ask draft finding: "— reason" without an outer bracket around a reason that has its own', () => {
  const row = { role: 'BUTTON', pin: 35, verdict: 'blocked', reasons: [{ message: 'Wired to the octal PSRAM bus (SPIIO4–7, SPIDQS). Espressif: do not use.' }] }
  assert.equal(findingText(row), 'BUTTON on GPIO35 is blocked — Wired to the octal PSRAM bus (SPIIO4–7, SPIDQS). Espressif: do not use')
  assert.equal(findingText({ role: 'LED', pin: 3, verdict: 'caution', reasons: [] }), 'LED on GPIO3 is caution')
})

test('ELF check: skipped says why, right after the verdict; never "passed" without an ELF', () => {
  const sim = elfCheck(fx('crash.decode'))
  assert.equal(sim.status, 'skipped')
  assert.equal(sim.label, 'elf check skipped · simulated build, no ELF')
  assert.equal(elfCheck({ checks: [], result: {} }).label, 'elf check skipped · no ELF to compare')
  assert.equal(elfCheck({ checks: [{ id: 'crash.elf_match', status: 'passed' }], result: {} }).label, 'elf match')
})
