// 02 CALC definitions (fields, units, defaults), request bodies, result rows, "Add to project" ops. Pure; the
// backend computes, the UI parses for feedback only. Field names follow calc.PARAMS.

export const CALC_DEFS = [
  { type: 'led', title: 'LED series resistor', short: 'LED',
    fields: [
      { name: 'v_supply', label: 'V supply', unit: 'V', def: '3.3', required: true },
      { name: 'v_f', label: 'V forward', unit: 'V', def: '2.0', required: true },
      { name: 'i_f', label: 'I forward', unit: 'A', def: '10mA', required: true },
      { name: 'series', label: 'E series', choice: ['E6', 'E12', 'E24'], def: 'E12' }
    ],
    main: 'r_chosen', exact: 'r_exact', deviation: 'r_deviation',
    rows: [['r_exact', 'R exact'], ['i_actual', 'I actual'], ['p_r', 'P resistor'], ['p_rating_min', 'P rating ≥']] },
  { type: 'npn', title: 'NPN low-side switch', short: 'NPN',
    fields: [
      { name: 'v_drive', label: 'V drive (GPIO)', unit: 'V', def: '3V3', required: true },
      { name: 'r_base', label: 'R base', unit: 'Ω', def: '1k', required: true },
      { name: 'i_load', label: 'I load', unit: 'A', def: '13mA', required: true },
      { name: 'r_pulldown', label: 'R pull-down', unit: 'Ω', def: '10k' },
      { name: 'part', label: 'Transistor', text: true, def: '2N2222A' },
      { name: 'load', label: 'Load', choice: ['laser', 'led', 'relay', 'motor', 'resistive', 'other'], def: 'other' }
    ],
    main: 'i_b', rows: [['forced_beta', 'β forced'], ['i_rb', 'I R base'], ['i_pd', 'I pull-down'], ['p_rb', 'P R base']] },
  { type: 'divider', title: 'Voltage divider (ADC)', short: 'DIV',
    fields: [
      { name: 'v_in_max', label: 'V in max', unit: 'V', def: '4.2', required: true },
      { name: 'r1', label: 'R1 (top)', unit: 'Ω', def: '100k', required: true },
      { name: 'r2', label: 'R2 (bottom)', unit: 'Ω', def: '100k', required: true },
      { name: 'adc_range', label: 'ADC max', unit: 'V', def: '' }
    ],
    main: 'v_out_max', rows: [['i_div', 'I divider'], ['r_source', 'R source'], ['p_r1', 'P R1'], ['p_r2', 'P R2']] },
  { type: 'i2c_pullup', title: 'I²C pull-up', short: 'I²C',
    fields: [
      { name: 'v_dd', label: 'V DD', unit: 'V', def: '3V3', required: true },
      { name: 'c_bus', label: 'C bus', unit: 'F', def: '100pF', required: true },
      { name: 'mode', label: 'Mode', choice: ['standard', 'fast'], def: 'standard' },
      { name: 'r_pullup', label: 'R pull-up (check)', unit: 'Ω', def: '' }
    ],
    main: 'suggested', rows: [['r_min', 'R min'], ['r_max', 'R max'], ['suggested_t_r', 't rise'], ['suggested_i_sink', 'I sink']] },
  // mainOptional: a result without headline value still shows (the failed check stays visible)
  { type: 'mosfet', title: 'N-MOSFET low-side switch', short: 'FET',
    fields: [
      { name: 'i_load', label: 'I load', unit: 'A', def: '2A', required: true },
      { name: 'v_supply', label: 'V load supply', unit: 'V', def: '12', required: true },
      { name: 'gate_v', label: 'V gate (GPIO)', unit: 'V', def: '3V3' },
      { name: 'part', label: 'MOSFET', text: true, def: 'AO3400A' },
      { name: 'r_gate', label: 'R gate', unit: 'Ω', def: '100' },
      { name: 'r_pulldown', label: 'R pull-down', unit: 'Ω', def: '100k' },
      { name: 'r_ds_on', label: 'R DS(on) yours', unit: 'Ω', def: '' },
      { name: 't_ambient', label: 'T ambient', suffix: '°C', temp: true, def: '25' }
    ],
    main: 'p_loss', mainOptional: true,
    rows: [['r_ds_on', 'R DS(on)'], ['v_ds_on', 'V drop'], ['t_j', 'T junction'], ['v_gs', 'V GS'], ['i_gate_peak', 'I gate peak']] },
  { type: 'ldo', title: 'Linear regulator (LDO)', short: 'LDO',
    fields: [
      { name: 'v_in', label: 'V in', unit: 'V', def: '5', required: true },
      { name: 'v_out', label: 'V out', unit: 'V', def: '3V3', required: true },
      // 500 mA: an ESP32-S3-WROOM-1 asks for a supply of at least 0.5 A (datasheet v1.8, Table 6-2; the backend cites it)
      { name: 'i_load', label: 'I load', unit: 'A', def: '500mA', required: true },
      { name: 'part', label: 'Regulator', text: true, def: 'AMS1117-3.3' },
      { name: 't_ambient', label: 'T ambient', suffix: '°C', temp: true, def: '25' }
    ],
    main: 'p_total', mainOptional: true,
    rows: [['t_j', 'T junction'], ['efficiency', 'Efficiency'], ['p_load', 'P load'], ['p_q', 'P quiescent'], ['v_headroom', 'V in − V out']] }
]

