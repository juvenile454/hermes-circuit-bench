// Station 03 WIRE helpers: building blocks (mirror of bench_core/schematic.blocks(), the backend validates again),
// SVG safety check, part ↔ wiring-row coupling, GPIO of a stored circuit. Pure.

export const WIRE_BLOCKS = [
  { block: 'npn_low_side', title: 'NPN low-side driver', params: [
    { name: 'r_base', label: 'R base', unit: 'Ω', def: '1k', required: true },
    { name: 'r_pulldown', label: 'R pull-down', unit: 'Ω', def: '10k' },
    { name: 'transistor', label: 'Transistor', text: true, def: '2N2222A' },
    { name: 'load', label: 'Load', text: true, def: 'load' },
    { name: 'supply', label: 'Load supply', choice: ['5V', '3V3'], def: '5V' },
    { name: 'net', label: 'Net', net: true, def: 'LOAD_EN' }] },
  { block: 'led', title: 'LED with series resistor', params: [
    { name: 'r_series', label: 'R series', unit: 'Ω', def: '150', required: true },
    { name: 'led', label: 'LED', text: true, def: 'LED' },
    { name: 'active', label: 'Active', choice: ['high', 'low'], def: 'high' },
    { name: 'net', label: 'Net', net: true, def: 'LED' }] },
  { block: 'button_pullup', title: 'Push button with pull-up', params: [
    { name: 'r_pullup', label: 'R pull-up', unit: 'Ω', def: '10k' },
    { name: 'button', label: 'Button', text: true, def: 'push button' },
    { name: 'net', label: 'Net', net: true, def: 'BUTTON' }] },
  { block: 'divider', title: 'Voltage divider', params: [
    { name: 'r1', label: 'R1 (top)', unit: 'Ω', def: '100k', required: true },
    { name: 'r2', label: 'R2 (bottom)', unit: 'Ω', def: '100k', required: true },
    { name: 'v_in', label: 'V in (label)', unit: 'V', def: '' },
    { name: 'source', label: 'Source', text: true, def: 'input' },
    { name: 'input_net', label: 'Input net', net: true, def: 'VIN' },
    { name: 'net', label: 'Net', net: true, def: 'VSENSE' }] }
]

/** Form of a block id: from `list` (offered blocks) first, then the base and extra blocks. */
export function wireBlock(id, list = null) {
  return (list || []).find(b => b.block === id) || WIRE_BLOCKS.find(b => b.block === id) || WIRE_EXTRA_BLOCKS.find(b => b.block === id) || null
}

const WIRE_NET_RE = /^[A-Za-z0-9_+.-]{1,32}$/

/** Form → {ok, params, errors}. Ohm/volt fields go as SI numbers (schematic params are numbers), parsed with `parse`. */
export function buildWireParams(block, form, parse) {
  const params = {}
  const errors = {}
  for (const p of block.params) {
    const raw = String(form[p.name] ?? '').trim()
    if (!raw) { if (p.required) errors[p.name] = 'required'; continue }
    if (p.choice) { if (p.choice.includes(raw)) params[p.name] = raw; else errors[p.name] = `one of ${p.choice.join(', ')}` }
    else if (p.net) { if (WIRE_NET_RE.test(raw)) params[p.name] = raw; else errors[p.name] = 'letters, digits, _ + . -' }
    else if (p.part) { if (/^[A-Z][A-Z0-9_]{0,15}$/.test(raw)) params[p.name] = raw; else errors[p.name] = 'a part ref such as U1' }
    else if (p.text) params[p.name] = raw.slice(0, 40)
    else {
      const q = parse(raw, p.unit)
      if (q.ok) params[p.name] = q.value; else errors[p.name] = q.error
    }
  }
  return { ok: !Object.keys(errors).length, params, errors }
}

/** Form values from stored params (numbers shown with SI prefixes by `fmt`). */
export function wireForm(block, stored = {}, fmt = v => String(v)) {
  const out = {}
  for (const p of block.params) {
    const v = stored?.[p.name]
    out[p.name] = v === undefined || v === null ? p.def : typeof v === 'number' && p.unit ? fmt(v, p.unit) : String(v)
  }
  return out
}

/**
 * The backend SVG is inserted inline (stroke = currentColor → bench colours). Refuse anything active: scripts,
 * event handlers, foreign objects, external references. → {ok, svg|reason}
 */
export function sanitizeSvg(text) {
  const s = String(text || '').trim()
  if (!/^<svg[\s>]/.test(s) || !/<\/svg>\s*$/.test(s)) return { ok: false, reason: 'not an SVG document' }
  if (s.length > 400_000) return { ok: false, reason: 'SVG too large' }
  const bad = [/<script/i, /<foreignObject/i, /\son[a-z]+\s*=/i, /javascript:/i, /<iframe/i, /<image/i, /\b(?:xlink:)?href\s*=/i, /<!ENTITY/i, /<style/i]
  for (const re of bad) if (re.test(s)) return { ok: false, reason: `unsafe SVG content (${re.source})` }
  return { ok: true, svg: s }
}

