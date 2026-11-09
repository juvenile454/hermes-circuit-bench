// Mini schematics of the six calculators of station 02 CALC. Pure functions,
// no SDK, no DOM: calcArt(type, env, opts) returns an SVG string with the circuit the calculator sizes and the values
// of the answer. The desktop computes nothing: every value is the `display` text of the backend answer (or a plain
// string such as the part name). A missing field drops its label; the drawing stays (the topology is the calculator's,
// not data). Self-contained (lib files import nothing): own escape and number helpers with the calcArt prefix.
// Strokes: wires 1.5 px, part bodies 2 px; colours only as var(--cb-…) tokens; no <style>, href,
// <image>, foreignObject or on* attributes (the sanitizeSvg list). Fixed size (never scaled), so 10/11 px text stays
// 10/11 px on screen.

export const CALC_ART_W = 288
const CALC_ART_TYPES = ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo']

/** `display` of a quantity of the answer, else null (never a number we format ourselves). */
export function calcArtDisp(q) {
  return q && typeof q === 'object' && typeof q.display === 'string' && q.display.trim() ? q.display.trim() : null
}

/** A plain string of the answer (part name, load kind), else null. */
function calcArtStr(s) {
  return typeof s === 'string' && s.trim() ? s.trim() : null
}

const CALC_ART_WIRE = { fill: 'none', stroke: 'var(--cb-fg-dim)', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
const CALC_ART_BODY = { fill: 'var(--cb-bg)', stroke: 'var(--cb-fg)', 'stroke-width': 2, 'stroke-linejoin': 'round' }

function calcArtWire(d) {
  return artEl('path', { d, ...CALC_ART_WIRE })
}

/** Resistor zigzag like 03 WIRE, centred on (x, y); horizontal 34×12 or vertical 12×30. */
function calcArtRes(x, y, vertical = false) {
  const len = vertical ? 30 : 34
  const amp = 5
  const lead = 3
  const n = 6
  const step = (len - 2 * lead) / n
  const pts = [[-len / 2, 0], [-len / 2 + lead, 0]]
  for (let i = 0; i < n; i++) pts.push([-len / 2 + lead + step * (i + 0.5), i % 2 ? amp : -amp])
  pts.push([len / 2 - lead, 0], [len / 2, 0])
  const d = pts.map(([a, b], i) => `${i ? 'L' : 'M'}${artNum(vertical ? x + b : x + a)} ${artNum(vertical ? y + a : y + b)}`).join('')
  return artEl('path', { class: 'cb-calc-art-r', d, fill: 'none', stroke: 'var(--cb-fg)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' })
}

/** Junction dot. */
function calcArtDot(x, y) {
  return artEl('circle', { cx: x, cy: y, r: 2.6, fill: 'var(--cb-fg-dim)' })
}

/** Open terminal (supply, GPIO, ADC input). */
function calcArtTerm(x, y) {
  return artEl('circle', { cx: x, cy: y, r: 3.2, fill: 'var(--cb-bg)', stroke: 'var(--cb-fg)', 'stroke-width': 1.5 })
}

/** Ground: lead from (x, y) down 6 px, three bars. */
function calcArtGnd(x, y) {
  const b = y + 6
  return artEl('path', { d: `M${x} ${y}V${b}M${x - 8} ${b}H${x + 8}M${x - 5} ${b + 3.5}H${x + 5}M${x - 2} ${b + 7}H${x + 2}`, ...CALC_ART_WIRE, stroke: 'var(--cb-fg)' })
}

/** Small arrowhead on a wire at (x, y) pointing 'r' or 'd' (the current direction). */
function calcArtArrow(x, y, dir = 'r') {
  const d = dir === 'd' ? `M${x - 3.5} ${y - 3.5}L${x} ${y + 1.5}L${x + 3.5} ${y - 3.5}Z` : `M${x - 3.5} ${y - 3.5}L${x + 1.5} ${y}L${x - 3.5} ${y + 3.5}Z`
  return artEl('path', { d, fill: 'var(--cb-fg-dim)' })
}

/** LED pointing right, centred on (x, y), two light arrows above. */
function calcArtLed(x, y) {
  const arrow = (ax, ay) => `M${ax} ${ay}L${ax + 6} ${ay - 7}M${ax + 6} ${ay - 7}L${ax + 1.5} ${ay - 6}M${ax + 6} ${ay - 7}L${ax + 5} ${ay - 2.5}`
  return artEl('g', { class: 'cb-calc-art-led' },
    artEl('path', { d: `M${x - 7} ${y - 8}L${x + 7} ${y}L${x - 7} ${y + 8}Z`, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${x + 7} ${y - 8}V${y + 8}`, ...CALC_ART_BODY }) +
    artEl('path', { d: arrow(x - 1, y - 11) + arrow(x + 5, y - 9), fill: 'none', stroke: 'var(--cb-fg)', 'stroke-width': 1.2, 'stroke-linecap': 'round' }))
}

/** NPN transistor in a circle centred on (cx, cy): base from the left at cy, collector up and emitter down at cx + 6. */
function calcArtNpn(cx, cy) {
  const ex = cx + 6
  const ey = cy + 12
  return artEl('g', { class: 'cb-calc-art-q' },
    artEl('circle', { cx, cy, r: 16, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${cx - 6} ${cy - 8}V${cy + 8}`, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${cx - 6} ${cy - 4}L${ex} ${cy - 12}M${cx - 6} ${cy + 4}L${ex} ${ey}`, ...CALC_ART_BODY, fill: 'none' }) +
    artEl('path', { d: `M${ex} ${ey}L${ex - 6.5} ${ey - 1}L${ex - 2.5} ${ey - 6}Z`, fill: 'var(--cb-fg)' }))
}

/** N-channel enhancement MOSFET in a circle centred on (cx, cy): gate from the left at cy, drain up and source down
 *  at cx + 6, body arrow into the channel, source tied to the body. */
function calcArtNmos(cx, cy) {
  const lx = cx + 6
  const ch = cx - 2
  return artEl('g', { class: 'cb-calc-art-q' },
    artEl('circle', { cx, cy, r: 16, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${cx - 7} ${cy - 8}V${cy + 8}`, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${ch} ${cy - 10}V${cy - 5}M${ch} ${cy - 2.5}V${cy + 2.5}M${ch} ${cy + 5}V${cy + 10}`, ...CALC_ART_BODY }) +
    artEl('path', { d: `M${ch} ${cy - 7.5}H${lx}V${cy - 12}M${ch} ${cy + 7.5}H${lx}V${cy + 12}M${lx} ${cy}V${cy + 7.5}M${lx} ${cy}H${ch + 5}`, ...CALC_ART_BODY, fill: 'none', 'stroke-width': 1.5 }) +
    artEl('path', { d: `M${ch + 1} ${cy}L${ch + 6} ${cy - 3}L${ch + 6} ${cy + 3}Z`, fill: 'var(--cb-fg)' }))
}

/** Capacitor (two plates) on a vertical lead at x, plates around y; dashed = the bus capacitance (not a part). */
function calcArtCap(x, y, dashed = false) {
  return artEl('path', { d: `M${x - 9} ${y - 2.5}H${x + 9}M${x - 9} ${y + 2.5}H${x + 9}`, ...CALC_ART_BODY, fill: 'none', 'stroke-dasharray': dashed ? '3 2' : undefined })
}

/** Load as a box (x, y = top left). */
function calcArtLoad(x, y, w, hh) {
  return artEl('rect', { class: 'cb-calc-art-load', x, y, width: w, height: hh, rx: 2, ...CALC_ART_BODY, 'stroke-dasharray': '4 2' })
}

const CALC_ART_SIZE = { ref: 10, val: 11, res: 11 }
const CALC_ART_FILL = { ref: 'var(--cb-fg-dim)', val: 'var(--cb-fg)' }

/** Estimated width (monospace 0.6 em, code points) of label parts. */
function calcArtWidth(parts) {
  return parts.reduce((a, [t, role]) => a + [...String(t)].length * 0.6 * CALC_ART_SIZE[role], 0)
}

/**
 * One label: parts [[text, role], …], role ref (10 px, dim), val (11 px, fg) or res (11 px, bold, tone of the result).
 * Parts with a null text drop; a label whose value parts all dropped keeps its ref only when `keepRef`. The label is
 * kept inside the drawing (shifted, never cut); wider than `max` (its free room next to the symbol) it drops.
 */
function calcArtLabel(x, y, parts, { anchor = 'start', keepRef = false, tone = 'fg', track, max = CALC_ART_W - 4 } = {}) {
  const vals = parts.filter(([, role]) => role !== 'ref')
  const live = vals.some(([t]) => t !== null && t !== undefined && t !== '')
  let use = live ? parts.filter(([t]) => t !== null && t !== undefined && t !== '') : keepRef ? parts.filter(([, role]) => role === 'ref') : []
  if (!use.length) return ''
  // a ref part ends with a space only when a value follows
  if (!live) use = use.map(([t, r]) => [String(t).trimEnd(), r])
  const w = calcArtWidth(use)
  if (w > max) return ''
  let x0 = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x
  x0 = Math.max(2, Math.min(CALC_ART_W - 2 - w, x0))
  const fill = role => role === 'res' ? (tone === 'bad' ? 'var(--cb-bad-text)' : tone === 'ok' ? 'var(--cb-ok-text)' : 'var(--cb-fg)') : CALC_ART_FILL[role]
  const spans = use.map(([t, role]) => artEl('tspan', { 'font-size': CALC_ART_SIZE[role], 'font-weight': role === 'res' ? 700 : role === 'val' ? 600 : undefined, fill: fill(role) }, artEsc(t))).join('')
  if (track) track.push(...use.filter(([, r]) => r !== 'ref').map(([t]) => String(t)))
  return artEl('text', { x: x0, y, 'text-anchor': 'start', 'xml:space': 'preserve' }, spans)
}

// ─── the six circuits (absolute coordinates in a CALC_ART_W wide box) ─────

function calcArtCircuitLed(r, inp, L) {
  const y = 34
  return {
    h: 84,
    body: calcArtWire(`M16 ${y}H236V58`) + calcArtTerm(16, y) + calcArtRes(92, y) + calcArtArrow(128, y) + calcArtLed(172, y) + calcArtGnd(236, 58) +
      L(8, 18, [['V ', 'ref'], [calcArtDisp(inp.v_supply), 'val']], { keepRef: true }) +
      L(92, 18, [['R ', 'ref'], [calcArtDisp(r.r_chosen), 'res']], { anchor: 'middle', keepRef: true }) +
      L(92, 57, [['I ', 'ref'], [calcArtDisp(r.i_actual), 'val']], { anchor: 'middle' }) +
      L(172, 59, [['V_f ', 'ref'], [calcArtDisp(inp.v_f), 'val']], { anchor: 'middle', keepRef: true }),
    shown: ['r_chosen', 'i_actual']
  }
}

/** Shared gate/base drive of the NPN and MOSFET switches: GPIO → series R → junction → pull-down to GND. */
function calcArtDrive(cy, rIn, rPd, vDrive, L, refIn) {
  return calcArtWire(`M16 ${cy}H207`) + calcArtTerm(16, cy) + calcArtRes(62, cy) + calcArtDot(114, cy) +
    calcArtWire(`M114 ${cy}V${cy + 46}`) + calcArtRes(114, cy + 24, true) + calcArtGnd(114, cy + 46) +
    L(8, cy + 20, [['GPIO', 'ref']], { keepRef: true }) +
    L(8, cy + 34, [[vDrive, 'val']]) +
    L(62, cy - 16, [[`${refIn} `, 'ref'], [rIn, 'val']], { anchor: 'middle', keepRef: true }) +
    L(106, cy + 22, [['R_PD', 'ref']], { anchor: 'end', keepRef: true }) +
    L(106, cy + 36, [[rPd, 'val']], { anchor: 'end' })
}

function calcArtCircuitNpn(r, inp, L) {
  const cy = 84
  const x = 220 // collector/emitter lead
  return {
    h: 148,
    body: calcArtDrive(cy, calcArtDisp(inp.r_base), calcArtDisp(inp.r_pulldown), calcArtDisp(inp.v_drive), L, 'R_B') +
      calcArtWire(`M${x} 17V30M${x} 56V72M${x} 96V122`) + calcArtTerm(x, 14) + calcArtLoad(x - 7, 30, 14, 26) + calcArtNpn(214, cy) + calcArtGnd(x, 122) +
      L(229, 18, [['V+', 'ref']], { keepRef: true }) +
      L(206, 40, [[calcArtStr(inp.load) ? `load ${calcArtStr(inp.load)}` : null, 'val']], { anchor: 'end' }) +
      L(206, 54, [['I ', 'ref'], [calcArtDisp(inp.i_load), 'val']], { anchor: 'end' }) +
      L(120, cy - 7, [['I_B ', 'ref'], [calcArtDisp(r.i_b), 'res']], { max: 77 }) +
      L(237, cy + 2, [[calcArtStr(inp.part), 'val']], { max: CALC_ART_W - 239 }) +
      // forced β, two lines
      (calcArtDisp(r.forced_beta) ? L(237, cy + 16, [['forced', 'ref']], { keepRef: true, max: CALC_ART_W - 239 }) : '') +
      L(237, cy + 30, [['β ', 'ref'], [calcArtDisp(r.forced_beta), 'val']], { max: CALC_ART_W - 239 }),
    shown: ['i_b', 'forced_beta']
  }
}

function calcArtCircuitMosfet(r, inp, L) {
  const cy = 84
  const x = 220 // drain/source lead
  return {
    h: 174,
    body: calcArtDrive(cy, calcArtDisp(inp.r_gate), calcArtDisp(inp.r_pulldown), calcArtDisp(inp.gate_v), L, 'R_G') +
      calcArtWire(`M${x} 17V30M${x} 56V72M${x} 96V122`) + calcArtTerm(x, 14) + calcArtLoad(x - 7, 30, 14, 26) + calcArtNmos(214, cy) + calcArtGnd(x, 122) +
      L(229, 18, [['V ', 'ref'], [calcArtDisp(inp.v_supply), 'val']], { keepRef: true }) +
      L(206, 40, [['load', 'ref']], { anchor: 'end', keepRef: true }) +
      L(206, 54, [['I ', 'ref'], [calcArtDisp(inp.i_load), 'val']], { anchor: 'end' }) +
      L(120, cy - 7, [['V_GS ', 'ref'], [calcArtDisp(r.v_gs), 'val']], { max: 77 }) +
      L(237, cy + 2, [[calcArtStr(inp.part), 'val']], { max: CALC_ART_W - 239 }) +
      artEl('path', { d: `M8 150H280`, stroke: 'var(--cb-stroke)', 'stroke-width': 1, 'stroke-dasharray': '2 3' }) +
      L(8, 166, [['V_DS(on) ', 'ref'], [calcArtDisp(r.v_ds_on), 'val']]) +
      L(280, 166, [['P loss ', 'ref'], [calcArtDisp(r.p_loss), 'res']], { anchor: 'end' }),
    shown: ['v_gs', 'p_loss', 'v_ds_on']
  }
}

function calcArtCircuitDivider(r, inp, L) {
  const x = 96
  const tap = 75
  return {
    h: 150,
    body: calcArtWire(`M${x} 17V136M${x} ${tap}H200`) + calcArtTerm(x, 14) + calcArtRes(x, 46, true) + calcArtRes(x, 104, true) + calcArtDot(x, tap) +
      calcArtTerm(203, tap) + calcArtGnd(x, 136) + calcArtArrow(x, 26, 'd') +
      L(106, 18, [['V_in ', 'ref'], [calcArtDisp(inp.v_in_max), 'val']], { keepRef: true }) +
      L(108, 47, [['R1 ', 'ref'], [calcArtDisp(inp.r1), 'val']], { keepRef: true }) +
      L(108, 109, [['R2 ', 'ref'], [calcArtDisp(inp.r2), 'val']], { keepRef: true }) +
      L(84, 30, [['I ', 'ref'], [calcArtDisp(r.i_div), 'val']], { anchor: 'end' }) +
      L(212, tap + 4, [['ADC ', 'ref'], [calcArtDisp(r.v_out_max), 'res']], { keepRef: true }) +
      L(140, tap + 18, [['R_src ', 'ref'], [calcArtDisp(r.r_source), 'val']]),
    shown: ['v_out_max', 'i_div', 'r_source']
  }
}

function calcArtCircuitI2c(r, inp, L) {
  const rail = 18
  const sda = 74
  const scl = 96
  const rp = calcArtDisp(r.suggested)
  return {
    h: 140,
    body: calcArtWire(`M40 ${rail}H150M40 ${rail}V${sda}M150 ${rail}V${scl}M40 ${sda}H244M150 ${scl}H244M200 ${scl}V${scl + 9}M200 ${scl + 14}V${scl + 24}`) +
      calcArtRes(40, 46, true) + calcArtRes(150, 46, true) + calcArtDot(40, sda) + calcArtDot(150, scl) + calcArtDot(200, scl) +
      calcArtCap(200, scl + 11.5, true) + calcArtGnd(200, scl + 24) +
      L(158, rail + 4, [['V_DD ', 'ref'], [calcArtDisp(inp.v_dd), 'val']], { keepRef: true }) +
      L(53, 50, [['R_p ', 'ref'], [rp, 'res']], { keepRef: true }) +
      L(163, 50, [['R_p ', 'ref'], [rp, 'res']], { keepRef: true }) +
      L(250, sda + 4, [['SDA', 'ref']], { keepRef: true }) +
      L(250, scl + 4, [['SCL', 'ref']], { keepRef: true }) +
      L(212, scl + 20, [['C_b ', 'ref'], [calcArtDisp(inp.c_bus), 'val']], { keepRef: true }) +
      L(50, scl + 24, [['t_r ', 'ref'], [calcArtDisp(r.suggested_t_r), 'val']]),
    shown: ['suggested', 'suggested_t_r']
  }
}

function calcArtCircuitLdo(r, inp, L) {
  const y = 60
  const part = calcArtStr(inp.part) || calcArtStr(r.part?.id)
  return {
    h: 112,
    body: calcArtWire(`M16 ${y}H104M184 ${y}H272M144 80V94`) + calcArtTerm(16, y) + calcArtTerm(272, y) +
      artEl('rect', { class: 'cb-calc-art-ic', x: 104, y: 40, width: 80, height: 40, rx: 2, ...CALC_ART_BODY }) + calcArtGnd(144, 94) + calcArtArrow(236, y) +
      L(110, 64, [['IN', 'ref']], { keepRef: true }) +
      L(178, 64, [['OUT', 'ref']], { anchor: 'end', keepRef: true }) +
      L(144, 76, [['GND', 'ref']], { anchor: 'middle', keepRef: true }) +
      L(144, 32, [[part, 'val']], { anchor: 'middle' }) +
      L(8, 44, [['V_in ', 'ref'], [calcArtDisp(inp.v_in), 'val']], { keepRef: true }) +
      L(280, 44, [['V_out ', 'ref'], [calcArtDisp(inp.v_out), 'val']], { anchor: 'end', keepRef: true }) +
      L(280, 80, [['I ', 'ref'], [calcArtDisp(inp.i_load), 'val']], { anchor: 'end' }) +
      L(8, 80, [['P ', 'ref'], [calcArtDisp(r.p_total), 'res']]) +
      L(8, 96, [['η ', 'ref'], [calcArtDisp(r.efficiency), 'val']]),
    shown: ['p_total', 'efficiency']
  }
}

const CALC_ART_CIRCUITS = {
  led: calcArtCircuitLed, npn: calcArtCircuitNpn, divider: calcArtCircuitDivider,
  i2c_pullup: calcArtCircuitI2c, mosfet: calcArtCircuitMosfet, ldo: calcArtCircuitLdo
}

const CALC_ART_TITLES = {
  led: 'LED with series resistor', npn: 'NPN low-side switch', divider: 'voltage divider into the ADC',
  i2c_pullup: 'I²C bus with pull-ups', mosfet: 'N-MOSFET low-side switch', ldo: 'linear regulator'
}

/**
 * Mini schematic of a calculator: { svg, label, shown, values } or null for an unknown type.
 *   env   the calc.* answer envelope (or null before the first calculation: the circuit without values)
 *   opts  { tone: 'ok' | 'bad' | 'fg' } colour of the result value (its worst check)
 * `shown` lists the result keys the drawing carries (the card leaves them out of its value rows), `values` the texts
 * drawn, `label` the aria-label.
 */
export function calcArt(type, env, { tone = 'fg' } = {}) {
  if (!CALC_ART_TYPES.includes(type)) return null
  const r = env && env.ok !== false && env.result && typeof env.result === 'object' ? env.result : {}
  const inp = r.inputs && typeof r.inputs === 'object' ? r.inputs : {}
  const values = []
  const L = (x, y, parts, o = {}) => calcArtLabel(x, y, parts, { tone, track: values, ...o })
  const c = CALC_ART_CIRCUITS[type](r, inp, L)
  const svg = artEl('svg', { xmlns: 'http://www.w3.org/2000/svg', class: 'cb-calc-svg', width: CALC_ART_W, height: c.h, viewBox: `0 0 ${CALC_ART_W} ${c.h}`,
    'aria-hidden': 'true', focusable: 'false', 'data-cb-calc-art': type }, c.body)
  const label = `Schematic: ${CALC_ART_TITLES[type]}${values.length ? ` (${values.join(', ')})` : ''}`
  return { svg, label, shown: c.shown.filter(k => calcArtDisp(r[k])), values }
}
