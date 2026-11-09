// Flash confirmation object ({port, mac, elf_sha256} from project + build job), port list order (real
// first, sim below), job progress, solder progress / next step, rail status after a fix, wiring helpers.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { flashConfirm, portRows, defaultPort, jobProgress, jobError, detectSummary, isSimPort, bareVariant } from '../desktop-src/lib/flash.js'
import { solderProgress, nextSolderStep, stageStatus, stagePanicCurrent } from '../desktop-src/lib/stages.js'
import { sanitizeSvg, wiringRows, refOfEnd, circuitGpio, buildWireParams, wireBlock, svgFileName } from '../desktop-src/lib/wire.js'
import { parseQuantity } from '../desktop-src/lib/units.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const project = fx('project.laser-trigger').result.project
const ports = fx('ports').result.ports
const buildDone = fx('job.build.done').result
const counts = { ok: 5, caution: 0, blocked: 0, unchecked: 0 }

test('flash confirmation: port + MAC from board.detected, ELF hash from the last build', () => {
  const c = flashConfirm(project)
  assert.equal(c.ok, true)
  assert.deepEqual(c.confirm, { port: 'sim://esp32s3-n16r8', mac: 'aa:bb:cc:dd:ee:ff', elf_sha256: project.firmware.last_build.elf_sha256 })
  assert.equal(c.simulated, true)
  assert.equal(c.alreadyFlashed, true)
})

test('flash confirmation: a newer finished build job wins; missing pieces are named', () => {
  const p = structuredClone(project)
  p.firmware.last_build.at = '2026-11-06T06:00:00Z' // older than the job (finished 06:50:45)
  const c = flashConfirm(p, buildDone)
  assert.equal(c.confirm.elf_sha256, buildDone.result.result.elf_sha256)
  assert.equal(c.alreadyFlashed, false)
  const older = flashConfirm(project, buildDone) // project build 2026-11-09 is newer than the job
  assert.equal(older.confirm.elf_sha256, project.firmware.last_build.elf_sha256)
  const none = structuredClone(project)
  delete none.board.detected
  none.firmware.last_build = { ok: false }
  assert.deepEqual(flashConfirm(none), { ok: false, confirm: null, missing: ['detect', 'mac', 'build'], simulated: false, alreadyFlashed: false })
  const running = flashConfirm(p, { ...buildDone, state: 'running' })
  assert.equal(running.confirm.elf_sha256, p.firmware.last_build.elf_sha256)
})

test('port list: real ports first, sim below and marked; listing never opens or detects', () => {
  const rows = portRows([...ports].reverse(), { detectedPort: 'sim://esp32s3-n16r8', selected: '/dev/ttyACM0' })
  assert.deepEqual(rows.map(r => [r.device, r.label, r.simulated]), [['/dev/ttyACM0', 'ESP', false], ['sim://esp32s3-n16r8', 'SIMULATED', true]])
  assert.equal(rows[1].detected, true)
  assert.equal(rows[0].selected, true)
  assert.equal(rows[0].kind, 'USB-Serial/JTAG')
  assert.equal(defaultPort(ports, 'sim://esp32s3-n16r8'), 'sim://esp32s3-n16r8')
  assert.equal(defaultPort(ports, null), '/dev/ttyACM0')
  assert.equal(defaultPort(ports.filter(p => p.simulated), null), 'sim://esp32s3-n16r8')
  assert.equal(defaultPort([], null), null)
  assert.ok(isSimPort('sim://x') && !isSimPort('/dev/ttyACM0') && !isSimPort(null))
  assert.equal(portRows(null).length, 0)
})

test('job progress: pio reports no percentage (indeterminate), done/failed', () => {
  assert.deepEqual(jobProgress(fx('job.build.running').result), { state: 'running', pct: null, indeterminate: true, text: 'running…', done: false, failed: false, running: true })
  assert.equal(jobProgress(buildDone).done, true)
  assert.equal(jobProgress(buildDone).pct, 100)
  assert.equal(jobProgress({ state: 'running', progress: 0.42 }).text, '42 %')
  assert.equal(jobProgress({ state: 'done', result: { ok: false } }).failed, true)
  assert.equal(jobProgress(null).state, 'none')
  assert.equal(jobError({ ok: false, error: { code: 'flash_disabled', message: 'off', hint: 'Agent settings' } }).code, 'flash_disabled')
  assert.equal(jobError(buildDone), null)
})

test('detection summary and variant mismatch', () => {
  const det = { ...project.board.detected, psram_mb: 8, usb_mode: 'USB-Serial/JTAG' }
  const s = detectSummary(det, project)
  assert.equal(s.mac, 'aa:bb:cc:dd:ee:ff')
  assert.equal(s.psram, '8 MB')
  assert.equal(s.variantDiffers, false)
  assert.equal(detectSummary({ ...det, variant_suggestion: 'n8r2' }, project).variantDiffers, true)
  assert.equal(detectSummary(null, project), null)
})

