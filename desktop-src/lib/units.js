// Quantity input for the calculators: '4k7', '4.7 kΩ', '10mA', '3V3' → SI value. Pure, no SDK.
// Mirrors circuit_bench/bench_core/units.py (the backend parses again and stays authoritative); the UI uses it to
// show the parsed value and an error next to the field before anything is sent.
//   number [exponent] [SI prefix] [unit]   10 mA, 4.7e3, 100nF, 2.2 µF
//   U_RKM code (letter = decimal point)       4k7, 1R5, R47, 3V3, 2u2
// Prefixes are case-sensitive (m milli, M mega; K is accepted as kilo). Units are case-insensitive. Decimal point only.

export const UNIT_HINT = 'examples: 4k7, 4.7 kΩ, 10mA, 3V3, 100nF, 2.2e-6'

const U_PREFIX_EXP = { p: -12, n: -9, u: -6, 'µ': -6, 'μ': -6, m: -3, k: 3, K: 3, M: 6, G: 9 }
const U_UNIT_WORDS = {
  v: 'V', volt: 'V', volts: 'V', a: 'A', amp: 'A', amps: 'A', 'ω': 'Ω', 'Ω': 'Ω', ohm: 'Ω', ohms: 'Ω', r: 'Ω',
  f: 'F', s: 's', w: 'W', hz: 'Hz'
}
const U_RKM_MARKS = { R: 'Ω', r: 'Ω', V: 'V', v: 'V', A: 'A', W: 'W' }
const U_RKM = /^(\d+)([pnuµμmkKMG]|[RrVvAW])(\d+)(.*)$/s
const U_RKM_LEAD_R = /^[Rr](\d+)(.*)$/s
const U_NUMBER = /^([+\-\u2212]?)((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(.*)$/s

function uUnitWord(word) {
  if (word in U_UNIT_WORDS) return U_UNIT_WORDS[word]
  return U_UNIT_WORDS[word.toLowerCase()] ?? null
}

function uFail(text, why) {
  const err = new Error(`cannot read ${JSON.stringify(String(text))} as a quantity${why ? `: ${why}` : ''}`)
  err.hint = String(text).includes(',') ? `use a decimal point, not a comma; ${UNIT_HINT}` : UNIT_HINT
  throw err
}

/** "4.7" + exponent 3 → 4700 exactly (string scaling avoids float noise). */
function uScaled(digits, exp, text) {
  const m = /^(.*?)(?:[eE]([+-]?\d+))?$/.exec(digits)
  const v = Number(`${m[1]}e${Number(m[2] || 0) + exp}`)
  if (!Number.isFinite(v)) uFail(text, 'out of range')
  return v
}

function uTail(text, rest) {
  const t = rest.replace(/\s+/g, '')
  if (!t) return [0, null]
  const u = uUnitWord(t)
  if (u) return [0, u]
  if (t[0] in U_PREFIX_EXP) {
    const r = t.slice(1)
    if (!r) return [U_PREFIX_EXP[t[0]], null]
    const u2 = uUnitWord(r)
    if (u2) return [U_PREFIX_EXP[t[0]], u2]
  }
  return uFail(text, `unknown unit or prefix "${t}"`)
}

function uParseRkm(text, s) {
  let m = U_RKM.exec(s)
  if (m) {
    const [, whole, mark, frac, rest] = m
    const restClean = rest.replace(/\s+/g, '')
    let restUnit = null
    if (restClean) {
      restUnit = uUnitWord(restClean)
      if (!restUnit) uFail(text, `unknown unit "${rest.trim()}" after the code`)
    }
    if (mark in U_RKM_MARKS) {
      const unit = U_RKM_MARKS[mark]
      if (restUnit && restUnit !== unit) uFail(text, `code ${whole}${mark}${frac} is in ${unit}, not ${restUnit}`)
      return [uScaled(`${whole}.${frac}`, 0, text), unit]
    }
    return [uScaled(`${whole}.${frac}`, U_PREFIX_EXP[mark], text), restUnit]
  }
  m = U_RKM_LEAD_R.exec(s)
  if (m) {
    const [, frac, rest] = m
    const restClean = rest.replace(/\s+/g, '')
    const unit = restClean ? uUnitWord(restClean) : 'Ω'
    if (unit !== 'Ω') uFail(text, 'an R code is in Ω')
    return [uScaled(`0.${frac}`, 0, text), 'Ω']
  }
  return null
}

/** [valueSI, unit|null]; throws Error(message) with .hint. Numbers pass through. */
export function parseRaw(text) {
  if (typeof text === 'number') {
    if (!Number.isFinite(text)) uFail(text, 'not a finite number')
    return [text, null]
  }
  if (typeof text !== 'string') uFail(text, 'expected a number or text')
  const s = text.trim()
  if (!s) uFail(text, 'empty')
  if (s.includes(',')) uFail(text, 'decimal comma')
  const rkm = uParseRkm(text, s)
  if (rkm) return rkm
  const m = U_NUMBER.exec(s)
  if (!m) uFail(text)
  const [, sign, digits, rest] = m
  const [exp, unit] = uTail(text, rest)
  const v = uScaled(digits, exp, text)
  return [sign === '-' || sign === '\u2212' ? -v : v, unit]
}

/**
 * Parse a calculator field. `unit` is the expected unit ('V', 'A', 'Ω', 'F', '' for a plain number).
 * → {ok: true, value, unit} | {ok: false, error, hint}. Empty text → {ok: false, empty: true}.
 */
export function parseQuantity(text, unit = null) {
  if (text === null || text === undefined || (typeof text === 'string' && !text.trim())) {
    return { ok: false, empty: true, error: 'required', hint: UNIT_HINT }
  }
  try {
    const [value, got] = parseRaw(text)
    if (unit === '' && got) return { ok: false, error: `a plain number, not a value in ${got}`, hint: 'give it without a unit' }
    if (unit && got && got !== unit) return { ok: false, error: `expected a value in ${unit}, got ${got}`, hint: `for example 10 m${unit}` }
    return { ok: true, value, unit: unit || got || '' }
  } catch (e) {
    return { ok: false, error: e.message, hint: e.hint || UNIT_HINT }
  }
}
