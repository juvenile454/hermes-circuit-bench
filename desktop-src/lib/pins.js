// Pin presentation: verdict → class/symbol/text, header-pin view state, assignment merge, modes, chips.
// Pure, no SDK. The rules themselves live in the backend (bench_core.pins); this file only maps their output to
// what the Bench shows. Colour is never the only carrier: every state also has a symbol and a word.

/** PLAN toolbar chips and variants; mirrors data/pins/*.json `variants` and data/boards (tests-js keep them in sync).
 *  `devkit`: the chip's default layout; last variant = chip default; `module`: variant is a whole module. */
export const CHIPS = [
  {
    id: 'esp32', label: 'ESP32', devkit: 'esp32-devkitc-v4',
    variants: [
      { id: 'wrover-e', label: 'WROVER-E', module: 'ESP32-WROVER-E', psram: 'spi', flash_mb: 8, psram_mb: 8 },
      { id: 'wroom-32e', label: 'WROOM-32E', module: 'ESP32-WROOM-32E', psram: null, flash_mb: 4, psram_mb: 0 }
    ]
  },
  { id: 'esp32s2', label: 'ESP32-S2', devkit: 'esp32-s2-devkitc-1', variants: [] },
  {
    id: 'esp32s3', label: 'ESP32-S3', devkit: 'esp32-s3-devkitc-1',
    variants: [
      { id: 'n4', label: 'N4', psram: null, flash_mb: 4, psram_mb: 0 },
      { id: 'n8', label: 'N8', psram: null, flash_mb: 8, psram_mb: 0 },
      { id: 'n16', label: 'N16', psram: null, flash_mb: 16, psram_mb: 0 },
      { id: 'n4r2', label: 'N4R2', psram: 'quad', flash_mb: 4, psram_mb: 2 },
      { id: 'n8r2', label: 'N8R2', psram: 'quad', flash_mb: 8, psram_mb: 2 },
      { id: 'n16r2', label: 'N16R2', psram: 'quad', flash_mb: 16, psram_mb: 2 },
      { id: 'n4r8', label: 'N4R8', psram: 'octal', flash_mb: 4, psram_mb: 8 },
      { id: 'n8r8', label: 'N8R8', psram: 'octal', flash_mb: 8, psram_mb: 8 },
      { id: 'n16r8', label: 'N16R8', psram: 'octal', flash_mb: 16, psram_mb: 8 }
    ]
  },
  { id: 'esp32c3', label: 'ESP32-C3', devkit: 'esp32-c3-devkitm-1', variants: [] },
  {
    id: 'esp32c6', label: 'ESP32-C6', devkit: 'esp32-c6-devkitc-1',
    variants: [
      { id: 'mini-1', label: 'MINI-1', module: 'ESP32-C6-MINI-1', psram: null, flash_mb: null, psram_mb: 0 },
      { id: 'wroom-1', label: 'WROOM-1', module: 'ESP32-C6-WROOM-1', psram: null, flash_mb: null, psram_mb: 0 }
    ]
  }
]

/** DevKit layouts of data/boards (tests-js keep them in sync). `module` null = no module data; `variant` null = unknown. */
export const DEVKITS = [
  { id: 'esp32-devkitc-v4', chip: 'esp32', label: 'DevKitC V4', title: 'ESP32-DevKitC', revision: 'V4', module: 'ESP32-WROOM-32E', variant: 'wroom-32e' },
  { id: 'wt32-eth01', chip: 'esp32', label: 'WT32-ETH01', title: 'WT32-ETH01', revision: 'V1.4', module: 'WT32-S1', variant: null },
  { id: 'esp32-s2-devkitc-1', chip: 'esp32s2', label: 'S2-DevKitC-1', title: 'ESP32-S2-DevKitC-1', revision: 'v1', module: 'ESP32-S2-SOLO-2', variant: null },
  { id: 'esp32-s3-devkitc-1', chip: 'esp32s3', label: 'S3-DevKitC-1', title: 'ESP32-S3-DevKitC-1', revision: 'v1.1', module: null, variant: null },
  { id: 'esp32-c3-devkitm-1', chip: 'esp32c3', label: 'C3-DevKitM-1', title: 'ESP32-C3-DevKitM-1', revision: 'v1', module: 'ESP32-C3-MINI-1', variant: null },
  { id: 'esp32-c6-devkitc-1', chip: 'esp32c6', label: 'C6-DevKitC-1', title: 'ESP32-C6-DevKitC-1', revision: 'v1.2', module: 'ESP32-C6-WROOM-1', variant: 'wroom-1' },
  { id: 'esp32-c6-devkitm-1', chip: 'esp32c6', label: 'C6-DevKitM-1', title: 'ESP32-C6-DevKitM-1', revision: 'v1', module: 'ESP32-C6-MINI-1', variant: 'mini-1' }
]