test('detection summary: the "?" of an unverified variant guess is not part of the comparison', () => {
  // a real board: board.variant_suggestion returns "n16r8?" (esptool cannot tell octal from quad PSRAM)
  const det = { ...project.board.detected, variant_suggestion: 'n16r8?', simulated: false }
  const s = detectSummary(det, project)
  assert.equal(project.board.variant, 'n16r8')
  assert.equal(s.variantDiffers, false)
  assert.equal(s.suggestion, 'n16r8')
  assert.equal(s.unverified, true)
  const other = detectSummary({ ...det, variant_suggestion: 'n8r2?' }, project)
  assert.equal(other.variantDiffers, true)
  assert.equal(other.suggestion, 'n8r2', 'the value the "Use …" button sends carries no "?"')
  assert.equal(other.unverified, true)
  // the simulated board reports a bare value
  assert.equal(detectSummary({ ...det, variant_suggestion: 'n16r8' }, project).unverified, false)
  assert.equal(bareVariant('n16r8?'), 'n16r8')
  assert.equal(bareVariant(' N16R8? '), 'n16r8')
  assert.equal(bareVariant('n16r8'), 'n16r8')
  assert.equal(bareVariant(null), null)
  assert.equal(bareVariant('?'), null)
})

test('station 05 and set_board never use the raw variant guess', () => {
  const live = readFileSync(join(ROOT, 'desktop-src', '26-live.js'), 'utf8')
  const fn = live.slice(live.indexOf('function applyVariant('), live.indexOf('\n}\n', live.indexOf('function applyVariant(')))
  assert.match(fn, /bareVariant\(/, 'applyVariant strips the "?" marker before set_board')
  const st = readFileSync(join(ROOT, 'desktop-src', '44-station-flash.js'), 'utf8')
  assert.doesNotMatch(st, /variant_suggestion/, 'the station reads the summary, not the raw guess')
  assert.match(st, /s\.unverified/, 'the match line says when the variant is unverified')
})

test('solder progress and the next step (key n)', () => {
  assert.deepEqual(solderProgress(project), { done: 0, total: 5 })
  assert.equal(nextSolderStep(project).n, 1)
  const p = structuredClone(project)
  p.solder.done = [p.solder.steps[0].id, p.solder.steps[1].id, 'gone-step']
  assert.deepEqual(solderProgress(p), { done: 2, total: 5 })
  assert.equal(nextSolderStep(p).n, 3)
  p.solder.done = p.solder.steps.map(s => s.id)
  assert.equal(nextSolderStep(p), null)
  assert.equal(stageStatus(p, counts, null).solder.text, '[✓]')
})

test('rail after the fix loop: PANIC while current, [✓] once flashed after it; flash BUILT when the build is newer', () => {
  assert.deepEqual(stageStatus(project, counts, null).debug, { text: 'PANIC', tone: 'bad', alert: true })
  const p = structuredClone(project)
  p.firmware.last_build = { ...p.firmware.last_build, elf_sha256: 'b'.repeat(64), at: '2026-11-09T20:18:00Z' }
  assert.equal(stageStatus(p, counts, null).flash.text, 'BUILT')
  p.firmware.last_flash = { ...p.firmware.last_flash, elf_sha256: 'b'.repeat(64), at: '2026-11-09T20:19:00Z' }
  assert.equal(stagePanicCurrent(p), false)
  assert.deepEqual(stageStatus(p, counts, null).debug, { text: '[✓]', tone: 'ok', alert: false })
  assert.equal(stageStatus(p, counts, null).flash.text, '[✓]')
})

test('wiring: refs at both ends, GPIO of a stored circuit, params as SI numbers, SVG safety', () => {
  const sch = fx('schematic.npn').result
  const rows = wiringRows(sch.wiring)
  assert.deepEqual(rows[0].refs, ['J1', 'R1'])
  assert.equal(refOfEnd('Q1.E'), 'Q1')
  assert.equal(refOfEnd('+5V'), null)
  assert.equal(circuitGpio(project, project.circuits[0]), 14)
  const r = buildWireParams(wireBlock('npn_low_side'), { r_base: '1k', r_pulldown: '10k', transistor: '2N2222A', load: 'laser module', supply: '5V', net: 'LASER_EN' }, parseQuantity)
  assert.deepEqual(r.params, { r_base: 1000, r_pulldown: 10000, transistor: '2N2222A', load: 'laser module', supply: '5V', net: 'LASER_EN' })
  assert.equal(buildWireParams(wireBlock('led'), { r_series: '' }, parseQuantity).errors.r_series, 'required')
  assert.equal(sanitizeSvg(sch.svg).ok, true)
  for (const bad of ['<svg><script>alert(1)</script></svg>', '<svg onload="x()"></svg>', '<svg><a href="https://x">x</a></svg>', '<div></div>',
    '<svg><foreignObject></foreignObject></svg>', '<svg><image xlink:href="data:x"/></svg>', '<svg><style>*{}</style></svg>']) {
    assert.equal(sanitizeSvg(bad).ok, false, bad)
  }
  assert.equal(svgFileName(project, 'laser'), 'laser-trigger-laser.svg')
})
