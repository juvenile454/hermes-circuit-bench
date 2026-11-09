// Formatting helpers (units, percentages, durations, clock times). Pure, no SDK. English UI: decimal point.

const SI = [
  [1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']
]

/** 0.00253 A → "2.53 mA", 4700 Ω → "4.7 kΩ". `digits` significant digits, trailing zeros dropped. */
export function formatSI(value, unit = '', digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (value === 0) return `0 ${unit}`.trim()
  const abs = Math.abs(value)
  let [scale, prefix] = SI[SI.length - 1]
  for (const [s, p] of SI) {
    if (abs >= s * 0.9995) { scale = s; prefix = p; break }
  }
  const n = Number((value / scale).toPrecision(digits))
  return `${n} ${prefix}${unit}`.trim()
}

/** Contract quantity {value, unit, display} → display text; falls back to formatSI. */
export function formatQty(q, digits = 3) {
  if (q === null || q === undefined) return '—'
  if (typeof q === 'number') return formatSI(q, '', digits)
  if (typeof q.display === 'string' && q.display) return q.display
  return formatSI(q.value, q.unit || '', digits)
}

/** 5.6 → "5.6 %" (value already in percent). */
export function formatPct(pct, digits = 1) {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return '—'
  return `${Number(pct.toFixed(digits))} %`
}

/** Fraction 0..1 → "42 %". */
export function formatFraction(f) {
  if (typeof f !== 'number' || !Number.isFinite(f)) return '—'
  return `${Math.round(Math.max(0, Math.min(1, f)) * 100)} %`
}

/** Seconds → "3.9 s", "42 s", "2:05 min". */
export function formatDuration(s) {
  if (typeof s !== 'number' || !Number.isFinite(s) || s < 0) return '—'
  if (s < 10) return `${Number(s.toFixed(1))} s`
  if (s < 60) return `${Math.round(s)} s`
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.round(s - m * 60)).padStart(2, '0')} min`
}

/** ISO 8601 → "22:41:07" (local time, or UTC with {utc: true}). Unknown → "—". */
export function formatClock(iso, { utc = false } = {}) {
  const d = new Date(iso)
  if (!iso || Number.isNaN(d.getTime())) return '—'
  const parts = utc ? [d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()] : [d.getHours(), d.getMinutes(), d.getSeconds()]
  return parts.map(n => String(n).padStart(2, '0')).join(':')
}

/** ISO 8601 → "2026-11-06 18:42" (local time). Unknown → "—". */
export function formatStamp(iso) {
  const d = new Date(iso)
  if (!iso || Number.isNaN(d.getTime())) return '—'
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Long hex digest → first n characters + "…". */
export function shortHash(hex, n = 8) {
  if (typeof hex !== 'string' || !hex) return '—'
  return hex.length > n ? `${hex.slice(0, n)}…` : hex
}

/** "▰▰▱▱▱" bar for done/total (max `width` cells). */
export function cellBar(done, total, width = 10) {
  if (!total || total < 0) return ''
  const cells = Math.min(width, total)
  const filled = Math.round((Math.max(0, Math.min(done, total)) / total) * cells)
  return '▰'.repeat(filled) + '▱'.repeat(cells - filled)
}

/** Keep a number and its unit together: "1 kΩ" → "1\u00a0kΩ" (no line break inside a value). */
export function nbspUnits(text) {
  return String(text ?? '').replace(/(\d) (?=(?:[GMkmµnp]?(?:Ω|F|A|V|W|Hz|s)|%|°C|MB|kB)(?![A-Za-z]))/g, '$1\u00a0')
}

/** Clip text to n characters with an ellipsis. */
export function clip(text, n) {
  const s = String(text ?? '')
  return s.length > n ? `${s.slice(0, Math.max(0, n - 1))}…` : s
}