export function devkitInfo(id) {
  return DEVKITS.find(d => d.id === id) || null
}

/** DevKit layouts of one chip (data order). */
export function devkitsOf(chip) {
  return DEVKITS.filter(d => d.chip === chip)
}

/** The DevKit the board view shows: `devkit` when it belongs to `chip`, else the chip's default DevKit (or null). */
export function resolveDevkit(chip, devkit) {
  return devkitInfo(devkit)?.chip === chip ? devkit : chipInfo(chip)?.devkit ?? null
}

/** Variant to preselect: the layout's module.variant; null if the module variant is unknown; else the chip default. */
export function defaultVariant(chip, devkit = null) {
  const c = chipInfo(chip)
  if (!c?.variants.length) return null
  const d = devkitInfo(devkit)
  if (d && d.chip === chip && d.module) return c.variants.some(v => v.id === d.variant) ? d.variant : null
  return c.variants[c.variants.length - 1].id
}

/** "ESP32-DevKitC V4" */
export function devkitTitle(d) {
  return d ? `${d.title}${d.revision ? ` ${d.revision}` : ''}` : ''
}

const stripFamily = s => String(s).replace(/^ESP32-/, '')

/** Module drawing from GET /boards/{id}: name without "ESP32-", flash, antenna, buttons (nothing invented). */
export function boardModule(layout, variant) {
  const m = layout?.module || null
  const known = !m || m.variant !== null && m.variant !== undefined
  const name = variant?.module && known ? stripFamily(variant.module) : m?.name ? stripFamily(m.name) : 'WROOM-1'
  const flash = !known ? m.flash_mb ?? null
    : variant?.flash_mb || (!variant || !m || variant.id === m.variant ? m?.flash_mb : null) || null
  const buttons = Array.isArray(layout?.buttons)
    ? layout.buttons.map(b => (/^reset$/i.test(b) ? 'RST' : String(b).toUpperCase()))
    : ['BOOT', 'RST']
  const antenna = !m ? 'PCB ANTENNA' : m.antenna === 'external' ? 'ANTENNA CONNECTOR' : m.antenna === 'pcb' ? 'PCB ANTENNA' : null
  return { name, flash_mb: flash, antenna, buttons }
}

const PORT_KIND = { usb_serial_jtag: 'USB Serial/JTAG', usb_uart_bridge: 'USB-to-UART bridge', usb_otg: 'USB OTG (drawing only)', rj45: 'RJ45 Ethernet jack' }

/** Jacks on the board edge: USB ports from `usb[]`, then `connectors[]` (WT32: RJ45 "LAN", no USB). */
export function boardPorts(layout) {
  const usb = (Array.isArray(layout?.usb) ? layout.usb : []).map(u => ({
    label: String(u.label), kind: String(u.kind), connector: false,
    title: `${u.label}: ${PORT_KIND[u.kind] || String(u.kind).replace(/_/g, ' ')}${Array.isArray(u.gpios) && u.gpios.length ? ` · GPIO${u.gpios.join('/')}` : ''}`
  }))
  const con = (Array.isArray(layout?.connectors) ? layout.connectors : []).map(c => ({
    label: String(c.label || c.kind || '').toUpperCase(), kind: String(c.kind), connector: true,
    title: `${c.label}: ${PORT_KIND[c.kind] || String(c.kind).replace(/_/g, ' ')}`
  }))
  return [...usb, ...con]
}

/** Part kinds of the `drawing` block (boards.DRAWING_KINDS). Anything else is not drawn. */
export const DRAWING_KINDS = ['usb_port', 'button', 'led', 'power_led', 'ldo', 'bridge_ic', 'rj45', 'phy_ic', 'antenna_connector']
const DRAWING_ZONES = ['below_module', 'middle', 'lower']
const DRAWING_SIDES = ['left', 'center', 'right']

