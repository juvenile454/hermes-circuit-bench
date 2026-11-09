// Model material tokens: low chroma, text contrast on material,
// state rings on the board face, identical in both looks; --cb-grid at 3 %.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { contrastRatio, hexToRgb } from '../desktop-src/lib/contrast.js'
import { PHOSPHOR, FOLLOW, MATERIAL } from '../desktop-src/lib/tokens.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop-src')
const KEYS = ['pcb', 'pcb-edge', 'silk', 'metal', 'metal-hi', 'metal-ink', 'tin', 'plastic', 'plastic-edge', 'copper', 'cavity']

/** sRGB hex → OKLCH [L, C, h°] (Björn Ottosson's OKLab matrices). Kept in the test: contrast.js is WCAG only. */
function oklch(hex) {
  const lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  const [r, g, b] = hexToRgb(hex).map(lin)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
  const A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
  return [L, Math.hypot(A, B), (Math.atan2(B, A) * 180 / Math.PI + 360) % 360]
}

test('oklch maths: white, black, sRGB red (reference values from the CSS Color 4 spec)', () => {
  const [Lw, Cw] = oklch('#ffffff')
  assert.ok(Math.abs(Lw - 1) < 1e-3 && Cw < 1e-3)
  assert.ok(oklch('#000000')[0] < 1e-6)
  const [L, C, h] = oklch('#ff0000')
  assert.ok(Math.abs(L - 0.628) < 2e-3 && Math.abs(C - 0.2577) < 2e-3 && Math.abs(h - 29.23) < 0.1, `${L} ${C} ${h}`)
})

test('the material set is complete and holds fixed hex values', () => {
  assert.deepEqual(Object.keys(MATERIAL).sort(), [...KEYS].sort())
  for (const [k, v] of Object.entries(MATERIAL)) assert.match(v, /^#[0-9a-f]{6}$/, k)
})

test('materials carry no state hue: OKLCH chroma ≤ 0.06', () => {
  const rows = Object.entries(MATERIAL).map(([k, v]) => [k, v, oklch(v)[1]])
  console.log(rows.map(([k, v, c]) => `${c <= 0.06 ? 'ok  ' : 'FAIL'} C=${c.toFixed(3)} ${k} ${v}`).join('\n'))
  assert.deepEqual(rows.filter(r => r[2] > 0.06).map(r => r[0]), [])
  // every state colour is far more saturated than any material
  for (const s of ['ok', 'active', 'warn', 'bad', 'power']) assert.ok(oklch(PHOSPHOR[s])[1] > 0.12, s)
})

test('text on material ≥ 4.5:1 (silk on pcb, metal-ink on metal and on the highlight)', () => {
  const pairs = [['silk on pcb', MATERIAL.silk, MATERIAL.pcb], ['silk on pcb-edge', MATERIAL.silk, MATERIAL['pcb-edge']],
    ['metal-ink on metal', MATERIAL['metal-ink'], MATERIAL.metal], ['metal-ink on metal-hi', MATERIAL['metal-ink'], MATERIAL['metal-hi']],
    ['silk on plastic', MATERIAL.silk, MATERIAL.plastic]]
  for (const [name, fg, bg] of pairs) {
    const r = contrastRatio(fg, bg)
    console.log(`${r.toFixed(2)}:1 ${name}`)
    assert.ok(r >= 4.5, `${name} ${r.toFixed(2)}:1`)
  }
})

test('state colours as a ring on the board face ≥ 3:1 (Phosphor, and the Nous app colours of the Follow look)', () => {
  // Nous light/dark state colours: the values test_ui1_contrast.mjs reads from the Hermes checkout (bf0203a794)
  const looks = {
    phosphor: Object.fromEntries(['ok', 'active', 'warn', 'bad', 'power'].map(k => [k, PHOSPHOR[k]])),
    'nous light': { ok: '#1f8a65', active: '#4c7f8c', warn: '#c08532', bad: '#cf2d56', power: '#9e94d5' },
    'nous dark': { ok: '#55a583', active: '#6f9ba6', warn: '#c08532', bad: '#e75e78', power: '#9e94d5' }
  }
  const fails = []
  for (const [look, cols] of Object.entries(looks)) {
    for (const [s, c] of Object.entries(cols)) {
      const r = contrastRatio(c, MATERIAL.pcb)
      console.log(`${look.padEnd(10)} ${s.padEnd(6)} ${r.toFixed(2)}:1 on pcb`)
      if (r < 3) fails.push(`${look} ${s} ${r.toFixed(2)}`)
    }
  }
  assert.deepEqual(fails, [])
})

test('materials are identical in both looks: outside PHOSPHOR/FOLLOW, set on .cb-root, never overridden by the theme look', () => {
  for (const k of KEYS) {
    assert.ok(!(k in PHOSPHOR) && !(k in FOLLOW), `${k} must not differ per look`)
  }
  const css = readFileSync(join(SRC, '10-tokens.js'), 'utf8')
  const theme = css.slice(css.indexOf('.cb-root[data-cb-look=theme]'))
  assert.ok(css.indexOf('${tokenVars(MATERIAL)}') > 0 && css.indexOf('${tokenVars(MATERIAL)}') < css.indexOf('.cb-root[data-cb-look=theme]'))
  assert.ok(!theme.includes('MATERIAL'))
  for (const k of KEYS) assert.ok(!new RegExp(`--cb-${k}:`).test(theme), `theme look overrides --cb-${k}`)
})

test('--cb-grid is 3 % in Phosphor (L8)', () => {
  const css = readFileSync(join(SRC, '10-tokens.js'), 'utf8')
  const base = css.slice(css.indexOf('.cb-root{'), css.indexOf('.cb-root[data-cb-look=theme]'))
  assert.match(base, /--cb-grid:color-mix\(in oklab,var\(--cb-ok\) 3%,transparent\);/)
})
