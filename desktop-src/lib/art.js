// Graphic primitives of the model language. Pure functions, no SDK, no DOM:
// each returns an SVG fragment as a string. Deterministic (same input → same string). Every value from data runs
// through artEsc; every coordinate through artNum (a finite number or 0). Colours only as var(--cb-…) tokens
// (presentation attributes with var() and color-mix() resolve in Chromium/Electron: probe 07.11.2026, Chromium 151).
// No <style>, no href/xlink, no <image>, no foreignObject, no on* attributes (the sanitizeSvg list, lib/wire.js).
// Names carry the prefix `art` because every desktop-src file shares one scope (glyph, pad, port, can … are locals
// elsewhere). The board model and stations draw with these; new primitives go to lib/art-<area>.js.

/** Escape text and attribute values (& < > " '). */
export function artEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/** A coordinate: finite number rounded to 2 decimals, anything else 0 (data never reaches an attribute raw). */
export function artNum(v) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0
}

/** Estimated width of monospace text: 0.6 em per character (code points). */
export function artTextWidth(str, px = 10) {
  return artNum([...String(str ?? '')].length * 0.6 * artNum(px))
}

/** Pin/pad states of the model → the word for aria-label and the tone token. */
export const ART_STATE_WORDS = {
  free: 'free',
  assigned: 'assigned',
  caution: 'caution',
  blocked: 'blocked',
  assigned_blocked: 'assigned · blocked',
  power: 'power',
  ground: 'ground / reset',
  nc: 'not connected',
  signal: 'board signal'
}
export const ART_STATES = Object.keys(ART_STATE_WORDS)
export const ART_STATE_TONE = {
  free: 'ok', assigned: 'active', caution: 'warn', blocked: 'bad', assigned_blocked: 'bad',
  power: 'power', ground: 'fg-dim', nc: 'fg-faint', signal: 'fg-dim'
}
/** Port kinds artPort draws. Anything else draws nothing (nothing is invented). */
export const ART_PORT_KINDS = ['micro_usb', 'usb_c', 'generic_usb', 'rj45', 'ipex']
/** Schematic outer size [w, h] of each port (for layout; not a physical dimension). */
export const ART_PORT_SIZE = { micro_usb: [44, 30], usb_c: [44, 26], generic_usb: [44, 30], rj45: [64, 60], ipex: [18, 18] }

const ART_NEUTRAL = ['ground', 'nc', 'signal']
/** Tone of a state. On the board (surface 'board') the neutral states print in silk: the material decides there,
 *  not the app theme (fg-dim of a light app theme would vanish on the dark board). */
const artTone = (state, surface = 'bench') => surface === 'board' && ART_NEUTRAL.includes(state) ? 'var(--cb-silk)' : `var(--cb-${ART_STATE_TONE[state] || 'fg-dim'})`

function artAttrs(attrs) {
  return Object.entries(attrs).filter(([, v]) => v !== undefined && v !== null && v !== false)
    .map(([k, v]) => ` ${k}="${typeof v === 'number' ? artNum(v) : artEsc(v)}"`).join('')
}

function artEl(tag, attrs, inner) {
  return inner === undefined ? `<${tag}${artAttrs(attrs)}/>` : `<${tag}${artAttrs(attrs)}>${inner}</${tag}>`
}

/** Instance prefix for ids: letters, digits and '-' only. */
function artPrefix(prefix) {
  const p = String(prefix ?? '').replace(/[^A-Za-z0-9-]+/g, '-').replace(/^-+|-+$/g, '')
  return p || 'art'
}

/** id of a def made by artDefs(prefix): artId('s3', 'tin') → 'cb-s3-tin'. */
export function artId(prefix, name) {
  return `cb-${artPrefix(prefix)}-${name}`
}

/** fill reference to a def when a prefix is given, else the flat token (the drawing works without defs). */
function artPaint(prefix, name, token) {
  return prefix ? `url(#${artId(prefix, name)})` : `var(--cb-${token})`
}

