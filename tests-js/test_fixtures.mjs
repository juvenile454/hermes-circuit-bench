// Every desktop fixture is a result envelope.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src', 'fixtures')
const REQUIRED = ['ok', 'action', 'summary', 'result', 'checks', 'warnings', 'assumptions', 'sources', 'simulated', 'error']
const STATUSES = new Set(['passed', 'failed', 'skipped', 'not_checked'])
const EXPECTED = ['health', 'projects.list', 'project.laser-trigger', 'board.esp32-s3-devkitc-1', 'pins.check', 'pins.suggest',
  'pins.info', 'calc.led', 'calc.npn', 'calc.divider', 'calc.i2c_pullup', 'schematic.npn', 'solder.plan', 'ports',
  'job.build.running', 'job.build.done', 'job.flash.done', 'serial.lines', 'crash.decode', 'doctor']

const files = readdirSync(DIR).filter(f => f.endsWith('.json')).sort()

test('all expected contract fixtures exist', () => {
  for (const name of EXPECTED) assert.ok(files.includes(`${name}.json`), `missing fixture ${name}.json`)
})

for (const f of files) {
  test(`fixture ${f} is an envelope`, () => {
    const env = JSON.parse(readFileSync(join(DIR, f), 'utf8'))
    for (const k of REQUIRED) assert.ok(k in env, `${f}: missing ${k}`)
    assert.equal(typeof env.summary, 'string')
    assert.ok(env.summary.length > 0)
    for (const c of env.checks) assert.ok(STATUSES.has(c.status), `${f}: bad check status ${c.status}`)
    if (env.ok) assert.equal(env.error, null)
    else assert.ok(env.error && env.error.code && env.error.message)
    assert.equal(typeof env.simulated, 'boolean')
  })
}
