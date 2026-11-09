// Board model graphic layer: the pcb with edge and thickness, the module
// (shield can with print, PCB antenna with keep-out or antenna connector), plastic header strips with tin pads and
// state rings, reservation brackets on the strips, ports, buttons and on-board parts from `drawing` (lib/pins.js
// boardParts). Pure string functions on top of lib/art.js (same bundle scope; tests concatenate both files), no SDK,
// no DOM. Geometry only from lib/board-geom.js. Every data value runs through artEsc / artNum (art.js).
// mode 'full': the PLAN layer behind the DOM pins (labels, tags and names are DOM, outside the pcb).
// mode 'compact': body, module, strips, pads with state, ports; no text at all (the twin chat card scales it).

const AB_SILK = 'var(--cb-silk)'
const AB_LS = 0.6 // letter-spacing of the silk print (px)
const abW = (s, px = 10, ls = AB_LS) => [...String(s ?? '')].length * (0.6 * px + ls)
// a side with a reservation bracket keeps its vertical label (centre AB_BR_TEXT from the pad, 13 px line box) clear;
// the label stands 30 px in from the pad (7 px air to the bracket line), regular weight, so it reads as silk
// print beside the strip and does not compete with the pads and their state rings
const AB_BR_TEXT = 30
const AB_BR_EXTRA = 12
const AB_ANT_LH = 13
const AB_LH = 13 // 10 px silk lines (line box 13 px)
const AB_SILK_LH = 14 // silk block lines (11 px title)
const AB_MOD_MIN = 72 // module height the layout aims for
const AB_MOD_FLOOR = 50 // never smaller (antenna 34 + a can with one line)
const AB_MOD_W = [104, 200]

/** Footprint of a part (part-local box; body = the drawn object, label lines beside or below it). `join`: a port's
 *  label and pins in one line with this separator ("UART · IO43/44"), else two lines. */
function artBoardFootprint(p, mode, join = null) {
  const text = mode !== 'compact'
  const lines = join !== null && p.label && p.sub ? [`${p.label}${join}${p.sub}`] : [p.label, p.sub].filter(Boolean)
  const tw = text ? Math.max(0, ...lines.map(l => abW(l))) : 0
  switch (p.kind) {
    case 'usb_port': case 'rj45': {
      const [w, h] = ART_PORT_SIZE[p.connector] || ART_PORT_SIZE.generic_usb
      const lh = text ? lines.length * AB_LH + 2 : 0
      return { w: Math.max(w, tw), h: h + lh, body: { w, h }, labelPos: 'above', lines: text ? lines : [] }
    }
    case 'antenna_connector': return { w: 18 + (text ? 5 + tw : 0), h: 18, body: { w: 18, h: 18 }, labelPos: 'right', lines: text ? lines : [] }
    case 'button': return { w: Math.max(30, text ? abW(p.label) : 0), h: text ? 44 : 26, body: { w: 30, h: 26 }, labelPos: 'below', lines: text ? [p.label] : [] }
    case 'led': return { w: 14 + (text ? 5 + tw : 0), h: Math.max(14, text ? lines.length * AB_LH : 0), body: { w: 14, h: 14 }, labelPos: 'right', lines: text ? lines : [] }
    case 'power_led': return { w: 12 + (text ? 5 + tw : 0), h: 12, body: { w: 12, h: 7 }, labelPos: 'right', lines: text ? lines : [] }
    case 'ldo': return { w: Math.max(26, tw), h: 24 + (text ? 15 : 0), body: { w: 26, h: 24 }, labelPos: 'below', lines: text ? [p.label] : [] }
    case 'bridge_ic': return { w: Math.max(26, tw), h: 30 + (text ? 15 : 0), body: { w: 26, h: 30 }, labelPos: 'below', lines: text ? [p.label] : [] }
    case 'phy_ic': return { w: Math.max(30, tw), h: 38 + (text ? 15 : 0), body: { w: 30, h: 38 }, labelPos: 'below', lines: text ? [p.label] : [] }
    default: return null
  }
}

/** Horizontal placement of the parts of one band inside [x0, x1]: left group from x0, right group to x1, centre
 *  group centred; if the groups collide, everything is spread evenly in L→C→R order. */
function artBoardRow(items, x0, x1) {
  const gap = 8
  const width = list => list.reduce((a, it) => a + it.fp.w, 0) + Math.max(0, list.length - 1) * gap
  const by = s => items.filter(it => it.side === s)
  const L = by('left'), C = by('center'), R = by('right')
  const put = (list, start) => { let x = start; for (const it of list) { it.x = x; x += it.fp.w + gap } }
  put(L, x0)
  put(R, x1 - width(R))
  put(C, (x0 + x1) / 2 - width(C) / 2)
  const ext = list => (list.length ? [list[0].x, list[list.length - 1].x + list[list.length - 1].fp.w] : null)
  const [l, c, r] = [ext(L), ext(C), ext(R)]
  const clash = (a, b) => a && b && a[1] + 4 > b[0]
  if (clash(l, c) || clash(c, r) || clash(l, r)) {
    const all = [...L, ...C, ...R]
    const free = Math.max(0, (x1 - x0) - all.reduce((a, it) => a + it.fp.w, 0))
    const g = all.length > 1 ? free / (all.length - 1) : 0
    let x = all.length > 1 ? x0 : (x0 + x1) / 2 - all[0].fp.w / 2
    for (const it of all) { it.x = x; x += it.fp.w + g }
  }
}