const buttonLabel = b => (/^reset$/i.test(String(b)) ? 'RST' : String(b).toUpperCase())
const gpioList = gpios => (Array.isArray(gpios) && gpios.length ? `IO${gpios.join('/')}` : '')

/** Board-model parts: from `drawing` where quoted, else generic with `schematic: true` (nothing invented).
 *  → { parts: [{ kind, label, sub, gpio, connector, place, schematic, live? }], drawing } */
export function boardParts(layout) {
  const d = layout?.drawing && Array.isArray(layout.drawing.parts) ? layout.drawing : null
  const usb = Array.isArray(layout?.usb) ? layout.usb : []
  const conns = Array.isArray(layout?.connectors) ? layout.connectors : []
  // buttons: the layout's list; without it the old BOOT/RST pair only when there is no drawing either
  const buttons = Array.isArray(layout?.buttons) ? layout.buttons.map(buttonLabel) : d ? [] : ['BOOT', 'RST']
  const onboard = Array.isArray(layout?.onboard) ? layout.onboard : []
  const place = p => (typeof p.edge === 'string'
    ? { edge: ['top', 'bottom', 'left', 'right'].includes(p.edge) ? p.edge : 'bottom', order: Number.isInteger(p.order) ? p.order : 99 }
    : { zone: DRAWING_ZONES.includes(p.zone) ? p.zone : 'middle', side: DRAWING_SIDES.includes(p.side) ? p.side : 'center' })
  const parts = []
  for (const p of d ? d.parts : []) {
    if (!p || !DRAWING_KINDS.includes(p.kind)) continue
    const base = { kind: p.kind, label: String(p.label ?? p.ref ?? ''), sub: '', gpio: null, connector: null, place: place(p), schematic: false }
    if (p.kind === 'usb_port') {
      const u = usb.find(x => x.label === p.ref)
      if (!u) continue
      parts.push({ ...base, label: String(u.label), sub: gpioList(u.gpios), ref: String(u.label), usbKind: String(u.kind),
        connector: ['micro_usb', 'usb_c'].includes(p.connector) ? p.connector : 'generic_usb' })
    } else if (p.kind === 'rj45') {
      const c = conns.find(x => x.kind === 'rj45')
      parts.push({ ...base, label: String(c?.label || p.label || 'RJ45').toUpperCase(), ref: c ? String(c.label) : null, connector: 'rj45' })
    } else if (p.kind === 'button') {
      parts.push({ ...base, label: buttonLabel(p.label) })
    } else if (p.kind === 'led') {
      parts.push({ ...base, gpio: Number.isInteger(p.gpio) ? p.gpio : null, sub: Number.isInteger(p.gpio) ? `IO${p.gpio}` : '' })
    } else if (p.kind === 'antenna_connector') {
      parts.push({ ...base, label: base.label || 'ANT', connector: 'ipex' })
    } else parts.push(base)
  }
  // generic fill-ins for what the layout has but the drawing does not place
  let order = Math.max(0, ...parts.filter(p => p.place.edge === 'bottom').map(p => p.place.order))
  for (const u of usb) {
    if (parts.some(p => p.kind === 'usb_port' && p.ref === u.label)) continue
    parts.push({ kind: 'usb_port', label: String(u.label), sub: gpioList(u.gpios), gpio: null, ref: String(u.label), usbKind: String(u.kind),
      connector: 'generic_usb', place: { edge: 'bottom', order: ++order }, schematic: true })
  }
  for (const c of conns) {
    if (c.kind !== 'rj45' || parts.some(p => p.kind === 'rj45')) continue
    parts.push({ kind: 'rj45', label: String(c.label || 'RJ45').toUpperCase(), sub: '', gpio: null, ref: String(c.label), connector: 'rj45',
      place: { edge: 'bottom', order: ++order }, schematic: true })
  }
  const drawnButtons = parts.filter(p => p.kind === 'button').map(p => p.label)
  const missing = buttons.filter(b => !drawnButtons.includes(b))
  missing.forEach((b, i) => parts.push({ kind: 'button', label: b, sub: '', gpio: null, connector: null, schematic: true,
    place: { zone: 'lower', side: missing.length === 1 ? 'center' : i === 0 ? 'left' : i === missing.length - 1 ? 'right' : 'center' } }))
  // on-board LEDs generic only without a drawing (a drawing lists what it can quote; nothing is added to it)
  const leds = d ? [] : onboard.filter(o => /\bLED\d*\b/i.test(String(o.what || '')) && Number.isInteger(o.gpio) && !parts.some(p => p.kind === 'led' && p.gpio === o.gpio))
  leds.forEach((o, i) => parts.push({ kind: 'led', label: String(o.what).split(/[\s,(]/)[0].toUpperCase().slice(0, 6), sub: `IO${o.gpio}`, gpio: o.gpio,
    connector: null, schematic: true, place: { zone: 'middle', side: leds.length === 1 ? 'left' : i === 0 ? 'left' : i === leds.length - 1 ? 'right' : 'center' } }))
  return { parts, drawing: Boolean(d) }
}

/** pinView state → model state (pad ring, label symbol). `unchecked` has none (null). */
export const PIN_ART_STATE = {
  free: 'free', used: 'assigned', 'used-warn': 'caution', 'used-bad': 'assigned_blocked', warn: 'caution', bad: 'blocked',
  power: 'power', ground: 'ground', reset: 'ground', nc: 'nc', signal: 'signal', unchecked: null
}

/** Word of a pinView state for aria-label and title (ring + symbol + word). */
export function pinStateWord(state) {
  return {
    free: 'free', used: 'assigned', 'used-warn': 'assigned · caution', 'used-bad': 'assigned · blocked', warn: 'caution', bad: 'blocked',
    power: 'power', ground: 'ground', reset: 'reset', nc: 'not connected', signal: 'board signal'
  }[state] || 'not checked'
}

/** Reservation of a header pin for the bracket on the strip: octal PSRAM (from the module variant), else the main
 *  reason of the map entry when it is a PSRAM, flash or USB rule. → label or null. */
export function pinReserve(hp, base, octal) {
  if (octal && Number.isInteger(hp?.gpio) && hp.gpio >= 33 && hp.gpio <= 37) return 'OCTAL PSRAM'
  const r = mainReason(base)
  if (!r || (r.severity !== 'blocked' && r.severity !== 'caution')) return null
  const tag = ruleTag(r.rule_id)
  return tag === 'PSRAM' ? 'PSRAM' : tag === 'FLASH' ? 'SPI FLASH' : tag === 'USB' ? 'USB' : null
}

/** Brackets of one side: runs of ≥ 2 neighbouring pins (no separator between them) with the same reservation.
 *  items: [{ slot, reserve, tone }] in slot order → [{ from, to, label, tone }] (tone 'bad' when a pin is blocked). */
export function boardBrackets(items) {
  const out = []
  let run = null
  for (const it of items || []) {
    if (run && it.reserve && it.reserve === run.label && it.slot === run.to + 1) {
      run.to = it.slot
      if (it.tone === 'bad') run.tone = 'bad'
      continue
    }
    if (run && run.to > run.from) out.push(run)
    run = it.reserve ? { from: it.slot, to: it.slot, label: it.reserve, tone: it.tone === 'bad' ? 'bad' : 'warn' } : null
  }
  if (run && run.to > run.from) out.push(run)
  return out
}

/** Everything the board model draws (PLAN BoardView and the twin chat card share it; pure).
 *  → { title, revision, module, parts, notes, sides, brackets, views, ledState, live, schematic } */
export function boardArtModel({ layout, chip = null, variant = null, base = new Map(), used = new Map(), selected = null, suggest = [], live = [], rev = null } = {}) {
  const mod = boardModule(layout, variant)
  const m = layout?.module || null
  const known = !m || (m.variant !== null && m.variant !== undefined)
  const octal = variant?.psram === 'octal'
  const psram = variant && known ? variant.psram_mb : m?.psram_mb
  const modName = `${mod.name}${variant && !variant.module ? ` · ${variant.label}` : ''}`
  const size = layout?.drawing?.module_size_mm
  const sizeOk = size && size.w > 0 && size.h > 0 && (!variant || !m || variant.id === m.variant)
  const { parts, drawing } = boardParts(layout)
  const views = { left: [], right: [] }
  const sides = { left: [], right: [] }
  const brackets = { left: [], right: [] }
  const ledState = {}
  for (const side of ['left', 'right']) {
    const items = []
    const rows = Array.isArray(layout?.[side]) ? layout[side] : []
    let slot = 0
    rows.forEach((hp, i) => {
      if (i > 0 && hp.header !== rows[i - 1].header) {
        views[side].push({ sep: String(hp.header ?? ''), slot })
        sides[side].push({ sep: String(hp.header ?? '') })
        slot++
      }
      const gpio = Number.isInteger(hp.gpio) ? hp.gpio : null
      const entry = gpio !== null ? base.get(gpio) : null
      const view = pinView(hp, gpio !== null ? used.get(gpio) : null, entry, layout?.onboard)
      const art = PIN_ART_STATE[view.state] ?? null
      const square = hp.n === 1 || view.state === 'power' || view.state === 'ground' || view.state === 'reset'
      const reserve = pinReserve(hp, entry, octal)
      views[side].push({ hp, view, art, square, reserve, slot })
      sides[side].push({ pin: { n: hp.n, state: art, square, selected: gpio !== null && gpio === selected, suggested: gpio !== null && suggest.includes(gpio) } })
      items.push({ slot, reserve, tone: view.state === 'bad' || view.state === 'used-bad' ? 'bad' : 'warn' })
      if (gpio !== null && ['assigned', 'assigned_blocked', 'blocked'].includes(art)) ledState[gpio] = art
      slot++
    })
    brackets[side] = boardBrackets(items)
  }
  const notes = []
  const unknown = Boolean(chip?.variants?.length) && !variant
  if (unknown) notes.push({ id: 'unknown', tone: 'warn', text: 'MODULE VARIANT UNKNOWN', title: 'Module variant unknown: rules that depend on the PSRAM are not passed. Choose the module if you know it.' })
  if (variant?.psram === 'spi') notes.push({ id: 'spi', tone: 'warn', text: 'PSRAM · IO16/17 RESERVED', title: 'ESP32-WROVER modules reserve GPIO16/17 for internal use (PSRAM)' })
  if (variant?.psram === 'quad') notes.push({ id: 'quad', tone: 'dim', text: 'QUAD PSRAM · NO EXTRA PINS', title: 'Quad PSRAM uses the flash pins; no header pin is reserved' })
  return {
    title: String(layout?.title || ''), revision: String(layout?.revision || ''), schematic: !drawing,
    module: { chip: chip?.label || '', name: modName, variant: '', flash_mb: mod.flash_mb, psram_mb: psram || null, rev: rev ? `rev ${rev}` : '',
      antenna: !m ? 'pcb' : m.antenna === 'external' ? 'external' : m.antenna === 'pcb' ? 'pcb' : null, antennaText: mod.antenna,
      sizeMm: sizeOk ? { w: size.w, h: size.h } : null },
    parts, notes, views, sides, brackets, ledState, live, buttons: mod.buttons
  }
}

/** Board-level warning severity → tone, symbol, word (never colour only). */
export function warningMeta(severity) {
  switch (severity) {
    case 'danger': return { tone: 'bad', symbol: '⚠', word: 'DANGER' }
    case 'caution': return { tone: 'warn', symbol: '!', word: 'CAUTION' }
    default: return { tone: 'dim', symbol: 'i', word: 'NOTE' }
  }
}

/** `layout.warnings` sorted danger > caution > info, each with its meta. */
export function boardWarnings(layout) {
  const order = { danger: 0, caution: 1, info: 2 }
  return (Array.isArray(layout?.warnings) ? layout.warnings : [])
    .filter(w => w && w.message)
    .map((w, i) => ({ id: w.id || `w${i}`, severity: w.severity, message: String(w.message), source_id: w.source_id || null, ...warningMeta(w.severity), i }))
    .sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3) || a.i - b.i)
    .map(({ i, ...w }) => w)
}

