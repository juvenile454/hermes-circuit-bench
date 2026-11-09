// Part pictograms of station 04 SOLDER. Pure functions, no SDK, no DOM:
// each returns an SVG string. Side view on a strip of board: the board line is the same for every kind, so the
// pictogram also shows how tall the part stands (flat → tall, the rule of thumb of the solder order).
// Self-contained (no imports, own helpers with the prefix solderArt: every desktop-src file shares one scope and
// lib/art.js is not importable here). Colours only as var(--cb-…) tokens: materials for the bodies, never a state
// colour in the material; annotations (the cathode symbol) draw in currentColor.
// Nothing is invented: a polarity mark is drawn only when the step carries a polarity hint backed by a source other
// than the rule of thumb (solderArtPolarity); a transistor never gets pin letters (no pinout is backed), only the tag
// "pinout: datasheet". No <style>, href, <image>, foreignObject or on* attributes (sanitizeSvg, lib/wire.js).

/** Kinds with an own drawing. Every other kind of data/solder/rules.json draws the generic part. */
export const SOLDER_ART_KINDS = ['wire_jumper', 'resistor', 'diode', 'led', 'transistor', 'electrolytic', 'ceramic', 'film',
  'capacitor', 'switch', 'header', 'connector', 'terminal', 'ic', 'module']

/** height_class of every kind in data/solder/rules.json (0 flat … 3 tall, 4 unknown). A copy for drawing only; the
 *  order itself comes from the backend. tests-js/test_vsolder_art.mjs keeps it equal to rules.json. */
export const SOLDER_ART_HEIGHT = {
  wire_jumper: 0, resistor: 1, diode: 1, ceramic: 2, inductor: 2, test_point: 2, crystal: 2, transistor: 2, ic: 2, led: 2,
  film: 3, fuse: 3, potentiometer: 3, buzzer: 3, relay: 3, capacitor: 3, electrolytic: 3, unknown: 4, header: 1, switch: 1,
  connector: 2, terminal: 2, module: 3, battery: 4
}

/** Words of the height classes (rules.json order.height_classes). */
export const SOLDER_ART_HEIGHT_WORDS = { 0: 'flat', 1: 'low', 2: 'medium', 3: 'tall', 4: 'unknown height' }

// top edge (y) of the generic body per height class; the drawn kinds stay inside the band of their class
const SOLDER_ART_GENERIC_TOP = { 0: 44, 1: 34, 2: 24, 3: 10, 4: 24 }

/** Viewbox of every pictogram (the board surface is at y = 50). */
export const SOLDER_ART_VIEW = [96, 64]
const SOLDER_ART_BOARD_Y = 50

// strokes stay 2 px (body) / 1.5 px (leads) at every size of the pictogram
const SA_NS = { 'vector-effect': 'non-scaling-stroke' }
// plastic bodies are lifted toward the metal highlight (a neutral mix of two material tokens, chroma stays ≤ 0.06), so a
// body stays visible on the dark bench; the edge is lighter than the body (lit edge)
const SA_PLASTIC = { fill: 'color-mix(in oklab, var(--cb-plastic) 78%, var(--cb-metal-hi))', stroke: 'color-mix(in oklab, var(--cb-plastic-edge) 55%, var(--cb-metal-hi))',
  'stroke-width': 2, ...SA_NS }
const SA_METAL = { fill: 'var(--cb-metal)', stroke: 'var(--cb-metal-ink)', 'stroke-width': 1, ...SA_NS }