/** Module lines on the can that fit its width (first line 13 px bold, others 10 px), at most `max` lines. */
function artBoardCanLines(m, maxW, max) {
  const fit13 = s => [...String(s)].length * (7.8 + 1.4) <= maxW
  const fit10 = s => abW(s) <= maxW
  const out = []
  if (m.chip && fit13(m.chip)) out.push(m.chip)
  const name = m.variant ? `${m.name} · ${m.variant}` : m.name
  if (name && fit10(name)) out.push(name)
  else {
    if (m.name && fit10(m.name)) out.push(m.name)
    if (m.variant && fit10(m.variant)) out.push(m.variant)
  }
  const mem = [m.flash_mb ? `${m.flash_mb} MB flash` : null, m.psram_mb ? `${m.psram_mb} MB PSRAM` : null].filter(Boolean)
  if (mem.length === 2 && fit10(mem.join(' · '))) out.push(mem.join(' · '))
  else for (const l of mem) if (fit10(l)) out.push(l)
  if (m.rev && fit10(m.rev)) out.push(m.rev)
  return out.slice(0, Math.max(0, max))
}

/**
 * Placement plan of the model in body coordinates (x from the left pcb edge, y from the pcb top). Pure; artBoard
 * draws it, the DOM notes use `notes`, tests check `texts` for overlaps.
 *   model { title, revision, module {chip, name, variant, flash_mb, psram_mb, antenna, sizeMm, rev}, parts, notes }
 */
