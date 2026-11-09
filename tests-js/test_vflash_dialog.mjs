// Hash in groups of eight, RAM/flash bars from the fixtures, check list in words, phase word of a running
// job, flash map only with result.images (the simulated flash has none), port connector symbol only when known.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { flashHashGroups, flashMemRows, flashCheckRows, flashJobPhase, flashMapMarks, flashPortConnector, flashConfirm, portRows } from '../desktop-src/lib/flash.js'
import { artPort } from '../desktop-src/lib/art.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const fx = name => JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', `${name}.json`), 'utf8'))
const project = fx('project.laser-trigger').result.project
const buildJob = fx('job.build.done').result
const flashJob = fx('job.flash.done').result
const s3 = fx('board.esp32-s3-devkitc-1').result
const ports = fx('ports').result.ports
const SRC = readFileSync(join(ROOT, 'desktop-src', '44-station-flash.js'), 'utf8')

test('hash: eight groups of eight that join back to the hash; other text stays one group', () => {
  const sha = project.firmware.last_build.elf_sha256
  const g = flashHashGroups(sha)
  assert.equal(g.length, 8)
  assert.ok(g.every(x => x.length === 8))
  assert.equal(g.join(''), sha)
  assert.deepEqual(flashHashGroups('abc'), ['abc'])
  assert.deepEqual(flashHashGroups(''), [])
  assert.deepEqual(flashHashGroups(null), [])
  assert.equal(flashHashGroups('A'.repeat(64)).length, 8)
})

test('memory bars: percentages from the project build, bytes only from a build job of the same ELF', () => {
  const rows = flashMemRows(project.firmware.last_build)
  assert.deepEqual(rows.map(r => [r.id, r.pct, r.used]), [['ram', 5.9, null], ['flash', 8.5, null]])
  // the job's ELF differs from the project's last build → no bytes
  assert.ok(flashMemRows(project.firmware.last_build, buildJob.result.result).every(r => r.used === null))
  const jr = buildJob.result.result
  const same = flashMemRows({ ok: true, elf_sha256: jr.elf_sha256, ram_pct: jr.ram_pct, flash_pct: jr.flash_pct }, jr)
  assert.deepEqual(same.map(r => [r.id, r.pct, r.used, r.total]), [['ram', 5.6, 18432, 327680], ['flash', 7.9, 263377, 3342336]])
  assert.deepEqual(flashMemRows({ ok: false, ram_pct: 3 }), [])
  assert.deepEqual(flashMemRows(null), [])
  assert.deepEqual(flashMemRows({ ok: true, ram_pct: 4 }).map(r => r.id), ['ram']) // missing flash_pct is not invented
})

test('check list in words: match / differs / not compared, never a bare ✓', () => {
  const conf = flashConfirm(project).confirm
  const rows = flashCheckRows(conf, project)
  assert.deepEqual(rows.map(r => [r.id, r.state, r.word]), [['port', 'match', 'match'], ['mac', 'match', 'match'], ['elf', 'match', 'match']])
  assert.equal(rows[2].at, project.firmware.last_build.at)
  assert.ok(rows.every(r => /^[A-Z][A-Za-z]+ /.test(r.text) && !r.text.includes('✓') && !r.text.includes('=')))
  const other = flashCheckRows({ ...conf, mac: '11:22:33:44:55:66', elf_sha256: 'f'.repeat(64) }, project)
  assert.deepEqual(other.map(r => r.state), ['match', 'differs', 'differs'])
  assert.equal(other[2].at, null)
  const none = flashCheckRows(conf, { board: {}, firmware: {} })
  assert.deepEqual(none.map(r => r.word), ['not compared', 'not compared', 'not compared'])
})