/** Variants grouped by PSRAM kind for the module choice (none, SPI, quad, octal; only non-empty groups, data order). */
export function variantGroups(chip) {
  const c = chipInfo(chip)
  const groups = [[null, 'no PSRAM'], ['spi', 'PSRAM'], ['quad', 'quad PSRAM'], ['octal', 'octal PSRAM']]
  return groups.map(([psram, label]) => ({ psram, label, variants: (c?.variants || []).filter(v => (v.psram ?? null) === psram) }))
    .filter(g => g.variants.length)
}

export const MODES = [
  ['out', 'out'], ['in', 'in'], ['in_pullup', 'in · pull-up'], ['in_pulldown', 'in · pull-down'], ['adc', 'adc'],
  ['pwm', 'pwm'], ['i2c_sda', 'i²c sda'], ['i2c_scl', 'i²c scl'], ['spi_sck', 'spi sck'], ['spi_mosi', 'spi mosi'],
  ['spi_miso', 'spi miso'], ['spi_cs', 'spi cs'], ['uart_tx', 'uart tx'], ['uart_rx', 'uart rx'], ['touch', 'touch']
]
const MODE_LABEL = Object.fromEntries(MODES)

export const ROLE_RE = /^[A-Z0-9_]{1,24}$/
export const NET_RE = /^[A-Za-z0-9_+\-./]{1,32}$/

