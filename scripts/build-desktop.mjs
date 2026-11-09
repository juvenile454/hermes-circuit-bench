#!/usr/bin/env node
// Builds circuit_bench/desktop/plugin.js from desktop-src/.
//   order: 00-head.js, lib/*.js, then [0-9]*.js (without 00-head.js), lexical
//   imports only in 00-head.js; `export` keywords elsewhere are removed; only `export default` of 90-register.js stays
//   node scripts/build-desktop.mjs          write the file
//   node scripts/build-desktop.mjs --check  exit 1 if the committed file differs from a fresh build
//   both fail when the product build exceeds BUNDLE_BUDGET
//   node scripts/build-desktop.mjs --with-fixtures --out=<file>
//        development build for E2E/screenshots: embeds desktop-src/fixtures/*.json as CB_FIXTURES
//        (the product build has CB_FIXTURES = null, never ships fixtures and replaces lib/fixtures.js by
//        `const createFixtureBackend = null`). --out is required here.
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const OUT = join(ROOT, 'circuit_bench', 'desktop', 'plugin.js')
export const BUNDLE_BUDGET = 760_000 // bytes of the product build (412 KB before the SVG board art, 634 KB after it;
// the SVG art is code, not assets, so the budget grew from 600 KB to 700 KB, dead styles were removed)
// module support: 700 KB → 760 KB (module planning 30 KB, calculator/wiring stations 15 KB, the rest is reserve)
const HEADER = '// GENERATED from desktop-src/ by scripts/build-desktop.mjs — do not edit\n'

const listJs = dir => (existsSync(dir) ? readdirSync(dir).filter(f => f.endsWith('.js')).sort() : [])

function strip(name, text) {
  const out = []
  for (const line of text.split('\n')) {
    if (/^\s*import\s/.test(line)) throw new Error(`${name}: imports are only allowed in 00-head.js`)
    if (name === '90-register.js' && /^\s*export\s+default\b/.test(line)) { out.push(line); continue }
    if (/^\s*export\s+default\b/.test(line)) throw new Error(`${name}: only 90-register.js may export default`)
    out.push(line.replace(/^(\s*)export\s+(?=(const|let|function|class|async)\b)/, '$1'))
  }
  return out.join('\n')
}

function fixturesBlock(withFixtures) {
  if (!withFixtures) return '// --- fixtures (product build: none)\nconst CB_FIXTURES = null'
  const dir = join(SRC, 'fixtures')
  const all = {}
  for (const f of readdirSync(dir).filter(f => f.endsWith('.json')).sort()) {
    all[f.slice(0, -5)] = JSON.parse(readFileSync(join(dir, f), 'utf8'))
  }
  return `// --- fixtures (DEVELOPMENT build, never commit)\nconst CB_FIXTURES = ${JSON.stringify(all)}`
}

export function build({ withFixtures = false } = {}) {
  const parts = [HEADER]
  const head = join(SRC, '00-head.js')
  parts.push(`// --- 00-head.js\n${readFileSync(head, 'utf8')}`)
  parts.push(fixturesBlock(withFixtures))
  for (const f of listJs(join(SRC, 'lib'))) {
    // the fixture backend only runs with embedded fixtures (20-api.js); the product build carries a stub
    if (!withFixtures && f === 'fixtures.js') { parts.push('// --- lib/fixtures.js (product build: none)\nconst createFixtureBackend = null'); continue }
    parts.push(`// --- lib/${f}\n${strip(`lib/${f}`, readFileSync(join(SRC, 'lib', f), 'utf8'))}`)
  }
  for (const f of listJs(SRC).filter(f => /^[0-9]/.test(f) && f !== '00-head.js')) {
    parts.push(`// --- ${f}\n${strip(f, readFileSync(join(SRC, f), 'utf8'))}`)
  }
  const text = parts.map(p => p.replace(/\s+$/, '')).join('\n\n') + '\n'
  if ((text.match(/^\s*export\s+default\b/gm) || []).length !== 1) throw new Error('exactly one export default expected (90-register.js)')
  return text
}

function nodeCheck(text) {
  const dir = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'cb-build-'))
  try {
    const f = join(dir, 'plugin.mjs')
    writeFileSync(f, text)
    execFileSync(process.execPath, ['--check', f], { stdio: 'inherit' })
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const withFixtures = process.argv.includes('--with-fixtures')
  const outArg = process.argv.find(a => a.startsWith('--out='))
  const text = build({ withFixtures })
  nodeCheck(text)
  if (!withFixtures && Buffer.byteLength(text) > BUNDLE_BUDGET) {
    console.error(`desktop build: ${Buffer.byteLength(text)} bytes exceed the budget of ${BUNDLE_BUDGET} bytes`)
    process.exit(1)
  }
  if (withFixtures) {
    if (!outArg) { console.error('--with-fixtures needs --out=<file> (never the committed plugin.js)'); process.exit(2) }
    const out = resolve(outArg.slice(6))
    if (out === OUT) { console.error('refusing to write a fixture build to circuit_bench/desktop/plugin.js'); process.exit(2) }
    mkdirSync(dirname(out), { recursive: true })
    writeFileSync(out, text)
    console.log(`desktop build (with fixtures): wrote ${out} (${text.length} bytes)`)
  } else if (process.argv.includes('--check')) {
    const current = existsSync(OUT) ? readFileSync(OUT, 'utf8') : ''
    if (current !== text) {
      console.error('circuit_bench/desktop/plugin.js is not the build of desktop-src/: run node scripts/build-desktop.mjs')
      process.exit(1)
    }
    console.log(`desktop build: up to date (${Buffer.byteLength(text)} of ${BUNDLE_BUDGET} bytes)`)
  } else {
    mkdirSync(dirname(OUT), { recursive: true })
    writeFileSync(OUT, text)
    console.log(`desktop build: wrote ${OUT} (${text.length} bytes)`)
  }
}
