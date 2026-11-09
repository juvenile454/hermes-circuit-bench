// The built desktop half keeps catalog rule 8 and the bundle build rules (static checks on plugin.js + CSS).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'desktop-src')
const product = build({ withFixtures: false })

/** Evaluate tokens + styles (no SDK needed) and return the CSS text of the <style> element. */
async function cssText() {
  const parts = ['lib/tokens.js', '10-tokens.js', '11-styles-ui2.js', '12-styles.js'].map(f => readFileSync(join(SRC, f), 'utf8').replace(/^export\s+(?=(const|function))/gm, ''))
  const mod = `${parts.join('\n')}\nexport { CB_CSS }\nfunction h() {}\n`
  const url = `data:text/javascript;base64,${Buffer.from(mod).toString('base64')}`
  return (await import(url)).CB_CSS
}

/** Top-level selectors of a stylesheet (inside @media/@container blocks too; @keyframes bodies skipped). */
function selectors(css) {
  const out = []
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  let depth = 0
  let buf = ''
  const stack = []
  for (const ch of clean) {
    if (ch === '{') {
      const head = buf.trim()
      stack.push(head)
      if (!head.startsWith('@') && !stack.slice(0, -1).some(s => s.startsWith('@keyframes'))) out.push(head)
      depth++
      buf = ''
    } else if (ch === '}') {
      stack.pop()
      depth--
      buf = ''
    } else if (ch === ';' && depth > 0) {
      buf = ''
    } else {
      buf += ch
    }
  }
  return out.flatMap(s => s.split(',').map(x => x.trim())).filter(Boolean)
}

test('only the three allowed imports, SDK as namespace', () => {
  const imports = product.split('\n').filter(l => /^\s*import\s/.test(l))
  assert.deepEqual(imports, [
    "import * as sdk from '@hermes/plugin-sdk'",
    "import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
    "import { jsx, jsxs, Fragment } from 'react/jsx-runtime'"
  ])
  assert.equal((product.match(/^\s*export\s+default\b/gm) || []).length, 1)
  assert.ok(product.includes('const CB_FIXTURES = null'))
})

test('no app-markup selectors, no prototype patching, no raw bridge (catalog rule 8)', () => {
  const code = product.replace(/^\s*\/\/.*$/gm, '')
  for (const bad of ['window.hermesDesktop', '.prototype.', '[data-slot', '[data-tree', 'closest(', 'closest?.(', 'document.body.', 'document.documentElement.',
    'document.querySelector', 'document.getElementBy', 'customCSS', 'fontUrl', 'requestTheme(', 'setTheme(']) {
    assert.ok(!code.includes(bad), `plugin.js contains ${bad}`)
  }
  assert.ok(!/\bclassName:\s*['"`][^'"`]*\w-\[[^\]]+\]/.test(code), 'Tailwind arbitrary-value class in plugin.js')
})

test('every CSS rule is scoped to .cb-root; no html/body rules', async () => {
  const css = await cssText()
  const sels = selectors(css)
  assert.ok(sels.length > 150, `parsed ${sels.length} selectors`)
  const bad = sels.filter(s => !/^\.cb-root(\b|[.[:])/.test(s) && !/^(from|to|\d+%)$/.test(s))
  assert.deepEqual(bad, [])
  assert.ok(!sels.some(s => /(^|\s)(html|body)\b/.test(s)))
  assert.ok(css.includes('@media (prefers-reduced-motion:reduce)'))
  assert.match(css, /\.cb-root\.cb-page::after/) // scanlines on the own root
})

test('theme: bench-phosphor, colours + typography only, never auto-selected', async () => {
  const theme = product.slice(product.indexOf('const BENCH_THEME'), product.indexOf('// --- 90-register.js'))
  assert.match(theme, /name: 'bench-phosphor'/)
  assert.match(theme, /label: 'Bench Phosphor'/)
  assert.ok(!/customCSS|fontUrl|darkColors/.test(theme))
  for (const builtin of ['cyberpunk', 'mono', 'nous', 'midnight', 'ember', 'slate', 'classic', 'github', 'catppuccin', 'everforest', 'solarized']) {
    assert.ok(!theme.includes(`name: '${builtin}'`))
  }
})

test('the product bundle loads without SDK globals at import time', async () => {
  // replace the three imports with stubs; module evaluation must not touch anything but sdk.atom
  const stub = product
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = { atom: v => ({ get: () => v, set() {}, subscribe() { return () => {} } }) }')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'", 'const useState = 0, useEffect = 0, useMemo = 0, useRef = 0, useCallback = 0')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'", 'const jsx = 0, jsxs = 0, Fragment = 0')
  const mod = await import(`data:text/javascript;base64,${Buffer.from(stub).toString('base64')}`)
  assert.equal(mod.default.id, 'circuit-bench')
  assert.equal(typeof mod.default.register, 'function')
})

test('bundle has no `!`+backtick sequence (Hermes install scanner: inline_shell_exec, high)', () => {
  // pattern from tools/skills_guard.py: !`[^`\s][^`\n]*`
  const hit = product.match(/!`[^`\s][^`\n]*`/)
  assert.equal(hit, null, hit && `found ${hit[0].slice(0, 60)}`)
})