export function chipInfo(id) {
  return CHIPS.find(c => c.id === id) || null
}

export function variantInfo(chip, variant) {
  return chipInfo(chip)?.variants.find(v => v.id === variant) || null
}

/** Toolbar title of a module variant: "8 MB flash, 8 MB PSRAM (octal)", "4 MB flash, no PSRAM". */
export function variantTitle(v) {
  if (!v) return ''
  const psram = v.psram ? `${v.psram_mb ? `${v.psram_mb} MB ` : ''}PSRAM${['quad', 'octal'].includes(v.psram) ? ` (${v.psram})` : ''}` : 'no PSRAM'
  return `${v.flash_mb ? `${v.flash_mb} MB flash` : v.module || v.label}, ${psram}`
}

export function modeLabel(mode) {
  return MODE_LABEL[mode] || String(mode || '—')
}

/** Mode as one word of at most 8 characters for the inspector's assignments column (64 px at 11 px): the input
 *  modes with a pull resistor as the Arduino word (INPUT_PULLUP → "pullup"), every other label already fits;
 *  modeLabel() stays the title and the screen-reader text. */
const MODE_SHORT = { in_pullup: 'pullup', in_pulldown: 'pulldown' }
export function modeShort(mode) {
  return MODE_SHORT[mode] || modeLabel(mode)
}