export function artBoardPlan(model, g, { mode = 'full' } = {}) {
  const text = mode !== 'compact'
  const x0 = g.inner.x0 + (text && model.brackets?.left?.length ? AB_BR_EXTRA : 0)
  const x1 = g.inner.x1 - (text && model.brackets?.right?.length ? AB_BR_EXTRA : 0)
  const innerW = x1 - x0
  const parts = (model.parts || []).map(p => ({ part: p, fp: artBoardFootprint(p, mode) })).filter(it => it.fp)
  const bandOf = it => {
    const pl = it.part.place || {}
    if (pl.edge === 'bottom') return 'bottom'
    if (pl.edge === 'top') return 'below_module'
    if (pl.edge === 'left' || pl.edge === 'right') return 'lower'
    return pl.zone || 'middle'
  }
  for (const it of parts) {
    it.band = bandOf(it)
    it.side = it.part.place?.edge === 'left' || it.part.place?.edge === 'right' ? it.part.place.edge : it.part.place?.side || 'center'
  }
  const inBand = b => parts.filter(it => it.band === b)
  const bottom = inBand('bottom').sort((a, b) => (a.part.place.order || 0) - (b.part.place.order || 0))
  let lower = inBand('lower')
  // ports and buttons share the bottom band when they fit side by side (C3: one port between BOOT and RST)
  const sumW = list => list.reduce((a, it) => a + it.fp.w, 0) + Math.max(0, list.length - 1) * 10
  // the bottom band keeps the full inner width unless a reservation bracket reaches down to it
  const lowBracket = side => text && (model.brackets?.[side] || []).some(br => boardSlotTop(g, br.to) + g.rowH + 2 > g.pcbBottom - 80)
  const bx0 = g.inner.x0 + (lowBracket('left') ? AB_BR_EXTRA : 0)
  const bx1 = g.inner.x1 - (lowBracket('right') ? AB_BR_EXTRA : 0)
  const bandW = bx1 - bx0
  const mergeable = lower.length > 0 && bottom.length > 0 && lower.every(it => it.part.kind === 'button' && it.side !== 'center')
  const fits = list => (mergeable ? sumW(lower) + sumW(list) + 16 : sumW(list)) <= bandW
  // port label and pins in one line when the band has room ("UART · IO43/44", else "UART IO43/44"), else two
  if (text && bottom.some(it => it.part.kind === 'usb_port' && it.part.sub)) {
    for (const sep of [' · ', ' ']) {
      const cand = bottom.map(it => (it.part.kind === 'usb_port' && it.part.sub ? { ...it, fp: artBoardFootprint(it.part, mode, sep) } : it))
      if (fits(cand)) { cand.forEach((c, i) => { bottom[i].fp = c.fp }); break }
    }
  }
  const merged = mergeable && fits(bottom)
  // bottom band: port bodies end portOut below the pcb edge, their labels stand above them
  const pcbB = g.pcbBottom
  let bottomH = 0
  for (const it of bottom) bottomH = Math.max(bottomH, it.fp.h - g.portOut)
  if (merged) for (const it of lower) bottomH = Math.max(bottomH, it.fp.h + 6)
  const bottomTop = pcbB - bottomH
  const bands = ['below_module', 'middle', 'lower'].map(name => ({ name, items: name === 'lower' && merged ? [] : inBand(name) }))
    .filter(b => b.items.length).map(b => ({ ...b, h: Math.max(...b.items.map(it => it.fp.h)) }))
  if (merged) lower = []
  // silk print: title, revision, "schematic · not to scale"; richer variants first, the note is required
  const note = 'schematic · not to scale'
  const titleOk = model.title && abW(model.title, 11, 1.2) <= innerW
  const silkOpts = !text ? [[]] : [
    // two lines first
    titleOk && model.revision && abW(`${model.revision} · ${note}`) <= innerW ? [[model.title, 11], [`${model.revision} · ${note}`, 10]] : null,
    titleOk && abW(note) <= innerW ? [[model.title, 11], [note, 10]] : null,
    titleOk ? [[model.title, 11], [`${model.revision ? `${model.revision} · ` : ''}schematic`, 10], ['not to scale', 10]] : null,
    abW(note) <= innerW ? [[note, 10]] : [['schematic', 10], ['not to scale', 10]]
  ].filter(Boolean)
  // DOM notes on the pcb (variant unknown, PSRAM reservations): each wraps inside the body, 13 px per line
  const noteBoxes = text ? (model.notes || []).map(n => ({ text: String(n?.text ?? n), lines: Math.max(1, Math.ceil((abW(n?.text ?? n) + 18) / Math.max(1, innerW))) })) : []
  const noteH = noteBoxes.reduce((a, n) => a + n.lines * 13 + 6, 0) + Math.max(0, noteBoxes.length - 1) * 4
  const top = 5
  let gapMin = 4
  let silk = silkOpts[silkOpts.length - 1]
  let modH = AB_MOD_MIN
  const roomFor = opt => {
    const silkH = opt.length ? opt.length * AB_SILK_LH + 2 : 0
    const nGaps = bands.length + (opt.length ? 1 : 0) + (noteH ? 1 : 0) + 1
    return bottomTop - top - bands.reduce((a, b) => a + b.h, 0) - silkH - noteH - nGaps * gapMin
  }
  for (const opt of silkOpts) {
    silk = opt
    modH = roomFor(opt)
    if (modH >= AB_MOD_MIN + 24 || opt === silkOpts[silkOpts.length - 1]) break
  }
  // a crowded small board (15 rows, narrow body, notes): tighter gaps before the module goes below its minimum
  if (modH < AB_MOD_MIN) { gapMin = 2; modH = roomFor(silk) }
  // module size: from module_size_mm when quoted, else the aspect of the module kind (schematic)
  const m = model.module || {}
  const aspect = m.sizeMm && m.sizeMm.w > 0 && m.sizeMm.h > 0 ? m.sizeMm.w / m.sizeMm.h : /MINI/i.test(String(m.name)) ? 0.8 : 0.7
  const maxW = Math.min(innerW, AB_MOD_W[1])
  const room = modH
  let mh = Math.max(AB_MOD_FLOOR, Math.min(room, Math.round(maxW / aspect)))
  const mw = Math.round(Math.max(Math.min(AB_MOD_W[0], maxW), Math.min(maxW, mh * aspect)))
  mh = Math.round(mh)
  const leftover = Math.max(0, room - mh)
  const silkH = silk.length ? silk.length * AB_SILK_LH + 2 : 0
  const blocks = [...(noteH ? [{ name: 'notes', h: noteH }] : []), ...bands.slice(0, 2), ...(silk.length ? [{ name: 'silk', h: silkH }] : []), ...bands.slice(2)]
  // silk right above the bottom band, the leftover room goes above it
  const silkLast = blocks.length > 1 && blocks[blocks.length - 1].name === 'silk'
  const gap = gapMin + leftover / (blocks.length + (silkLast ? 0 : 1))
  const mod = { x: Math.round(x0 + (innerW - mw) / 2), y: top, w: mw, h: mh, schematic: !m.sizeMm }
  // the keep-out note in one line, or two when the module is narrow (each line box 13 px, lines 13 px apart)
  const antLines = text && m.antenna === 'pcb' ? (abW('keep metal clear', 10, 0.4) <= mw - 16 ? ['keep metal clear'] : ['keep metal', 'clear']) : []
  const ant = m.antenna === 'pcb' ? Math.max(antLines.length > 1 ? 44 : 30, Math.min(52, Math.round(mh * 0.28))) : m.antenna === 'external' ? 28 : 0
  mod.antLines = antLines
  mod.antH = ant
  mod.can = { x: mod.x + 5, y: mod.y + ant + 4, w: mw - 10, h: mh - ant - 9 }
  mod.lines = text ? artBoardCanLines(m, mod.can.w - 16, Math.floor((mod.can.h - 8) / 16)) : []
  let y = top + mh + gap
  const out = { module: mod, notes: [], parts: [], silk: null, texts: [], merged, bottomTop }
  for (const b of blocks) {
    if (b.name === 'notes') {
      let ny = y
      out.notes = noteBoxes.map(n => { const r = { text: n.text, x: x0, y: Math.round(ny), w: innerW, h: n.lines * 13 + 6 }; ny += r.h + 4; return r })
    }
    else if (b.name === 'silk') out.silk = { y: Math.round(y), x: x0 + innerW / 2, lines: silk }
    else {
      artBoardRow(b.items, x0, x1)
      for (const it of b.items) out.parts.push({ ...it, y: Math.round(y + (b.h - it.fp.h) / 2) })
    }
    y += b.h + gap
  }
  // bottom band
  if (bottom.length) {
    const lw = merged ? inBand('lower') : []
    const lL = lw.filter(it => it.side === 'left'), lR = lw.filter(it => it.side === 'right')
    let gx = bx0
    for (const it of lL) { it.x = gx; gx += it.fp.w + 10 }
    let rx = bx1
    for (const it of [...lR].reverse()) { rx -= it.fp.w; it.x = rx; rx -= 10 }
    const span0 = merged ? gx : bx0, span1 = merged ? rx + (lR.length ? 10 : 0) : bx1
    let px = span0 + (span1 - span0 - sumW(bottom)) / 2
    for (const it of bottom) {
      it.x = px; px += it.fp.w + 10
      out.parts.push({ ...it, y: pcbB + g.portOut - it.fp.h })
    }
    for (const it of lw) out.parts.push({ ...it, y: pcbB - 6 - it.fp.h })
  }
  for (const p of out.parts) { p.x = Math.round(p.x); p.y = Math.round(p.y) }
  // port labels end on the 8 px grid (line box bottom = baseline + 3.5), at least 2 px above the port body;
  // the label only moves up (≤ 7 px) where no other part is in the way, else it keeps its place in the footprint
  for (const p of out.parts) {
    if (p.fp.labelPos !== 'above' || !p.fp.lines.length) continue
    const bodyTop = p.y + p.fp.h - p.fp.body.h
    const bottomY = Math.floor((bodyTop - 2) / 8) * 8
    const n = p.fp.lines.length
    const top = bottomY - n * AB_LH
    const free = out.parts.every(o => o === p || o.x >= p.x + p.fp.w || o.x + o.fp.w <= p.x || o.y >= p.y || o.y + o.fp.h <= top) &&
      top >= mod.y + mod.h && !(out.silk && out.silk.lines.length && out.silk.y + out.silk.lines.length * AB_SILK_LH + 1 > top)
    if (!free) continue
    p.labelYs = p.fp.lines.map((_, i) => bottomY - 3.5 - (n - 1 - i) * AB_LH)
    p.labelTop = top
  }
  // the silk block sits 8 px above what is below it (port labels, buttons), its last line on the 8 px grid too;
  // it only moves where nothing above it is in the way
  if (text && out.silk && out.silk.lines.length) {
    const n = out.silk.lines.length
    const sw = Math.max(...out.silk.lines.map(([s, px]) => abW(s, px, px === 11 ? 1.2 : AB_LS)))
    const sx0 = out.silk.x - sw / 2, sx1 = out.silk.x + sw / 2
    const silkBottom = y0 => y0 + n * AB_SILK_LH + 0.5
    const under = out.parts.filter(p => p.x < sx1 && p.x + p.fp.w > sx0 && p.y >= out.silk.y).map(p => p.labelTop ?? p.y)
    const above = [mod.y + mod.h, ...out.parts.filter(p => p.y < out.silk.y).map(p => p.y + p.fp.h)]
    if (under.length) {
      const target = Math.floor((Math.min(...under) - 8) / 8) * 8
      const ny = target - 0.5 - n * AB_SILK_LH
      if (ny >= Math.max(...above) + 4 && silkBottom(ny) <= Math.min(...under) - 6) out.silk.y = ny
    }
  }
  // text boxes (for the overlap test and the drawing)
  const box = (x, yb, s, px, ls, anchor = 'middle') => {
    const w = abW(s, px, ls)
    const bx = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x
    out.texts.push({ text: s, x0: bx, x1: bx + w, y0: yb - px * 0.95, y1: yb + px * 0.35 }) // the 1.3 em line box the audit measures
  }
  if (text) {
    mod.textY = []
    if (mod.lines.length) {
      const sizes = mod.lines.map((_, i) => (i === 0 ? 13 : 10))
      let ty = mod.can.y + mod.can.h / 2 - (sizes.reduce((a, s) => a + s + 6, -6)) / 2
      mod.lines.forEach((l, i) => { ty += sizes[i]; box(mod.can.x + mod.can.w / 2, ty - 1, l, sizes[i], i === 0 ? 1.4 : 0.6); ty += 6 })
    }
    if (ant && m.antenna === 'pcb') {
      mod.antLines.forEach((l, i, a) => box(mod.x + mw / 2, mod.y + ant - 5 - (a.length - 1 - i) * AB_ANT_LH, l, 10, 0.4))
    }
    if (out.silk) {
      let ty = out.silk.y
      for (const [s, px] of out.silk.lines) { ty += AB_SILK_LH; box(out.silk.x, ty - 3, s, px, px === 11 ? 1.2 : AB_LS) }
    }
    for (const p of out.parts) {
      const { fp } = p
      const bx = p.x + (fp.labelPos === 'right' ? 0 : (fp.w - fp.body.w) / 2)
      if (fp.labelPos === 'above') fp.lines.forEach((l, i) => box(p.x + fp.w / 2, p.labelYs ? p.labelYs[i] : p.y + 10 + i * AB_LH, l, 10, AB_LS))
      else if (fp.labelPos === 'below') fp.lines.forEach(l => box(p.x + fp.w / 2, p.y + fp.body.h + (p.part.kind === 'button' ? 14 : 13), l, 10, AB_LS))
      else {
        const n = fp.lines.length
        fp.lines.forEach((l, i) => box(bx + fp.body.w + 5, p.y + fp.h / 2 + 4 - (n - 1) * AB_LH / 2 + i * AB_LH, l, 10, AB_LS, 'start'))
      }
    }
  }
  return out
}