/** Temperature input in °C ('25', '25 °C', '-10C'); mirrors calc_power._temp (the backend stays authoritative). */
export function parseTempC(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return { ok: false, empty: true, error: 'required' }
  const s = raw.replace(/\s*(?:°\s*C|deg\s*C|C)\s*$/i, '').replace('\u2212', '-')
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(s)) return { ok: false, empty: false, error: 'a temperature in °C, e.g. 25' }
  const value = Number(s)
  if (value < -60 || value > 150) return { ok: false, empty: false, error: 'between -60 and 150 °C' }
  return { ok: true, empty: false, value }
}

export function calcDef(type) {
  return CALC_DEFS.find(d => d.type === type) || null
}

/** Initial form values of a calculator: defaults, or the inputs of a stored project calc (SI numbers). */
const CALC_PREFIX = [[1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'u'], [1e-9, 'n'], [1e-12, 'p']]

/** SI number → short input text the parser reads back: 1000 Ω → "1k", 0.013 A → "13mA", 3.3 V → "3.3". */
export function siInputText(value, unit) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value)
  if (value === 0) return '0'
  const a = Math.abs(value)
  const [mul, pre] = CALC_PREFIX.find(([m]) => a >= m * 0.9999999) || CALC_PREFIX[CALC_PREFIX.length - 1]
  const m = Number((value / mul).toPrecision(6))
  const u = unit === 'Ω' || !unit ? '' : unit
  return pre ? `${m}${pre}${u}` : String(m)
}

export function initialForm(def, stored = null) {
  const out = {}
  for (const f of def.fields) {
    const v = stored?.inputs?.[f.name]
    out[f.name] = v === undefined || v === null ? f.def
      : typeof v === 'object' && v.display ? v.display : typeof v === 'number' && f.unit !== undefined ? siInputText(v, f.unit) : String(v)
  }
  return out
}

/** Validate a form (parse = parseQuantity) → {ok, body, errors}; quantities go as typed text (backend parses). */
export function buildCalcBody(def, form, parse) {
  const body = {}
  const errors = {}
  for (const f of def.fields) {
    const raw = String(form[f.name] ?? '').trim()
    if (!raw) {
      if (f.required) errors[f.name] = 'required'
      continue
    }
    if (f.choice) {
      if (!f.choice.includes(raw)) errors[f.name] = `one of ${f.choice.filter(Boolean).join(', ')}`
      else body[f.name] = raw
    } else if (f.text) {
      body[f.name] = raw.slice(0, 40)
    } else if (f.temp) {
      const t = parseTempC(raw)
      if (!t.ok) errors[f.name] = t.error
      else body[f.name] = raw
    } else {
      const q = parse(calcPlainText(f, raw), f.unit)
      if (!q.ok) errors[f.name] = q.error
      else body[f.name] = raw
    }
  }
  // one_of: a set complete, else _need + the empty set fields
  if (def.oneOf && !def.oneOf.some(s => s.every(n => body[n] !== undefined))) {
    errors._need = calcNeedText(def)
    for (const n of def.oneOf.flat()) if (body[n] === undefined && !errors[n]) errors[n] = 'one set required'
  }
  return { ok: !Object.keys(errors).length, body, errors }
}