/** "R1.2" → "R1", "J1-20 · IO14" → "J1", "Q1.B" → "Q1". */
export function refOfEnd(end) {
  const m = /^([A-Z][A-Z_]*\d+)/.exec(String(end || '').trim())
  return m ? m[1] : null
}

/** Board rails and ground as bench_core/wiring.py names them (RAILS, GROUND); a test keeps them equal. */
export const WIRE_RAILS = ['3V3', '5V']
export const WIRE_GROUND = 'GND'

/** Meaning of a net for its colour: board supply → power, ground → ground, else signal. */
export function wireNetClass(net) {
  return WIRE_RAILS.includes(net) ? 'power' : net === WIRE_GROUND ? 'ground' : 'signal'
}

/** Wiring rows with the part refs at both ends (hover coupling part ↔ row) and the net's class. */
export function wiringRows(wiring) {
  return (wiring || []).map((w, i) => ({ i, from: w.from, to: w.to, net: w.net, netClass: wireNetClass(w.net),
    refs: [...new Set([refOfEnd(w.from), refOfEnd(w.to)].filter(Boolean))] }))
}

/** Refs in an SVG (data-ref attributes, single or double quoted), first occurrence order. */
export function svgRefs(svg) {
  return [...new Set([...String(svg || '').matchAll(/data-ref=(["'])([A-Z][A-Z0-9_]*)\1/g)].map(m => m[2]))]
}

/** viewBox of the backend SVG → {x, y, w, h} or null. The plan never draws below scale 1, so its smallest text
 *  (pin markers, font-size 10) stays ≥ 10 px. */
export function svgViewBox(svg) {
  const m = /<svg\b[^>]*\sviewBox=(["'])([^"']+)\1/.exec(String(svg || ''))
  const n = m ? m[2].trim().split(/[\s,]+/).map(Number) : []
  return n.length === 4 && n.every(Number.isFinite) && n[2] > 0 && n[3] > 0 ? { x: n[0], y: n[1], w: n[2], h: n[3] } : null
}

/** Highlight in the plan and the tables: {refs: [...], net} (either may be empty). */
export function wireHl(refs = [], net = null) {
  const r = (refs || []).filter(x => /^[A-Z][A-Z0-9_]*$/.test(x))
  const n = typeof net === 'string' && /^[A-Za-z0-9_+.-]{1,32}$/.test(net) ? net : null
  return r.length || n ? { refs: r, net: n } : null
}

/** Identity of a highlight (null → ''), for "nothing changed" checks. */
export function wireHlKey(hl) {
  return hl ? `${hl.refs.join(',')}|${hl.net || ''}` : ''
}

/** Is an SVG element (its data-ref / data-net / data-pin) part of the highlight? */
export function wireHlHas(hl, { ref = null, net = null, pin = null } = {}) {
  if (!hl) return false
  const pinRef = pin ? refOfEnd(pin) : null
  return Boolean((net && hl.net === net) || (ref && hl.refs.includes(ref)) || (pinRef && hl.refs.includes(pinRef)))
}

/** Hover target under the pointer: walk from the element up to (not including) `stop` and take the first
 *  data-ref (a part) or data-net (a net: wire, port, net label). `attr(node, name)` reads an attribute. */
export function wireHoverTarget(node, stop, attr = (n, k) => n?.getAttribute?.(k) ?? null) {
  for (let n = node; n && n !== stop; n = n.parentNode) {
    const ref = attr(n, 'data-ref')
    if (ref) return wireHl([ref])
    const pin = attr(n, 'data-pin')
    if (pin) return wireHl([refOfEnd(pin)].filter(Boolean))
    const net = attr(n, 'data-net')
    if (net) return wireHl([], net)
  }
  return null
}

/** Row selected for a highlight: same net, or (a part highlight) a part at one of its ends. */
export function wireRowOn(hl, row) {
  if (!hl) return false
  return hl.net ? row.net === hl.net : row.refs.some(r => hl.refs.includes(r))
}

/** Highlight of a hovered row: its net and the parts at its ends. Only refs of `parts` count (a board header such
 *  as J1 in "J1-20 · IO14" is a port of the plan, not a part). */
export function wireRowHl(row, parts = []) {
  const own = new Set((parts || []).map(p => p.ref))
  return wireHl(row.refs.filter(r => own.has(r)), row.net)
}

/** Warnings split for the inspector: danger/caution as warning cards, the rest (info) in the list. */
export function wireWarnings(warnings) {
  const ws = warnings || []
  return { cards: ws.filter(w => w.severity === 'danger' || w.severity === 'caution'), notes: ws.filter(w => w.severity !== 'danger' && w.severity !== 'caution') }
}

/** GPIO of a stored circuit: the assignment on the circuit's net, else the role named like the circuit id. */
export function circuitGpio(project, circuit) {
  const as = project?.assignments || []
  const net = circuit?.params?.net
  const hit = (net && as.find(a => a.net === net)) || as.find(a => a.role === String(circuit?.id || '').toUpperCase())
  return hit ? hit.pin : null
}

/** Safe file name for "Save SVG". */
export function svgFileName(project, circuitId) {
  const clean = x => String(x || '').toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
  return `${clean(project?.id) || 'bench'}-${clean(circuitId) || 'circuit'}.svg`
}

// more blocks (module, level_shifter) only when the backend names them.

/** Local forms beyond the base set; `module` draws a module part of the project (params.part = its ref). */
export const WIRE_EXTRA_BLOCKS = [
  { block: 'module', title: 'Module part of the project', params: [{ name: 'part', label: 'Module part', part: true, required: true, def: '' }] },
  { block: 'level_shifter', title: 'Level shifter (BSS138 channel)', params: [] }
]

/** Groups of the block pick; unknown blocks go to `more`. */
export const WIRE_GROUPS = [['basic', ['npn_low_side', 'led', 'button_pullup', 'divider']], ['modules', ['module', 'level_shifter']]]

const WIRE_TYPE = { ohm: { unit: 'Ω' }, volt: { unit: 'V' }, text: { text: true }, net: { net: true }, choice: {} }
const WIRE_ID_RE = /^[a-z0-9_]{1,32}$/

/** A backend catalogue entry ({block, title, params: [{name, type, default, required, choices}]}) as a form; null if unusable. */
export function wireBlockOf(b) {
  if (!b || !WIRE_ID_RE.test(b.block)) return null
  const params = (Array.isArray(b.params) ? b.params : []).filter(p => p && typeof p.name === 'string' && WIRE_TYPE[p.type]).map(p => ({
    name: p.name, label: p.name.replace(/_/g, ' '), required: Boolean(p.required), ...WIRE_TYPE[p.type],
    ...(p.type === 'choice' && Array.isArray(p.choices) ? { choice: p.choices.map(String) } : {}), def: p.default == null ? '' : String(p.default) }))
  return { block: b.block, title: typeof b.title === 'string' ? b.title : b.block.replace(/_/g, ' '), params }
}

/** Block names of the backend: result.blocks, or the hint of a render without a block ("blocks: led, …"); else null. */
export function wireBlockNames(env) {
  const list = env?.result?.blocks
  if (Array.isArray(list)) return list.map(b => (typeof b === 'string' ? b : b?.block)).filter(n => WIRE_ID_RE.test(n))
  const m = env && !env.ok ? /blocks:\s*([a-z0-9_, ]+)/.exec(String(env.error?.hint || '')) : null
  const names = m ? m[1].split(',').map(x => x.trim()).filter(x => WIRE_ID_RE.test(x)) : []
  return names.length ? names : null
}

/** Offered blocks: the base set without names, else exactly the named ones (local form, backend table, or no fields). */
export function wireBlockList(names, env = null) {
  if (!Array.isArray(names) || !names.length) return WIRE_BLOCKS
  const remote = (Array.isArray(env?.result?.blocks) ? env.result.blocks : []).map(wireBlockOf).filter(Boolean)
  return names.map(n => [...WIRE_BLOCKS, ...remote, ...WIRE_EXTRA_BLOCKS].find(b => b.block === n) || { block: n, title: n.replace(/_/g, ' '), params: [] })
}

/** The block pick in groups [{id, blocks}], empty groups left out, `more` last. */
export function wireGroups(blocks) {
  const known = WIRE_GROUPS.flatMap(([, ids]) => ids)
  return [...WIRE_GROUPS, ['more', null]].map(([id, ids]) => ({ id, blocks: (blocks || []).filter(b => (ids ? ids.includes(b.block) : !known.includes(b.block))) }))
    .filter(g => g.blocks.length)
}

/** Module parts of the project (parts with `module`), by ref: [{ref, label, title}]. */
export function wireModuleParts(project) {
  const key = r => { const m = /^([A-Z]+)(\d+)$/.exec(r); return m ? [m[1], Number(m[2])] : [r, 0] }
  return (project?.parts || []).filter(p => p && typeof p.module === 'string' && p.module && typeof p.ref === 'string')
    .sort((a, b) => { const [pa, na] = key(a.ref); const [pb, nb] = key(b.ref); return pa < pb ? -1 : pa > pb ? 1 : na - nb })
    .map(p => ({ ref: p.ref, label: `${p.ref} ${p.value || p.module}`, title: `${p.module}${p.variant ? ` · ${p.variant}` : ''}` }))
}
