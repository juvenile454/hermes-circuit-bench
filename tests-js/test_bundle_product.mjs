// The product build ships no development fixture backend: lib/fixtures.js is replaced by a one-line stub, the
// development build (--with-fixtures) still embeds it. Everything the product uses from that file is the stub name.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const product = build({ withFixtures: false })
const dev = build({ withFixtures: true })

test('product build: no fixture backend, a stub instead, below 735 000 bytes', () => {
  assert.ok(!product.includes('function createFixtureBackend'), 'fixture backend in the product build')
  assert.ok(product.includes('// --- lib/fixtures.js (product build: none)\nconst createFixtureBackend = null'))
  assert.ok(product.includes('const CB_FIXTURES = null'))
  const size = Buffer.byteLength(product)
  assert.ok(size < 735_000, `product build has ${size} bytes`)
})

test('development build with fixtures keeps the fixture backend', () => {
  assert.ok(dev.includes('function createFixtureBackend'))
  assert.ok(dev.includes('// --- lib/fixtures.js\n'))
  assert.ok(!dev.includes('const createFixtureBackend = null'))
})

test('the product code uses nothing else from lib/fixtures.js', () => {
  const fx = readFileSync(join(SRC, 'lib', 'fixtures.js'), 'utf8')
  const names = [...fx.matchAll(/^(?:export\s+)?(?:async\s+)?(?:function\s+|const\s+|let\s+)([A-Za-z_$][\w$]*)/gm)].map(m => m[1])
  assert.ok(names.includes('createFixtureBackend') && names.length > 3, names.join(', '))
  const others = [...readdirSync(join(SRC, 'lib')).filter(f => f.endsWith('.js') && f !== 'fixtures.js').map(f => join(SRC, 'lib', f)),
    ...readdirSync(SRC).filter(f => /^[0-9].*\.js$/.test(f)).map(f => join(SRC, f))]
  const code = others.map(f => readFileSync(f, 'utf8')).join('\n')
  const used = names.filter(n => new RegExp(`(?<![\\w$.])${n.replace(/\$/g, '\\$')}(?![\\w$])`).test(code))
  assert.deepEqual(used, ['createFixtureBackend'])
})

test('the committed plugin.js is the stubbed product build', () => {
  const committed = readFileSync(join(ROOT, 'circuit_bench', 'desktop', 'plugin.js'), 'utf8')
  assert.ok(!committed.includes('function createFixtureBackend'))
  assert.ok(Buffer.byteLength(committed) < 735_000)
})