/** Raw GET /calc entry (choices, one_of). */
export function calcRawMeta(env, kind) {
  const list = env?.ok ? env.result?.calculators : null
  return (Array.isArray(list) && list.find(c => c && c.kind === kind)) || null
}

/** Def with backend choices ('' first unless required + default) and one_of. */
export function calcApplyMeta(def, raw) {
  if (!raw || !def) return def
  const ch = new Map((raw.params || []).filter(p => p && Array.isArray(p.choices) && p.choices.length).map(p => [p.name, p.choices.map(String)]))
  const fields = def.fields.map(f => {
    const c = ch.get(f.name)
    if (!c) return f
    const d = c.includes(f.def) ? f.def : ''
    return { ...f, choice: f.required && d ? c : ['', ...c], def: d }
  })
  const oneOf = (Array.isArray(raw.one_of) ? raw.one_of : []).filter(s => Array.isArray(s) && s.length && s.every(n => fields.some(f => f.name === n)))
  return { ...def, fields, ...(oneOf.length ? { oneOf } : {}) }
}

/** "needs V out, or R top + R bottom" */
export function calcNeedText(def) {
  const label = n => def.fields.find(f => f.name === n)?.label || calcParamLabel(n)
  return `needs ${(def.oneOf || []).map(s => s.map(label).join(' + ')).join(', or ')}`
}

/** Worst check (only passed is checked): 'failed' > 'not_checked' (skipped, unknown) > 'passed'; null. */
export function worstCheck(checks) {
  const list = Array.isArray(checks) ? checks : []
  if (!list.length) return null
  if (list.some(c => c?.status === 'failed')) return 'failed'
  return list.every(c => c?.status === 'passed') ? 'passed' : 'not_checked'
}

/** Colour of a result value from its worst check: failed → bad, not checked → neutral, passed → ok. */
export function valueTone(checks) {
  const w = worstCheck(checks)
  return w === 'failed' ? 'bad' : w === 'passed' ? 'ok' : 'fg'
}

/** The headline value, E-series deviation and secondary rows of a calc.* result envelope. */
export function calcView(def, env) {
  const r = env?.result || {}
  if (def.generic) {
    // generic: headline = result.main or the first quantity, the rest are rows
    const rows = calcResultRows(r)
    const at = rows.findIndex(x => x.k === r.main)
    const all = at > 0 ? [rows[at], ...rows.filter((_, i) => i !== at)] : rows
    const ok = Boolean(env?.ok)
    return { ok, main: all[0]?.q || (ok ? { value: null, unit: '', display: '—' } : null), mainLabel: all[0]?.label || 'result',
      deviation: null, exact: null, series: null, rows: all.slice(1), formula: typeof r.formula === 'string' ? r.formula : null,
      steps: Array.isArray(r.steps) ? r.steps : [], hfe: null, adc: null }
  }
  const q = k => (r[k] && typeof r[k] === 'object' && 'display' in r[k] ? r[k] : null)
  const main = q(def.main) || (def.mainOptional && env?.ok ? { value: null, unit: '', display: '—' } : null)
  return {
    ok: Boolean(env?.ok) && Boolean(main),
    main,
    mainLabel: { led: `R (${r.series || 'E12'})`, npn: 'I base', divider: 'V out max', i2c_pullup: 'R suggested',
      mosfet: 'P conduction', ldo: 'P regulator' }[def.type],
    deviation: def.deviation ? q(def.deviation) : null,
    exact: def.exact ? q(def.exact) : null,
    series: r.series || (def.type === 'i2c_pullup' ? 'E12' : null),
    rows: def.rows.map(([k, label]) => ({ k, label, q: q(k) })).filter(x => x.q),
    formula: typeof r.formula === 'string' ? r.formula : null,
    steps: Array.isArray(r.steps) ? r.steps : [],
    hfe: r.hfe && typeof r.hfe === 'object' ? r.hfe : null,
    adc: r.adc ?? null
  }
}