/** <defs> for one model instance: gradients pcb/metal/tin, hatch (blocked), shadow, glow. Ids cb-<prefix>-…. */
export function artDefs(prefix) {
  const id = n => artId(prefix, n)
  const stop = (offset, color) => artEl('stop', { offset, 'stop-color': color })
  return '<defs>' +
    artEl('linearGradient', { id: id('pcb'), x1: 0, y1: 0, x2: 1, y2: 1 },
      stop(0, 'var(--cb-pcb)') + stop(1, 'color-mix(in oklab, var(--cb-pcb) 72%, var(--cb-cavity))')) +
    artEl('linearGradient', { id: id('metal'), x1: 0, y1: 0, x2: 1, y2: 1 },
      stop(0, 'var(--cb-metal-hi)') + stop(0.45, 'var(--cb-metal)') + stop(1, 'color-mix(in oklab, var(--cb-metal-hi) 55%, var(--cb-metal))')) +
    artEl('radialGradient', { id: id('tin'), cx: 0.35, cy: 0.35, r: 0.8 },
      stop(0, 'color-mix(in oklab, var(--cb-tin) 35%, var(--cb-metal-hi))') + stop(0.6, 'var(--cb-tin)') + stop(1, 'color-mix(in oklab, var(--cb-tin) 60%, var(--cb-plastic))')) +
    artEl('pattern', { id: id('hatch'), width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
      artEl('rect', { width: 2.2, height: 5, fill: 'var(--cb-bad)' })) +
    artEl('filter', { id: id('shadow'), x: '-20%', y: '-20%', width: '140%', height: '160%' },
      artEl('feDropShadow', { dx: 0, dy: 3, stdDeviation: 2.5, 'flood-color': 'var(--cb-cavity)', 'flood-opacity': 0.7 })) +
    artEl('filter', { id: id('glow'), x: '-50%', y: '-50%', width: '200%', height: '200%' },
      artEl('feGaussianBlur', { stdDeviation: 2 })) +
    '</defs>'
}

/**
 * Shapes of a state symbol in a 12×12 box centred on (x, y): [[tag, attrs], …]. `ink` is the symbol colour,
 * `knock` the cut-out colour (the ✕ in the filled ⊗). Shared by artGlyph (strings) and Glyph (30-ui-kit.js).
 * ○ free · ● assigned · ◇ caution · ⊗ blocked · filled ⊗ assigned·blocked · ▣ power · □ ground/reset · – nc · · signal
 */
export function artGlyphShapes(state, x = 6, y = 6, ink = 'currentColor', knock = 'var(--cb-ink)') {
  const cx = artNum(x)
  const cy = artNum(y)
  const ring = { fill: 'none', stroke: ink, 'stroke-width': 2 }
  const cross = c => ['path', { d: `M${artNum(cx - 2.6)} ${artNum(cy - 2.6)}L${artNum(cx + 2.6)} ${artNum(cy + 2.6)}M${artNum(cx + 2.6)} ${artNum(cy - 2.6)}L${artNum(cx - 2.6)} ${artNum(cy + 2.6)}`,
    fill: 'none', stroke: c, 'stroke-width': 1.8, 'stroke-linecap': 'round' }]
  switch (state) {
    case 'free': return [['circle', { cx, cy, r: 5, ...ring }]]
    case 'assigned': return [['circle', { cx, cy, r: 6, fill: ink }]]
    case 'caution': return [['path', { d: `M${cx} ${artNum(cy - 5.5)}L${artNum(cx + 5.5)} ${cy}L${cx} ${artNum(cy + 5.5)}L${artNum(cx - 5.5)} ${cy}Z`, ...ring, 'stroke-linejoin': 'round' }]]
    case 'blocked': return [['circle', { cx, cy, r: 5, ...ring }], cross(ink)]
    case 'assigned_blocked': return [['circle', { cx, cy, r: 6, fill: ink }], cross(knock)]
    case 'power': return [['rect', { x: artNum(cx - 5), y: artNum(cy - 5), width: 10, height: 10, rx: 1, ...ring }], ['rect', { x: artNum(cx - 2), y: artNum(cy - 2), width: 4, height: 4, fill: ink }]]
    case 'ground': return [['rect', { x: artNum(cx - 5), y: artNum(cy - 5), width: 10, height: 10, rx: 1, ...ring }]]
    case 'nc': return [['path', { d: `M${artNum(cx - 5)} ${cy}H${artNum(cx + 5)}`, fill: 'none', stroke: ink, 'stroke-width': 2, 'stroke-linecap': 'round' }]]
    case 'signal': return [['circle', { cx, cy, r: 2.2, fill: ink }]]
    default: return []
  }
}

/** State symbol (≥ 12 px) centred on (x, y) in the state's tone. Unknown state → ''.
 *  surface: 'bench' (default, beside the board) or 'board' (printed on the pcb). */
export function artGlyph(state, x, y, { surface = 'bench' } = {}) {
  const shapes = artGlyphShapes(state, x, y, artTone(state, surface))
  if (!shapes.length) return ''
  return artEl('g', { class: 'cb-art-glyph', 'data-cb-state': state }, shapes.map(([t, a]) => artEl(t, a)).join(''))
}

/** Pad on the board: tin with a state ring (2 px); assigned glows, blocked is hatched. square = pin 1 / power. */
export function artPad(x, y, { square = false, state = 'free', prefix = '' } = {}) {
  const px = artNum(x)
  const py = artNum(y)
  const known = state in ART_STATE_WORDS
  const st = known ? state : 'free'
  // neutral pads (ground, nc, signal) ring in silk (artTone 'board')
  const ring = artTone(st, 'board')
  const shape = (extra) => square
    ? artEl('rect', { x: artNum(px - 6.5), y: artNum(py - 6.5), width: 13, height: 13, rx: 1, ...extra })
    : artEl('circle', { cx: px, cy: py, r: 6.5, ...extra })
  const glow = st === 'assigned'
    ? artEl('circle', { cx: px, cy: py, r: 9, fill: 'none', stroke: 'var(--cb-active)', 'stroke-opacity': 0.45, 'stroke-width': 3, filter: prefix ? `url(#${artId(prefix, 'glow')})` : undefined })
    : ''
  const hatch = (st === 'blocked' || st === 'assigned_blocked') ? shape({ fill: prefix ? `url(#${artId(prefix, 'hatch')})` : 'none' }) : ''
  // assigned: filled, else tin
  const fill = st === 'assigned' ? 'var(--cb-active)' : artPaint(prefix, 'tin', 'tin')
  return artEl('g', { class: 'cb-art-pad', 'data-cb-state': st },
    glow + shape({ fill, stroke: ring, 'stroke-width': 2 }) + hatch)
}

/** Tag beside a label: 16 px high, 10 px capitals. assigned / assigned·blocked are filled (the latter + ✕, drawn as a
 *  shape, not font text), the rest outlined. side 'l' ends at x, side 'r' starts at x; y is the centre line.
 *  Empty text → ''. surface as in artGlyph. */
export function artPill(text, state, x, y, side = 'r', { surface = 'bench' } = {}) {
  const label = String(text ?? '').toUpperCase()
  if (!label) return ''
  const st = state in ART_STATE_WORDS ? state : 'free'
  const solid = st === 'assigned' || st === 'assigned_blocked'
  const cross = st === 'assigned_blocked'
  const tw = artNum(artTextWidth(label, 10) + [...label].length * 0.8)
  const w = artNum(tw + 12 + (cross ? 12 : 0))
  const x0 = side === 'l' ? artNum(artNum(x) - w) : artNum(x)
  const cy = artNum(y)
  const c = artTone(st, surface)
  const ink = solid ? 'var(--cb-ink)' : c
  const xc = artNum(x0 + w - 10)
  const mark = cross
    ? artEl('path', { class: 'cb-art-x', d: `M${artNum(xc - 3)} ${artNum(cy - 3)}L${artNum(xc + 3)} ${artNum(cy + 3)}M${artNum(xc + 3)} ${artNum(cy - 3)}L${artNum(xc - 3)} ${artNum(cy + 3)}`,
      fill: 'none', stroke: ink, 'stroke-width': 1.8, 'stroke-linecap': 'round' })
    : ''
  return artEl('g', { class: 'cb-art-pill', 'data-cb-state': st },
    artEl('rect', { x: x0, y: artNum(cy - 8), width: w, height: 16, rx: 2, fill: solid ? c : 'none', stroke: c, 'stroke-opacity': solid ? 1 : 0.6 }) +
    artEl('text', { x: artNum(x0 + 6 + tw / 2), y: artNum(cy + 3.6), 'text-anchor': 'middle', 'font-size': 10, 'font-weight': solid ? 700 : 500, 'letter-spacing': 0.8, fill: ink }, artEsc(label)) +
    mark)
}

/** Port at the board edge, (x, y) = top left, size ART_PORT_SIZE[kind]. Unknown kind → '' (never guessed).
 *  generic_usb: metal jack with a plain opening, no form claim, data-cb-schematic="true". */
export function artPort(kind, x, y, { prefix = '' } = {}) {
  if (!ART_PORT_KINDS.includes(kind)) return ''
  const [w, h] = ART_PORT_SIZE[kind]
  const px = artNum(x)
  const py = artNum(y)
  const metal = artPaint(prefix, 'metal', 'metal')
  const shadow = prefix ? `url(#${artId(prefix, 'shadow')})` : undefined
  const shell = (extra = {}) => artEl('rect', { x: px, y: py, width: w, height: h, rx: 3, fill: metal, stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2, ...extra })
  let body = ''
  if (kind === 'micro_usb') {
    // trapezoid opening (wide side up) with the tongue
    body = shell() + artEl('path', { d: `M${px + 7} ${py + 9}H${px + w - 7}L${px + w - 12} ${py + h - 7}H${px + 12}Z`, fill: 'var(--cb-cavity)' }) +
      artEl('rect', { x: px + 14, y: py + 13, width: w - 28, height: 3, rx: 1, fill: 'var(--cb-plastic-edge)' })
  } else if (kind === 'usb_c') {
    // stadium opening, centred tongue
    body = shell({ rx: 6 }) + artEl('rect', { x: px + 6, y: py + 7, width: w - 12, height: h - 14, rx: (h - 14) / 2, fill: 'var(--cb-cavity)' }) +
      artEl('rect', { x: px + 12, y: py + h / 2 - 1.5, width: w - 24, height: 3, rx: 1.5, fill: 'var(--cb-plastic-edge)' })
  } else if (kind === 'generic_usb') {
    body = shell() + artEl('rect', { x: px + 8, y: py + 9, width: w - 16, height: h - 18, rx: 1, fill: 'var(--cb-cavity)' })
  } else if (kind === 'rj45') {
    // jack block: square opening with the latch notch
    body = shell({ rx: 2 }) + artEl('path', { d: `M${px + 8} ${py + 10}H${px + w - 8}V${py + h - 16}H${px + w / 2 + 8}V${py + h - 8}H${px + w / 2 - 8}V${py + h - 16}H${px + 8}Z`, fill: 'var(--cb-cavity)' })
  } else if (kind === 'ipex') {
    // small coax receptacle (U.FL style): square base plate, round socket, centre pin
    body = artEl('rect', { x: px, y: py, width: w, height: h, rx: 1.5, fill: metal, stroke: 'var(--cb-plastic-edge)', 'stroke-width': 1.5 }) +
      artEl('circle', { cx: px + w / 2, cy: py + h / 2, r: w / 2 - 3, fill: 'var(--cb-metal-hi)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 1.5 }) +
      artEl('circle', { cx: px + w / 2, cy: py + h / 2, r: w / 2 - 6, fill: 'var(--cb-plastic)' }) +
      artEl('circle', { cx: px + w / 2, cy: py + h / 2, r: 1.5, fill: 'var(--cb-tin)' })
  }
  return artEl('g', { class: 'cb-art-port', 'data-cb-port': kind, 'data-cb-schematic': kind === 'generic_usb' ? 'true' : undefined, filter: shadow }, body)
}

/** Tactile button 30×26 at (x, y) with its silkscreen label below (10 px). */
export function artButton(x, y, label, { prefix = '' } = {}) {
  const px = artNum(x)
  const py = artNum(y)
  const shadow = prefix ? `url(#${artId(prefix, 'shadow')})` : undefined
  return artEl('g', { class: 'cb-art-button' },
    artEl('g', { filter: shadow },
      artEl('rect', { x: px, y: py, width: 30, height: 26, rx: 2, fill: 'var(--cb-plastic)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2 }) +
      artEl('circle', { cx: px + 15, cy: py + 13, r: 7.5, fill: 'var(--cb-plastic-edge)', stroke: 'var(--cb-metal)', 'stroke-width': 1 })) +
    (label ? artEl('text', { x: px + 15, y: py + 40, 'text-anchor': 'middle', 'font-size': 10, 'letter-spacing': 1.2, fill: 'var(--cb-silk)' }, artEsc(label)) : ''))
}

/** IC body (plastic) with pin-1 dot; `pins` legs per long side (top and bottom), optional silk `label` inside. */
export function artIc(x, y, w, h, { pins = 0, label = '', prefix = '' } = {}) {
  const px = artNum(x)
  const py = artNum(y)
  const bw = Math.max(0, artNum(w))
  const bh = Math.max(0, artNum(h))
  const n = Math.max(0, Math.min(64, Math.floor(artNum(pins))))
  const shadow = prefix ? `url(#${artId(prefix, 'shadow')})` : undefined
  let legs = ''
  for (let k = 0; k < n; k++) {
    const lx = artNum(px + (bw / (n + 1)) * (k + 1) - 1.5)
    legs += artEl('rect', { x: lx, y: artNum(py - 5), width: 3, height: 5, fill: 'var(--cb-tin)' }) + artEl('rect', { x: lx, y: artNum(py + bh), width: 3, height: 5, fill: 'var(--cb-tin)' })
  }
  return artEl('g', { class: 'cb-art-ic' }, legs +
    artEl('rect', { x: px, y: py, width: bw, height: bh, rx: 2, fill: 'var(--cb-plastic)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2, filter: shadow }) +
    artEl('circle', { cx: artNum(px + 6), cy: artNum(py + 6), r: 2, fill: 'var(--cb-plastic-edge)' }) +
    (label ? artEl('text', { x: artNum(px + bw / 2), y: artNum(py + bh / 2 + 3.5), 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--cb-silk)' }, artEsc(label)) : ''))
}

/** Shield can (metal) with printed lines: the first 13 px bold, the others 10 px, in metal-ink, centred. */
export function artCan(x, y, w, h, lines = [], { prefix = '' } = {}) {
  const px = artNum(x)
  const py = artNum(y)
  const bw = Math.max(0, artNum(w))
  const bh = Math.max(0, artNum(h))
  const rows = (Array.isArray(lines) ? lines : [lines]).filter(l => l !== null && l !== undefined && String(l) !== '').slice(0, 6)
  const sizes = rows.map((_, i) => (i === 0 ? 13 : 10))
  const total = sizes.reduce((a, s) => a + s + 6, -6)
  let ty = py + bh / 2 - total / 2
  const text = rows.map((l, i) => {
    ty += sizes[i]
    const t = artEl('text', { x: artNum(px + bw / 2), y: artNum(ty - 1), 'text-anchor': 'middle', 'font-size': sizes[i], 'font-weight': i === 0 ? 800 : 500, 'letter-spacing': i === 0 ? 1.4 : 0.6, fill: 'var(--cb-metal-ink)' }, artEsc(l))
    ty += 6
    return t
  }).join('')
  const shadow = prefix ? `url(#${artId(prefix, 'shadow')})` : undefined
  return artEl('g', { class: 'cb-art-can' },
    artEl('rect', { x: px, y: py, width: bw, height: bh, rx: 4, fill: artPaint(prefix, 'metal', 'metal'), stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2, filter: shadow }) +
    (bw > 12 && bh > 12 ? artEl('rect', { x: px + 6, y: py + 6, width: bw - 12, height: bh - 12, rx: 3, fill: 'none', stroke: 'var(--cb-metal-hi)', 'stroke-opacity': 0.7 }) : '') +
    text)
}

/** PCB antenna: dashed keep-out, copper meander, note lines (default 'keep metal clear', [] = none).
 *  opts { lines, lineH, inset, fill, spacing }. */
export function artAntenna(x, y, w, h, { lines = ['keep metal clear'], lineH = 12, inset = 0, fill = 'none', spacing = 1.6 } = {}) {
  const px = artNum(x)
  const py = artNum(y)
  const bw = Math.max(0, artNum(w))
  const bh = Math.max(0, artNum(h))
  const textH = lines.length ? lines.length * lineH + 2 : 0
  const top = py + inset + 6
  const bottom = py + Math.max(14, bh - textH - 6)
  const m = inset + 9
  let d = `M${artNum(px + m)} ${artNum(bottom)}V${artNum(top)}`
  let up = true
  for (let cx = px + m; cx + 11 <= px + bw - m; cx += 11) {
    d += `H${artNum(cx + 11)}V${artNum(up ? bottom : top)}`
    up = !up
  }
  return artEl('g', { class: 'cb-art-antenna' },
    artEl('rect', { x: px + inset, y: py + inset, width: Math.max(0, bw - 2 * inset), height: Math.max(0, bh - 1.5 * inset), rx: 2, fill,
      stroke: 'var(--cb-silk)', 'stroke-opacity': 0.7, 'stroke-dasharray': '4 3' }) +
    artEl('path', { d, fill: 'none', stroke: 'var(--cb-copper)', 'stroke-width': 3, 'stroke-linejoin': 'round' }) +
    lines.map((l, i) => artEl('text', { x: artNum(px + bw / 2), y: artNum(py + bh - 5 - (lines.length - 1 - i) * lineH), 'text-anchor': 'middle',
      'font-size': 10, 'letter-spacing': spacing, fill: 'var(--cb-silk)' }, artEsc(l))).join(''))
}