export function gpioName(n) {
  return Number.isInteger(n) ? `GPIO${n}` : '—'
}

/** Verdict → class suffix, symbol, word. Unknown verdicts read as "not checked", never as ok. */
export function verdictMeta(verdict) {
  switch (verdict) {
    case 'ok': return { tone: 'ok', symbol: '✓', text: 'ok', stamp: 'OK' }
    case 'caution': return { tone: 'warn', symbol: '!', text: 'caution', stamp: 'CAUTION' }
    case 'blocked': return { tone: 'bad', symbol: '✕', text: 'blocked', stamp: 'BLOCKED' }
    default: return { tone: 'none', symbol: '?', text: 'not checked', stamp: 'UNCHECKED' }
  }
}

/** "J3-13" → {header: "J3", n: 13}. */
export function splitHeader(h) {
  const m = /^([A-Z]+\d*)-(\d+)$/.exec(String(h || ''))
  return m ? { header: m[1], n: Number(m[2]) } : null
}

/** Short tag for a rule id on the board (the full message stays in the inspector). */
const RULE_TAGS = {
  strapping: 'STRAP', octal_psram: 'PSRAM', psram_16_17: 'PSRAM', spi_flash: 'FLASH', usb_jtag: 'USB', uart0: 'UART0', pad_jtag: 'JTAG',
  jtag: 'JTAG', adc2_wifi: 'ADC2', input_only: 'IN ONLY', no_pulls: 'NO PULL', gpio36_39_irq: 'IRQ', onboard: 'ON-BOARD'
}

export function ruleTag(ruleId) {
  const key = String(ruleId || '').split('.').pop()
  return RULE_TAGS[key] || key.toUpperCase().slice(0, 8)
}