function siOf(v) {
  return v && typeof v === 'object' && 'value' in v ? v.value : v
}

function refNumbers(parts, letter) {
  const re = new RegExp(`^${letter}(\\d+)$`)
  return (parts || []).map(p => re.exec(p.ref)).filter(Boolean).map(m => Number(m[1]))
}

/** Next free reference with a prefix (R → R5 when R1..R4 exist). */
export function nextRef(parts, letter, taken = []) {
  const used = new Set([...refNumbers(parts, letter), ...refNumbers(taken.map(ref => ({ ref })), letter)])
  let n = 1
  while (used.has(n)) n++
  return `${letter}${n}`
}

/** Next free calc id of a type: led-1, led-2 … */
export function nextCalcId(project, type) {
  const prefix = type === 'i2c_pullup' ? 'i2c' : type === 'divider' ? 'div' : type
  const ids = new Set((project?.calcs || []).map(c => c.id))
  let n = 1
  while (ids.has(`${prefix}-${n}`)) n++
  return `${prefix}-${n}`
}

function ohmsText(q) {
  const v = siOf(q)
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  const [scale, p] = v >= 1e6 ? [1e6, 'M'] : v >= 1e3 ? [1e3, 'k'] : [1, '']
  return `${Number((v / scale).toPrecision(3))} ${p}Ω`
}

/** Parts a calculation adds to the BOM (refs continue the project's numbering). */
export function partsFromCalc(type, env, project, calcId) {
  const r = env?.result || {}
  const inp = r.inputs || {}
  const parts = project?.parts || []
  const out = []
  const add = (letter, kind, value, extra = {}) => {
    if (!value) return
    const ref = nextRef(parts, letter, out.map(p => p.ref))
    out.push({ ref, kind, value, from_calc: calcId, ...extra })
  }
  if (type === 'led') {
    add('R', 'resistor', ohmsText(r.r_chosen))
    add('LED', 'led', 'LED')
  } else if (type === 'npn') {
    add('R', 'resistor', ohmsText(inp.r_base))
    add('R', 'resistor', ohmsText(inp.r_pulldown))
    add('Q', 'transistor', typeof inp.part === 'string' ? inp.part : 'NPN')
  } else if (type === 'divider') {
    add('R', 'resistor', ohmsText(inp.r1))
    add('R', 'resistor', ohmsText(inp.r2))
  } else if (type === 'i2c_pullup') {
    const v = ohmsText(r.suggested)
    add('R', 'resistor', v)
    add('R', 'resistor', v)
  } else if (type === 'mosfet') {
    add('R', 'resistor', ohmsText(inp.r_gate))
    add('R', 'resistor', ohmsText(inp.r_pulldown))
    add('Q', 'transistor', typeof inp.part === 'string' ? inp.part : 'N-MOSFET')
  } else if (type === 'ldo') {
    add('U', 'ic', typeof inp.part === 'string' ? inp.part : 'LDO')
  }
  return out
}

/** PATCH ops for "Add to project": add_calc (inputs as SI numbers like the demo recipe) + add_parts. */
export function calcOps(type, env, project) {
  const id = nextCalcId(project, type)
  const r = env?.result || {}
  const inputs = {}
  for (const [k, v] of Object.entries(r.inputs || {})) inputs[k] = siOf(v)
  const result = { summary: env?.summary || '', checks: env?.checks || [] }
  for (const [k, v] of Object.entries(r)) if (k !== 'inputs' && k !== 'steps') result[k] = v
  const ops = [{ op: 'add_calc', calc: { id, type, inputs, result, assumptions: env?.assumptions || [], sources: (env?.sources || []).map(s => s.id) } }]
  const parts = partsFromCalc(type, env, project, id)
  if (parts.length) ops.push({ op: 'add_parts', parts })
  return { id, ops, parts }
}