const saRect = (x, y, w, h, extra = {}) => artEl('rect', { x, y, width: w, height: h, ...extra })
const saLead = d => artEl('path', { d, fill: 'none', stroke: 'var(--cb-metal)', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', ...SA_NS })
const saPad = (x, w = 10) => saRect(x - w / 2, SOLDER_ART_BOARD_Y - 2, w, 2.5, { rx: 1, fill: 'var(--cb-tin)' })
const saBoard = () => saRect(2, SOLDER_ART_BOARD_Y, 92, 6, { rx: 1, fill: 'var(--cb-pcb)', stroke: 'var(--cb-pcb-edge)', 'stroke-width': 1, ...SA_NS })
// axial lead: from the body end (bx, by) out and down into the pad at px
const saAxial = (bx, by, px) => saLead(`M${bx} ${by}H${px + (px < bx ? 2 : -2)}Q${px} ${by} ${px} ${by + 2}V${SOLDER_ART_BOARD_Y}`)

/** Package family of a transistor step from the project parts (part.package, e.g. "TO-18"): 'can' | 'to92' | null. */
export function solderArtPackage(step, parts) {
  const refs = new Set(step?.refs || [])
  const pk = (parts || []).filter(p => p && refs.has(p.ref)).map(p => String(p.package || '').toUpperCase().replace(/\s+/g, ''))
  if (!pk.length || pk.some(p => !p)) return null
  if (pk.every(p => /^TO-?(18|5|39|46|72)\b/.test(p))) return 'can'
  if (pk.every(p => /^TO-?92\b/.test(p))) return 'to92'
  return null
}

/** Does a hint carry a source other than the rule of thumb? */
export function solderArtSourced(hint) {
  return (hint?.source_ids || []).some(id => id && id !== 'rule-of-thumb')
}

/**
 * Polarity mark of a step → {mark, label, code, source_ids} | null. Only from a hint the step carries (code
 * polarity, or pinout for a transistor) with a source beyond the rule of thumb:
 *   electrolytic → 'minus-stripe' · diode → 'cathode-band' · led → 'cathode' · transistor → 'pinout-datasheet'
 * Every other kind (and every unsourced hint) → null: nothing is drawn.
 */
export function solderArtPolarity(step) {
  const kind = step?.kind
  const want = kind === 'transistor' ? 'pinout' : 'polarity'
  const hint = (step?.hints || []).find(x => x && x.code === want && solderArtSourced(x))
  if (!hint) return null
  const marks = {
    electrolytic: ['minus-stripe', 'stripe = minus'],
    diode: ['cathode-band', 'band = cathode'],
    led: ['cathode', 'cathode: datasheet'],
    transistor: ['pinout-datasheet', 'pinout: datasheet']
  }
  const m = marks[kind]
  return m ? { mark: m[0], label: m[1], code: hint.code, source_ids: [...hint.source_ids] } : null
}

/** Hint row category by code: 'polarity' | 'heat' | 'safety' | 'tip' (label word of the hint line). */
export function solderArtHintKind(hint) {
  const code = String(hint?.code || '')
  if (['polarity', 'pinout', 'kind_uncertain', 'kind_by_value'].includes(code)) return 'polarity'
  if (code === 'orientation') return hint?.severity === 'info' ? 'tip' : 'polarity'
  if (code === 'heat_sensitive') return 'heat'
  if (/_safety$/.test(code) || ['low_voltage_only', 'check_shorts', 'check_manually'].includes(code)) return 'safety'
  return 'tip'
}

/** Body of each kind: () → {top, svg}. `pol` = solderArtPolarity mark or null, `pkg` = transistor package. */
function solderArtBody(kind, pol, pkg) {
  const B = SOLDER_ART_BOARD_Y
  const mark = m => pol?.mark === m
  switch (kind) {
    case 'wire_jumper':
      return { top: 44, svg: saPad(22) + saPad(74) +
        artEl('path', { d: `M22 ${B}V46Q22 44 24 44H72Q74 44 74 46V${B}`, fill: 'none', stroke: 'var(--cb-tin)', 'stroke-width': 2, 'stroke-linecap': 'round', ...SA_NS }) }
    case 'resistor':
      return { top: 35, svg: saPad(14) + saPad(82) + saAxial(30, 41, 14) + saAxial(66, 41, 82) +
        artEl('path', { d: 'M30 37Q30 35 33 35H38Q40 37 42 37H54Q56 37 58 35H63Q66 35 66 37V45Q66 47 63 47H58Q56 45 54 45H42Q40 45 38 47H33Q30 47 30 45Z', ...SA_PLASTIC }) }
    case 'diode':
      return { top: 36, svg: saPad(14) + saPad(82) + saAxial(34, 41, 14) + saAxial(62, 41, 82) +
        saRect(34, 36, 28, 10, { rx: 3, ...SA_PLASTIC }) +
        (mark('cathode-band') ? saRect(53, 36.5, 5, 9, { fill: 'var(--cb-silk)', 'data-cb-mark': 'cathode-band' }) : '') }
    case 'header': {
      const pins = [24, 36, 48, 60, 72]
      return { top: 32, svg: pins.map(x => saPad(x, 6)).join('') + saRect(18, 42, 60, 8, { rx: 1, ...SA_PLASTIC }) +
        pins.map(x => saRect(x - 1.25, 32, 2.5, 10, { fill: 'var(--cb-metal)' })).join('') }
    }
    case 'switch':
      return { top: 32, svg: saPad(30, 8) + saPad(66, 8) + saLead(`M32 48V${B}`) + saLead(`M64 48V${B}`) +
        saRect(28, 40, 40, 9, { rx: 1, ...SA_PLASTIC }) + saRect(28, 37.5, 40, 3, SA_METAL) +
        // round plunger
        saRect(42, 33, 12, 5, { rx: 1, ...SA_PLASTIC }) + artEl('ellipse', { cx: 48, cy: 33, rx: 6, ry: 2, fill: 'var(--cb-metal-hi)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 1, ...SA_NS }) }
    case 'ceramic':
      return { top: 21, svg: saPad(38, 8) + saPad(58, 8) + saLead(`M44 37V42L38 46V${B}`) + saLead(`M52 37V42L58 46V${B}`) +
        artEl('ellipse', { cx: 48, cy: 30, rx: 12, ry: 9, ...SA_PLASTIC }) }
    case 'transistor': {
      const legs = [38, 48, 58].map(x => saPad(x, 6) + saLead(`M${x} 39V${B}`)).join('')
      if (pkg === 'can') {
        // metal can (TO-18 family): flange with the tab, cylinder, flat lid
        return { top: 20, svg: legs + saRect(32, 34, 32, 5, { rx: 1.5, ...SA_METAL }) + saRect(64, 35, 5, 3, SA_METAL) +
          artEl('path', { d: 'M36 34V23H60V34Z', ...SA_METAL }) +
          artEl('ellipse', { cx: 48, cy: 23, rx: 12, ry: 3, fill: 'var(--cb-metal-hi)', stroke: 'var(--cb-metal-ink)', 'stroke-width': 1, ...SA_NS }) +
          artEl('path', { d: 'M40 27V32', stroke: 'var(--cb-metal-hi)', 'stroke-width': 2, 'stroke-linecap': 'round', ...SA_NS }) }
      }
      if (pkg === 'to92') {
        return { top: 22, svg: legs + artEl('path', { d: 'M36 39V30Q36 22 48 22Q60 22 60 30V39Z', ...SA_PLASTIC }) }
      }
      return { top: 24, svg: legs + saRect(36, 24, 24, 15, { rx: 2, ...SA_PLASTIC }) }
    }
    case 'ic': {
      const legs = [26, 34, 42, 50, 58, 66].map(x => saPad(x, 5) + saLead(`M${x} 37V40L${x} ${B}`)).join('')
      return { top: 25, svg: legs + saRect(22, 25, 52, 12, { rx: 2, ...SA_PLASTIC }) }
    }
    case 'led': {
      const cathode = mark('cathode')
      // schematic diode symbol (triangle + bar) above the cathode lead: annotation, not a physical feature
      // the cathode is not drawn on a lead (which lead it is comes from the part's datasheet, rules.json): a schematic
      // diode symbol beside the body names the mark (bar = cathode); the tag under the picture says "cathode: datasheet"
      const sym = cathode ? artEl('g', { 'data-cb-mark': 'cathode', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', ...SA_NS },
        artEl('path', { d: 'M68 16H80L74 25Z' }) + artEl('path', { d: 'M68 26H80' }) + artEl('path', { d: 'M74 12V16M74 26V30' })) : ''
      return { top: 20, svg: saPad(43, 8) + saPad(53, 8) + saLead(`M43 39V${B}`) + saLead(`M53 39V${B}`) +
        saRect(35, 36, 26, 3, { rx: 1, ...SA_PLASTIC }) + artEl('path', { d: 'M38 37V30A10 10 0 0 1 58 30V37Z', ...SA_PLASTIC }) + sym }
    }
    case 'connector':
      return { top: 24, svg: [36, 48, 60].map(x => saPad(x, 6) + saLead(`M${x} 48V54`)).join('') +
        saRect(26, 24, 44, 25, { rx: 1.5, ...SA_PLASTIC }) + saRect(32, 28, 32, 10, { rx: 1, fill: 'var(--cb-cavity)' }) +
        // contacts in the opening (no pinout)
        [36, 48, 60].map(x => saRect(x - 1.5, 30, 3, 7, { rx: 0.5, fill: 'var(--cb-tin)' })).join('') }
    case 'terminal':
      return { top: 22, svg: [36, 60].map(x => saPad(x, 8) + saLead(`M${x} 48V54`)).join('') +
        saRect(24, 26, 48, 23, { rx: 1.5, ...SA_PLASTIC }) + saRect(30, 22, 12, 4, { rx: 1, ...SA_METAL }) + saRect(54, 22, 12, 4, { rx: 1, ...SA_METAL }) +
        saRect(30, 35, 12, 8, { rx: 1, fill: 'var(--cb-cavity)' }) + saRect(54, 35, 12, 8, { rx: 1, fill: 'var(--cb-cavity)' }) }
    case 'film':
      return { top: 10, svg: saPad(40, 8) + saPad(56, 8) + saLead(`M40 46V${B}`) + saLead(`M56 46V${B}`) +
        saRect(30, 10, 36, 36, { rx: 4, ...SA_PLASTIC }) }
    case 'electrolytic': {
      const stripe = mark('minus-stripe')
        // the stripe sits on the side of the negative lead (Rubycon: the sleeve stripe marks the negative lead)
        ? artEl('g', { 'data-cb-mark': 'minus-stripe' }, saRect(50, 11, 12, 36, { fill: 'var(--cb-silk)' }) +
          [17, 27, 37].map(y => artEl('path', { d: `M53 ${y}H59`, stroke: 'var(--cb-plastic)', 'stroke-width': 2.5, ...SA_NS })).join(''))
        : ''
      return { top: 7, svg: saPad(42, 8) + saPad(54, 8) + saLead(`M42 47V${B}`) + saLead(`M54 47V${B}`) +
        saRect(32, 9, 32, 39, { rx: 4, ...SA_PLASTIC }) + stripe + saRect(33, 7, 30, 4, { rx: 2, ...SA_METAL }) }
    }
    case 'capacitor':
      // type unclear: outline only, dashed (the drawing does not decide ceramic vs. electrolytic)
      return { top: 9, schematic: true, svg: saPad(42, 8) + saPad(54, 8) + saLead(`M42 47V${B}`) + saLead(`M54 47V${B}`) +
        saRect(32, 9, 32, 39, { rx: 4, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-dasharray': '4 3', ...SA_NS }) +
        artEl('path', { d: 'M43 22Q43 16 48 16Q53 16 53 21Q53 25 48 27V31M48 36V36.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round', ...SA_NS }) }
    case 'module':
      return { top: 10, svg: [24, 36, 48, 60, 72].map(x => saPad(x, 6)).join('') + saRect(18, 30, 60, 20, { rx: 1, ...SA_PLASTIC }) +
        saRect(12, 26, 72, 4, { rx: 1, fill: 'var(--cb-pcb)', stroke: 'var(--cb-pcb-edge)', 'stroke-width': 1, ...SA_NS }) +
        saRect(24, 10, 36, 16, { rx: 1.5, ...SA_METAL }) + saRect(66, 20, 10, 6, { rx: 1, ...SA_PLASTIC }) }
    default: {
      // generic part: dashed plastic body of the height of its class, two leads (data-cb-schematic)
      const cls = SOLDER_ART_HEIGHT[kind] ?? 4
      const top = SOLDER_ART_GENERIC_TOP[cls] ?? 24
      const unknown = cls === 4
      return { top, schematic: true, svg: saPad(40, 8) + saPad(56, 8) + saLead(`M40 46V${B}`) + saLead(`M56 46V${B}`) +
        saRect(30, top, 36, 46 - top, { rx: 3, ...(unknown ? { fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5 } : SA_PLASTIC), 'stroke-dasharray': '4 3', ...SA_NS }) }
    }
  }
}

/** Top edge (viewbox y) of a kind's drawing: smaller = taller. Used by the tests (flat → tall). */
export function solderArtTop(kind, pkg = null) {
  return solderArtBody(kind, null, pkg).top
}

/**
 * Pictogram of a part kind as an SVG string.
 * opts: { polarity: solderArtPolarity(step) | null, pkg: solderArtPackage(…), w, h (px), label (aria-label) }
 * Decorative when label is empty (aria-hidden). data-cb-art = the drawn kind or 'generic'.
 */
export function solderArtPart(kind, { polarity = null, pkg = null, w = 96, h = 64, label = '' } = {}) {
  const k = String(kind || 'unknown')
  const drawn = SOLDER_ART_KINDS.includes(k)
  const pol = drawn ? polarity : null // kinds without a drawing fall to the generic part, without marks
  const body = solderArtBody(k, pol, pkg)
  const [vw, vh] = SOLDER_ART_VIEW
  const aria = label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': 'true' }
  return artEl('svg', { xmlns: 'http://www.w3.org/2000/svg', viewBox: `0 0 ${vw} ${vh}`, width: w, height: h, class: 'cb-part-art',
    focusable: 'false', 'data-cb-art': drawn ? k : 'generic', 'data-cb-kind': k, 'data-cb-schematic': body.schematic ? 'true' : undefined,
    'data-cb-polarity': pol?.mark || undefined, ...aria },
  saBoard() + body.svg)
}