/** Highest-severity reason of a check/map entry (blocked > caution > info). */
export function mainReason(entry) {
  const order = { blocked: 0, caution: 1, info: 2 }
  const rs = Array.isArray(entry?.reasons) ? [...entry.reasons] : []
  rs.sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3))
  return rs[0] || null
}

/**
 * Project assignments merged with a pins.check result. A check entry only counts when role, pin and mode match
 * (a stale or foreign check never overrides the project); otherwise the verdict stored in the project is used.
 */
export function mergeAssignments(assignments, checkPins) {
  const byRole = new Map()
  for (const p of Array.isArray(checkPins) ? checkPins : []) byRole.set(p.role, p)
  return (Array.isArray(assignments) ? assignments : []).map(a => {
    const c = byRole.get(a.role)
    const fresh = c && c.pin === a.pin && c.mode === a.mode
    return {
      role: a.role, mode: a.mode, pin: a.pin, net: a.net ?? null, updated_by: a.updated_by ?? null,
      verdict: fresh ? c.verdict : (a.verdict ?? null),
      rule_ids: fresh ? c.rule_ids || [] : a.rule_ids || [],
      reasons: fresh ? c.reasons || [] : [],
      functions: fresh ? c.functions || [] : [],
      header: fresh ? c.header ?? null : null,
      alternatives: fresh ? c.alternatives || [] : [],
      checked: Boolean(fresh)
    }
  })
}

