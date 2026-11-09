// Directive ::bench attributes (strings only, garbage renders nothing), session id, card summaries.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseDirectiveAttrs, directiveSession, directiveSummary, DIRECTIVE_VIEWS } from '../desktop-src/lib/directive.js'
import { projectPanicCurrent } from '../desktop-src/lib/crash.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const project = JSON.parse(readFileSync(join(ROOT, 'desktop-src', 'fixtures', 'project.laser-trigger.json'), 'utf8')).result.project

test('valid attributes (as the host hands them over: lower-cased keys, string values)', () => {
  for (const view of DIRECTIVE_VIEWS) {
    const a = parseDirectiveAttrs({ project: 'laser-trigger', view })
    assert.equal(a.project, 'laser-trigger')
    assert.equal(a.view, view)
    assert.ok(a.title)
  }
  assert.equal(parseDirectiveAttrs({ project: 'laser-trigger', view: 'crash' }).station, 'debug')
  assert.equal(parseDirectiveAttrs({ project: 'laser-trigger', view: 'pins', empty: '', n: '3' }).station, 'plan')
})

test('garbage renders nothing: unquoted values arrive as missing, numbers/bools are never accepted', () => {
  // unquoted `project=laser-trigger` and bare keys never reach the card: attrs then lack `project`
  for (const attrs of [{}, { view: 'pins' }, { project: '' }, { project: 'Laser!!', view: 'pins' }, { project: 'laser-trigger', view: 'shell' },
    { project: 'laser-trigger', view: '' }, { project: 'laser-trigger', view: 'Pins' }, { project: 5 }, { project: true, view: 'pins' },
    { project: 'laser-trigger', view: ['pins'] }, { project: 'a'.repeat(49) }, { project: '../../etc/passwd' }, { project: 'laser-trigger\n' },
    { project: '<img src=x onerror=alert(1)>' }, null, 'project=laser-trigger', [['project', 'x']]]) {
    assert.equal(parseDirectiveAttrs(attrs), null, JSON.stringify(attrs))
  }
})

test('sessionId ?? null: only plain short ids (B passes local-…, v0.22.5 none)', () => {
  assert.equal(directiveSession({ sessionId: 'local-ac17f00d' }), 'local-ac17f00d')
  assert.equal(directiveSession({}), null)
  assert.equal(directiveSession({ sessionId: undefined }), null)
  assert.equal(directiveSession({ sessionId: 'x y' }), null)
  assert.equal(directiveSession({ sessionId: 42 }), null)
  assert.equal(directiveSession(null), null)
})

test('card summaries per view from the demo project', () => {
  const opts = { panicCurrent: projectPanicCurrent }
  const pins = directiveSummary('pins', project, opts)
  assert.equal(pins.headline.text, '5✓ 0! 0✕')
  assert.equal(pins.rows[0].value, 'IO14')
  assert.equal(directiveSummary('calc', project, opts).headline.text, '2 calculations')
  assert.equal(directiveSummary('wire', project, opts).rows[0].value, 'npn_low_side')
  assert.equal(directiveSummary('solder', project, opts).headline.text, '0/5 done')
  assert.equal(directiveSummary('flash', project, opts).headline.text, 'flashed')
  const crash = directiveSummary('crash', project, opts)
  assert.equal(crash.headline.text, 'PANIC CAUGHT')
  assert.match(crash.rows[1].value, /write_sensor_buffer/)
  // flashed after the panic: the card says fixed
  const fixed = structuredClone(project)
  fixed.firmware.last_flash.at = '2026-11-09T20:20:00Z'
  assert.equal(directiveSummary('crash', fixed, opts).headline.tone, 'ok')
  assert.equal(directiveSummary('pins', null).headline.text, 'no project')
})