/** PCB antenna inside the module (art.js artAntenna with the model's note lines). */
function artBoardAntenna(x, y, w, h, lines) {
  return artAntenna(x, y, w, h, { lines, lineH: AB_ANT_LH, inset: 2, fill: 'var(--cb-pcb)', spacing: 0.4 })
}

const abTone = st => `var(--cb-${ART_STATE_TONE[st] || 'fg-dim'})`

/** One part (body + silk labels) at its plan position. */
function artBoardPart(p, prefix, { ledState = {}, live = [] } = {}) {
  const { part, fp } = p
  const bx = p.x + (fp.labelPos === 'right' ? 0 : (fp.w - fp.body.w) / 2)
  const by = fp.labelPos === 'above' ? p.y + fp.h - fp.body.h : fp.labelPos === 'right' ? p.y + (fp.h - fp.body.h) / 2 : p.y
  const shadow = prefix ? `url(#${artId(prefix, 'shadow')})` : undefined
  const silk = (s, x, y, anchor = 'middle') => artEl('text', { x: artNum(x), y: artNum(y), 'text-anchor': anchor, 'font-size': 10, 'letter-spacing': AB_LS, fill: AB_SILK }, artEsc(s))
  let body = ''
  let labels = ''
  if (part.kind === 'usb_port' || part.kind === 'rj45') {
    body = artPort(part.connector, bx, by, { prefix })
    if (live.includes(part.ref)) {
      body += artEl('rect', { class: 'cb-art-live', x: artNum(bx - 3), y: artNum(by - 3), width: fp.body.w + 6, height: fp.body.h + 6, rx: 4, fill: 'none', stroke: 'var(--cb-active)', 'stroke-width': 2 })
    }
    labels = fp.lines.map((l, i) => silk(l, p.x + fp.w / 2, p.labelYs ? p.labelYs[i] : p.y + 10 + i * AB_LH)).join('')
  } else if (part.kind === 'antenna_connector') {
    body = artPort('ipex', bx, by, { prefix })
  } else if (part.kind === 'button') {
    return artEl('g', { class: 'cb-art-part', 'data-cb-part': 'button', 'data-cb-schematic': part.schematic ? 'true' : undefined },
      artButton(bx, by, fp.lines[0] || '', { prefix }))
  } else if (part.kind === 'led') {
    const st = Number.isInteger(part.gpio) ? ledState[part.gpio] : null
    body = artEl('g', { filter: shadow },
      artEl('rect', { x: bx, y: by, width: 14, height: 14, rx: 2, fill: 'var(--cb-metal-hi)', stroke: st ? abTone(st) : 'var(--cb-plastic-edge)', 'stroke-width': 2 }) +
      artEl('circle', { cx: bx + 7, cy: by + 7, r: 4, fill: 'var(--cb-silk)', stroke: 'var(--cb-metal)', 'stroke-width': 1 }))
  } else if (part.kind === 'power_led') {
    body = artEl('rect', { x: bx + 1, y: by, width: 10, height: 7, rx: 1, fill: 'var(--cb-metal-hi)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 1 }) +
      artEl('rect', { x: bx + 4, y: by + 1, width: 4, height: 5, fill: 'var(--cb-silk)', 'fill-opacity': 0.6 })
  } else if (part.kind === 'ldo') {
    // regulator: tab on top, three legs below
    body = artEl('rect', { x: bx + 5, y: by, width: 16, height: 5, fill: 'var(--cb-tin)' }) +
      [0, 1, 2].map(k => artEl('rect', { x: bx + 4 + k * 8, y: by + 20, width: 3, height: 4, fill: 'var(--cb-tin)' })).join('') +
      artEl('rect', { x: bx, y: by + 4, width: 26, height: 16, rx: 2, fill: 'var(--cb-plastic)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2, filter: shadow })
  } else if (part.kind === 'bridge_ic') {
    body = artIc(bx, by + 5, 26, 20, { pins: 4, prefix })
  } else if (part.kind === 'phy_ic') {
    body = artIc(bx, by + 5, 30, 28, { pins: 5, prefix })
  }
  if (fp.labelPos === 'below') labels = fp.lines.map(l => silk(l, p.x + fp.w / 2, p.y + fp.body.h + 13)).join('')
  if (fp.labelPos === 'right') {
    const n = fp.lines.length
    labels = fp.lines.map((l, i) => silk(l, bx + fp.body.w + 5, p.y + fp.h / 2 + 4 - (n - 1) * AB_LH / 2 + i * AB_LH, 'start')).join('')
  }
  return artEl('g', { class: 'cb-art-part', 'data-cb-part': part.kind, 'data-cb-schematic': part.schematic ? 'true' : undefined }, body + labels)
}

/** Pad of a state (art.js artPad); `null` = not checked: tin with a dashed neutral ring (never reads as ok). */
function artBoardPad(x, y, state, square, prefix) {
  if (state) return artPad(x, y, { square, state, prefix })
  const shape = square
    ? artEl('rect', { x: artNum(x - 6.5), y: artNum(y - 6.5), width: 13, height: 13, rx: 1 })
    : artEl('circle', { cx: artNum(x), cy: artNum(y), r: 6.5 })
  return artEl('g', { class: 'cb-art-pad', 'data-cb-state': 'unchecked', fill: prefix ? `url(#${artId(prefix, 'tin')})` : 'var(--cb-tin)',
    stroke: AB_SILK, 'stroke-width': 2, 'stroke-dasharray': '2.5 2' }, shape)
}

/** Header strips, pads, rings and reservation brackets of one side (board coordinates). */
function artBoardSide(model, g, side, prefix, mode) {
  const slots = model.sides?.[side] || []
  const px = boardPadX(g, side)
  const dir = side === 'left' ? 1 : -1
  const top = i => boardSlotTop(g, i)
  let out = ''
  // plastic strips, one per header segment (a separator slot splits them: WT32 PROG / IO)
  let seg = null
  const segs = []
  slots.forEach((s, i) => {
    if (s.sep) { if (seg) segs.push(seg); seg = null; return }
    if (!seg) seg = { a: i, b: i }
    else seg.b = i
  })
  if (seg) segs.push(seg)
  for (const s of segs) {
    const sy = top(s.a) - 3
    const sh = (s.b - s.a + 1) * g.pitch - g.rowGap + 6
    out += artEl('rect', { class: 'cb-art-strip', x: px - g.stripHW, y: sy, width: g.stripHW * 2, height: sh, rx: 2,
      fill: 'color-mix(in oklab, var(--cb-plastic) 88%, var(--cb-metal-hi))', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 2,
      filter: prefix ? `url(#${artId(prefix, 'shadow')})` : undefined }) +
      // moulded top face: a faint highlight along the outer edge of the bar
      artEl('path', { d: `M${artNum(px - g.stripHW + 2)} ${artNum(sy + 2)}V${artNum(sy + sh - 2)}`, stroke: 'var(--cb-metal-hi)', 'stroke-opacity': 0.14, 'stroke-width': 1 })
    for (let i = s.a; i <= s.b; i++) {
      const c = Math.min(16, g.pitch - 2)
      out += artEl('rect', { x: artNum(px - c / 2), y: artNum(boardSlotY(g, i) - c / 2), width: c, height: c, rx: 1, fill: 'var(--cb-plastic)', stroke: 'var(--cb-plastic-edge)', 'stroke-width': 1 })
    }
  }
  // brackets: on the strip (dashed frame + hatch for blocked), a bracket line and the vertical label in the lane
  for (const br of model.brackets?.[side] || []) {
    const y0 = top(br.from) - 2
    const y1 = top(br.to) + g.rowH + 2
    const tone = br.tone === 'bad' ? 'var(--cb-bad)' : 'var(--cb-warn)'
    const lx = px + dir * (g.stripHW + 2)
    const span = y1 - y0
    const label = abW(br.label, 10, 1) > span + 2 * g.pitch ? String(br.label).split(' ').pop() : br.label
    out += artEl('g', { class: 'cb-art-bracket', 'data-cb-tone': br.tone },
      artEl('rect', { x: px - g.stripHW - 2, y: y0, width: g.stripHW * 2 + 4, height: span, rx: 3, fill: br.tone === 'bad' && prefix ? `url(#${artId(prefix, 'hatch')})` : 'none',
        'fill-opacity': 0.3, stroke: tone, 'stroke-width': 1.5, 'stroke-dasharray': '3 2' }) +
      artEl('path', { d: `M${artNum(lx)} ${artNum(y0)}h${dir * 3}V${artNum(y1)}h${-dir * 3}`, fill: 'none', stroke: tone, 'stroke-width': 1.5 }) +
      (mode === 'compact' ? '' : artEl('text', { x: 0, y: 0, transform: `translate(${artNum(side === 'left' ? px + AB_BR_TEXT : px - AB_BR_TEXT)} ${artNum((y0 + y1) / 2)}) rotate(-90)`,
        'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': 10, 'letter-spacing': 1, fill: AB_SILK }, artEsc(label))))
  }
  // pads (pin 1 and supply/ground pads square), selection pulse ring, suggestion ring, pin-1 marker
  slots.forEach((s, i) => {
    if (!s.pin) return
    const y = boardSlotY(g, i)
    const p = s.pin
    out += artBoardPad(px, y, p.state, Boolean(p.square), prefix)
    // drilled hole with the pin: the pad reads as a through-hole pad
    out += artEl('circle', { class: 'cb-art-drill', cx: px, cy: artNum(y), r: 2.4, fill: 'var(--cb-cavity)', stroke: 'var(--cb-metal-hi)', 'stroke-opacity': 0.5, 'stroke-width': 0.75 })
    if (p.n === 1 && mode !== 'compact') {
      out += artEl('rect', { class: 'cb-art-pin1', x: artNum(side === 'left' ? px - g.stripHW - 5 : px + g.stripHW + 2), y: artNum(y - g.rowH / 2 + 1), width: 3, height: artNum(g.rowH - 2), rx: 1, fill: AB_SILK })
    }
    if (p.suggested) out += artEl('circle', { cx: px, cy: artNum(y), r: 10, fill: 'none', stroke: 'var(--cb-ok)', 'stroke-width': 1.5, 'stroke-dasharray': '3 2' })
    if (p.selected) {
      out += artEl('circle', { class: 'cb-bsel', cx: px, cy: artNum(y), r: 10.5, fill: 'none', stroke: p.state === 'blocked' || p.state === 'assigned_blocked' ? 'var(--cb-bad)' : 'var(--cb-active)', 'stroke-width': 2 })
    }
  })
  return out
}

/**
 * The model as one SVG string (aria-hidden; the DOM carries the meaning). g = boardGeom(…); model as in
 * artBoardPlan plus sides {left, right: [{sep} | {pin: {n, state, square, selected, suggested}}]}, brackets
 * {left, right}, ledState {gpio: state}, live [port refs], schematic (no drawing: generic placement).
 * opts { prefix (instance id prefix, required for several models on one page), mode 'full' | 'compact' }.
 */
export function artBoard(model, g, { prefix = 'board', mode = 'full' } = {}) {
  const plan = artBoardPlan(model, g, { mode })
  const compact = mode === 'compact'
  const W = compact ? g.bodyW : g.width
  const H = g.height
  const ox = compact ? 0 : g.gutterL
  const bw = g.bodyW
  const pb = g.pcbBottom
  const dots = artEl('pattern', { id: artId(prefix, 'dots'), width: 12, height: 12, patternUnits: 'userSpaceOnUse' },
    artEl('circle', { cx: 6, cy: 6, r: 0.8, fill: 'var(--cb-pcb-edge)' }))
  const defs = artDefs(prefix).replace('</defs>', `${dots}</defs>`)
  const m = plan.module
  const mod = model.module || {}
  let modArt = artEl('rect', { x: m.x, y: m.y, width: m.w, height: m.h, rx: 3, fill: 'color-mix(in oklab, var(--cb-pcb) 82%, var(--cb-cavity))',
    stroke: 'var(--cb-pcb-edge)', 'stroke-width': 1.5, filter: `url(#${artId(prefix, 'shadow')})` })
  if (mod.antenna === 'pcb') {
    modArt += artBoardAntenna(m.x, m.y, m.w, m.antH, compact ? [] : m.antLines || [])
    // feed: the meander's start runs into the module under the can
    modArt += artEl('path', { d: `M${artNum(m.x + 9)} ${artNum(m.y + Math.max(14, m.antH - ((m.antLines || []).length ? m.antLines.length * AB_ANT_LH + 2 : 0) - 6))}V${artNum(m.can.y + 6)}`, stroke: 'var(--cb-copper)', 'stroke-width': 3, fill: 'none' })
  }
  else if (mod.antenna === 'external') {
    modArt += artPort('ipex', m.x + m.w / 2 - 9, m.y + 5, { prefix })
    if (!compact) modArt += artEl('text', { x: artNum(m.x + m.w / 2 + 14), y: artNum(m.y + 18), 'font-size': 10, 'letter-spacing': AB_LS, fill: AB_SILK }, 'ANT')
  }
  modArt += artCan(m.can.x, m.can.y, m.can.w, m.can.h, compact ? [] : m.lines, { prefix })
  const silk = plan.silk && !compact
    ? plan.silk.lines.map(([s, px], i) => artEl('text', { x: artNum(plan.silk.x), y: artNum(plan.silk.y + AB_SILK_LH * (i + 1) - 3), 'text-anchor': 'middle',
      'font-size': px, 'font-weight': px === 11 ? 700 : 400, 'letter-spacing': px === 11 ? 1.2 : AB_LS, fill: AB_SILK }, artEsc(s))).join('')
    : ''
  const body = artEl('g', { transform: `translate(${artNum(ox)} 0)` },
    // thickness (edge below), face with gradient and dot texture, a faint top highlight
    artEl('rect', { x: 0, y: 5, width: bw, height: pb, rx: 10, fill: 'color-mix(in oklab, var(--cb-pcb-edge) 70%, var(--cb-cavity))', filter: `url(#${artId(prefix, 'shadow')})` }) +
    artEl('rect', { x: 0.5, y: 3, width: bw - 1, height: pb, rx: 10, fill: 'var(--cb-pcb-edge)' }) +
    artEl('rect', { class: 'cb-art-pcb', x: 0, y: 0, width: bw, height: pb, rx: 10, fill: `url(#${artId(prefix, 'pcb')})`, stroke: 'var(--cb-pcb-edge)', 'stroke-width': 1.5 }) +
    artEl('rect', { x: 0, y: 0, width: bw, height: pb, rx: 10, fill: `url(#${artId(prefix, 'dots')})`, 'fill-opacity': 0.45 }) +
    artEl('path', { d: `M10 1.2H${artNum(bw - 10)}`, stroke: 'var(--cb-metal-hi)', 'stroke-opacity': 0.18, 'stroke-width': 1 }) +
    artEl('g', { class: 'cb-art-module', 'data-cb-schematic': m.schematic ? 'true' : undefined }, modArt) +
    silk +
    plan.parts.map(p => artBoardPart(p, prefix, { ledState: model.ledState || {}, live: model.live || [] })).join(''))
  const sides = compact
    ? artEl('g', { transform: `translate(${artNum(-g.gutterL)} 0)` }, artBoardSide(model, g, 'left', prefix, mode) + artBoardSide(model, g, 'right', prefix, mode))
    : artBoardSide(model, g, 'left', prefix, mode) + artBoardSide(model, g, 'right', prefix, mode)
  const size = compact ? {} : { width: W, height: H }
  // the art primitives tag their state as data-cb-state; on the board that name belongs to the DOM pin rows (the E2E
  // counts [data-cb-state=nc] etc.), so the drawing carries it as data-cb-art-state
  return artEl('svg', { xmlns: 'http://www.w3.org/2000/svg', class: 'cb-board-svg', viewBox: `0 0 ${artNum(W)} ${artNum(H)}`, ...size,
    'aria-hidden': 'true', focusable: 'false', 'data-cb-mode': compact ? 'compact' : 'full', 'data-cb-schematic': model.schematic ? 'true' : undefined },
  (defs + body + sides).replace(/ data-cb-state="/g, ' data-cb-art-state="'))
}

// ─── Twin: the compact model in the chat card and as a live twin in 05 FLASH / 06 DEBUG ─────────────────────────
// The twin draws only what the store reports: the port of the selected serial port (its kind maps to exactly one
// drawn usb port), a pulse along the trace port → module while a flash job runs, the result after it, a panic, serial
// activity from arriving lines. Nothing is simulated, nothing is estimated.

/** usb ref of the drawn port a serial port arrives on: GET /ports `kind` → usb[] kind through `kindMap` (the bundle
 *  passes lib/flash.js FLASH_PORT_USB), exactly one drawn usb_port of that kind. Simulated / unknown → null. */
export function twinPortRef(port, model, kindMap) {
  if (!port || port.simulated || !kindMap) return null
  const want = Object.hasOwn(kindMap, String(port.kind)) ? kindMap[port.kind] : null
  if (!want) return null
  const hits = (model?.parts || []).filter(p => p && p.kind === 'usb_port' && p.usbKind === want && p.ref)
  return hits.length === 1 ? String(hits[0].ref) : null
}

/** Flash state of the twin from the store's flash job (jobProgress shape): running | done | failed | null. */
export function twinFlashState(progress) {
  if (!progress) return null
  return progress.running ? 'running' : progress.failed ? 'failed' : progress.done ? 'done' : null
}

export const TWIN_RX_WINDOW_MS = 1500

/** Serial activity from the line buffer (lib/serial.js: lastSeq, epoch): a line counts as arriving when the sequence
 *  grows (or a new epoch brings lines) after the first look; what was already in the buffer never lights. Pure:
 *  prev = previous state or null, → { seq, epoch, at, active, until }. */
export function twinSerialTrack(prev, buf, now, windowMs = TWIN_RX_WINDOW_MS) {
  const seq = Number.isInteger(buf?.lastSeq) ? buf.lastSeq : 0
  const epoch = buf?.epoch ?? null
  let at = prev?.at || 0
  if (prev && (seq > prev.seq || (epoch !== prev.epoch && seq > 0))) at = now
  const until = at ? at + windowMs : 0
  return { seq, epoch, at, active: Boolean(at) && now < until, until }
}

/** Points of the trace from the top of the port body to the bottom of the module (board coordinates, compact plan). */
function twinTrace(plan, ref) {
  const p = plan.parts.find(it => it.part.kind === 'usb_port' && it.part.ref === ref)
  if (!p) return null
  const bx = p.x + (p.fp.w - p.fp.body.w) / 2
  const by = p.y + p.fp.h - p.fp.body.h
  const m = plan.module
  const x0 = bx + p.fp.body.w / 2
  const x1 = m.x + m.w / 2
  const yTop = m.y + m.h
  const yMid = Math.round((by + yTop) / 2)
  return [[x0, by], [x0, yMid], [x1, yMid], [x1, yTop]]
}

/** Point at fraction f of a polyline. */
function twinAlong(pts, f) {
  const seg = pts.slice(1).map((q, i) => Math.hypot(q[0] - pts[i][0], q[1] - pts[i][1]))
  let d = seg.reduce((a, b) => a + b, 0) * f
  for (let i = 0; i < seg.length; i++) {
    if (d <= seg[i] || i === seg.length - 1) {
      const t = seg[i] ? Math.min(1, d / seg[i]) : 0
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t]
    }
    d -= seg[i]
  }
  return pts[pts.length - 1]
}

const TWIN_DOTS = [0.12, 0.37, 0.62, 0.87]

/**
 * The compact model as one SVG string, optionally turned 90° clockwise (`turn`: antenna right, J1 on top, ports on the
 * left), with the twin layer: trace + pulse dots while `flash` = 'running', the trace solid after 'done'. `port` is the
 * usb ref that lights (model.live gets it). → { svg, view: [w, h], module: {x, y} (centre, % of the view), port }
 */
/** Pad centre of `gpio` in a compact twin, view percent {x, y} or null; turned like artBoardTwin. */
export function artBoardTwinPad(model, g, gpio, turn = true) {
  for (const side of ['left', 'right']) {
    const v = (model?.views?.[side] || []).find(e => e.hp && e.hp.gpio === gpio)
    if (!v) continue
    const x = boardPadX(g, side) - g.gutterL
    const y = boardSlotY(g, v.slot)
    const [vx, vy] = turn ? [g.height - y, x] : [x, y]
    const [vw, vh] = turn ? [g.height, g.bodyW] : [g.bodyW, g.height]
    return { x: Math.round((vx / vw) * 1000) / 10, y: Math.round((vy / vh) * 1000) / 10 }
  }
  return null
}

export function artBoardTwin(model, g, { prefix = 'twin', turn = true, port = null, flash = null } = {}) {
  const live = port ? [port] : []
  const m2 = { ...model, live }
  const inner = artBoard(m2, g, { prefix, mode: 'compact' })
  const plan = artBoardPlan(m2, g, { mode: 'compact' })
  const W = g.bodyW
  const H = g.height
  const pts = port && (flash === 'running' || flash === 'done') ? twinTrace(plan, port) : null
  let layer = ''
  if (pts) {
    const d = pts.map((q, i) => `${i ? 'L' : 'M'}${artNum(q[0])} ${artNum(q[1])}`).join('')
    layer += artEl('path', { class: 'cb-twin-trace', d, fill: 'none', stroke: flash === 'done' ? 'var(--cb-ok)' : 'var(--cb-active)', 'stroke-width': 3,
      'stroke-linejoin': 'round', 'stroke-opacity': flash === 'done' ? 0.8 : 0.45 })
    if (flash === 'running') {
      layer += TWIN_DOTS.map((f, i) => {
        const [x, y] = twinAlong(pts, f)
        return artEl('circle', { class: `cb-twin-dot cb-twin-dot--${i}`, cx: artNum(x), cy: artNum(y), r: 5, fill: 'var(--cb-active)' })
      }).join('')
    }
  }
  const body = inner.replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '') + (layer ? artEl('g', { class: 'cb-twin-layer', 'data-cb-twin-flash': flash }, layer) : '')
  const vw = turn ? H : W
  const vh = turn ? W : H
  const content = turn ? artEl('g', { transform: `translate(${artNum(H)} 0) rotate(90)` }, body) : body
  const svg = artEl('svg', { xmlns: 'http://www.w3.org/2000/svg', class: 'cb-board-svg cb-twin-svg', viewBox: `0 0 ${artNum(vw)} ${artNum(vh)}`, 'aria-hidden': 'true',
    focusable: 'false', 'data-cb-mode': 'compact', 'data-cb-turn': turn ? 'true' : undefined, 'data-cb-schematic': model.schematic ? 'true' : undefined }, content)
  // module centre in view percent (DOM stamps sit there; turned: (x, y) → (H − y, x))
  const mc = [plan.module.can.x + plan.module.can.w / 2, plan.module.can.y + plan.module.can.h / 2]
  const at = turn ? [H - mc[1], mc[0]] : mc
  const pct = v => Math.round(v * 1000) / 10
  return { svg, view: [vw, vh], module: { x: pct(at[0] / vw), y: pct(at[1] / vh) }, port: pts ? port : live.length && plan.parts.some(p => p.part.ref === port) ? port : null }
}
