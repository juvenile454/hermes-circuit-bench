// Contrast maths (WCAG 2.x relative luminance) for the Bench Phosphor tokens. Pure, no SDK.
// Used by tests-js/test_ui1_contrast.mjs to prove the contrast targets: text and state colours ≥ 7:1 on --cb-bg,
// --cb-fg-faint (decoration only) ≥ 3:1; follow-theme text variants ≥ 4.5:1 on the app background.

export function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex).trim())
  if (!m) throw new Error(`not a hex colour: ${hex}`)
  let s = m[1]
  if (s.length === 3) s = s.split('').map(c => c + c).join('')
  return [0, 2, 4].map(i => parseInt(s.slice(i, i + 2), 16))
}

function srgbChannel(c8) {
  const c = c8 / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex)
  return 0.2126 * srgbChannel(r) + 0.7152 * srgbChannel(g) + 0.0722 * srgbChannel(b)
}

export function contrastRatio(a, b) {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/** Straight sRGB mix (`p` of `a` over `b`), the worst case for color-mix tints on dark ground. */
export function mixHex(a, b, p) {
  const ca = hexToRgb(a)
  const cb = hexToRgb(b)
  return '#' + ca.map((v, i) => Math.round(v * p + cb[i] * (1 - p)).toString(16).padStart(2, '0')).join('')
}

/** Rows {fg, bg, ratio, min, pass} for a table of [name, fg, bg, min]. */
export function contrastReport(pairs) {
  return pairs.map(([name, fg, bg, min]) => {
    const ratio = contrastRatio(fg, bg)
    return { name, fg, bg, ratio: Math.round(ratio * 100) / 100, min, pass: ratio >= min }
  })
}

// ─── CSS color-mix(in oklab, …) with alpha, as the browser computes it (CSS Color 4/5) ─────────────

const toHexRgb = rgb => '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')
const linToSrgb = c => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)

/** sRGB hex → OKLab [L, a, b] (Björn Ottosson's matrices). */
export function hexToOklab(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbChannel)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]
}

/** OKLab → sRGB [r, g, b] 0–255 (clipped to the sRGB gamut). */
export function oklabToRgb([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3
  const lin = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s]
  return lin.map(c => linToSrgb(Math.max(0, Math.min(1, c))) * 255)
}

/** color-mix(in oklab, a p, b) with alpha (premultiplied interpolation). Colours are {hex, alpha}. → {hex, alpha} */
export function oklabMix(a, b, p) {
  const aa = a.alpha ?? 1
  const ba = b.alpha ?? 1
  const A = hexToOklab(a.hex).map(v => v * aa)
  const B = hexToOklab(b.hex).map(v => v * ba)
  const alpha = p * aa + (1 - p) * ba
  const lab = A.map((v, i) => (alpha ? (p * v + (1 - p) * B[i]) / alpha : 0))
  return { hex: toHexRgb(oklabToRgb(lab)), alpha }
}

/** A colour with alpha painted over an opaque background (gamma-encoded sRGB, as browsers composite). → hex */
export function composite(c, bgHex) {
  const fg = hexToRgb(c.hex)
  const bg = hexToRgb(bgHex)
  const a = c.alpha ?? 1
  return toHexRgb(fg.map((v, i) => v * a + bg[i] * (1 - a)))
}

/** straight sRGB color-mix with alpha (premultiplied), as `color-mix(in srgb, …)` */
function srgbMix(a, b, p) {
  const aa = a.alpha ?? 1
  const ba = b.alpha ?? 1
  const alpha = p * aa + (1 - p) * ba
  const A = hexToRgb(a.hex)
  const B = hexToRgb(b.hex)
  return { hex: toHexRgb(A.map((v, i) => (alpha ? (p * v * aa + (1 - p) * B[i] * ba) / alpha : 0))), alpha }
}

function splitTop(s) {
  const out = []
  let depth = 0
  let cur = ''
  for (const ch of s) {
    if (ch === '(') depth++
    if (ch === ')') depth--
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue }
    cur += ch
  }
  if (cur.trim()) out.push(cur.trim())
  return out
}

const NAMED = { transparent: { hex: '#000000', alpha: 0 }, black: { hex: '#000000', alpha: 1 }, white: { hex: '#ffffff', alpha: 1 } }

/**
 * Evaluate the CSS colour expressions the Bench tokens use, with the app's variables given as `vars`
 * ({'--ui-green': '#1f8a65' | {hex, alpha} | 'css expression'}) and `scheme` ('light' | 'dark') for light-dark().
 * Supports #hex, named transparent/black/white, var(), color-mix(in oklab|srgb, A [p%], B [q%]), light-dark(A, B).
 * → {hex, alpha}. Throws on anything else, so a token the test cannot evaluate fails loudly.
 */
export function resolveCss(expr, vars = {}, scheme = 'light') {
  const s = String(expr).trim()
  if (/^#[0-9a-f]{3,6}$/i.test(s)) return { hex: '#' + hexToRgb(s).map(v => v.toString(16).padStart(2, '0')).join(''), alpha: 1 }
  if (NAMED[s]) return NAMED[s]
  const m = /^([a-z-]+)\((.*)\)$/s.exec(s)
  if (!m) throw new Error(`cannot evaluate colour: ${s}`)
  const [, fn, body] = m
  const args = splitTop(body)
  if (fn === 'var') {
    const v = vars[args[0]]
    if (v === undefined) {
      if (args.length > 1) return resolveCss(args.slice(1).join(','), vars, scheme)
      throw new Error(`unknown variable ${args[0]}`)
    }
    return typeof v === 'object' ? v : resolveCss(v, vars, scheme)
  }
  if (fn === 'light-dark') return resolveCss(scheme === 'dark' ? args[1] : args[0], vars, scheme)
  if (fn === 'color-mix') {
    const space = /^in\s+(oklab|srgb)$/.exec(args[0])
    if (!space || args.length !== 3) throw new Error(`unsupported color-mix: ${s}`)
    const part = a => {
      const pm = /^(.*?)\s+(\d+(?:\.\d+)?)%$/s.exec(a)
      return pm ? { c: resolveCss(pm[1], vars, scheme), p: Number(pm[2]) / 100 } : { c: resolveCss(a, vars, scheme), p: null }
    }
    const A = part(args[1])
    const B = part(args[2])
    const p = A.p ?? (B.p !== null ? 1 - B.p : 0.5)
    return space[1] === 'oklab' ? oklabMix(A.c, B.c, p) : srgbMix(A.c, B.c, p)
  }
  throw new Error(`unsupported function ${fn}()`)
}