test('job phase word: from the log tail while running, null when finished', () => {
  assert.equal(flashJobPhase(flashJob), null)
  assert.equal(flashJobPhase(buildJob), null)
  assert.deepEqual(flashJobPhase(fx('job.build.running').result), { word: 'building', pct: null })
  assert.deepEqual(flashJobPhase({ kind: 'flash', state: 'queued', progress: null }), { word: 'queued', pct: null })
  const run = (kind, lines, progress = null) => flashJobPhase({ kind, state: 'running', progress, log_tail: lines })
  assert.deepEqual(run('flash', ['Connecting....', 'Chip is ESP32-S3', 'Writing at 0x00010000 [=====>     ] 52.3%'], 0.523), { word: 'writing', pct: 52 })
  assert.equal(run('flash', ['Writing at 0x00010000... (100 %)', 'Hash of data verified.']).word, 'verifying')
  assert.equal(run('flash', ['Hash of data verified.', 'Hard resetting via RTS pin...']).word, 'resetting')
  assert.equal(run('flash', ['Connecting...']).word, 'connecting')
  assert.equal(run('flash', []).word, 'flashing')
  assert.equal(run('build', ['Compiling .pio/build/s3/src/main.cpp.o', 'Linking .pio/build/s3/firmware.elf']).word, 'linking')
  assert.equal(run('build', buildJob.log_tail.slice(0, 3)).word, 'compiling')
  assert.equal(run('detect', ['Connecting....']).word, 'connecting')
  assert.equal(run('flash', [], 2).pct, 100)
})

test('flash map: only with result.images; sorted by offset, offsets and names only (no sizes)', () => {
  // the simulated flash (fixture) reports no images: nothing is drawn
  assert.equal(flashMapMarks(flashJob.result.result.images), null)
  assert.equal(flashMapMarks([]), null)
  assert.equal(flashMapMarks(buildJob.result.result.images), null) // build images are {name: sha}, not a write list
  const images = [ // synthetic board.flash result (board.py _write_list shape)
    { offset: '0x10000', name: 'firmware.bin', sha256: 'a'.repeat(64) },
    { offset: '0x0', name: 'bootloader.bin', sha256: 'b'.repeat(64) },
    { offset: '0x8000', name: 'partitions.bin', sha256: 'c'.repeat(64) },
    { offset: '0xe000', name: 'boot_app0.bin', sha256: 'd'.repeat(64) }]
  const m = flashMapMarks(images)
  assert.deepEqual(m.marks.map(x => [x.n, x.offset, x.name]), [[1, '0x0', 'bootloader.bin'], [2, '0x8000', 'partitions.bin'], [3, '0xe000', 'boot_app0.bin'], [4, '0x10000', 'firmware.bin']])
  assert.ok(m.marks.every((x, i, a) => x.frac >= 0 && x.frac < 1 && (i === 0 || x.frac > a[i - 1].frac)))
  assert.equal(m.highest, '0x10000')
  assert.ok(m.marks.every(x => !('size' in x) && !('end' in x)))
  assert.equal(flashMapMarks([{ offset: 'zz', name: 'x' }, { offset: '0x1000' }]), null) // invalid rows dropped
  assert.match(SRC, /flashMapMarks\(res\?\.images\)/)
})

test('port symbol: artPort shape only for the detected real port with a known board connector', () => {
  const real = ports.find(p => !p.simulated) // usb_serial_jtag → S3 "USB" port, connector null → generic jack
  assert.equal(flashPortConnector(real, s3, real.device), 'generic_usb')
  const bridge = { ...real, kind: 'cp210x' } // → S3 "UART" port, Micro-USB in the board data
  assert.equal(flashPortConnector(bridge, s3, real.device), 'micro_usb')
  assert.equal(flashPortConnector(real, s3, null), null) // not detected: which board is on it is unknown
  assert.equal(flashPortConnector(ports.find(p => p.simulated), s3, 'sim://esp32s3-n16r8'), null)
  assert.equal(flashPortConnector({ ...real, kind: 'usb_cdc_app' }, s3, real.device), null)
  assert.equal(flashPortConnector(real, { usb: s3.usb }, real.device), null) // no drawing block → nothing
  assert.equal(flashPortConnector(bridge, null, real.device), null)
  for (const k of ['generic_usb', 'micro_usb']) assert.ok(artPort(k, 0, 0).includes(`data-cb-port="${k}"`))
  assert.equal(portRows(ports).length, 2)
})

test('dialog markup: confirm unchanged, Cancel/primary data-cb kept, hash contiguous, checks in words', () => {
  assert.match(SRC, /flashFirmware\(confirm\)/)
  assert.match(SRC, /'data-cb': 'flash-cancel'/)
  assert.match(SRC, /kind: 'warn', onClick: go, disabled: busy, 'data-cb': 'flash-confirm'/)
  assert.match(SRC, /'data-cb': 'flash-hash'/)
  assert.ok(!/= detection|= last build/.test(SRC), 'old "✓ = …" marks are gone')
  assert.match(SRC, /'data-cb': `flash-check-\$\{c\.id\}`/)
  assert.ok(!/document\.querySelector/.test(SRC))
})