// ─── Result bands and check chips (pure; the card only lays them out) ──────────────────

/** A quantity of the answer with a display text, else null. */
function calcQ(x) {
  return x && typeof x === 'object' && typeof x.display === 'string' && x.display.trim() ? x : null
}

/** Finite number of a quantity, else null. */
function calcNum(x) {
  const v = calcQ(x)?.value
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** Position on a track, 0…1, or null (never NaN). Drawing only: the number is never shown. */
function calcFrac(a, b) {
  if (a === null || b === null || !(b > 0) || a < 0) return null
  const f = a / b
  return Number.isFinite(f) ? Math.max(0, Math.min(1, f)) : null
}

/** Check whose id ends with `.<suffix>` → its status ('passed' | 'failed' | …) or null. */
function calcCheckStatus(checks, suffix) {
  const c = (Array.isArray(checks) ? checks : []).find(x => typeof x?.id === 'string' && x.id.endsWith(`.${suffix}`))
  return c ? String(c.status || 'unknown') : null
}

/** Tone of a single check status (a failure is never green; not checked is neutral). */
export function calcCheckTone(status) {
  return status === 'failed' ? 'bad' : status === 'passed' ? 'ok' : 'fg'
}

/** The assumption with a key, else null. */
function calcAssumption(env, key) {
  const a = (Array.isArray(env?.assumptions) ? env.assumptions : []).find(x => x?.key === key)
  return a && typeof a.value === 'string' ? { value: a.value, reason: typeof a.reason === 'string' ? a.reason : '' } : null
}

/** Result bands from the answer only: ruler (LED exact → E-series, deviation), meter (LED p_r vs p_rating_min;
 *  LDO/MOSFET T_A…T_J max, t_j tone), window (I²C R_min…R_max, suggested on a log track). Missing fields: no band;
 *  frac null when not drawable; `keys` = result keys shown (left out of the value rows). */
export function calcBands(def, env) {
  const r = env && env.ok && env.result && typeof env.result === 'object' ? env.result : null
  if (!r || !def) return []
  const inp = r.inputs && typeof r.inputs === 'object' ? r.inputs : {}
  const out = []
  if (def.type === 'led') {
    const exact = calcQ(r.r_exact)
    const chosen = calcQ(r.r_chosen)
    if (exact && chosen) {
      const dev = calcQ(r.r_deviation)
      const dv = calcNum(r.r_deviation)
      out.push({ kind: 'ruler', id: 'r', keys: ['r_exact', 'r_chosen', 'r_deviation'],
        from: { label: 'exact', display: exact.display },
        to: { label: typeof r.series === 'string' ? r.series : 'chosen', display: chosen.display },
        delta: dev ? `${dv !== null && dv > 0 && !/^[+−-]/.test(dev.display) ? '+' : ''}${dev.display}` : null,
        down: calcNum(r.r_chosen) !== null && calcNum(r.r_exact) !== null && calcNum(r.r_chosen) < calcNum(r.r_exact) })
    }
    const p = calcQ(r.p_r)
    const lim = calcQ(r.p_rating_min)
    if (p && lim) {
      const a = calcAssumption(env, 'p_rating')
      out.push({ kind: 'meter', id: 'p', keys: ['p_r', 'p_rating_min'], label: 'P resistor', value: p.display,
        limitLabel: 'rating ≥', limit: lim.display, start: null, frac: calcFrac(calcNum(r.p_r), calcNum(r.p_rating_min)),
        tone: 'fg', note: a ? { lead: 'rating =', value: a.value, reason: a.reason } : null })
    }
  } else if (def.type === 'ldo' || def.type === 'mosfet') {
    const tj = calcQ(r.t_j)
    const max = calcQ(r.part?.t_j_max)
    if (tj && max) {
      const ta = calcQ(inp.t_ambient)
      const t0 = ta ? calcNum(ta) : null
      const t1 = calcNum(r.t_j)
      const t2 = calcNum(r.part.t_j_max)
      const theta = calcQ(r.part?.r_th_ja)
      const st = calcCheckStatus(env.checks, 't_j')
      out.push({ kind: 'meter', id: 't', keys: ['t_j'], label: 'T junction', value: tj.display, limitLabel: 'T_J max', limit: max.display,
        start: ta ? ta.display : null,
        frac: t0 === null || t1 === null || t2 === null ? null : calcFrac(t1 - t0, t2 - t0),
        tone: calcCheckTone(st), status: st,
        note: theta ? { lead: def.type === 'ldo' ? 'θ_JA' : 'R_θJA', value: theta.display, reason: typeof theta.conditions === 'string' ? theta.conditions : '' } : null })
    }
  } else if (def.type === 'i2c_pullup') {
    const lo = calcQ(r.r_min)
    const hi = calcQ(r.r_max)
    const s = calcQ(r.suggested)
    if (lo && hi && s) {
      const a = calcNum(r.r_min)
      const b = calcNum(r.r_max)
      const v = calcNum(r.suggested)
      let frac = null
      if (a > 0 && b > a && v > 0) {
        const f = Math.log(v / a) / Math.log(b / a)
        frac = Number.isFinite(f) ? Math.max(0, Math.min(1, f)) : null
      }
      const st = calcCheckStatus(env.checks, 'window')
      out.push({ kind: 'window', id: 'w', keys: ['r_min', 'r_max'], min: { label: 'R min', display: lo.display }, max: { label: 'R max', display: hi.display },
        mark: s.display, frac, tone: calcCheckTone(st), status: st })
    }
  }
  return out
}

const CALC_CHECK_WORDS = { passed: 'passed', failed: 'failed', skipped: 'skipped', not_checked: 'not checked' }
const CALC_CHECK_SYMBOLS = { passed: '✓', failed: '✕', skipped: '○', not_checked: '?' }

/** Checks as chips: symbol + name + status word (state never by colour alone, a failure never green). */
export function calcChips(checks) {
  return (Array.isArray(checks) ? checks : []).filter(c => c && typeof c === 'object').map((c, i) => {
    const status = CALC_CHECK_WORDS[c.status] ? c.status : 'unknown'
    const id = typeof c.id === 'string' ? c.id : `check-${i + 1}`
    const name = id.split('.').slice(2).join(' ').replace(/_/g, ' ') || id
    return { id, name, status, word: CALC_CHECK_WORDS[status] || 'unknown', sym: CALC_CHECK_SYMBOLS[status] || '?',
      tone: status === 'failed' ? 'bad' : status === 'passed' ? 'ok' : 'dim', detail: typeof c.detail === 'string' ? c.detail : '' }
  })
}

/** Steps of the formula drawer: [{name, expr, value}] with texts only (a step without a name is left out). */
export function calcSteps(steps) {
  return (Array.isArray(steps) ? steps : []).filter(s => s && typeof s.name === 'string' && s.name)
    .map(s => ({ name: s.name, expr: typeof s.expr === 'string' ? s.expr : '', value: calcQ(s.value)?.display || '' }))
}

/** The formula string split at '; ' into one line per equation. */
export function calcFormulaLines(formula) {
  return typeof formula === 'string' ? formula.split(/;\s+/).map(x => x.trim()).filter(Boolean) : []
}

/** Does the typed text already name the unit? ("10mA" → A, "3V3" → V, "4k7 ohm" → Ω) */
export function calcTypedUnit(text, unit) {
  const t = String(text ?? '')
  return unit === 'Ω' ? /Ω|ohm/i.test(t) : unit ? t.toLowerCase().includes(unit.toLowerCase()) : false
}

/** Verdict next to the headline value: symbol + words (counted, not computed). */
export function calcVerdict(checks) {
  const list = (Array.isArray(checks) ? checks : []).filter(c => c && typeof c === 'object')
  const n = st => list.filter(c => c.status === st).length
  const worst = worstCheck(list)
  if (worst === 'failed') return ['✕', `${n('failed')} of ${list.length} failed`, 'bad']
  if (worst === 'not_checked') return ['?', `${list.length - n('passed')} of ${list.length} not checked`, 'dim']
  if (worst === 'passed') return ['✓', list.length === 1 ? 'check passed' : `all ${list.length} passed`, 'ok']
  return null
}

// a GET /calc kind without a def above gets a generic card (params as inputs, envelope only).

const CALC_QTY_UNITS = ['V', 'A', 'Ω', 'F', 'Hz', 'W', 's'] // units lib/units.js reads; 'K' would read as kilo

/** Input name → label: "v_in" → "V in", "r_shunt" → "R shunt", "n_leds" → "N leds". */
export function calcParamLabel(name) {
  const parts = String(name || '').split('_').filter(Boolean)
  if (!parts.length) return ''
  if (parts[0].length === 1) parts[0] = parts[0].toUpperCase()
  else parts[0] = parts[0][0].toUpperCase() + parts[0].slice(1)
  return parts.join(' ')
}

/** Field of a register param: quantity, °C, plain number (''/int/K) or text. */
function calcMetaField(p) {
  const unit = typeof p.unit === 'string' ? p.unit : ''
  const d = p.default
  const f = { name: p.name, label: calcParamLabel(p.name), required: Boolean(p.required) }
  if (CALC_QTY_UNITS.includes(unit)) Object.assign(f, { unit, def: typeof d === 'number' ? siInputText(d, unit) : typeof d === 'string' ? d : '' })
  else if (unit === '°C') Object.assign(f, { suffix: '°C', temp: true, def: typeof d === 'number' || typeof d === 'string' ? String(d) : '' })
  else if (unit === '' || unit === 'int' || unit === 'K') Object.assign(f, { unit: '', suffix: unit === 'K' ? 'K' : undefined, kelvin: unit === 'K', def: typeof d === 'number' ? String(d) : '' })
  else Object.assign(f, { text: true, def: typeof d === 'string' || typeof d === 'number' ? String(d) : '' })
  return f
}

/** Text for the unit parser: a kelvin field may end in "K" (else read as kilo). */
export function calcPlainText(f, raw) {
  return f?.kelvin ? String(raw ?? '').replace(/\s*K$/, '') : raw
}

/** Short tag: one word → 4 letters (OPTO), more → initials (CS). */
const calcShort = kind => {
  const w = kind.split('_').filter(Boolean)
  return (w.length > 1 ? w.map(x => x[0]).join('') : (w[0] || kind).slice(0, 4)).toUpperCase()
}

/** Generic card definition of a register entry. */
export function calcGenericDef(meta) {
  const kind = String(meta?.kind || '')
  return { type: kind, generic: true, title: meta?.title || kind, short: calcShort(kind),
    summary: typeof meta?.summary === 'string' ? meta.summary : '', group: meta?.group || 'basics',
    fields: (Array.isArray(meta?.params) ? meta.params : []).filter(p => p && typeof p.name === 'string').map(calcMetaField) }
}

/** Quantities and short texts of an answer in order: [{k, label, q}]. */
export function calcResultRows(result) {
  const r = result && typeof result === 'object' ? result : {}
  const out = []
  for (const [k, v] of Object.entries(r)) {
    if (['inputs', 'steps', 'formula', 'checks', 'summary', 'main'].includes(k)) continue
    if (calcQ(v)) out.push({ k, label: calcParamLabel(k), q: v })
    else if ((typeof v === 'string' && v.trim() && v.length <= 32) || (typeof v === 'number' && Number.isFinite(v))) out.push({ k, label: calcParamLabel(k), q: { display: String(v) } })
  }
  return out
}

/** Groups [{id, defs}]: basics (the six cards, also without GET /calc) first, then the register groups; none empty. */
export function calcGroups(list, groups = []) {
  const metas = Array.isArray(list) ? list : []
  const order = ['basics', ...(Array.isArray(groups) ? groups : []).filter(g => typeof g === 'string' && g !== 'basics')]
  for (const m of metas) if (!order.includes(m.group)) order.push(m.group)
  const defsOf = id => [...(id === 'basics' ? CALC_DEFS : []),
    ...metas.filter(m => (m.group || 'basics') === id && !calcDef(m.kind)).map(calcGenericDef)]
  return order.map(id => ({ id, defs: defsOf(id) })).filter(g => g.defs.length)
}