export function countVerdicts(rows) {
  const out = { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
  for (const r of rows || []) {
    if (r.verdict === 'ok') out.ok++
    else if (r.verdict === 'caution') out.caution++
    else if (r.verdict === 'blocked') out.blocked++
    else out.unchecked++
  }
  return out
}

/** Map check (all header GPIOs, mode "in") → Map gpio → entry. */
export function mapByGpio(mapResult) {
  const m = new Map()
  for (const p of mapResult?.pins || []) m.set(p.pin, p)
  return m
}

/**
 * View state of one header pin.
 *   hp      layout pin {header, n, label, kind, gpio?}
 *   used    merged assignment on this GPIO (or null)
 *   base    map entry for this GPIO (or null when the map is not available)
 * → {state, tone, name, tag, symbol, title, gpio}
 *   state: power | ground | reset | nc | signal | used | used-warn | used-bad | free | warn | bad | unchecked
 */
export function pinView(hp, used, base, onboard) {
  const gpio = Number.isInteger(hp?.gpio) ? hp.gpio : null
  const label = String(hp?.label ?? '')
  if (hp?.kind === 'power') return { state: 'power', tone: 'power', name: label, tag: '', symbol: '⏻', title: `${label} supply`, gpio: null }
  if (hp?.kind === 'ground') return { state: 'ground', tone: 'faint', name: 'GND', tag: '', symbol: '⏚', title: 'Ground', gpio: null }
  // nc / signal: plain pins with symbol and word, never colour only
  if (hp?.kind === 'nc') return { state: 'nc', tone: 'faint', name: label || 'NC', tag: '∅ unwired', symbol: '∅', title: `${label || 'NC'}: not connected`, gpio: null }
  if (hp?.kind === 'signal') return { state: 'signal', tone: 'dim', name: label, tag: '~ signal', symbol: '~', title: `${label}: board signal, not a GPIO`, gpio: null }
  if (hp?.kind === 'reset' || gpio === null) return { state: 'reset', tone: 'faint', name: label || '—', tag: '', symbol: '', title: label === 'RST' ? 'Reset (EN)' : label === 'EN' ? 'EN (chip enable, reset)' : label, gpio: null }
  // "4" (S3-DevKitC-1) and "IO4" (DevKitC V4, C3-DevKitM-1) both read IO4; named pins (TX, VP, D2) keep the number as tag
  const plain = /^\d+$/.test(label) || label === `IO${gpio}`
  const name = plain ? `IO${gpio}` : label
  const suffix = plain ? '' : ` · ${gpio}`
  if (used) {
    const v = verdictMeta(used.verdict)
    const state = used.verdict === 'blocked' ? 'used-bad' : used.verdict === 'caution' ? 'used-warn' : 'used'
    const sym = used.verdict === 'ok' ? '' : ` ${v.symbol}`
    return { state, tone: state === 'used' ? 'active' : v.tone, name, tag: `${used.role}${sym}`, symbol: v.symbol,
      title: `${gpioName(gpio)} → ${used.role} (${modeLabel(used.mode)}): ${v.text}`, gpio }
  }
  const board = (onboard || []).find(o => o.gpio === gpio)
  if (!base) {
    return { state: 'unchecked', tone: 'faint', name, tag: board ? 'ON-BOARD' : '', symbol: '?', title: `${gpioName(gpio)}: not checked`, gpio }
  }
  const reason = mainReason(base)
  const v = verdictMeta(base.verdict)
  if (base.verdict === 'blocked' || base.verdict === 'caution') {
    let tag = reason ? ruleTag(reason.rule_id) : v.stamp
    if (reason?.rule_id === 'onboard' && board) tag = clipTag(board.what)
    return { state: base.verdict === 'blocked' ? 'bad' : 'warn', tone: v.tone, name, tag: `${tag}${suffix}`, symbol: v.symbol,
      title: `${gpioName(gpio)}: ${v.text}${reason ? ` — ${reason.message}` : ''}`, gpio }
  }
  return { state: 'free', tone: 'ok', name, tag: suffix ? suffix.slice(3) : '', symbol: '○',
    title: `${gpioName(gpio)}: free${reason ? ` (${reason.message})` : ''}`, gpio }
}

/** Short on-board tag: text before a comma or bracket, whole words up to 10 characters ("Ethernet REF_CLK input
 *  ..." → "ETHERNET", "485_EN, the RS485 enable pin" → "485_EN"); a single longer word is cut. */
export function clipTag(what) {
  const s = String(what || '').split(/[,(]/)[0].trim().toUpperCase()
  if (s.length <= 10) return s
  let out = ''
  for (const word of s.split(/\s+/)) {
    const next = out ? `${out} ${word}` : word
    if (next.length > 10) break
    out = next
  }
  return out || s.slice(0, 10)
}

/** Validate an assign form → list of {field, message}. */
export function validateAssign({ role, mode, pin, net }) {
  const errors = []
  if (!ROLE_RE.test(String(role || ''))) errors.push({ field: 'role', message: 'Role: A–Z, 0–9 and _ only, 1–24 characters.' })
  if (!MODE_LABEL[mode]) errors.push({ field: 'mode', message: 'Choose a mode.' })
  if (!Number.isInteger(pin) || pin < 0 || pin > 48) errors.push({ field: 'pin', message: 'GPIO number 0–48.' })
  if (net && !NET_RE.test(String(net))) errors.push({ field: 'net', message: 'Net: letters, digits and _ + - . / only, up to 32.' })
  return errors
}

/** Board pins of a layout as rows for the two sides (left J1/J2, right J3; WT32: PROG + IO on both sides). */
export function headerRows(layout) {
  return { left: Array.isArray(layout?.left) ? layout.left : [], right: Array.isArray(layout?.right) ? layout.right : [] }
}

/** Header ids of one side in order, each once (WT32 left: ["PROG", "IO"]). */
export function headerIds(rows) {
  return [...new Set((rows || []).map(p => p.header).filter(Boolean))]
}

/** All GPIOs broken out on the headers (for the full-board map check). */
export function headerGpios(layout) {
  const { left, right } = headerRows(layout)
  return [...left, ...right].filter(p => p.kind === 'gpio' && Number.isInteger(p.gpio)).map(p => p.gpio)
}

/** Pseudo assignments for the board map: every header GPIO in mode "in" (role IO<n>). */
export function mapAssignments(layout) {
  return headerGpios(layout).map(g => ({ role: `IO${g}`, mode: 'in', pin: g }))
}

/** Chips for suggestions: [{gpio, header}] minus taken pins. */
export function suggestionChips(suggestResult, role) {
  const req = (suggestResult?.requests || []).find(r => !role || r.role === role)
  return req ? (req.suggestions || []).map(s => ({ gpio: s.gpio, header: s.header || null })) : []
}

/** One finding for the "Ask Hermes" draft: "BUTTON on GPIO35 is blocked — Wired to …" (no outer brackets). */
export function findingText(row) {
  const msg = String(row?.reasons?.[0]?.message || '').trim().replace(/[.\s]+$/, '')
  return `${row?.role} on GPIO${row?.pin} is ${row?.verdict}${msg ? ` — ${msg}` : ''}`
}
