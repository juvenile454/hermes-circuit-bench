// GENERATED from desktop-src/ by scripts/build-desktop.mjs — do not edit

// --- 00-head.js
// Circuit Bench — desktop half. Plain ESM, loaded uncompiled by Hermes Desktop.
// Only @hermes/plugin-sdk, react and react/jsx-runtime are importable. Optional SDK parts: `sdk.X` + typeof check.
import * as sdk from '@hermes/plugin-sdk'
import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const PLUGIN_ID = 'circuit-bench'

// --- fixtures (product build: none)
const CB_FIXTURES = null

// --- lib/api.js
// REST helpers for the bench API: result envelopes, error mapping, query strings. Pure.

function isEnvelope(x) {
  return Boolean(x) && typeof x === 'object' && typeof x.ok === 'boolean' && 'error' in x && 'result' in x
}

/** Client-side error envelope. Codes outside contracts.ERROR_CODES are UI-only: backend_unavailable, network_error, unauthorized,
 *  backend_error, bad_response, fixture_missing. */
function errorEnvelope(action, code, message, hint = null, http = null) {
  return {
    ok: false, action: action || 'request', summary: message, result: null, checks: [], warnings: [], assumptions: [],
    sources: [], simulated: false, error: { code, message, hint }, http
  }
}

/** ctx.rest throws `Error("<status>: <body>")` (+ `statusCode`) for HTTP >= 400; anything else is transport. */
function parseRestError(err, action) {
  const msg = String(err?.message ?? err ?? '')
  // Electron IPC wraps the message on newer hosts: "Error invoking remote method 'hermes:api': Error: 503: {…}"
  const m = /^(\d{3}):\s?([\s\S]*)$/.exec(msg) || /\bError:\s(\d{3}):\s?([\s\S]*)$/.exec(msg)
  const status = Number.isInteger(err?.statusCode) ? err.statusCode : m ? Number(m[1]) : null
  const body = m ? m[2] : ''
  if (status) {
    let parsed = null
    const at = body.indexOf('{')
    if (at >= 0) {
      try { parsed = JSON.parse(body.slice(at)) } catch { parsed = null }
    }
    if (isEnvelope(parsed)) return { ...parsed, http: status }
    if (status === 404) {
      return errorEnvelope(action, 'backend_unavailable', 'The Circuit Bench backend did not answer this route (404).',
        'Enable the Circuit Bench agent plugin (Capabilities → Plugins) and restart the backend.', 404)
    }
    if (status === 401 || status === 403) {
      return errorEnvelope(action, 'unauthorized', `The backend refused the request (${status}).`, 'Reconnect to Hermes and try again.', status)
    }
    const detail = parsed && typeof parsed.detail === 'string' ? parsed.detail : body.slice(0, 160)
    return errorEnvelope(action, 'backend_error', `Backend error ${status}${detail ? `: ${detail}` : ''}`, 'Try again; see the backend log.', status)
  }
  if (/bridge unavailable/i.test(msg)) {
    return errorEnvelope(action, 'network_error', 'Hermes Desktop bridge unavailable.', 'Restart Hermes Desktop.', null)
  }
  return errorEnvelope(action, 'network_error', `Cannot reach the Hermes backend${msg ? ` (${msg.slice(0, 120)})` : ''}.`,
    'Check that the backend is running, then retry.', null)
}

/** A 2xx body that is not an envelope (should not happen with the bench routes). */
function asEnvelope(body, action) {
  if (isEnvelope(body)) return body
  return errorEnvelope(action, 'bad_response', 'The backend answered with an unexpected shape.', null, 200)
}

/** {a: 1, b: null, c: "x y"} → "?a=1&c=x%20y" (null/undefined skipped, booleans as true/false). */
function query(params) {
  const parts = []
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

/** True when an error means "the backend is not there" (empty state instead of a red error). */
function isOffline(env) {
  return Boolean(env && !env.ok && ['backend_unavailable', 'network_error'].includes(env.error?.code))
}

// --- lib/art-board.js
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
function artBoardPlan(model, g, { mode = 'full' } = {}) {
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
function artBoard(model, g, { prefix = 'board', mode = 'full' } = {}) {
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
function twinPortRef(port, model, kindMap) {
  if (!port || port.simulated || !kindMap) return null
  const want = Object.hasOwn(kindMap, String(port.kind)) ? kindMap[port.kind] : null
  if (!want) return null
  const hits = (model?.parts || []).filter(p => p && p.kind === 'usb_port' && p.usbKind === want && p.ref)
  return hits.length === 1 ? String(hits[0].ref) : null
}

/** Flash state of the twin from the store's flash job (jobProgress shape): running | done | failed | null. */
function twinFlashState(progress) {
  if (!progress) return null
  return progress.running ? 'running' : progress.failed ? 'failed' : progress.done ? 'done' : null
}

const TWIN_RX_WINDOW_MS = 1500

/** Serial activity from the line buffer (lib/serial.js: lastSeq, epoch): a line counts as arriving when the sequence
 *  grows (or a new epoch brings lines) after the first look; what was already in the buffer never lights. Pure:
 *  prev = previous state or null, → { seq, epoch, at, active, until }. */
function twinSerialTrack(prev, buf, now, windowMs = TWIN_RX_WINDOW_MS) {
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
function artBoardTwinPad(model, g, gpio, turn = true) {
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

function artBoardTwin(model, g, { prefix = 'twin', turn = true, port = null, flash = null } = {}) {
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

// --- lib/art-calc.js
// Mini schematics of the six calculators of station 02 CALC. Pure functions,
// no SDK, no DOM: calcArt(type, env, opts) returns an SVG string with the circuit the calculator sizes and the values
// of the answer. The desktop computes nothing: every value is the `display` text of the backend answer (or a plain
// string such as the part name). A missing field drops its label; the drawing stays (the topology is the calculator's,
// not data). Self-contained (lib files import nothing): own escape and number helpers with the calcArt prefix.
// Strokes: wires 1.5 px, part bodies 2 px; colours only as var(--cb-…) tokens; no <style>, href,
// <image>, foreignObject or on* attributes (the sanitizeSvg list). Fixed size (never scaled), so 10/11 px text stays
// 10/11 px on screen.

const CALC_ART_W = 288
const CALC_ART_TYPES = ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo']

/** `display` of a quantity of the answer, else null (never a number we format ourselves). */
function calcArtDisp(q) {
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
function calcArt(type, env, { tone = 'fg' } = {}) {
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

// --- lib/art-parts.js
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
const SOLDER_ART_KINDS = ['wire_jumper', 'resistor', 'diode', 'led', 'transistor', 'electrolytic', 'ceramic', 'film',
  'capacitor', 'switch', 'header', 'connector', 'terminal', 'ic', 'module']

/** height_class of every kind in data/solder/rules.json (0 flat … 3 tall, 4 unknown). A copy for drawing only; the
 *  order itself comes from the backend. tests-js/test_vsolder_art.mjs keeps it equal to rules.json. */
const SOLDER_ART_HEIGHT = {
  wire_jumper: 0, resistor: 1, diode: 1, ceramic: 2, inductor: 2, test_point: 2, crystal: 2, transistor: 2, ic: 2, led: 2,
  film: 3, fuse: 3, potentiometer: 3, buzzer: 3, relay: 3, capacitor: 3, electrolytic: 3, unknown: 4, header: 1, switch: 1,
  connector: 2, terminal: 2, module: 3, battery: 4
}

/** Words of the height classes (rules.json order.height_classes). */
const SOLDER_ART_HEIGHT_WORDS = { 0: 'flat', 1: 'low', 2: 'medium', 3: 'tall', 4: 'unknown height' }

// top edge (y) of the generic body per height class; the drawn kinds stay inside the band of their class
const SOLDER_ART_GENERIC_TOP = { 0: 44, 1: 34, 2: 24, 3: 10, 4: 24 }

/** Viewbox of every pictogram (the board surface is at y = 50). */
const SOLDER_ART_VIEW = [96, 64]
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
function solderArtPackage(step, parts) {
  const refs = new Set(step?.refs || [])
  const pk = (parts || []).filter(p => p && refs.has(p.ref)).map(p => String(p.package || '').toUpperCase().replace(/\s+/g, ''))
  if (!pk.length || pk.some(p => !p)) return null
  if (pk.every(p => /^TO-?(18|5|39|46|72)\b/.test(p))) return 'can'
  if (pk.every(p => /^TO-?92\b/.test(p))) return 'to92'
  return null
}

/** Does a hint carry a source other than the rule of thumb? */
function solderArtSourced(hint) {
  return (hint?.source_ids || []).some(id => id && id !== 'rule-of-thumb')
}

/**
 * Polarity mark of a step → {mark, label, code, source_ids} | null. Only from a hint the step carries (code
 * polarity, or pinout for a transistor) with a source beyond the rule of thumb:
 *   electrolytic → 'minus-stripe' · diode → 'cathode-band' · led → 'cathode' · transistor → 'pinout-datasheet'
 * Every other kind (and every unsourced hint) → null: nothing is drawn.
 */
function solderArtPolarity(step) {
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
function solderArtHintKind(hint) {
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
function solderArtTop(kind, pkg = null) {
  return solderArtBody(kind, null, pkg).top
}

/**
 * Pictogram of a part kind as an SVG string.
 * opts: { polarity: solderArtPolarity(step) | null, pkg: solderArtPackage(…), w, h (px), label (aria-label) }
 * Decorative when label is empty (aria-hidden). data-cb-art = the drawn kind or 'generic'.
 */
function solderArtPart(kind, { polarity = null, pkg = null, w = 96, h = 64, label = '' } = {}) {
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

// --- lib/art-shell.js
// Frame of the Bench: station symbols of the rail, the rail's state words and the HUD key figures as
// words. Pure functions, no SDK, no DOM; every name carries the prefix `shell` (one shared bundle scope). Shapes are
// [[tag, attrs], …] like artGlyphShapes (lib/art.js), drawn by the kit as inline SVG with currentColor.

/** Station symbols in a 16×16 box, 1.5 px strokes, drawn with `ink`. Unknown id → []. */
function shellStationShapes(id, ink = 'currentColor') {
  const line = { fill: 'none', stroke: ink, 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }
  switch (id) {
    // 01 PLAN: a chip with pins on both sides
    case 'plan': return [['rect', { x: 4.5, y: 3, width: 7, height: 10, rx: 1, ...line }],
      ['path', { d: 'M2 5.5H4.5M2 8H4.5M2 10.5H4.5M11.5 5.5H14M11.5 8H14M11.5 10.5H14', ...line }]]
    // 02 CALC: a resistor (zigzag) between two leads
    case 'calc': return [['path', { d: 'M1.5 8H3.5L5 5L7 11L9 5L11 11L12.5 8H14.5', ...line }]]
    // 03 WIRE: two nodes, one orthogonal net between them
    case 'wire': return [['path', { d: 'M4 4H8V12H12', ...line }], ['circle', { cx: 3, cy: 4, r: 1.6, fill: ink }], ['circle', { cx: 13, cy: 12, r: 1.6, fill: ink }]]
    // 04 SOLDER: an iron (handle + tip) and a joint
    case 'solder': return [['path', { d: 'M14 2L9 7', ...line, 'stroke-width': 3 }], ['path', { d: 'M9 7L4.5 11.5', ...line }],
      ['circle', { cx: 3.5, cy: 12.5, r: 1.8, fill: ink }]]
    // 05 FLASH: a lightning bolt
    case 'flash': return [['path', { d: 'M9 1.5L3.5 9H7.5L6.5 14.5L12.5 6.5H8.5Z', ...line }]]
    // 06 DEBUG: a trace with a spike (the serial monitor)
    case 'debug': return [['path', { d: 'M1.5 9H4.5L6 3.5L8.5 13L10 9H14.5', ...line }]]
    default: return []
  }
}

/** Rail grammar: stageStatus text → { glyph, num, code, pct }; num + code (hidden) = the original text. */
function shellRailMark(text) {
  const t = String(text ?? '')
  let m
  if (t === '[✓]') return { glyph: 'done', num: '', code: t, pct: null }
  if (t === '[ ]' || t === '') return { glyph: t ? 'todo' : '', num: '', code: t, pct: null }
  if ((m = /^(\d+)✕$/.exec(t))) return { glyph: 'blocked', num: m[1], code: '✕', pct: null }
  if ((m = /^(\d*)!$/.exec(t))) return { glyph: 'caution', num: m[1], code: '!', pct: null }
  if ((m = /^(\d+)%$/.exec(t))) return { glyph: 'progress', num: t, code: '', pct: Math.max(0, Math.min(100, Number(m[1]))) }
  if (t === 'PANIC') return { glyph: 'panic', num: t, code: '', pct: null }
  if (t === 'FAIL') return { glyph: 'blocked', num: '', code: t, pct: null }
  if (t === 'BUILT') return { glyph: 'built', num: '', code: t, pct: null }
  return { glyph: '', num: t, code: '', pct: null }
}

/** Rail mark shapes (12×12): done, todo, built, progress (arc by pct); none for panic. */
function shellMarkShapes(glyph, pct = 0, ink = 'currentColor') {
  const ring = { fill: 'none', stroke: ink, 'stroke-width': 2 }
  switch (glyph) {
    case 'done': return [['circle', { cx: 6, cy: 6, r: 5, ...ring }], ['path', { d: 'M3.5 6.2L5.3 8L8.6 4.4', fill: 'none', stroke: ink, 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }]]
    case 'todo': return [['circle', { cx: 6, cy: 6, r: 5, fill: 'none', stroke: ink, 'stroke-width': 1.2, opacity: 0.7 }]]
    case 'built': return [['circle', { cx: 6, cy: 6, r: 5, ...ring }], ['circle', { cx: 6, cy: 6, r: 2, fill: ink }]]
    case 'progress': {
      const p = Math.max(0, Math.min(100, Number(pct) || 0))
      const out = [['circle', { cx: 6, cy: 6, r: 5, ...ring, opacity: 0.35 }]]
      if (p >= 100) out.push(['circle', { cx: 6, cy: 6, r: 5, ...ring }])
      else if (p > 0) {
        const a = (p / 100) * 2 * Math.PI
        const x = Math.round((6 + 5 * Math.sin(a)) * 100) / 100
        const y = Math.round((6 - 5 * Math.cos(a)) * 100) / 100
        out.push(['path', { d: `M6 1A5 5 0 ${p > 50 ? 1 : 0} 1 ${x} ${y}`, ...ring, 'stroke-linecap': 'round' }])
      }
      return out
    }
    default: return []
  }
}

/** The rail's state word under the station name (short: ≤ 10 characters). `status` is stageStatus()[id]
 *  (lib/stages.js), `counts` countVerdicts(), `solder` solderProgress(). The PANIC badge stays the only panic hint
 *  of the navigation, so the debug word never says "panic". */
function shellRailWord(id, status, { project = null, counts = null, solder = null } = {}) {
  if (!project || !status) return ''
  const t = status.text || ''
  const done = t === '[✓]'
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`
  switch (id) {
    // the right column (stageStatus text) already carries the state mark (1✕, 3!, [✓], 40%); the word adds what
    // the mark does not say: how many pins, what is left, what happened
    case 'plan': {
      const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
      const total = c.ok + c.caution + c.blocked + c.unchecked
      return total ? n(total, 'pin', 'pins') : 'no pins'
    }
    case 'calc': return done ? `${(project.calcs || []).length} saved` : 'none yet'
    case 'wire': return done ? n((project.circuits || []).length, 'circuit', 'circuits') : 'none yet'
    case 'solder': {
      if (status.tone === 'warn') return 'outdated'
      if (!solder?.total) return 'no plan'
      return done ? 'all done' : `${solder.total - solder.done} to go`
    }
    case 'flash': return t === 'FAIL' ? 'failed' : done ? 'flashed' : t === 'BUILT' ? 'built' : 'not built'
    case 'debug': return t === 'PANIC' ? 'to fix' : done ? 'fixed' : 'no crash'
    default: return ''
  }
}

/** HUD figures as words: PINS ✓ 4 ok ! 0 ✕ 1 blocked (+ ⊗/◇ module danger/caution when > 0;
 *  with > 2 counts the ok count hides, only the worst keeps its word),
 *  SOLDER 3/6, BUILD word → {pins: {items, label}, solder: {text, label}, build: {word, tone, label}}; label = full
 *  sentence for aria-label/title (the narrow HUD shows symbol + number). */
function shellKpis(counts, solder, build, mods = null) {
  const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
  const items = [
    { key: 'ok', symbol: '✓', n: c.ok, word: 'ok', tone: 'ok' },
    { key: 'caution', symbol: '!', n: c.caution, word: 'caution', tone: c.caution ? 'warn' : 'dim' },
    { key: 'blocked', symbol: '✕', n: c.blocked, word: 'blocked', tone: c.blocked ? 'bad' : 'dim' }
  ]
  if (c.unchecked) items.push({ key: 'unchecked', symbol: '?', n: c.unchecked, word: 'unchecked', tone: 'dim' })
  if (mods?.danger) items.push({ key: 'mod-danger', symbol: '⊗', n: mods.danger, word: mods.dangerWord || 'module danger', tone: 'bad' })
  if (mods?.caution) items.push({ key: 'mod-caution', symbol: '◇', n: mods.caution, word: mods.cautionWord || 'module caution', tone: 'warn' })
  // a zero count stays as symbol + number (quiet); only counts that matter spend the room for their word
  for (const it of items) it.quiet = it.n === 0
  const pinsLabel = `Pins: ${items.map(i => `${i.n} ${i.word}`).join(', ')}`
  // HUD room with module findings and > 2 counts: ok count hidden, only the worst keeps its word (label keeps all)
  const loud = items.filter(i => !i.quiet)
  const worst = loud.find(i => i.tone === 'bad') || loud.find(i => i.tone === 'warn')
  if ((mods?.danger || mods?.caution) && loud.length > 2) {
    for (const it of loud) if (it !== worst) { it.word = ''; it.quiet ||= it.key === 'ok' }
    if (worst?.key === 'mod-danger') worst.word = 'module danger'
    else if (worst?.key === 'mod-caution') worst.word = 'module caution'
  }
  const s = solder || { done: 0, total: 0 }
  const solderText = s.total ? `${s.done}/${s.total}` : '—'
  const solderLabel = s.total ? `Solder: ${s.done} of ${s.total} steps done` : 'Solder: no plan yet'
  const b = build || { tone: 'faint', text: '—' }
  const word = b.text === 'OK' ? 'built' : b.text === 'FAIL' ? 'failed' : 'not built'
  const tone = b.text === 'OK' ? 'ok' : b.text === 'FAIL' ? 'bad' : 'dim'
  const ram = typeof b.ram === 'number' && Number.isFinite(b.ram) ? b.ram : null
  const buildLabel = `Build: ${word}${ram !== null ? `, RAM ${Math.round(ram * 10) / 10} %` : ''}`
  return { pins: { items, label: pinsLabel }, solder: { text: solderText, label: solderLabel }, build: { word, tone, ram, label: buildLabel } }
}

// --- lib/art.js
// Graphic primitives of the model language. Pure functions, no SDK, no DOM:
// each returns an SVG fragment as a string. Deterministic (same input → same string). Every value from data runs
// through artEsc; every coordinate through artNum (a finite number or 0). Colours only as var(--cb-…) tokens
// (presentation attributes with var() and color-mix() resolve in Chromium/Electron: probe 07.11.2026, Chromium 151).
// No <style>, no href/xlink, no <image>, no foreignObject, no on* attributes (the sanitizeSvg list, lib/wire.js).
// Names carry the prefix `art` because every desktop-src file shares one scope (glyph, pad, port, can … are locals
// elsewhere). The board model and stations draw with these; new primitives go to lib/art-<area>.js.

/** Escape text and attribute values (& < > " '). */
function artEsc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/** A coordinate: finite number rounded to 2 decimals, anything else 0 (data never reaches an attribute raw). */
function artNum(v) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0
}

/** Estimated width of monospace text: 0.6 em per character (code points). */
function artTextWidth(str, px = 10) {
  return artNum([...String(str ?? '')].length * 0.6 * artNum(px))
}

/** Pin/pad states of the model → the word for aria-label and the tone token. */
const ART_STATE_WORDS = {
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
const ART_STATES = Object.keys(ART_STATE_WORDS)
const ART_STATE_TONE = {
  free: 'ok', assigned: 'active', caution: 'warn', blocked: 'bad', assigned_blocked: 'bad',
  power: 'power', ground: 'fg-dim', nc: 'fg-faint', signal: 'fg-dim'
}
/** Port kinds artPort draws. Anything else draws nothing (nothing is invented). */
const ART_PORT_KINDS = ['micro_usb', 'usb_c', 'generic_usb', 'rj45', 'ipex']
/** Schematic outer size [w, h] of each port (for layout; not a physical dimension). */
const ART_PORT_SIZE = { micro_usb: [44, 30], usb_c: [44, 26], generic_usb: [44, 30], rj45: [64, 60], ipex: [18, 18] }

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
function artId(prefix, name) {
  return `cb-${artPrefix(prefix)}-${name}`
}

/** fill reference to a def when a prefix is given, else the flat token (the drawing works without defs). */
function artPaint(prefix, name, token) {
  return prefix ? `url(#${artId(prefix, name)})` : `var(--cb-${token})`
}

/** <defs> for one model instance: gradients pcb/metal/tin, hatch (blocked), shadow, glow. Ids cb-<prefix>-…. */
function artDefs(prefix) {
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
function artGlyphShapes(state, x = 6, y = 6, ink = 'currentColor', knock = 'var(--cb-ink)') {
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
function artGlyph(state, x, y, { surface = 'bench' } = {}) {
  const shapes = artGlyphShapes(state, x, y, artTone(state, surface))
  if (!shapes.length) return ''
  return artEl('g', { class: 'cb-art-glyph', 'data-cb-state': state }, shapes.map(([t, a]) => artEl(t, a)).join(''))
}

/** Pad on the board: tin with a state ring (2 px); assigned glows, blocked is hatched. square = pin 1 / power. */
function artPad(x, y, { square = false, state = 'free', prefix = '' } = {}) {
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
function artPill(text, state, x, y, side = 'r', { surface = 'bench' } = {}) {
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
function artPort(kind, x, y, { prefix = '' } = {}) {
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
function artButton(x, y, label, { prefix = '' } = {}) {
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
function artIc(x, y, w, h, { pins = 0, label = '', prefix = '' } = {}) {
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
function artCan(x, y, w, h, lines = [], { prefix = '' } = {}) {
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
function artAntenna(x, y, w, h, { lines = ['keep metal clear'], lineH = 12, inset = 0, fill = 'none', spacing = 1.6 } = {}) {
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

// --- lib/board-geom.js
// Board geometry of the board model: the ONLY source of the measures that the SVG
// layer (lib/art-board.js) and the DOM pin rows (30-ui-board.js, CSS variables on [data-cb=board]) share.
// Pure, no SDK, no DOM, self-contained (tests import it as a plain ES module).
//
// Horizontal, left side from the outer edge of the board box inwards (the right side is mirrored):
//   [2][mark markW][4][tag tagW][6][name nameW][5][glyph 12][4] | pcb edge | lane to the pad centre at stripX
// The DOM row of a pin spans from the outer edge to the end of its pad cell (rowW = gutter + stripX + padCell/2).
// Labels and tags never scale: they sit in these fixed columns outside the pcb body. The body takes 220–340 px.
// Vertical: pcb top, header label zone (topZone), one slot per pin or header separator (pitch = rowH + rowGap), the
// pcb tail, then the port overhang (bottomZone = tail + overhang + 3 ≤ 36).

const BOARD_GEOM_BODY = [220, 340] // pcb body width range in px
const BOARD_GEOM_MARK = 0 // no mark column any more (the selection caret sits in the name→glyph gap)
const BOARD_GEOM_TAG = [56, 120] // tag column range
const BOARD_GEOM_STRIP_X = 15 // strip (pad) centre, from the pcb edge
const BOARD_GEOM_STRIP_HW = 9 // half width of the plastic strip
const BOARD_GEOM_LANE = 16 // lane between strip and the inner parts (reservation brackets print here)
const BOARD_GEOM_PAD_CELL = 14 // DOM pad cell (pad Ø 13)
const BOARD_GEOM_TAIL = 14 // pcb below the last slot
const BOARD_GEOM_PORT_OUT = 9 // ports overhang the bottom pcb edge by this much
const BOARD_GEOM_BOTTOM = BOARD_GEOM_TAIL + BOARD_GEOM_PORT_OUT + 3 // 26 px ≤ 36
const BG_FIXED = 2 + 6 + 5 + 12 + 4 // outer pad, tag→name, name→glyph, glyph, glyph→pcb edge
const BG_MARK_GAP = 4

const bgClamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
/** Monospace width estimate (0.6 em per code point + letter-spacing). */
const boardTextW = (s, px = 12, ls = 0) => [...String(s ?? '')].length * (0.6 * px + ls)
/** Width a pin tag needs: 10 px capitals, letter-spacing 0.4 px, 5 px padding and 1 px border each side. */
const boardTagW = s => (String(s ?? '') ? Math.ceil(boardTextW(String(s).toUpperCase(), 10, 0.4) + 12) : 0)

/** Slots of one side: the pins in data order, a separator slot where the header id changes (WT32: PROG → IO). */
function boardSlots(rows) {
  const out = []
  const list = Array.isArray(rows) ? rows : []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i].header !== list[i - 1].header) out.push({ sep: String(list[i].header ?? '') })
    out.push({ pin: list[i], index: i })
  }
  return out
}

/** The name a pin row shows (same rule as pinView in lib/pins.js: "4" and "IO4" → IO4, ground → GND). */
function boardPinName(hp) {
  if (hp?.kind === 'ground') return 'GND'
  const label = String(hp?.label ?? '')
  if (hp?.kind === 'gpio' && Number.isInteger(hp?.gpio)) return /^\d+$/.test(label) || label === `IO${hp.gpio}` ? `IO${hp.gpio}` : label
  if (hp?.kind === 'nc') return label || 'NC'
  return label || '—'
}

/** Pitch candidates, largest first: the largest that fits the measured height wins (floor 15). Up to 22 px with the
 *  console open, 28 px without. Without a height: start values 18 / 20. */
const BG_PITCH_OPEN = [22, 21, 20, 19, 18, 17, 16, 15]
const BG_PITCH_FREE = [28, 26, 24, 22, 20, 19, 18, 17, 16, 15]
const BG_PITCH_START = { open: 18, free: 20 }
const bgTop = pitch => (pitch >= 18 ? 18 : 16)

/**
 * boardGeom({ rows, consoleOpen, width, layout, height, tagWidth, mode }) →
 *   { rowH, rowGap, pitch, bodyW, gutterL, gutterR, stripX, topZone, bottomZone, height, … }
 *   rows        slot count (max of both sides); default from the layout (separator slots included)
 *   consoleOpen pitch candidates (open console: 22 → 15, else 28 → 15)
 *   width       available width of the board box, default 640
 *   height      available height from the board top to the end of the scroll area (optional): the largest pitch
 *               whose board fits; without it the largest candidate
 *   layout      GET /boards/{id} result (slot count, widest pin name)
 *   tagWidth    width the widest tag needs (boardTagW); the tag column takes it within 56–120 px
 *   mode        'full' (default) | 'compact' (no gutters, pitch 18, body 240; the chat card scales it)
 */
function boardGeom({ rows = null, consoleOpen = true, width = null, layout = null, height = null, tagWidth = 0, mode = 'full' } = {}) {
  const left = boardSlots(layout?.left)
  const right = boardSlots(layout?.right)
  const slots = Math.max(1, Number.isInteger(rows) && rows > 0 ? rows : Math.max(left.length, right.length))
  const compact = mode === 'compact'
  // vertical
  const boardH = p => bgTop(p) + slots * p + BOARD_GEOM_BOTTOM
  let pitch = 18
  if (!compact) {
    const cands = consoleOpen ? BG_PITCH_OPEN : BG_PITCH_FREE
    const hh = Number(height)
    pitch = Number.isFinite(hh) && hh > 0 ? (cands.find(p => boardH(p) <= hh) ?? cands[cands.length - 1]) : BG_PITCH_START[consoleOpen ? 'open' : 'free']
  }
  const rowGap = pitch >= 18 ? 2 : 1
  const rowH = pitch - rowGap
  const topZone = bgTop(pitch)
  // horizontal
  const names = [...(layout?.left || []), ...(layout?.right || [])].map(boardPinName)
  const nameW = compact ? 0 : Math.ceil(Math.max(30, ...names.map(n => boardTextW(n, 12))) + 3)
  const avail = Number.isFinite(Number(width)) && Number(width) > 0 ? Math.floor(Number(width)) : 640
  let markW = compact ? 0 : BOARD_GEOM_MARK
  let tagW = 0
  let bodyW = 240
  let tagFits = true
  if (!compact) {
    const gutterFor = (m, t) => (m ? m + BG_MARK_GAP : 0) + t + nameW + BG_FIXED
    const need = bgClamp(Math.ceil(Number(tagWidth) || 0), BOARD_GEOM_TAG[0], BOARD_GEOM_TAG[1])
    // the body gives way first (340 → 220), then the mark column, then the tags (they get an ellipsis + title)
    if (avail - 2 * gutterFor(markW, need) < BOARD_GEOM_BODY[0]) markW = 0
    const spare = Math.floor((avail - BOARD_GEOM_BODY[0]) / 2) - gutterFor(markW, 0)
    tagW = bgClamp(Math.min(need, spare), BOARD_GEOM_TAG[0], BOARD_GEOM_TAG[1])
    tagFits = tagW >= Math.ceil(Number(tagWidth) || 0)
    bodyW = bgClamp(avail - 2 * gutterFor(markW, tagW), BOARD_GEOM_BODY[0], BOARD_GEOM_BODY[1])
  }
  const gutter = compact ? 0 : (markW ? markW + BG_MARK_GAP : 0) + tagW + nameW + BG_FIXED
  const stripX = BOARD_GEOM_STRIP_X
  const innerX0 = stripX + BOARD_GEOM_STRIP_HW + BOARD_GEOM_LANE
  return {
    mode: compact ? 'compact' : 'full', slots, rowH, rowGap, pitch, topZone, bottomZone: BOARD_GEOM_BOTTOM,
    pcbBottom: topZone + slots * pitch + BOARD_GEOM_TAIL, height: boardH(pitch),
    bodyW, gutterL: gutter, gutterR: gutter, width: gutter * 2 + bodyW, stripX, stripHW: BOARD_GEOM_STRIP_HW, lane: BOARD_GEOM_LANE,
    markW, tagW, tagFits, nameW, padCell: BOARD_GEOM_PAD_CELL, rowW: compact ? 0 : gutter + stripX + BOARD_GEOM_PAD_CELL / 2,
    inner: { x0: innerX0, x1: bodyW - innerX0 }, portOut: BOARD_GEOM_PORT_OUT
  }
}

/** Top edge (board coordinates) of slot i. */
function boardSlotTop(g, i) {
  return g.topZone + i * g.pitch
}

/** Centre line (board coordinates) of slot i. */
function boardSlotY(g, i) {
  return g.topZone + i * g.pitch + g.rowH / 2
}

/** Pad centre x (board coordinates) of a side. */
function boardPadX(g, side) {
  return side === 'left' ? g.gutterL + g.stripX : g.gutterL + g.bodyW - g.stripX
}

/** CSS variables for [data-cb=board]: the DOM rows use exactly these numbers (the geometry test compares them). */
function boardGeomVars(g) {
  const px = v => `${v}px`
  return {
    '--cb-row-h': px(g.rowH), '--cb-row-gap': px(g.rowGap), '--cb-body-w': px(g.bodyW), '--cb-gutter': px(g.gutterL),
    '--cb-top': px(g.topZone), '--cb-mark-w': px(g.markW), '--cb-tag-w': px(g.tagW), '--cb-name-w': px(g.nameW),
    '--cb-strip-x': px(g.stripX), '--cb-row-w': px(g.rowW), '--cb-board-w': px(g.width), '--cb-board-h': px(g.height)
  }
}

// --- lib/calc.js
// 02 CALC definitions (fields, units, defaults), request bodies, result rows, "Add to project" ops. Pure; the
// backend computes, the UI parses for feedback only. Field names follow calc.PARAMS.

const CALC_DEFS = [
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
function parseTempC(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return { ok: false, empty: true, error: 'required' }
  const s = raw.replace(/\s*(?:°\s*C|deg\s*C|C)\s*$/i, '').replace('\u2212', '-')
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(s)) return { ok: false, empty: false, error: 'a temperature in °C, e.g. 25' }
  const value = Number(s)
  if (value < -60 || value > 150) return { ok: false, empty: false, error: 'between -60 and 150 °C' }
  return { ok: true, empty: false, value }
}

function calcDef(type) {
  return CALC_DEFS.find(d => d.type === type) || null
}

/** Initial form values of a calculator: defaults, or the inputs of a stored project calc (SI numbers). */
const CALC_PREFIX = [[1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'u'], [1e-9, 'n'], [1e-12, 'p']]

/** SI number → short input text the parser reads back: 1000 Ω → "1k", 0.013 A → "13mA", 3.3 V → "3.3". */
function siInputText(value, unit) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value)
  if (value === 0) return '0'
  const a = Math.abs(value)
  const [mul, pre] = CALC_PREFIX.find(([m]) => a >= m * 0.9999999) || CALC_PREFIX[CALC_PREFIX.length - 1]
  const m = Number((value / mul).toPrecision(6))
  const u = unit === 'Ω' || !unit ? '' : unit
  return pre ? `${m}${pre}${u}` : String(m)
}

function initialForm(def, stored = null) {
  const out = {}
  for (const f of def.fields) {
    const v = stored?.inputs?.[f.name]
    out[f.name] = v === undefined || v === null ? f.def
      : typeof v === 'object' && v.display ? v.display : typeof v === 'number' && f.unit !== undefined ? siInputText(v, f.unit) : String(v)
  }
  return out
}

/** Validate a form (parse = parseQuantity) → {ok, body, errors}; quantities go as typed text (backend parses). */
function buildCalcBody(def, form, parse) {
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
function calcRawMeta(env, kind) {
  const list = env?.ok ? env.result?.calculators : null
  return (Array.isArray(list) && list.find(c => c && c.kind === kind)) || null
}

/** Def with backend choices ('' first unless required + default) and one_of. */
function calcApplyMeta(def, raw) {
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
function calcNeedText(def) {
  const label = n => def.fields.find(f => f.name === n)?.label || calcParamLabel(n)
  return `needs ${(def.oneOf || []).map(s => s.map(label).join(' + ')).join(', or ')}`
}

/** Worst check (only passed is checked): 'failed' > 'not_checked' (skipped, unknown) > 'passed'; null. */
function worstCheck(checks) {
  const list = Array.isArray(checks) ? checks : []
  if (!list.length) return null
  if (list.some(c => c?.status === 'failed')) return 'failed'
  return list.every(c => c?.status === 'passed') ? 'passed' : 'not_checked'
}

/** Colour of a result value from its worst check: failed → bad, not checked → neutral, passed → ok. */
function valueTone(checks) {
  const w = worstCheck(checks)
  return w === 'failed' ? 'bad' : w === 'passed' ? 'ok' : 'fg'
}

/** The headline value, E-series deviation and secondary rows of a calc.* result envelope. */
function calcView(def, env) {
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
function nextRef(parts, letter, taken = []) {
  const used = new Set([...refNumbers(parts, letter), ...refNumbers(taken.map(ref => ({ ref })), letter)])
  let n = 1
  while (used.has(n)) n++
  return `${letter}${n}`
}

/** Next free calc id of a type: led-1, led-2 … */
function nextCalcId(project, type) {
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
function partsFromCalc(type, env, project, calcId) {
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
function calcOps(type, env, project) {
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
function calcCheckTone(status) {
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
function calcBands(def, env) {
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
function calcChips(checks) {
  return (Array.isArray(checks) ? checks : []).filter(c => c && typeof c === 'object').map((c, i) => {
    const status = CALC_CHECK_WORDS[c.status] ? c.status : 'unknown'
    const id = typeof c.id === 'string' ? c.id : `check-${i + 1}`
    const name = id.split('.').slice(2).join(' ').replace(/_/g, ' ') || id
    return { id, name, status, word: CALC_CHECK_WORDS[status] || 'unknown', sym: CALC_CHECK_SYMBOLS[status] || '?',
      tone: status === 'failed' ? 'bad' : status === 'passed' ? 'ok' : 'dim', detail: typeof c.detail === 'string' ? c.detail : '' }
  })
}

/** Steps of the formula drawer: [{name, expr, value}] with texts only (a step without a name is left out). */
function calcSteps(steps) {
  return (Array.isArray(steps) ? steps : []).filter(s => s && typeof s.name === 'string' && s.name)
    .map(s => ({ name: s.name, expr: typeof s.expr === 'string' ? s.expr : '', value: calcQ(s.value)?.display || '' }))
}

/** The formula string split at '; ' into one line per equation. */
function calcFormulaLines(formula) {
  return typeof formula === 'string' ? formula.split(/;\s+/).map(x => x.trim()).filter(Boolean) : []
}

/** Does the typed text already name the unit? ("10mA" → A, "3V3" → V, "4k7 ohm" → Ω) */
function calcTypedUnit(text, unit) {
  const t = String(text ?? '')
  return unit === 'Ω' ? /Ω|ohm/i.test(t) : unit ? t.toLowerCase().includes(unit.toLowerCase()) : false
}

/** Verdict next to the headline value: symbol + words (counted, not computed). */
function calcVerdict(checks) {
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
function calcParamLabel(name) {
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
function calcPlainText(f, raw) {
  return f?.kelvin ? String(raw ?? '').replace(/\s*K$/, '') : raw
}

/** Short tag: one word → 4 letters (OPTO), more → initials (CS). */
const calcShort = kind => {
  const w = kind.split('_').filter(Boolean)
  return (w.length > 1 ? w.map(x => x[0]).join('') : (w[0] || kind).slice(0, 4)).toUpperCase()
}

/** Generic card definition of a register entry. */
function calcGenericDef(meta) {
  const kind = String(meta?.kind || '')
  return { type: kind, generic: true, title: meta?.title || kind, short: calcShort(kind),
    summary: typeof meta?.summary === 'string' ? meta.summary : '', group: meta?.group || 'basics',
    fields: (Array.isArray(meta?.params) ? meta.params : []).filter(p => p && typeof p.name === 'string').map(calcMetaField) }
}

/** Quantities and short texts of an answer in order: [{k, label, q}]. */
function calcResultRows(result) {
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
function calcGroups(list, groups = []) {
  const metas = Array.isArray(list) ? list : []
  const order = ['basics', ...(Array.isArray(groups) ? groups : []).filter(g => typeof g === 'string' && g !== 'basics')]
  for (const m of metas) if (!order.includes(m.group)) order.push(m.group)
  const defsOf = id => [...(id === 'basics' ? CALC_DEFS : []),
    ...metas.filter(m => (m.group || 'basics') === id && !calcDef(m.kind)).map(calcGenericDef)]
  return order.map(id => ({ id, defs: defsOf(id) })).filter(g => g.defs.length)
}

// --- lib/contrast.js
// Contrast maths (WCAG 2.x relative luminance) for the Bench Phosphor tokens. Pure, no SDK.
// Used by tests-js/test_ui1_contrast.mjs to prove the contrast targets: text and state colours ≥ 7:1 on --cb-bg,
// --cb-fg-faint (decoration only) ≥ 3:1; follow-theme text variants ≥ 4.5:1 on the app background.

function hexToRgb(hex) {
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

function luminance(hex) {
  const [r, g, b] = hexToRgb(hex)
  return 0.2126 * srgbChannel(r) + 0.7152 * srgbChannel(g) + 0.0722 * srgbChannel(b)
}

function contrastRatio(a, b) {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/** Straight sRGB mix (`p` of `a` over `b`), the worst case for color-mix tints on dark ground. */
function mixHex(a, b, p) {
  const ca = hexToRgb(a)
  const cb = hexToRgb(b)
  return '#' + ca.map((v, i) => Math.round(v * p + cb[i] * (1 - p)).toString(16).padStart(2, '0')).join('')
}

/** Rows {fg, bg, ratio, min, pass} for a table of [name, fg, bg, min]. */
function contrastReport(pairs) {
  return pairs.map(([name, fg, bg, min]) => {
    const ratio = contrastRatio(fg, bg)
    return { name, fg, bg, ratio: Math.round(ratio * 100) / 100, min, pass: ratio >= min }
  })
}

// ─── CSS color-mix(in oklab, …) with alpha, as the browser computes it (CSS Color 4/5) ─────────────

const toHexRgb = rgb => '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('')
const linToSrgb = c => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)

/** sRGB hex → OKLab [L, a, b] (Björn Ottosson's matrices). */
function hexToOklab(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbChannel)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]
}

/** OKLab → sRGB [r, g, b] 0–255 (clipped to the sRGB gamut). */
function oklabToRgb([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3
  const lin = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s]
  return lin.map(c => linToSrgb(Math.max(0, Math.min(1, c))) * 255)
}

/** color-mix(in oklab, a p, b) with alpha (premultiplied interpolation). Colours are {hex, alpha}. → {hex, alpha} */
function oklabMix(a, b, p) {
  const aa = a.alpha ?? 1
  const ba = b.alpha ?? 1
  const A = hexToOklab(a.hex).map(v => v * aa)
  const B = hexToOklab(b.hex).map(v => v * ba)
  const alpha = p * aa + (1 - p) * ba
  const lab = A.map((v, i) => (alpha ? (p * v + (1 - p) * B[i]) / alpha : 0))
  return { hex: toHexRgb(oklabToRgb(lab)), alpha }
}

/** A colour with alpha painted over an opaque background (gamma-encoded sRGB, as browsers composite). → hex */
function composite(c, bgHex) {
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
function resolveCss(expr, vars = {}, scheme = 'light') {
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

// --- lib/crash.js
// Crash-decode presentation helpers (pure; tested in tests-js/test_ui1_api.mjs and test_ui2_panic.mjs).

/**
 * ELF check of a crash.decode envelope: passed (match), failed (mismatch), skipped (no ELF, e.g. sim build).
 * `label` carries the reason right after the verdict (e.g. "elf check skipped · simulated build, no
 * ELF"); `short` is the compact form for the console card. A skipped check is never shown as passed.
 */
function elfCheck(env) {
  const r = env?.result || {}
  const c = (env?.checks || []).find(x => x.id === 'crash.elf_match')
  const status = c?.status || (r.elf_match === true ? 'passed' : r.elf_match === false ? 'failed' : 'skipped')
  // word + reason: the 06 DEBUG check line ("elf check  ○ skipped · simulated build, no ELF")
  if (status === 'passed') {
    return { status, tone: 'ok', symbol: '✓', text: 'elf match', label: 'elf match', short: 'elf match', detail: c?.detail,
      word: 'match', reason: c?.detail || 'ELF hash matches the log' }
  }
  if (status === 'failed') {
    return { status, tone: 'bad', symbol: '✕', text: 'elf mismatch', label: 'elf mismatch · other build', short: 'elf mismatch',
      detail: c?.detail || 'The log was produced by a different firmware build.', word: 'mismatch', reason: 'the log comes from another build' }
  }
  const reason = env?.simulated ? 'simulated build, no ELF' : 'no ELF to compare'
  return { status: 'skipped', tone: 'faint', symbol: '○', text: 'elf check skipped', label: `elf check skipped · ${reason}`,
    short: env?.simulated ? 'elf skipped · sim' : 'elf skipped', detail: c?.detail || 'no ELF file to compare', word: 'skipped', reason }
}

/**
 * Key registers of a panic per architecture, with what the register holds (ESP-IDF Fatal Errors: EXCVADDR / MTVAL
 * hold the accessed address). Only names; the values come from the decoder.
 */
const KEY_REGISTERS = {
  xtensa: [['PC', 'program counter'], ['EXCCAUSE', 'exception cause'], ['EXCVADDR', 'accessed address']],
  riscv: [['MEPC', 'exception pc'], ['MCAUSE', 'trap cause'], ['MTVAL', 'trap value']]
}

/**
 * Register bank of a crash.decode result → {key: [{k, v, label, note}], all: [{k, v, key}]} or
 * null. `key` keeps the architecture's order (only registers the dump has); `note` on the cause register is the
 * decoder's reason name, which it read from that register (cpu exceptions only). `all` is the dump in log order.
 */
function registerBank(result) {
  const regs = result?.registers || {}
  const names = Object.keys(regs)
  if (!names.length) return null
  const arch = result.arch === 'riscv' || (!result.arch && ('MEPC' in regs || 'MCAUSE' in regs)) ? 'riscv' : 'xtensa'
  const keys = KEY_REGISTERS[arch].filter(([k]) => regs[k])
  const cause = arch === 'riscv' ? 'MCAUSE' : 'EXCCAUSE'
  const note = k => (k === cause && result.kind === 'cpu_exception' && result.reason ? result.reason : null)
  const keySet = new Set(keys.map(([k]) => k))
  return {
    arch,
    key: keys.map(([k, label]) => ({ k, v: regs[k], label, note: note(k) })),
    all: names.map(k => ({ k, v: regs[k], key: keySet.has(k) }))
  }
}

const crashHexLow = s => String(s || '').toLowerCase()

/**
 * Where a hovered frame or register shows up in a raw log line (frame ↔ log coupling) →
 * [[start, end], …] character ranges. mark = {kind: 'pc', value} matches the PC of a "PC:SP" pair in a
 * "Backtrace:" line; {kind: 'reg', name, value} matches "NAME : value" in a register dump line. Hex is compared
 * case-insensitively; a value never matches inside a longer number.
 */
function logMarkRanges(text, mark) {
  const s = String(text || '')
  if (!mark?.value || !s) return []
  const v = crashHexLow(mark.value).replace(/[^0-9a-fx]/g, '')
  if (!/^0x[0-9a-f]+$/.test(v)) return []
  const low = s.toLowerCase()
  const out = []
  if (mark.kind === 'pc') {
    if (!/^\s*backtrace:/.test(low)) return []
    const re = /(0x[0-9a-f]+):0x[0-9a-f]+/g
    for (let m = re.exec(low); m; m = re.exec(low)) if (m[1] === v) out.push([m.index, m.index + m[1].length])
    return out
  }
  if (mark.kind === 'reg' && /^[A-Za-z][A-Za-z0-9]*$/.test(String(mark.name || ''))) {
    const re = new RegExp(`(^|[^a-z0-9])(${String(mark.name).toLowerCase()}\\s*:\\s*(0x[0-9a-f]+))`, 'g')
    for (let m = re.exec(low); m; m = re.exec(low)) {
      if (m[3] === v) { const at = m.index + m[1].length; out.push([at, at + m[2].length]) }
    }
  }
  return out
}

/** A text split into plain and marked parts → [{t, mark}] (for rendering logMarkRanges). */
function splitMarked(text, ranges) {
  const s = String(text || '')
  if (!ranges?.length) return [{ t: s, mark: false }]
  const out = []
  let at = 0
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    if (a < at) continue
    if (a > at) out.push({ t: s.slice(at, a), mark: false })
    out.push({ t: s.slice(a, b), mark: true })
    at = b
  }
  if (at < s.length) out.push({ t: s.slice(at), mark: false })
  return out
}

/** "write_sensor_buffer(unsigned char*, unsigned int)" → "write_sensor_buffer(…)"; no-arg and plain names unchanged. */
function shortFunction(fn) {
  const s = String(fn || '').trim()
  const m = /^([^(]+)\((.*)\)(\s*(?:const)?\s*)$/.exec(s)
  if (!m) return s || '??'
  return m[2].trim() ? `${m[1]}(…)${m[3].trimEnd()}` : s
}

/** "write_sensor_buffer(unsigned char*, unsigned int) (src/main.cpp:44)" → {fn, file, line} */
function splitTopFrame(text) {
  const s = String(text || '')
  const m = /^(.*?)\s*\(([^()]*):(\d+)\)\s*$/.exec(s)
  return m ? { fn: m[1], file: m[2], line: Number(m[3]) } : { fn: s, file: null, line: null }
}

/**
 * Data for the PanicCard and the 06 DEBUG panic view, from (in this order of preference) the crash.decode envelope,
 * the project's stored debug.last_panic and the serial panic message ({seq, summary, log_ref}).
 * → null when there is nothing to show.
 */
function panicCardData(decodeEnv, lastPanic = null, serialPanic = null) {
  const env = decodeEnv?.ok ? decodeEnv : null
  const r = env?.result || null
  if (!r && !lastPanic && !serialPanic) return null
  const reason = r?.reason || lastPanic?.reason || (serialPanic?.summary ? String(serialPanic.summary).split(' · ')[0] : null) || 'panic'
  const coreRaw = r?.core ?? lastPanic?.core ?? (/core\s+(\d+)/i.exec(serialPanic?.summary || '') || [])[1]
  const core = coreRaw === undefined || coreRaw === null ? null : Number(coreRaw)
  let frames = (r?.frames || []).map((f, i) => ({ i: f.i ?? i, fn: String(f.function || '??'), short: shortFunction(f.function),
    file: f.file || '??', base: String(f.file || '??').split('/').pop(), line: f.line ?? null, pc: f.pc || '', inlined: Boolean(f.inlined) }))
  if (!frames.length && lastPanic?.top_frame) {
    const t = splitTopFrame(lastPanic.top_frame)
    frames = [{ i: 0, fn: t.fn, short: shortFunction(t.fn), file: t.file || '??', base: String(t.file || '??').split('/').pop(), line: t.line, pc: '', inlined: false }]
  }
  const regs = r?.registers || {}
  return {
    reason,
    core,
    title: `${reason}${core !== null ? ` · core ${core}` : ''}`,
    decoded: Boolean(r),
    simulated: Boolean(env?.simulated),
    frames,
    top: frames[0] || null,
    interpretation: (r?.interpretation || []).map(x => ({ code: x.code, text: x.text, source_id: x.source_id || null })),
    registers: ['PC', 'EXCCAUSE', 'EXCVADDR'].filter(k => regs[k]).map(k => ({ k, v: regs[k] })),
    bank: registerBank(r),
    // the interpretation the decoder summary does not already say (the summary is the lead sentence on 06 DEBUG)
    extra: (r?.interpretation || []).filter(x => !saidIn(env?.summary || '', x.text)).map(x => ({ code: x.code, text: x.text, source_id: x.source_id || null })),
    resetReason: r?.reset_reason || null,
    elf: env ? elfCheck(env) : null,
    logRef: serialPanic?.log_ref || lastPanic?.log_ref || null,
    summary: env?.summary || (serialPanic ? `${serialPanic.summary}` : lastPanic ? `${reason}${core !== null ? ` on core ${core}` : ''}` : '')
  }
}

/** The project's stored panic still describes the firmware on the board (no successful flash after it). */
function projectPanicCurrent(project) {
  const p = project?.debug?.last_panic
  if (!p) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at || !p.at) return true
  return String(p.at) >= String(f.at)
}

const normText = t => String(t || '').toLowerCase().replace(/\s+/g, ' ').replace(/[.\s]+$/, '').trim()

/** Is the interpretation already said by the summary? (whole text, or the part after "EXCVADDR 0x…: ") */
function saidIn(summary, text) {
  const s = normText(summary)
  const t = normText(text)
  if (!t) return true
  if (s.includes(t)) return true
  const tail = t.includes(': ') ? t.slice(t.indexOf(': ') + 2) : ''
  return Boolean(tail && tail.length > 12 && s.includes(tail))
}

/**
 * "Fix with Hermes" composer draft (never sent): the reason once (the decoder summary), the top frames, only
 * the interpretation the summary does not already say, where the firmware lives (as the agent reads it:
 * `bench_project get → firmware.dir`) and the ask (explain, fix, rebuild, ask before flashing).
 */
function fixDraftText(project, decode) {
  const r = decode?.result || {}
  const frames = (r.frames || []).slice(0, 3).map(f => `#${f.i} ${f.function} (${f.file}:${f.line})`)
  const fw = project?.firmware || {}
  const port = project?.board?.detected?.port
  const summary = String(decode?.summary || '').trim()
  const headline = summary || `${r.reason || '?'} on core ${r.core ?? '?'}.`
  const extra = (r.interpretation || []).map(x => String(x.text || '').trim()).filter(t => t && !saidIn(summary, t))
  return [
    `Fix ${project?.id ?? 'bench'} panic`,  // first line = session title in sidebar and tab: keep it short
    `Circuit Bench — project "${project?.id ?? '?'}", station 06 DEBUG: the firmware panicked${port ? ` on ${port}${/^sim:/.test(port) ? ' (simulated board)' : ''}` : ''}.`,
    `Panic: ${headline}`,
    frames.length ? `Top frames:\n${frames.join('\n')}` : null,
    extra.length ? `Interpretation: ${extra.join(' ')}` : null,
    fw.dir || fw.env ? `Firmware: bench_project get → firmware.dir${fw.env ? ` (PlatformIO env ${fw.env})` : ''}.` : null,
    'Read the source, explain the cause, propose a fix, rebuild with bench_board, and ask before flashing.'
  ].filter(Boolean).join('\n')
}

// --- lib/directive.js
// Directive `::bench{project="…" view="…"}`. Pure.
// Attributes are strings only (only quoted values survive, keys are lower-cased). Anything else, an unknown
// view or a bad id renders nothing. The card reads the project itself; numbers/bools never come from attributes.

const DIRECTIVE_ID_RE = /^[a-z0-9-]{1,48}$/
const DIRECTIVE_VIEWS = ['pins', 'calc', 'wire', 'solder', 'flash', 'crash']
const DIRECTIVE_STATION = { pins: 'plan', calc: 'calc', wire: 'wire', solder: 'solder', flash: 'flash', crash: 'debug' }
const DIRECTIVE_TITLE = { pins: 'PIN MAP', calc: 'CALCULATIONS', wire: 'WIRING', solder: 'SOLDER ORDER', flash: 'BUILD & FLASH', crash: 'PANIC' }

/** → {project, view, station, title} or null. `view` defaults to "pins" only when absent. */
function parseDirectiveAttrs(attrs) {
  if (!attrs || typeof attrs !== 'object' || Array.isArray(attrs)) return null
  const project = attrs.project
  if (typeof project !== 'string' || !DIRECTIVE_ID_RE.test(project)) return null
  const view = attrs.view === undefined ? 'pins' : attrs.view
  if (typeof view !== 'string' || !DIRECTIVE_VIEWS.includes(view)) return null
  return { project, view, station: DIRECTIVE_STATION[view], title: DIRECTIVE_TITLE[view] }
}

/** Session id from the render props (B has it, v0.22.5 not): `sessionId ?? null`, only a plain short string. */
function directiveSession(props) {
  const sid = props?.sessionId ?? null
  return typeof sid === 'string' && sid.length <= 128 && /^[A-Za-z0-9_.:-]+$/.test(sid) ? sid : null
}

function dClock(iso) {
  const d = new Date(iso)
  return !iso || Number.isNaN(d.getTime()) ? '—' : [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':')
}

/**
 * Compact facts of a project for one view → {headline: {text, tone}, rows: [{k, label, value, tone}]}.
 * `panicCurrent(project)` is injected (lib/crash.js projectPanicCurrent).
 */
function directiveSummary(view, project, { panicCurrent = () => true } = {}) {
  if (!project) return { headline: { text: 'no project', tone: 'dim' }, rows: [] }
  const rows = []
  if (view === 'pins') {
    const as = project.assignments || []
    const c = { ok: 0, caution: 0, blocked: 0 }
    for (const a of as) if (c[a.verdict] !== undefined) c[a.verdict]++
    for (const a of as.slice(0, 6)) rows.push({ k: a.role, label: a.role, value: `IO${a.pin}`, tone: a.verdict === 'blocked' ? 'bad' : a.verdict === 'caution' ? 'warn' : 'active' })
    const tone = c.blocked ? 'bad' : c.caution ? 'warn' : as.length ? 'ok' : 'dim'
    return { headline: { text: `${c.ok}✓ ${c.caution}! ${c.blocked}✕`, tone }, rows }
  }
  if (view === 'calc') {
    for (const calc of (project.calcs || []).slice(0, 5)) {
      const r = calc.result || {}
      const main = r.r_chosen || r.i_b || r.v_out_max || r.suggested
      rows.push({ k: calc.id, label: `${calc.type} · ${calc.id}`, value: main?.display || '—', tone: 'fg' })
    }
    return { headline: { text: `${(project.calcs || []).length} calculations`, tone: rows.length ? 'ok' : 'dim' }, rows }
  }
  if (view === 'wire') {
    for (const ci of (project.circuits || []).slice(0, 5)) rows.push({ k: ci.id, label: ci.id, value: ci.block, tone: 'fg' })
    const nc = (project.circuits || []).length
    const np = (project.parts || []).length
    return { headline: { text: `${nc} circuit${nc === 1 ? '' : 's'} · ${np} part${np === 1 ? '' : 's'} in the project`, tone: rows.length ? 'ok' : 'dim' }, rows }
  }
  if (view === 'solder') {
    const steps = project.solder?.steps || []
    const done = new Set(project.solder?.done || [])
    const n = steps.filter(s => done.has(s.id)).length
    for (const s of steps.slice(0, 6)) rows.push({ k: s.id, label: `${done.has(s.id) ? '[✓]' : '[ ]'} ${s.n}`, value: s.kind, tone: done.has(s.id) ? 'ok' : 'dim' })
    return { headline: { text: steps.length ? `${n}/${steps.length} done` : 'no plan yet', tone: steps.length && n === steps.length ? 'ok' : steps.length ? 'active' : 'dim' }, rows }
  }
  if (view === 'flash') {
    const fw = project.firmware || {}
    const det = project.board?.detected
    if (det) rows.push({ k: 'det', label: 'board', value: `${det.port}${det.simulated ? ' (sim)' : ''}`, tone: det.simulated ? 'active' : 'ok' })
    if (fw.last_build) rows.push({ k: 'b', label: `build ${dClock(fw.last_build.at)}`, value: fw.last_build.ok ? `ok · ram ${fw.last_build.ram_pct ?? '—'} %` : 'FAILED', tone: fw.last_build.ok ? 'ok' : 'bad' })
    if (fw.last_flash) rows.push({ k: 'f', label: `flash ${dClock(fw.last_flash.at)}`, value: fw.last_flash.ok ? 'ok' : 'FAILED', tone: fw.last_flash.ok ? 'ok' : 'bad' })
    return { headline: { text: fw.last_flash?.ok ? 'flashed' : fw.last_build?.ok ? 'built' : 'not built', tone: fw.last_flash?.ok ? 'ok' : fw.last_build?.ok ? 'active' : 'dim' }, rows }
  }
  if (view === 'crash') {
    const p = project.debug?.last_panic
    if (!p) return { headline: { text: 'no panic recorded', tone: 'ok' }, rows }
    const live = panicCurrent(project)
    rows.push({ k: 'r', label: 'reason', value: `${p.reason || p.kind}${p.core !== undefined ? ` · core ${p.core}` : ''}`, tone: live ? 'bad' : 'dim' })
    if (p.top_frame) rows.push({ k: 't', label: '#0', value: p.top_frame, tone: live ? 'bad' : 'dim' })
    rows.push({ k: 'a', label: 'at', value: dClock(p.at), tone: 'dim' })
    if (!live && project.firmware?.last_flash?.ok) rows.push({ k: 'f', label: 'flashed after it', value: dClock(project.firmware.last_flash.at), tone: 'ok' })
    return { headline: { text: live ? 'PANIC CAUGHT' : 'NO CURRENT PANIC', tone: live ? 'bad' : 'ok' }, rows }
  }
  return { headline: { text: '', tone: 'dim' }, rows }
}

// --- lib/fixtures.js (product build: none)
const createFixtureBackend = null

// --- lib/flash.js
// Station 05 FLASH helpers: port list (never opens anything), detection summary, flash confirmation object, job
// progress text. Pure.

const PORT_KIND_LABEL = {
  usb_serial_jtag: 'USB-Serial/JTAG', usb_cdc_app: 'USB CDC (app)', cp210x: 'CP210x', ch340: 'CH340', ch343: 'CH343',
  ch9102: 'CH9102', ftdi: 'FTDI', unknown: 'serial', sim: 'simulated'
}

/**
 * Rows for the port list: real ports first (likely ESP boards on top), simulated ports below, each marked.
 * Only describes; detection and the monitor start on a click.
 */
function portRows(ports, { detectedPort = null, selected = null } = {}) {
  const list = Array.isArray(ports) ? ports.filter(p => p && typeof p.device === 'string') : []
  const real = list.filter(p => !p.simulated).sort((a, b) => Number(Boolean(b.likely_esp)) - Number(Boolean(a.likely_esp)))
  const sim = list.filter(p => p.simulated)
  return [...real, ...sim].map(p => ({
    device: p.device,
    simulated: Boolean(p.simulated),
    label: p.simulated ? 'SIMULATED' : p.likely_esp ? 'ESP' : 'SERIAL',
    kind: PORT_KIND_LABEL[p.kind] || p.kind || 'serial',
    description: p.description || '',
    detected: p.device === detectedPort,
    selected: p.device === selected,
    noAutoReset: p.kind === 'usb_cdc_app'
  }))
}

/** Default port for the station: the detected one if still listed, else the first ESP-like real port, else sim. */
function defaultPort(ports, detectedPort = null) {
  const rows = portRows(ports, { detectedPort })
  return rows.find(r => r.detected)?.device || rows.find(r => !r.simulated && r.label === 'ESP')?.device || rows.find(r => r.simulated)?.device || null
}

function isSimPort(port) {
  return typeof port === 'string' && port.startsWith('sim://')
}

/**
 * Confirmation of the flash dialog: {port, mac, elf_sha256} from project.board.detected and
 * project.firmware.last_build (the flash route compares exactly these). `buildJob` (done) may be newer than
 * the project copy in the UI. → {ok, confirm, missing: [..], stale}
 */
function flashConfirm(project, buildJob = null) {
  const det = project?.board?.detected || null
  let build = project?.firmware?.last_build || null
  const jobRes = buildJob?.state === 'done' ? buildJob.result?.result : null
  if (jobRes?.elf_sha256 && buildJob.result?.ok && (!build?.at || !buildJob.finished || buildJob.finished >= build.at)) {
    build = { ok: true, elf_sha256: jobRes.elf_sha256, at: buildJob.finished, ram_pct: jobRes.ram_pct, flash_pct: jobRes.flash_pct }
  }
  const missing = []
  if (!det?.port) missing.push('detect')
  if (!det?.mac) missing.push('mac')
  if (!build || build.ok !== true || !build.elf_sha256) missing.push('build')
  const confirm = missing.length ? null : { port: det.port, mac: String(det.mac).toLowerCase(), elf_sha256: String(build.elf_sha256).toLowerCase() }
  const flash = project?.firmware?.last_flash
  return {
    ok: !missing.length,
    confirm,
    missing,
    simulated: isSimPort(det?.port),
    alreadyFlashed: Boolean(confirm && flash?.ok && flash.elf_sha256 === confirm.elf_sha256 && flash.port === confirm.port)
  }
}

/** GET /board/flash/check → {state: ready | locked | unknown, code, message, hint}. Reads the answer
 *  only (the backend decides); no answer or an error envelope is `unknown`, never a lock. */
function flashGate(env) {
  const r = env && env.ok === true ? env.result : null
  if (!r || typeof r.ready !== 'boolean') return { state: 'unknown', code: null, message: null, hint: null }
  if (r.ready) return { state: 'ready', code: null, message: null, hint: null }
  const f = r.refusal || {}
  return { state: 'locked', code: f.code || 'refused', message: f.message || env.summary || 'flashing would be refused', hint: f.hint || null }
}

/** Job object → {state, pct (0..100|null), indeterminate, text, done, failed}. pio reports no percentage. */
function jobProgress(job) {
  if (!job) return { state: 'none', pct: null, indeterminate: false, text: '', done: false, failed: false, running: false }
  const state = job.state
  const running = state === 'queued' || state === 'running'
  const pct = typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.round(Math.max(0, Math.min(1, job.progress)) * 100) : null
  const failed = state === 'failed' || (state === 'done' && job.result && job.result.ok === false)
  const text = state === 'queued' ? 'queued…' : state === 'running' ? (pct === null ? 'running…' : `${pct} %`)
    : failed ? 'failed' : state === 'done' ? 'done' : String(state || '')
  return { state, pct: running ? pct : state === 'done' ? 100 : pct, indeterminate: running && pct === null, text, done: state === 'done' && !failed, failed, running }
}

/** Error of a finished job (or a refused start) as {code, message, hint}. */
function jobError(envOrJob) {
  const env = envOrJob?.result && 'job_id' in (envOrJob.result || {}) ? envOrJob.result.result : envOrJob?.job_id ? envOrJob.result : envOrJob
  if (!env || env.ok !== false) return null
  return { code: env.error?.code || 'failed', message: env.error?.message || env.summary || 'failed', hint: env.error?.hint || null }
}

/** Module variant id without the trailing "?" that marks an unverified guess ("n16r8?" → "n16r8"); null if empty.
 *  set_board only knows bare ids. */
function bareVariant(v) {
  if (typeof v !== 'string') return null
  return v.trim().replace(/\?+$/, '').trim().toLowerCase() || null
}

/** Detection result (board.detect result) → compact rows + whether the variant differs from the project.
 *  A real board's guess ends in "?" (esptool cannot tell octal from quad PSRAM): `suggestion` is the bare id,
 *  `unverified` keeps the mark. */
function detectSummary(res, project) {
  if (!res) return null
  const raw = typeof res.variant_suggestion === 'string' ? res.variant_suggestion.trim() : ''
  const suggestion = bareVariant(raw)
  const want = bareVariant(project?.board?.variant)
  return {
    port: res.port || null,
    chip: res.chip || '—',
    mac: res.mac || '—',
    flash: res.flash_size ? String(res.flash_size).replace(/(\d)\s*([KMG]B)\b/, '$1 $2') : '—',
    psram: res.psram_mb ? `${res.psram_mb} MB` : res.features?.some?.(f => /PSRAM/i.test(f)) ? 'yes' : 'none',
    usb: res.usb_mode || null,
    features: Array.isArray(res.features) ? res.features : [],
    suggestion,
    unverified: Boolean(suggestion && raw.endsWith('?')),
    variantDiffers: Boolean(suggestion && want && suggestion !== want),
    simulated: Boolean(res.simulated)
  }
}

// ─── What the dialog and the station draw (pure; nothing is estimated) ──────────────────────────

/** A 64-digit SHA-256 in eight groups of eight (for reading aloud and comparing); anything else unchanged in one
 *  group, nothing → []. The groups join back to the input (the dialog text keeps the hash contiguous). */
function flashHashGroups(hex) {
  const s = String(hex ?? '').trim()
  if (!s) return []
  return /^[0-9a-fA-F]{64}$/.test(s) ? s.match(/.{8}/g) : [s]
}

/** RAM/flash rows of a build: [{id, label, pct, used, total}] for every delivered percentage. Bytes only from a build
 *  job result of the same ELF (the project record keeps percentages only). */
function flashMemRows(build, jobResult = null) {
  if (!build || build.ok !== true) return []
  const same = Boolean(jobResult && jobResult.elf_sha256 && jobResult.elf_sha256 === build.elf_sha256)
  const num = v => typeof v === 'number' && Number.isFinite(v) ? v : null
  return [['ram', 'RAM'], ['flash', 'Flash']].flatMap(([id, label]) => {
    const pct = num(build[`${id}_pct`])
    if (pct === null) return []
    const used = same ? num(jobResult[`${id}_used`]) : null
    const total = same ? num(jobResult[`${id}_total`]) : null
    return [{ id, label, pct, used: used !== null && total ? used : null, total: used !== null && total ? total : null }]
  })
}

/** Check list of the flash dialog in words. Each row: {id, state: 'match'|'differs'|'unchecked', word, text, at?}.
 *  Compares the confirmation (what the backend checks) with the detection and the last build. */
function flashCheckRows(confirm, project) {
  const det = project?.board?.detected || {}
  const b = project?.firmware?.last_build || {}
  const cmp = (a, c) => (!a || !c ? 'unchecked' : String(a).toLowerCase() === String(c).toLowerCase() ? 'match' : 'differs')
  const word = { match: 'match', differs: 'differs', unchecked: 'not compared' }
  const port = cmp(det.port, confirm?.port)
  const mac = cmp(det.mac, confirm?.mac)
  const elf = cmp(b.ok ? b.elf_sha256 : null, confirm?.elf_sha256)
  return [
    { id: 'port', state: port, word: word[port],
      text: port === 'match' ? 'Port matches the detection' : port === 'differs' ? 'Port differs from the detection' : 'Port not compared: no detection' },
    { id: 'mac', state: mac, word: word[mac],
      text: mac === 'match' ? 'MAC matches the detected board' : mac === 'differs' ? 'MAC differs from the detected board' : 'MAC not compared: no detected MAC' },
    { id: 'elf', state: elf, word: word[elf], at: elf === 'match' ? b.at || null : null,
      text: elf === 'match' ? 'Firmware hash matches the last build' : elf === 'differs' ? 'Firmware hash differs from the last build' : 'Firmware hash not compared: no successful build' }
  ]
}

// last log line → phase word (esptool 4.x/5.x and PlatformIO wording; the newest matching line wins)
const FLASH_PHASES = {
  flash: [[/Hard resetting|Leaving\.\.\.|Resetting/i, 'resetting'], [/Hash of data verified/i, 'verifying'],
    [/Writing at|Wrote \d+ bytes/i, 'writing'], [/Flash will be erased|Erasing|Compressed \d+ bytes/i, 'preparing'],
    [/Connecting|Detecting chip|Chip is|Chip type|Uploading stub|Stub (?:flasher )?running|Changing baud/i, 'connecting']],
  build: [[/Building .*\.bin|Creating .*image/i, 'making image'], [/Checking size|Retrieving maximum/i, 'checking size'],
    [/Linking/i, 'linking'], [/Compiling|Archiving/i, 'compiling'], [/Processing|Tool Manager|Installing|Resolving/i, 'preparing']],
  detect: [[/Hard resetting|Leaving/i, 'resetting'], [/MAC:|Crystal|Features|Chip is|Chip type/i, 'reading chip'],
    [/Connecting|Detecting chip/i, 'connecting']]
}
const FLASH_PHASE_DEFAULT = { flash: 'flashing', build: 'building', detect: 'detecting' }

/** Phase word of a running job from its log tail: {word, pct (0..100|null)}; null when the job does not run. */
function flashJobPhase(job) {
  if (!job || (job.state !== 'queued' && job.state !== 'running')) return null
  const pct = typeof job.progress === 'number' && Number.isFinite(job.progress) ? Math.round(Math.max(0, Math.min(1, job.progress)) * 100) : null
  if (job.state === 'queued') return { word: 'queued', pct: null }
  const rules = FLASH_PHASES[job.kind] || []
  const tail = Array.isArray(job.log_tail) ? job.log_tail : []
  for (let i = tail.length - 1; i >= 0; i--) {
    const hit = rules.find(([re]) => re.test(String(tail[i] ?? '')))
    if (hit) return { word: hit[1], pct }
  }
  return { word: FLASH_PHASE_DEFAULT[job.kind] || 'running', pct }
}

/** Marks of the flash map: the written images (board.flash result.images: [{offset, name, sha256}]) on an address
 *  axis from 0 to just past the highest offset. Offsets and names only, no sizes. No images → null. */
function flashMapMarks(images) {
  if (!Array.isArray(images) || !images.length) return null
  const marks = images.filter(im => im && /^0x[0-9a-f]+$/i.test(String(im.offset ?? '')) && im.name)
    .map(im => ({ offset: String(im.offset).toLowerCase(), addr: parseInt(im.offset, 16), name: String(im.name), sha256: im.sha256 ? String(im.sha256) : null }))
    .sort((a, b) => a.addr - b.addr)
  if (!marks.length) return null
  const max = marks[marks.length - 1].addr
  const span = max > 0 ? max * 1.12 : 1
  return { marks: marks.map((m, i) => ({ ...m, n: i + 1, frac: Math.round((m.addr / span) * 10000) / 10000 })), highest: marks[marks.length - 1].offset }
}

// port kind (board.ports) → kind of the board's usb[] interface it arrives on
const FLASH_PORT_USB = { usb_serial_jtag: 'usb_serial_jtag', cp210x: 'usb_uart_bridge', ch340: 'usb_uart_bridge', ch343: 'usb_uart_bridge',
  ch9102: 'usb_uart_bridge', ftdi: 'usb_uart_bridge' }

/** Connector to draw beside a port (same artPort kinds as the board model): only for the real port the project's
 *  board was detected on, whose kind leads to exactly one usb[] entry of the board with a drawn usb_port. connector
 *  null in the board data → 'generic_usb' (the board model's generic jack). Anything unknown → null (nothing drawn). */
function flashPortConnector(port, layout, detectedPort) {
  if (!port || port.simulated || !detectedPort || port.device !== detectedPort) return null
  const want = FLASH_PORT_USB[port.kind]
  const usb = Array.isArray(layout?.usb) ? layout.usb.filter(u => u && u.kind === want) : []
  if (!want || usb.length !== 1) return null
  const parts = Array.isArray(layout?.drawing?.parts) ? layout.drawing.parts : []
  const part = parts.filter(p => p && p.kind === 'usb_port' && p.ref === usb[0].label)
  if (part.length !== 1) return null
  const c = part[0].connector
  return c === 'micro_usb' || c === 'usb_c' ? c : c === null || c === undefined ? 'generic_usb' : null
}

// --- lib/format.js
// Formatting helpers (units, percentages, durations, clock times). Pure, no SDK. English UI: decimal point.

const SI = [
  [1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n'], [1e-12, 'p']
]

/** 0.00253 A → "2.53 mA", 4700 Ω → "4.7 kΩ". `digits` significant digits, trailing zeros dropped. */
function formatSI(value, unit = '', digits = 3) {
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
function formatQty(q, digits = 3) {
  if (q === null || q === undefined) return '—'
  if (typeof q === 'number') return formatSI(q, '', digits)
  if (typeof q.display === 'string' && q.display) return q.display
  return formatSI(q.value, q.unit || '', digits)
}

/** 5.6 → "5.6 %" (value already in percent). */
function formatPct(pct, digits = 1) {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return '—'
  return `${Number(pct.toFixed(digits))} %`
}

/** Fraction 0..1 → "42 %". */
function formatFraction(f) {
  if (typeof f !== 'number' || !Number.isFinite(f)) return '—'
  return `${Math.round(Math.max(0, Math.min(1, f)) * 100)} %`
}

/** Seconds → "3.9 s", "42 s", "2:05 min". */
function formatDuration(s) {
  if (typeof s !== 'number' || !Number.isFinite(s) || s < 0) return '—'
  if (s < 10) return `${Number(s.toFixed(1))} s`
  if (s < 60) return `${Math.round(s)} s`
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.round(s - m * 60)).padStart(2, '0')} min`
}

/** ISO 8601 → "22:41:07" (local time, or UTC with {utc: true}). Unknown → "—". */
function formatClock(iso, { utc = false } = {}) {
  const d = new Date(iso)
  if (!iso || Number.isNaN(d.getTime())) return '—'
  const parts = utc ? [d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()] : [d.getHours(), d.getMinutes(), d.getSeconds()]
  return parts.map(n => String(n).padStart(2, '0')).join(':')
}

/** ISO 8601 → "2026-11-06 18:42" (local time). Unknown → "—". */
function formatStamp(iso) {
  const d = new Date(iso)
  if (!iso || Number.isNaN(d.getTime())) return '—'
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Long hex digest → first n characters + "…". */
function shortHash(hex, n = 8) {
  if (typeof hex !== 'string' || !hex) return '—'
  return hex.length > n ? `${hex.slice(0, n)}…` : hex
}

/** "▰▰▱▱▱" bar for done/total (max `width` cells). */
function cellBar(done, total, width = 10) {
  if (!total || total < 0) return ''
  const cells = Math.min(width, total)
  const filled = Math.round((Math.max(0, Math.min(done, total)) / total) * cells)
  return '▰'.repeat(filled) + '▱'.repeat(cells - filled)
}

/** Keep a number and its unit together: "1 kΩ" → "1\u00a0kΩ" (no line break inside a value). */
function nbspUnits(text) {
  return String(text ?? '').replace(/(\d) (?=(?:[GMkmµnp]?(?:Ω|F|A|V|W|Hz|s)|%|°C|MB|kB)(?![A-Za-z]))/g, '$1\u00a0')
}

/** Clip text to n characters with an ellipsis. */
function clip(text, n) {
  const s = String(text ?? '')
  return s.length > n ? `${s.slice(0, Math.max(0, n - 1))}…` : s
}

// --- lib/modules.js
// Module helpers: pure; top-level names mod*/MOD_* (shared lib scope)

const MOD_BASIC_CALCS = ['led', 'npn', 'divider', 'i2c_pullup', 'mosfet', 'ldo'] // modspec.BASIC_CALCS, order fixed
const MOD_FIXED_RAILS = { GND: 0, '3V3': 3.3, '5V': 5 } // modspec.FIXED_RAILS
const MOD_MAX_CONN = 48 // modspec.MAX_CONN
const MOD_OPS = ['add_module', 'connect', 'set_rails'] // modspec.MODULE_OPS
const MOD_NET_RE = /^[A-Za-z0-9_+.-]{1,32}$/
const MOD_FAMILIES = ['display', 'pixel', 'level', 'logic', 'switch', 'env', 'ambient', 'motion', 'prox', 'adc', 'powermon',
  'thermo', 'rtc', 'iox', 'motor', 'power', 'wired', 'radio', 'net'] // modspec.FAMILIES
const MOD_FAMILY_WORDS = { env: 'environment', prox: 'proximity', powermon: 'power monitor', thermo: 'temperature', iox: 'IO expander', rtc: 'RTC', adc: 'ADC' }

const modRefKey = ref => {
  const m = /^([A-Z]+)(\d+)$/.exec(String(ref || ''))
  return m ? [m[1], Number(m[2])] : [String(ref || ''), 0]
}
const modByRef = (a, b) => {
  const [pa, na] = modRefKey(a.ref)
  const [pb, nb] = modRefKey(b.ref)
  return pa < pb ? -1 : pa > pb ? 1 : na - nb
}

// parts with `module`, sorted by ref (U1, U2, … U10)
function moduleInstances(project) {
  const parts = Array.isArray(project?.parts) ? project.parts : []
  return parts.filter(p => p && typeof p.module === 'string' && p.module).map(p => ({
    ref: p.ref, module: p.module, variant: p.variant ?? null, kind: p.kind || 'module', value: p.value || p.module,
    address: p.address ?? null, conn: p.conn && typeof p.conn === 'object' ? { ...p.conn } : {},
    facts: p.facts && typeof p.facts === 'object' ? { ...p.facts } : {}, qty: p.qty ?? 1
  })).sort(modByRef)
}

// modules + plain parts (data order)
function partGroups(project) {
  const parts = Array.isArray(project?.parts) ? project.parts : []
  return { modules: moduleInstances(project), others: parts.filter(p => p && !(typeof p.module === 'string' && p.module)) }
}

// next free U<n> (upper case, like add_module)
function modNextRef(parts, prefix = 'U') {
  const used = new Set((parts || []).map(p => String(p?.ref || '').toUpperCase()))
  let n = 1
  while (used.has(`${prefix}${n}`)) n++
  return `${prefix}${n}`
}

// "U1 BME280 · I²C 0x76"
function modInstanceLabel(inst, info = null) {
  if (!inst) return ''
  const name = info?.short || inst.value || info?.title || inst.module
  const ifs = modInterfaces(info?.interfaces)
  const bus = ifs.length ? ifs[0] : null
  const addr = inst.address ? modAddress(inst.address) : null
  return [`${inst.ref} ${name}`, [bus, addr].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
}

const MOD_SI = [[1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n']]

function modSI(value, unit, digits = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (value === 0) return `0 ${unit}`
  const abs = Math.abs(value)
  let [scale, prefix] = MOD_SI[MOD_SI.length - 1]
  for (const [s, p] of MOD_SI) if (abs >= s * 0.9995) { scale = s; prefix = p; break }
  return `${Number((value / scale).toPrecision(digits))} ${prefix}${unit}`
}

const modNum = x => (typeof x === 'number' ? x : x && typeof x === 'object' && typeof x.value === 'number' ? x.value : null)

const modVolts = v => modSI(modNum(v), 'V')
const modAmps = a => modSI(modNum(a), 'A')

function modAddress(a) {
  if (typeof a === 'number' && Number.isInteger(a) && a >= 0 && a < 128) return `0x${a.toString(16).padStart(2, '0')}`
  const s = String(a ?? '').trim()
  return /^0x[0-9a-f]{1,2}$/i.test(s) ? `0x${s.slice(2).toLowerCase().padStart(2, '0')}` : s
}

function modAddresses(list, chosen = null) {
  const raw = Array.isArray(list) ? list : Array.isArray(list?.value) ? list.value : list == null ? [] : [list]
  const want = chosen == null ? null : modAddress(chosen)
  return raw.map(modAddress).filter(Boolean).map(a => (a === want ? `•${a}` : a)).join(' / ')
}

// "1.71–3.6 V" / "VDD 1.71–3.6 V · …"
function modSupply(s) {
  if (s == null) return '—'
  if (typeof s === 'string') return s || '—'
  if (typeof s === 'number') return modVolts(s)
  if (typeof s !== 'object') return '—'
  const range = r => {
    const [lo, hi, typ] = [r?.min, r?.max, r?.typ].map(modNum)
    if (lo !== null && hi !== null) {
      const [a, b] = [modVolts(lo), modVolts(hi)].map(x => x.split(' '))
      return `${a[1] === b[1] ? a[0] : a.join(' ')}–${b.join(' ')}`
    }
    return typ !== null ? modVolts(typ) : hi !== null ? `≤ ${modVolts(hi)}` : lo !== null ? `≥ ${modVolts(lo)}` : null
  }
  if ('min' in s || 'max' in s || 'typ' in s) return range(s) || '—'
  const parts = Object.entries(s).map(([pin, r]) => { const t = range(r); return t ? `${pin} ${t}` : null }).filter(Boolean)
  return parts.length ? parts.join(' · ') : '—'
}

const MOD_INTERFACE_LABELS = { i2c: 'I²C', spi: 'SPI', uart: 'UART', onewire: '1-Wire', i2s: 'I²S', analog: 'analog',
  digital: 'digital', pwm: 'PWM', led_serial: 'LED serial', parallel: 'parallel' }

const modInterfaceLabel = t => MOD_INTERFACE_LABELS[t] || String(t || '')

function modInterfaces(list) {
  const out = []
  for (const x of Array.isArray(list) ? list : []) {
    const l = modInterfaceLabel(typeof x === 'string' ? x : x?.type)
    if (l && !out.includes(l)) out.push(l)
  }
  return out
}

// findings: words of the generic rules
const MOD_WARNING_WORDS = {
  mod_address_conflict: 'address conflict', mod_address_reserved: 'reserved address', mod_address_select: 'address select',
  mod_bus_speed: 'bus speed', mod_pin_role: 'pin role', mod_spi_cs: 'shared CS', mod_unconnected: 'not connected',
  mod_supply_range: 'supply range', mod_level_in: 'input level', mod_level_out: 'output level',
  mod_power_budget: 'power budget', mod_required_parts: 'required part', mod_hazard: 'hazard', mod_unknown: 'unknown module',
  mod_net_shared_signals: 'shared bus net', mod_pullup_parallel: 'parallel pull-ups'
}

const MOD_SEVERITY_LOOK = {
  danger: { symbol: '⊗', tone: 'bad', level: 'danger' },
  caution: { symbol: '◇', tone: 'warn', level: 'caution' },
  info: { symbol: 'i', tone: 'dim', level: 'note' }
}

const MOD_UP = /^([a-z]+\d[a-z0-9]*|bm[ep]|vi[hl]|sdo|sd[ai]|scl|cs|rw|gnd|oled|xshut|int)$/
// modules.env.bmp_vs_bme / mod_env_bmp_vs_bme → "BMP vs BME (environment)"
function modWarningWord(code) {
  const rest = String(code || '').replace(/^mod(ules)?[._]/, '').replace(/\./g, '_')
  if (MOD_WARNING_WORDS[`mod_${rest}`]) return MOD_WARNING_WORDS[`mod_${rest}`]
  const fam = MOD_FAMILIES.find(f => rest.startsWith(`${f}_`))
  const w = (fam ? rest.slice(fam.length + 1) : rest).split('_').filter(Boolean).map(t => (MOD_UP.test(t) ? t.toUpperCase() : t)).join(' ')
  return w ? (fam ? `${w} (${MOD_FAMILY_WORDS[fam] || fam})` : w) : 'module finding'
}

// one finding of a level → its word in HUD/rail ("1 address conflict" instead of "1 module caution")
const modShortWord = c => { const w = c ? modWarningWord(c) : ''; return w && w.length <= 16 ? w : null } // HUD room
const modCountWords = m => ({ ...m, dangerWord: modShortWord(m.dangerCode), cautionWord: modShortWord(m.cautionCode) })

function modWarningMeta(w) {
  const look = MOD_SEVERITY_LOOK[w?.severity] || MOD_SEVERITY_LOOK.info
  return { ...look, severity: MOD_SEVERITY_LOOK[w?.severity] ? w.severity : 'info', word: modWarningWord(w?.code) }
}

function modStatusMeta(status) {
  switch (status) {
    case 'passed': case 'pass': return { symbol: '✓', word: 'ok', tone: 'ok' }
    case 'failed': case 'fail': return { symbol: '✕', word: 'failed', tone: 'bad' }
    case 'warn': return { symbol: '◇', word: 'caution', tone: 'warn' }
    case 'skipped': return { symbol: '○', word: 'skipped', tone: 'dim' }
    default: return { symbol: '?', word: 'not checked', tone: 'dim' }
  }
}

function modulesResult(env) {
  const m = env && env.ok ? env.result?.modules : null
  return m && typeof m === 'object' ? m : null
}

// warnings mod_* (danger first), checks modules.* (compact check 'modules' "failed: a, b; …" split per rule)
function modFindings(env) {
  if (!env || !env.ok) return { warnings: [], checks: [] }
  const rank = { danger: 0, caution: 1, info: 2 }
  const warnings = (Array.isArray(env.warnings) ? env.warnings : [])
    .map((w, i) => ({ w, i })).filter(({ w }) => w && String(w.code || '').startsWith('mod_'))
    .sort((a, b) => (rank[a.w.severity] ?? 3) - (rank[b.w.severity] ?? 3) || a.i - b.i)
    .map(({ w }) => ({ ...w, ...modWarningMeta(w) }))
  const checks = (Array.isArray(env.checks) ? env.checks : []).flatMap(c => (c?.id === 'modules'
    ? String(c.detail || '').split('; ').flatMap(g => { const [st, ids] = g.split(': '); return ids ? ids.split(', ').map(id => ({ id: `modules.${id}`, status: st.replace(' ', '_') })) : [] })
    : String(c?.id || '').startsWith('modules.') ? [c] : [])).map(c => ({ ...c, ...modStatusMeta(c.status) }))
  return { warnings, checks }
}

// rails with texts, load fraction (null without a limit)
function modRails(env) {
  const m = modulesResult(env)
  return (Array.isArray(m?.rails) ? m.rails : []).map(r => {
    const limit = modNum(r.limit)
    const peak = modNum(r.i_peak) ?? modNum(r.i_max) ?? modNum(r.i_typ)
    return { net: r.net, volts: modVolts(r.volts), typ: modAmps(r.i_typ), max: modAmps(r.i_max), peak: modAmps(r.i_peak),
      limit: limit === null ? null : modAmps(limit), limitSource: r.limit_source ?? null,
      frac: limit && peak !== null ? Math.max(0, peak / limit) : null }
  })
}

// project ops (PATCH /projects/{id})
const modDefined = o => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined))

function addModuleOp({ module, variant, ref, conn, address, facts, qty } = {}) {
  if (typeof module !== 'string' || !module.trim()) throw new Error('add_module needs a module id')
  return modDefined({ op: 'add_module', module: module.trim(), variant: variant || undefined, ref: ref ? String(ref).trim().toUpperCase() : undefined,
    conn: conn && Object.keys(conn).length ? { ...conn } : undefined, address: address ? modAddress(address) : undefined,
    facts: facts && Object.keys(facts).length ? { ...facts } : undefined, qty: qty === undefined || qty === null ? undefined : Number(qty) })
}

// connect merges; null disconnects
function connectOp(ref, conn) {
  if (!ref) throw new Error('connect needs a ref')
  if (!conn || typeof conn !== 'object' || !Object.keys(conn).length) throw new Error('connect needs at least one pin')
  return { op: 'connect', ref: String(ref).trim().toUpperCase(), conn: { ...conn } }
}

function setRailsOp({ rails, rail_limits: limits } = {}) {
  if (!rails && !limits) throw new Error('set_rails needs rails or rail_limits')
  return modDefined({ op: 'set_rails', rails: rails ? { ...rails } : undefined, rail_limits: limits ? { ...limits } : undefined })
}

// conn problems
function modConnProblems(conn) {
  const out = []
  const entries = Object.entries(conn || {})
  if (entries.length > MOD_MAX_CONN) out.push(`at most ${MOD_MAX_CONN} pins per part`)
  for (const [pin, net] of entries) if (net !== null && !MOD_NET_RE.test(String(net))) out.push(`${pin}: net name ${JSON.stringify(net)} not allowed`)
  return out
}

function modCheckExtras(project) {
  if (!moduleInstances(project).length) return {}
  return { parts: JSON.parse(JSON.stringify(project.parts)), options: JSON.parse(JSON.stringify(project.options || {})) }
}

const MOD_CALC_META_FIELDS = ['calculators', 'calcs', 'items']

// GET /calc → [{kind, title, group, summary, params, basic}]
function calcMetaOf(env) {
  if (!env || !env.ok || !env.result || typeof env.result !== 'object') return []
  const field = MOD_CALC_META_FIELDS.find(f => Array.isArray(env.result[f]))
  const raw = field ? env.result[field] : Array.isArray(env.result) ? env.result : []
  const list = raw.map(c => [c, c?.kind ?? c?.type ?? c?.id]).filter(([, k]) => typeof k === 'string').map(([c, kind]) => ({
    kind, title: c.title || kind, group: c.group || 'basics', summary: c.summary || '',
    params: (Array.isArray(c.params) ? c.params : []).map(p => (typeof p === 'string' ? { name: p, unit: '', required: false, default: null }
      : { name: p.name, unit: p.unit ?? '', required: Boolean(p.required), default: p.default ?? null })),
    basic: MOD_BASIC_CALCS.includes(kind)
  }))
  const basic = MOD_BASIC_CALCS.map(k => list.find(c => c.kind === k)).filter(Boolean)
  return [...basic, ...list.filter(c => !c.basic)]
}

// categories: result.categories or of the loaded items, + extras
const modCategories = (res, ...extra) => [...new Set([...(Array.isArray(res?.categories) ? res.categories : (res?.items || []).map(m => m.category)), ...extra].filter(Boolean))].sort()

// counts.hidden ("mod_bus_speed U2,U3") → "bus speed U2 U3"
const modHidden = list => (Array.isArray(list) ? list : []).map(x => { const [c, r] = String(x).split(' '); return [modWarningWord(c), (r || '').replace(/,/g, ' ')].join(' ').trim() })

const modCategoryLabel = c => String(c || '').replace('.', ' · ').replace(/_/g, ' ')

// modspec.SIGNAL_MODES (first = assign preset)
const MOD_SIGNAL_MODES = {
  i2c_sda: ['i2c_sda'], i2c_scl: ['i2c_scl'], spi_sck: ['spi_sck'], spi_cs: ['spi_cs', 'out'], spi_sdi: ['spi_mosi'],
  spi_sdo: ['spi_miso'], uart_rx: ['uart_tx'], uart_tx: ['uart_rx'], onewire: ['out', 'in_pullup', 'in'], i2s_bclk: ['out'],
  i2s_ws: ['out'], i2s_din: ['out'], i2s_dout: ['in'], digital_in: ['out', 'pwm', 'spi_mosi', 'spi_sck', 'spi_cs'], pwm_in: ['pwm', 'out'],
  led_data_in: ['out', 'pwm', 'spi_mosi'], reset_in: ['out'], enable_in: ['out'], digital_out: ['in', 'in_pullup', 'in_pulldown', 'spi_miso'],
  open_drain_out: ['in', 'in_pullup', 'in_pulldown'], analog_out: ['adc']
}
// bus lines [role, net]; more devices join the net
const MOD_BUS_LINES = { i2c_sda: ['SDA', 'SDA0'], i2c_scl: ['SCL', 'SCL0'], spi_sck: ['SCK', 'SCK0'], spi_sdi: ['MOSI', 'MOSI0'], spi_sdo: ['MISO', 'MISO0'] }

const modAssignNet = a => a?.net || (Number.isInteger(a?.pin) ? `GPIO${a.pin}` : null)
const modFixed = n => Object.hasOwn(MOD_FIXED_RAILS, n)
const modKeep = t => String(t ?? '').replace(/(\d) (?=[GMkmµnp]?(?:Ω|F|A|V|W|Hz)(?![A-Za-z]))/g, '$1\u00a0')

// ESP-facing pins (tied only when wired): linked | bus (connect) | open (assign)
function modPinLinks(inst, info, assignments = []) {
  const list = Array.isArray(assignments) ? assignments : []
  return (Array.isArray(info?.pins) ? info.pins : []).filter(p => MOD_SIGNAL_MODES[p.signal] && !(p.tie && !inst?.conn?.[p.name])).map(p => {
    const modes = MOD_SIGNAL_MODES[p.signal]
    const net = inst?.conn?.[p.name] ?? null
    const a = net ? list.find(x => modAssignNet(x) === net || net === `GPIO${x.pin}`) || null : null
    const bus = !net && MOD_BUS_LINES[p.signal] ? list.find(x => modes.includes(x.mode)) || null : null
    return { pin: p.name, signal: p.signal, mode: modes[0], net, assignment: a, bus, must: Boolean(p.must_connect), optional: !p.must_connect && !MOD_BUS_LINES[p.signal],
      state: a ? 'linked' : bus ? 'bus' : 'open' }
  })
}

// assign preset for an open module pin
function modAssignInit(inst, link, assignments = []) {
  const taken = new Set((assignments || []).map(a => a.role))
  const own = `${inst.ref}_${link.pin}`.toUpperCase().replace(/[^A-Z0-9_]/g, '_').slice(0, 24)
  const line = MOD_BUS_LINES[link.signal]
  const role = line && !taken.has(line[0]) ? line[0] : own
  const net = link.net && !modFixed(link.net) && !/^GPIO\d+$/.test(link.net) ? link.net : line && !taken.has(line[0]) ? line[1] : own
  return { role, mode: link.mode, pin: null, net, link: { ref: inst.ref, pin: link.pin } }
}

// proposed conn: bus nets, a fixed rail in the supply range, GND, address select; not tied pins
function modSuggestConn(info, assignments = [], address = null) {
  const pins = Array.isArray(info?.pins) ? info.pins : []
  const conn = {}
  const inRange = (pin, v) => {
    const s = info?.supplies?.[pin]
    const lo = modNum(s?.min)
    const hi = modNum(s?.max)
    return lo !== null && hi !== null && v >= lo && v <= hi
  }
  for (const p of pins) {
    if (p.tie) continue
    if (MOD_BUS_LINES[p.signal]) {
      const a = (assignments || []).find(x => MOD_SIGNAL_MODES[p.signal].includes(x.mode))
      if (a) conn[p.name] = modAssignNet(a)
    } else if (p.signal === 'gnd') conn[p.name] = 'GND'
    else if (p.signal === 'supply') {
      const rail = ['3V3', '5V'].find(r => inRange(p.name, MOD_FIXED_RAILS[r]))
      if (rail) conn[p.name] = rail
    }
  }
  const netOf = (name, depth = 0) => {
    if (modFixed(name)) return name
    if (conn[name]) return conn[name]
    const t = pins.find(x => x.name === name)?.tie
    return t && depth < 4 ? netOf(t, depth + 1) : null
  }
  for (const i of Array.isArray(info?.interfaces) ? info.interfaces : []) {
    const sel = i?.select
    const want = modAddress(address ?? i.default ?? '')
    if (!sel?.pin || !sel.map || !want) continue
    const key = Object.keys(sel.map).find(k => modAddress(sel.map[k]) === want)
    const net = key ? netOf(key) : null
    if (net) conn[sel.pin] = net
  }
  return conn
}

function modAddressChoices(info) {
  const i = (Array.isArray(info?.interfaces) ? info.interfaces : []).find(x => x?.addresses)
  if (!i) return { list: [], def: null }
  const raw = Array.isArray(i.addresses) ? i.addresses : Array.isArray(i.addresses?.value) ? i.addresses.value : []
  return { list: raw.map(modAddress), def: i.default ? modAddress(i.default) : null, page: i.addresses?.page ?? null }
}

// worst warning per ref
function modRefFindings(warnings) {
  const out = {}
  for (const w of warnings || []) for (const r of Array.isArray(w.refs) ? w.refs : []) if (!out[r]) out[r] = w
  return out
}

function modFText(f) {
  if (f == null) return '—'
  if (typeof f !== 'object') return typeof f === 'boolean' ? (f ? 'yes' : 'no') : String(f)
  if (typeof f.value === 'number') return modSI(f.value, f.unit || '')
  if (typeof f.value === 'boolean') return f.value ? 'yes' : 'no'
  if (typeof f.rel === 'number') return `${f.rel} × ${f.of || '?'}`
  if (typeof f.rel_offset === 'number') return `${f.of || '?'} ${f.rel_offset < 0 ? '−' : '+'} ${Math.abs(f.rel_offset)} ${f.unit || 'V'}`
  return f.value != null ? String(f.value) : '—'
}

function modEvidence(f) {
  if (!f || typeof f !== 'object') return ''
  const ev = Array.isArray(f.evidence) ? f.evidence.join(' … ') : f.evidence || ''
  return [f.page != null ? `p. ${f.page}` : '', ev ? `“${ev}”` : '', f.conditions || ''].filter(Boolean).join(' · ')
}

// required part → calc kind | null
function modRequireCalc(req, info) {
  const code = String(req?.code || '')
  const sig = new Set((Array.isArray(req?.pins) ? req.pins : []).map(n => (info?.pins || []).find(p => p.name === n)?.signal))
  if (/pull_?up/.test(code) && (sig.has('i2c_sda') || sig.has('i2c_scl'))) return 'i2c_pullup'
  if (/divider/.test(code)) return 'divider'
  if (/ldo|regulator/.test(code)) return 'ldo'
  return null
}

function modRequireText(r) {
  return [r?.code, [r?.value, r?.kind].filter(Boolean).join(' '), [(r?.pins || []).join(', '), r?.to].filter(Boolean).join(' → ')]
    .filter(Boolean).join(' · ')
}

// --- lib/pins.js
// Pin presentation: verdict → class/symbol/text, header-pin view state, assignment merge, modes, chips.
// Pure, no SDK. The rules themselves live in the backend (bench_core.pins); this file only maps their output to
// what the Bench shows. Colour is never the only carrier: every state also has a symbol and a word.

/** PLAN toolbar chips and variants; mirrors data/pins/*.json `variants` and data/boards (tests-js keep them in sync).
 *  `devkit`: the chip's default layout; last variant = chip default; `module`: variant is a whole module. */
const CHIPS = [
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
const DEVKITS = [
  { id: 'esp32-devkitc-v4', chip: 'esp32', label: 'DevKitC V4', title: 'ESP32-DevKitC', revision: 'V4', module: 'ESP32-WROOM-32E', variant: 'wroom-32e' },
  { id: 'wt32-eth01', chip: 'esp32', label: 'WT32-ETH01', title: 'WT32-ETH01', revision: 'V1.4', module: 'WT32-S1', variant: null },
  { id: 'esp32-s2-devkitc-1', chip: 'esp32s2', label: 'S2-DevKitC-1', title: 'ESP32-S2-DevKitC-1', revision: 'v1', module: 'ESP32-S2-SOLO-2', variant: null },
  { id: 'esp32-s3-devkitc-1', chip: 'esp32s3', label: 'S3-DevKitC-1', title: 'ESP32-S3-DevKitC-1', revision: 'v1.1', module: null, variant: null },
  { id: 'esp32-c3-devkitm-1', chip: 'esp32c3', label: 'C3-DevKitM-1', title: 'ESP32-C3-DevKitM-1', revision: 'v1', module: 'ESP32-C3-MINI-1', variant: null },
  { id: 'esp32-c6-devkitc-1', chip: 'esp32c6', label: 'C6-DevKitC-1', title: 'ESP32-C6-DevKitC-1', revision: 'v1.2', module: 'ESP32-C6-WROOM-1', variant: 'wroom-1' },
  { id: 'esp32-c6-devkitm-1', chip: 'esp32c6', label: 'C6-DevKitM-1', title: 'ESP32-C6-DevKitM-1', revision: 'v1', module: 'ESP32-C6-MINI-1', variant: 'mini-1' }
]

function devkitInfo(id) {
  return DEVKITS.find(d => d.id === id) || null
}

/** DevKit layouts of one chip (data order). */
function devkitsOf(chip) {
  return DEVKITS.filter(d => d.chip === chip)
}

/** The DevKit the board view shows: `devkit` when it belongs to `chip`, else the chip's default DevKit (or null). */
function resolveDevkit(chip, devkit) {
  return devkitInfo(devkit)?.chip === chip ? devkit : chipInfo(chip)?.devkit ?? null
}

/** Variant to preselect: the layout's module.variant; null if the module variant is unknown; else the chip default. */
function defaultVariant(chip, devkit = null) {
  const c = chipInfo(chip)
  if (!c?.variants.length) return null
  const d = devkitInfo(devkit)
  if (d && d.chip === chip && d.module) return c.variants.some(v => v.id === d.variant) ? d.variant : null
  return c.variants[c.variants.length - 1].id
}

/** "ESP32-DevKitC V4" */
function devkitTitle(d) {
  return d ? `${d.title}${d.revision ? ` ${d.revision}` : ''}` : ''
}

const stripFamily = s => String(s).replace(/^ESP32-/, '')

/** Module drawing from GET /boards/{id}: name without "ESP32-", flash, antenna, buttons (nothing invented). */
function boardModule(layout, variant) {
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
function boardPorts(layout) {
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
const DRAWING_KINDS = ['usb_port', 'button', 'led', 'power_led', 'ldo', 'bridge_ic', 'rj45', 'phy_ic', 'antenna_connector']
const DRAWING_ZONES = ['below_module', 'middle', 'lower']
const DRAWING_SIDES = ['left', 'center', 'right']

const buttonLabel = b => (/^reset$/i.test(String(b)) ? 'RST' : String(b).toUpperCase())
const gpioList = gpios => (Array.isArray(gpios) && gpios.length ? `IO${gpios.join('/')}` : '')

/** Board-model parts: from `drawing` where quoted, else generic with `schematic: true` (nothing invented).
 *  → { parts: [{ kind, label, sub, gpio, connector, place, schematic, live? }], drawing } */
function boardParts(layout) {
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
const PIN_ART_STATE = {
  free: 'free', used: 'assigned', 'used-warn': 'caution', 'used-bad': 'assigned_blocked', warn: 'caution', bad: 'blocked',
  power: 'power', ground: 'ground', reset: 'ground', nc: 'nc', signal: 'signal', unchecked: null
}

/** Word of a pinView state for aria-label and title (ring + symbol + word). */
function pinStateWord(state) {
  return {
    free: 'free', used: 'assigned', 'used-warn': 'assigned · caution', 'used-bad': 'assigned · blocked', warn: 'caution', bad: 'blocked',
    power: 'power', ground: 'ground', reset: 'reset', nc: 'not connected', signal: 'board signal'
  }[state] || 'not checked'
}

/** Reservation of a header pin for the bracket on the strip: octal PSRAM (from the module variant), else the main
 *  reason of the map entry when it is a PSRAM, flash or USB rule. → label or null. */
function pinReserve(hp, base, octal) {
  if (octal && Number.isInteger(hp?.gpio) && hp.gpio >= 33 && hp.gpio <= 37) return 'OCTAL PSRAM'
  const r = mainReason(base)
  if (!r || (r.severity !== 'blocked' && r.severity !== 'caution')) return null
  const tag = ruleTag(r.rule_id)
  return tag === 'PSRAM' ? 'PSRAM' : tag === 'FLASH' ? 'SPI FLASH' : tag === 'USB' ? 'USB' : null
}

/** Brackets of one side: runs of ≥ 2 neighbouring pins (no separator between them) with the same reservation.
 *  items: [{ slot, reserve, tone }] in slot order → [{ from, to, label, tone }] (tone 'bad' when a pin is blocked). */
function boardBrackets(items) {
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
function boardArtModel({ layout, chip = null, variant = null, base = new Map(), used = new Map(), selected = null, suggest = [], live = [], rev = null } = {}) {
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
function warningMeta(severity) {
  switch (severity) {
    case 'danger': return { tone: 'bad', symbol: '⚠', word: 'DANGER' }
    case 'caution': return { tone: 'warn', symbol: '!', word: 'CAUTION' }
    default: return { tone: 'dim', symbol: 'i', word: 'NOTE' }
  }
}

/** `layout.warnings` sorted danger > caution > info, each with its meta. */
function boardWarnings(layout) {
  const order = { danger: 0, caution: 1, info: 2 }
  return (Array.isArray(layout?.warnings) ? layout.warnings : [])
    .filter(w => w && w.message)
    .map((w, i) => ({ id: w.id || `w${i}`, severity: w.severity, message: String(w.message), source_id: w.source_id || null, ...warningMeta(w.severity), i }))
    .sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3) || a.i - b.i)
    .map(({ i, ...w }) => w)
}

/** Variants grouped by PSRAM kind for the module choice (none, SPI, quad, octal; only non-empty groups, data order). */
function variantGroups(chip) {
  const c = chipInfo(chip)
  const groups = [[null, 'no PSRAM'], ['spi', 'PSRAM'], ['quad', 'quad PSRAM'], ['octal', 'octal PSRAM']]
  return groups.map(([psram, label]) => ({ psram, label, variants: (c?.variants || []).filter(v => (v.psram ?? null) === psram) }))
    .filter(g => g.variants.length)
}

const MODES = [
  ['out', 'out'], ['in', 'in'], ['in_pullup', 'in · pull-up'], ['in_pulldown', 'in · pull-down'], ['adc', 'adc'],
  ['pwm', 'pwm'], ['i2c_sda', 'i²c sda'], ['i2c_scl', 'i²c scl'], ['spi_sck', 'spi sck'], ['spi_mosi', 'spi mosi'],
  ['spi_miso', 'spi miso'], ['spi_cs', 'spi cs'], ['uart_tx', 'uart tx'], ['uart_rx', 'uart rx'], ['touch', 'touch']
]
const MODE_LABEL = Object.fromEntries(MODES)

const ROLE_RE = /^[A-Z0-9_]{1,24}$/
const NET_RE = /^[A-Za-z0-9_+\-./]{1,32}$/

function chipInfo(id) {
  return CHIPS.find(c => c.id === id) || null
}

function variantInfo(chip, variant) {
  return chipInfo(chip)?.variants.find(v => v.id === variant) || null
}

/** Toolbar title of a module variant: "8 MB flash, 8 MB PSRAM (octal)", "4 MB flash, no PSRAM". */
function variantTitle(v) {
  if (!v) return ''
  const psram = v.psram ? `${v.psram_mb ? `${v.psram_mb} MB ` : ''}PSRAM${['quad', 'octal'].includes(v.psram) ? ` (${v.psram})` : ''}` : 'no PSRAM'
  return `${v.flash_mb ? `${v.flash_mb} MB flash` : v.module || v.label}, ${psram}`
}

function modeLabel(mode) {
  return MODE_LABEL[mode] || String(mode || '—')
}

/** Mode as one word of at most 8 characters for the inspector's assignments column (64 px at 11 px): the input
 *  modes with a pull resistor as the Arduino word (INPUT_PULLUP → "pullup"), every other label already fits;
 *  modeLabel() stays the title and the screen-reader text. */
const MODE_SHORT = { in_pullup: 'pullup', in_pulldown: 'pulldown' }
function modeShort(mode) {
  return MODE_SHORT[mode] || modeLabel(mode)
}

function gpioName(n) {
  return Number.isInteger(n) ? `GPIO${n}` : '—'
}

/** Verdict → class suffix, symbol, word. Unknown verdicts read as "not checked", never as ok. */
function verdictMeta(verdict) {
  switch (verdict) {
    case 'ok': return { tone: 'ok', symbol: '✓', text: 'ok', stamp: 'OK' }
    case 'caution': return { tone: 'warn', symbol: '!', text: 'caution', stamp: 'CAUTION' }
    case 'blocked': return { tone: 'bad', symbol: '✕', text: 'blocked', stamp: 'BLOCKED' }
    default: return { tone: 'none', symbol: '?', text: 'not checked', stamp: 'UNCHECKED' }
  }
}

/** "J3-13" → {header: "J3", n: 13}. */
function splitHeader(h) {
  const m = /^([A-Z]+\d*)-(\d+)$/.exec(String(h || ''))
  return m ? { header: m[1], n: Number(m[2]) } : null
}

/** Short tag for a rule id on the board (the full message stays in the inspector). */
const RULE_TAGS = {
  strapping: 'STRAP', octal_psram: 'PSRAM', psram_16_17: 'PSRAM', spi_flash: 'FLASH', usb_jtag: 'USB', uart0: 'UART0', pad_jtag: 'JTAG',
  jtag: 'JTAG', adc2_wifi: 'ADC2', input_only: 'IN ONLY', no_pulls: 'NO PULL', gpio36_39_irq: 'IRQ', onboard: 'ON-BOARD'
}

function ruleTag(ruleId) {
  const key = String(ruleId || '').split('.').pop()
  return RULE_TAGS[key] || key.toUpperCase().slice(0, 8)
}

/** Highest-severity reason of a check/map entry (blocked > caution > info). */
function mainReason(entry) {
  const order = { blocked: 0, caution: 1, info: 2 }
  const rs = Array.isArray(entry?.reasons) ? [...entry.reasons] : []
  rs.sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3))
  return rs[0] || null
}

/**
 * Project assignments merged with a pins.check result. A check entry only counts when role, pin and mode match
 * (a stale or foreign check never overrides the project); otherwise the verdict stored in the project is used.
 */
function mergeAssignments(assignments, checkPins) {
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

function countVerdicts(rows) {
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
function mapByGpio(mapResult) {
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
function pinView(hp, used, base, onboard) {
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
function clipTag(what) {
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
function validateAssign({ role, mode, pin, net }) {
  const errors = []
  if (!ROLE_RE.test(String(role || ''))) errors.push({ field: 'role', message: 'Role: A–Z, 0–9 and _ only, 1–24 characters.' })
  if (!MODE_LABEL[mode]) errors.push({ field: 'mode', message: 'Choose a mode.' })
  if (!Number.isInteger(pin) || pin < 0 || pin > 48) errors.push({ field: 'pin', message: 'GPIO number 0–48.' })
  if (net && !NET_RE.test(String(net))) errors.push({ field: 'net', message: 'Net: letters, digits and _ + - . / only, up to 32.' })
  return errors
}

/** Board pins of a layout as rows for the two sides (left J1/J2, right J3; WT32: PROG + IO on both sides). */
function headerRows(layout) {
  return { left: Array.isArray(layout?.left) ? layout.left : [], right: Array.isArray(layout?.right) ? layout.right : [] }
}

/** Header ids of one side in order, each once (WT32 left: ["PROG", "IO"]). */
function headerIds(rows) {
  return [...new Set((rows || []).map(p => p.header).filter(Boolean))]
}

/** All GPIOs broken out on the headers (for the full-board map check). */
function headerGpios(layout) {
  const { left, right } = headerRows(layout)
  return [...left, ...right].filter(p => p.kind === 'gpio' && Number.isInteger(p.gpio)).map(p => p.gpio)
}

/** Pseudo assignments for the board map: every header GPIO in mode "in" (role IO<n>). */
function mapAssignments(layout) {
  return headerGpios(layout).map(g => ({ role: `IO${g}`, mode: 'in', pin: g }))
}

/** Chips for suggestions: [{gpio, header}] minus taken pins. */
function suggestionChips(suggestResult, role) {
  const req = (suggestResult?.requests || []).find(r => !role || r.role === role)
  return req ? (req.suggestions || []).map(s => ({ gpio: s.gpio, header: s.header || null })) : []
}

/** One finding for the "Ask Hermes" draft: "BUTTON on GPIO35 is blocked — Wired to …" (no outer brackets). */
function findingText(row) {
  const msg = String(row?.reasons?.[0]?.message || '').trim().replace(/[.\s]+$/, '')
  return `${row?.role} on GPIO${row?.pin} is ${row?.verdict}${msg ? ` — ${msg}` : ''}`
}

// --- lib/seq.js
// Serial line buffer: seq-based merge, duplicates dropped, gaps marked, epoch reset. Pure.
// Messages: {t: "line", seq, ts, text} | {t: "panic", seq, summary, log_ref} | {t: "state", port, state, epoch?}.
// seq rises monotonically per port and epoch. A new epoch (backend restart) starts seq at 1 again.

const LINE_LIMIT = 2000

function emptyBuffer() {
  return { epoch: null, lastSeq: 0, lines: [], panic: null, state: null, dropped: 0 }
}

/**
 * Merge messages into a buffer (returns a new buffer; the input is not changed).
 * opts.epoch   epoch of a polling batch (GET /serial/tail); stream messages carry it in `state`.
 * opts.limit   max kept entries (oldest dropped first).
 * Entries in `lines`: {k: "line", seq, ts, text} | {k: "gap", from, to} | {k: "epoch", epoch}.
 */
function mergeLines(buf, msgs, opts = {}) {
  const limit = opts.limit ?? LINE_LIMIT
  const out = { ...buf, lines: buf.lines.slice() }
  const switchEpoch = epoch => {
    if (epoch === undefined || epoch === null || epoch === out.epoch) return
    if (out.epoch !== null) out.lines.push({ k: 'epoch', epoch })
    out.epoch = epoch
    out.lastSeq = 0
  }
  switchEpoch(opts.epoch)
  for (const m of Array.isArray(msgs) ? msgs : [msgs]) {
    if (!m || typeof m !== 'object') continue
    if (m.t === 'state') {
      switchEpoch(m.epoch)
      out.state = { port: m.port ?? null, state: m.state ?? null, detail: m.detail ?? null }
      continue
    }
    if (!Number.isInteger(m.seq) || m.seq < 1) continue
    if (m.t === 'panic') {
      out.panic = { seq: m.seq, summary: m.summary ?? '', log_ref: m.log_ref ?? null }
      continue
    }
    if (m.t !== 'line') continue
    if (m.seq <= out.lastSeq) { out.dropped++; continue }
    if (out.lastSeq > 0 && m.seq > out.lastSeq + 1) out.lines.push({ k: 'gap', from: out.lastSeq + 1, to: m.seq - 1 })
    out.lines.push({ k: 'line', seq: m.seq, ts: m.ts ?? '', text: String(m.text ?? '') })
    out.lastSeq = m.seq
  }
  if (out.lines.length > limit) out.lines = out.lines.slice(out.lines.length - limit)
  return out
}

/** Gaps (missed seq ranges) in a buffer. */
function gapsOf(buf) {
  return buf.lines.filter(l => l.k === 'gap').map(l => ({ from: l.from, to: l.to }))
}

/** Highlight class for a log line: panic | bt (backtrace/registers) | hl (boot banner) | rom | ''. */
function lineClass(text) {
  const s = String(text || '')
  if (/Guru Meditation|panic'ed|abort\(\) was called|Brownout detector|assert failed|Stack smashing/i.test(s)) return 'panic'
  if (/^\s*(Backtrace:|PC\s*:|EXCVADDR|EXCCAUSE|Core\s+\d+ register dump|A\d+\s*:|ELF file SHA256)/.test(s)) return 'bt'
  if (/^(ESP-ROM:|rst:0x|boot:0x|load:0x|entry 0x|mode:|SPIWP:|clk_drv|Saved PC:)/.test(s)) return 'rom'
  if (/\bboot\b.*\b(ok|ready|laser off)\b|^\[[a-z0-9-]+\]/i.test(s)) return 'hl'
  return ''
}

/** Plain-text log (for copy): "ts text" per line, gaps as markers. */
function bufferText(buf) {
  return buf.lines.map(l => (l.k === 'line' ? `${l.ts ? `${l.ts} ` : ''}${l.text}` : l.k === 'gap'
    ? `… ${l.to - l.from + 1} line(s) missed (seq ${l.from}–${l.to}) …` : `— backend restarted (epoch ${l.epoch}) —`)).join('\n')
}

/**
 * Display model of a log: runs of blank lines fold into one (the copy text keeps them), and every panic —
 * from its "Guru Meditation…"/abort line to "Rebooting..." (or the next boot banner, or the end) — becomes one
 * block. → [{k: 'line'|'gap'|'epoch', …} | {k: 'panic', seq, lines: [...]}]
 */
function logView(lines) {
  const out = []
  let block = null
  let blank = false
  for (const l of lines || []) {
    if (l.k !== 'line') {
      block = null
      blank = false
      out.push(l)
      continue
    }
    const empty = !String(l.text || '').trim()
    if (empty && blank) continue
    blank = empty
    if (!empty && lineClass(l.text) === 'panic' && /Guru Meditation|panic'ed|abort\(\) was called|Stack smashing|assert failed/i.test(l.text)) {
      block = { k: 'panic', seq: l.seq, lines: [l] }
      out.push(block)
      continue
    }
    if (block && /^(ESP-ROM:|rst:0x)/.test(l.text)) block = null
    if (block) {
      block.lines.push(l)
      if (/^Rebooting\.\.\./.test(l.text)) block = null
      continue
    }
    out.push(l)
  }
  return out
}

/** The panic blocks of a display model, newest last → [{seq, first, last}] (seq of the Guru line). */
function panicBlocks(view) {
  return (view || []).filter(e => e.k === 'panic').map(e => ({ seq: e.seq, first: e.lines[0]?.seq ?? e.seq, last: e.lines[e.lines.length - 1]?.seq ?? e.seq }))
}

// --- lib/serial.js
// Live serial client: WebSocket stream with the mandatory polling fallback. Pure (all
// side effects are injected), so node tests drive it with fake timers, sockets and tail answers.
//
//   createSerialClient({ port, socket, tail, timers, onUpdate, initial })
//     socket(path, onMessage) → disposer      ctx.socket (receive-only, reconnects on its own)
//     tail(port, after) → Promise<envelope>   GET /serial/tail?port=&after=  (result: lines, panic, epoch, state)
//     timers: { setTimeout, clearTimeout }    ctx.setTimeout-like (returns an id or a disposer)
//     onUpdate({ buf, mode, state, simulated, error })
//   .start()   subscribe the socket; if it delivers nothing within SOCKET_GRACE_MS → polling every POLL_MS
//   .stop()    dispose the socket and stop polling (the port itself is closed by the caller: POST /serial/close)
//
// Rules: duplicates are dropped per epoch by seq (lib/seq.js); a new epoch (backend restart) resets the dedupe; a
// `lagging` state or a gap makes the client fetch the missing range from the tail and fill it in; when the socket
// starts delivering again while polling, polling stops (the server resends state + the last ≤ 200 lines on connect).
// The client never opens a port: opening is POST /serial/open, done by the caller after a click.
// `seq` = { mergeLines, emptyBuffer } from lib/seq.js (injected: lib files are concatenated, never import each other).

const SOCKET_GRACE_MS = 3000
const POLL_MS = 1000
const FILL_DELAY_MS = 250

function streamPath(port) {
  return `/serial/stream?port=${encodeURIComponent(port)}`
}

/** Insert lines that fall into gap markers (missed ranges) of `buf`; returns a new buffer. */
function fillGaps(buf, lines) {
  const fill = (lines || []).filter(l => l && l.t === 'line' && Number.isInteger(l.seq)).sort((a, b) => a.seq - b.seq)
  if (!fill.length || !buf.lines.some(l => l.k === 'gap')) return buf
  const out = []
  for (const entry of buf.lines) {
    if (entry.k !== 'gap') { out.push(entry); continue }
    let from = entry.from
    for (const l of fill) {
      if (l.seq < from || l.seq > entry.to) continue
      if (l.seq > from) out.push({ k: 'gap', from, to: l.seq - 1 })
      out.push({ k: 'line', seq: l.seq, ts: l.ts ?? '', text: String(l.text ?? '') })
      from = l.seq + 1
    }
    if (from <= entry.to) out.push({ k: 'gap', from, to: entry.to })
  }
  return { ...buf, lines: out }
}

/** First missed seq of a buffer (lowest gap start) or null. */
function firstGap(buf) {
  const g = buf.lines.find(l => l.k === 'gap')
  return g ? g.from : null
}

function createSerialClient({ port, socket, tail, timers, onUpdate, seq, initial = null, graceMs = SOCKET_GRACE_MS, pollMs = POLL_MS }) {
  const { mergeLines } = seq
  let buf = initial || seq.emptyBuffer()
  let mode = 'connecting' // connecting | socket | poll | stopped
  let error = null
  let simulated = null
  let disposeSocket = null
  let graceTimer = null
  let pollTimer = null
  let fillTimer = null
  let polling = false
  let stopped = false
  let socketMessages = 0

  const clear = t => {
    if (t === null || t === undefined) return
    if (typeof t === 'function') { try { t() } catch { /* already gone */ } } else timers.clearTimeout(t)
  }
  const emit = () => onUpdate?.({ buf, mode, state: buf.state?.state ?? null, simulated, error })

  function scheduleFill() {
    if (fillTimer !== null || stopped) return
    fillTimer = timers.setTimeout(async () => {
      fillTimer = null
      const from = firstGap(buf)
      if (from === null) return
      const env = await tail(port, from - 1)
      if (stopped || !env?.ok) return
      if (env.result?.epoch && buf.epoch && env.result.epoch !== buf.epoch) return // restarted meanwhile: gap is moot
      buf = fillGaps(buf, env.result?.lines || [])
      emit()
    }, FILL_DELAY_MS)
  }

  function onSocket(msg) {
    if (stopped || !msg || typeof msg !== 'object') return
    socketMessages++
    if (graceTimer !== null) { clear(graceTimer); graceTimer = null }
    if (mode !== 'socket') {
      mode = 'socket'
      if (pollTimer !== null) { clear(pollTimer); pollTimer = null }
    }
    if (msg.t === 'state' && typeof msg.simulated === 'boolean') simulated = msg.simulated
    const before = firstGap(buf)
    buf = mergeLines(buf, msg)
    error = null
    if ((msg.t === 'state' && /lagging/i.test(String(msg.detail || ''))) || (firstGap(buf) !== null && firstGap(buf) !== before)) scheduleFill()
    emit()
  }

  async function pollOnce() {
    if (stopped || polling) return
    polling = true
    try {
      let env = await tail(port, buf.lastSeq)
      if (stopped || mode === 'socket') return
      if (env?.ok && env.result?.epoch && buf.epoch !== null && env.result.epoch !== buf.epoch && buf.lastSeq > 0) {
        env = await tail(port, 0) // backend restarted: seq starts at 1 again, read the new epoch from its start
        if (stopped || mode === 'socket') return
      }
      if (!env?.ok) {
        error = env?.error?.message || 'serial tail failed'
      } else {
        const r = env.result || {}
        if (typeof r.simulated === 'boolean') simulated = r.simulated
        const msgs = [{ t: 'state', port: r.port ?? port, state: r.state ?? null, epoch: r.epoch }, ...(r.lines || []).map(l => ({ t: 'line', ...l }))]
        if (r.panic) msgs.push({ ...r.panic, t: 'panic' })
        buf = mergeLines(buf, msgs, { epoch: r.epoch })
        error = null
      }
      emit()
    } finally {
      polling = false
      if (!stopped && mode === 'poll') pollTimer = timers.setTimeout(pollOnce, pollMs)
    }
  }

  function startPolling() {
    graceTimer = null
    if (stopped || mode === 'socket') return
    mode = 'poll'
    emit()
    pollOnce()
  }

  return {
    start() {
      stopped = false
      mode = 'connecting'
      emit()
      try {
        disposeSocket = typeof socket === 'function' ? socket(streamPath(port), onSocket) : null
      } catch (e) {
        disposeSocket = null
        error = String(e?.message || e)
      }
      // no socket (OAuth remote, host isolation, error): poll at once; else give the socket SOCKET_GRACE_MS
      if (!disposeSocket) startPolling()
      else graceTimer = timers.setTimeout(startPolling, graceMs)
    },
    stop() {
      stopped = true
      for (const t of [graceTimer, pollTimer, fillTimer]) clear(t)
      graceTimer = pollTimer = fillTimer = null
      if (disposeSocket) { try { disposeSocket() } catch { /* gone */ } }
      disposeSocket = null
      mode = 'stopped'
      emit()
    },
    buffer: () => buf,
    mode: () => mode,
    socketMessages: () => socketMessages
  }
}

/**
 * Coalesce a burst of updates into one apply per `ms` (observed: a real board in a reboot loop sends ~75 lines/s; one
 * store update per line re-rendered the whole Bench each time and froze the window). push(v) keeps the newest value;
 * the first push of a quiet period applies after `ms`. cancel() drops a pending value, flush() applies it now.
 */
function coalescer(timers, ms, apply) {
  let pending
  let has = false
  let timer = null
  const clear = () => {
    if (timer === null) return
    if (typeof timer === 'function') { try { timer() } catch { /* gone */ } } else timers.clearTimeout(timer)
    timer = null
  }
  const flush = () => {
    clear()
    if (!has) return
    const v = pending
    has = false
    pending = undefined
    apply(v)
  }
  return {
    push(v) {
      pending = v
      has = true
      if (timer === null) timer = timers.setTimeout(() => { timer = null; flush() }, ms)
    },
    flush,
    cancel() { clear(); has = false; pending = undefined },
    pending: () => has
  }
}

/**
 * Should a newly announced panic be decoded? A board in a reboot loop announces the same crash on every boot; it is
 * decoded once per flash. A different summary, a new flash (`flashAt`) or no decode yet → decode. Decoding a repeat
 * after a rebuild would also use the new ELF for the old firmware's addresses (wrong lines).
 * cur = {status, key, summary, flashAt} of the decoded panic; pn = {log_ref, summary}.
 */
function panicNeedsDecode(cur, pn, flashAt = null) {
  if (!pn?.log_ref) return false
  if (!cur?.key) return true
  if (cur.key === pn.log_ref) return false
  if (!['ready', 'loading'].includes(cur.status)) return true
  return !(cur.summary === pn.summary && (cur.flashAt ?? null) === (flashAt ?? null))
}

/**
 * The entries of a log view that go into the DOM: the newest `limit`, extended back to a held panic block so the
 * block the user reads stays put. → a slice of `view`.
 */
function renderWindow(view, holdSeq = null, limit = 800) {
  const list = view || []
  let from = Math.max(0, list.length - limit)
  if (holdSeq !== null && holdSeq !== undefined && from > 0) {
    const i = list.findIndex(e => e.k === 'panic' && e.seq === holdSeq)
    if (i >= 0 && i < from) from = i
  }
  return from ? list.slice(from) : list
}

// Reset reasons in the ROM banner ("rst:0x15 (USB_UART_CHIP_RESET),boot:…") that mean the board was reset from
// outside: power-on 0x1, the USB-Serial/JTAG chip reset 0x15 (esptool, a flash, the RESET key) and 0x16. Observed
// on a real ESP32-S3 (2026-11-06): a panic reboots with rst:0xc (RTC_SW_CPU_RST), the reset after a flash shows rst:0x15.
// Watchdog and brownout resets also follow a panic. A UI heuristic, not a check (board-observed).
const EXTERNAL_RESETS = [0x1, 0x15, 0x16]

/**
 * Is a serial panic still current? After a panic the board reboots on its own (rst:0xc) and, in a reboot loop,
 * panics again: the panic stays current. A boot banner with an outside reset (power-on, esptool/flash) or a ROM
 * banner without a reset reason followed by output means new firmware or a fresh start: stale. (Observed: the old rule,
 * stale at any banner, hid the panic of a real reboot loop between two announcements.)
 */
function panicCurrent(buf) {
  const p = buf?.panic
  if (!p) return false
  const lines = buf.lines || []
  let rom = false
  for (const l of lines) {
    if (l.k !== 'line' || l.seq <= p.seq) continue
    const m = /^rst:0x([0-9a-fA-F]+)/.exec(l.text)
    if (m) {
      if (EXTERNAL_RESETS.includes(parseInt(m[1], 16))) return false
      rom = false
      continue
    }
    if (/^ESP-ROM:/.test(l.text)) { rom = true; continue }
    if (rom && !/^Build:/.test(l.text)) return false // a banner without a reset reason, then output: a new boot
  }
  return true
}

/** UTC time (ms) of a serial artifact name "panic-YYYYMMDD-HHMMSS[-n].log" (serialport.open_artifact), else NaN. */
function logRefTime(ref) {
  const m = /^[a-z]+-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(?:-\d+)?\.log$/.exec(String(ref || ''))
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : NaN
}

/**
 * The serial panic is current (panicCurrent) and not older than the last good flash of the project: a panic from
 * before the flash came from the old firmware (observed: after the flash, lines lost while the USB port re-enumerated
 * left the old panic "current").
 */
function serialPanicLive(buf, project) {
  if (!buf?.panic || !panicCurrent(buf)) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at) return true
  const pt = logRefTime(buf.panic.log_ref)
  const ft = Date.parse(f.at)
  return !(Number.isFinite(pt) && Number.isFinite(ft) && pt < ft)
}

const ROM_LINE = /^(ESP-ROM:|Build:|rst:0x|Saved PC:|SPIWP:|mode:|load:|entry |SHA-256 comparison|Calculated:|Expected:|Attempting to boot|E \(\d+\) esp_core_dump)/
const PANIC_LINE = /Guru Meditation Error|abort\(\) was called|Brownout detector was triggered|panic'ed/

/**
 * Did the firmware run after a flash without a panic? Lines with seq > `afterSeq`: at least `min` lines of the
 * application (not ROM/bootloader output) and no panic line. A board whose "boot ok" line was missed (the port
 * re-enumerated after RESET) or a firmware that never prints one is still recognised. → {n, last} | null
 */
function cleanRunAfter(buf, afterSeq, min = 3) {
  if (!Number.isInteger(afterSeq)) return null
  let n = 0
  let last = null
  for (const l of buf?.lines || []) {
    if (l.k !== 'line' || l.seq <= afterSeq) continue
    if (PANIC_LINE.test(l.text)) return null
    const t = String(l.text || '').trim()
    if (!t || ROM_LINE.test(t)) continue
    n++
    last = l
  }
  return n >= min ? { n, last } : null
}

/** Last line of the buffer matching `re` (e.g. /boot ok/). */
function lastLineMatching(buf, re) {
  for (let i = (buf?.lines || []).length - 1; i >= 0; i--) {
    const l = buf.lines[i]
    if (l.k === 'line' && re.test(l.text)) return l
  }
  return null
}

/**
 * Console state on the Bench page: `pane` (serial pane open, a slim bar points there) |
 * `collapsed` (the user hid it) | `idle` (no port open and nothing to show: one 34 px bar, the board gets the room) |
 * `open`. An open monitor, a buffered log of an open port, a running job, a current panic or a click on the bar
 * (`pinned`, session only) open it.
 */
function consoleMode({ paneOpen = false, cons = 'open', pinned = false, monitorOpen = false, serialOpen = false, jobRunning = false, panic = false } = {}) {
  if (paneOpen) return 'pane'
  if (cons === 'collapsed') return 'collapsed'
  if (monitorOpen || serialOpen || jobRunning || panic || pinned) return 'open'
  return 'idle'
}

/**
 * What an empty serial console says and offers → {kind, text, action: {label, port}|null}.
 * `ports` = GET /ports list, `serial` = {port, note, status}, `backendDown` when the bench backend is unreachable.
 */
function serialEmptyState({ ports = [], serial = {}, backendDown = false } = {}) {
  if (backendDown) return { kind: 'offline', text: 'Bench backend not available — no serial data.', action: null }
  const list = Array.isArray(ports) ? ports : []
  const isSim = d => /^sim:\/\//.test(String(d || ''))
  if (serial.port && !isSim(serial.port) && serial.note === 'real-port') {
    return { kind: 'real', text: `Monitor closed for ${serial.port}. Ports open only on your click.`, action: { label: '06 DEBUG ›', port: null } }
  }
  if (serial.status === 'error' && serial.note) return { kind: 'error', text: `Serial read failed: ${serial.note}`, action: null }
  const sim = isSim(serial.port) ? serial.port : (list.find(p => p.simulated) || {}).device || null
  const real = list.find(p => !p.simulated && p.likely_esp)
  if (real) return { kind: 'real', text: `Board on ${real.device}. Ports open only on your click.`, action: { label: '06 DEBUG ›', port: null } }
  if (sim) return { kind: 'sim', text: 'Simulated board ready.', action: { label: 'Open monitor ›', port: sim } }
  return { kind: 'none', text: 'No serial port found. Plug in a board; 05 FLASH lists the ports.', action: null }
}

// --- lib/stages.js
// Stations 01–06, rail status and HUD key figures. Pure, no SDK.

const STATIONS = [
  { id: 'plan', n: '01', title: 'Plan', heading: 'PIN MAP', icon: 'circuit-board' },
  { id: 'calc', n: '02', title: 'Calc', heading: 'CALCULATORS', icon: 'symbol-numeric' },
  { id: 'wire', n: '03', title: 'Wire', heading: 'WIRING', icon: 'git-merge' },
  { id: 'solder', n: '04', title: 'Solder', heading: 'SOLDER ORDER', icon: 'flame' },
  { id: 'flash', n: '05', title: 'Flash', heading: 'BUILD & FLASH', icon: 'zap' },
  { id: 'debug', n: '06', title: 'Debug', heading: 'SERIAL & PANIC', icon: 'debug-alt' }
]

const STATION_IDS = STATIONS.map(s => s.id)
const VIEW_TO_STATION = { pins: 'plan', calc: 'calc', wire: 'wire', solder: 'solder', flash: 'flash', crash: 'debug' }

function stationInfo(id) {
  return STATIONS.find(s => s.id === id) || STATIONS[0]
}

function isStation(id) {
  return STATION_IDS.includes(id)
}

/** Solder progress {done, total} (done counts only ids that are still steps). */
function solderProgress(project) {
  const steps = project?.solder?.steps || []
  const ids = new Set(steps.map(s => s.id))
  const done = (project?.solder?.done || []).filter(id => ids.has(id)).length
  return { done, total: steps.length }
}

/** Solder plan outdated? parts refs vs step refs → {stale, missing, gone, reopen: done steps a re-plan
 *  unticks (the backend keeps a tick only for an unchanged step id kind + refs, e.g. R5 joins the resistors)}. */
function solderStale(project) {
  const steps = project?.solder?.steps || []
  const none = { stale: false, missing: [], gone: [], reopen: [] }
  if (!steps.length) return none
  const parts = (project?.parts || []).filter(p => p && p.ref)
  const inPlan = new Set(steps.flatMap(s => s.refs || []))
  const have = new Set(parts.map(p => p.ref))
  const missingParts = parts.filter(p => !inPlan.has(p.ref))
  const gone = [...inPlan].filter(r => !have.has(r))
  if (!missingParts.length && !gone.length) return none
  const done = new Set(project?.solder?.done || [])
  const reopen = steps.filter(s => done.has(s.id) && (missingParts.some(p => p.kind === s.kind) || (s.refs || []).some(r => !have.has(r))))
  return { stale: true, missing: missingParts.map(p => p.ref), gone,
    reopen: reopen.map(s => ({ n: s.n, kind: s.kind, id: s.id, gains: missingParts.filter(p => p.kind === s.kind).map(p => p.ref) })) }
}

/** 05 FLASH, real board only: a hint (never a block) when the solder plan is unfinished or outdated. → text | null */
function flashSolderHint(project, port) {
  if (!port || /^sim:\/\//.test(String(port))) return null
  const sp = solderProgress(project)
  if (!sp.total) return null
  const st = solderStale(project)
  if (st.stale) return `solder plan outdated (${st.missing.length ? `${st.missing.join(', ')} not in it` : `${st.gone.join(', ')} removed`}) — board not finished?`
  return sp.done < sp.total ? `solder ${sp.done}/${sp.total} — board not finished?` : null
}

/** Panic key: changes when a new panic is stored, so the rail blinks again. */
function panicKey(project) {
  const p = project?.debug?.last_panic
  return p ? `${p.reason || ''}@${p.at || ''}` : null
}

/** pins.check result.modules.counts → {danger, caution}; dangerCode/cautionCode: the code when one finding. */
function stageModCounts(env) {
  const c = env?.ok ? env.result?.modules?.counts : null
  const n = k => (Number.isInteger(c?.[k]) && c[k] > 0 ? c[k] : 0)
  const ws = env?.ok && Array.isArray(env.warnings) ? env.warnings.filter(w => /^mod_/.test(w?.code || '')) : []
  const one = k => { const x = ws.filter(w => w.severity === k); return n(k) === 1 && x.length === 1 ? x[0].code : null }
  return { danger: n('danger'), caution: n('caution'), dangerCode: one('danger'), cautionCode: one('caution') }
}

/** Rail status per station → {text, tone, alert}. counts: verdict counts; panicSeen: last panic key seen (06
 *  opened); mods: stageModCounts() — module dangers count as ✕, cautions as ! (never [✓]). */
function stageStatus(project, counts, panicSeen, mods = null) {
  const out = {}
  const c = counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 }
  const m = mods || { danger: 0, caution: 0 }
  const bad = c.blocked + m.danger
  const warn = c.caution + m.caution
  const md = [m.danger ? `${m.danger} ${m.dangerWord || 'module danger'}` : '', m.caution ? `${m.caution} ${m.cautionWord || 'module caution'}` : ''].filter(Boolean).join(' · ')
  const total = c.ok + c.caution + c.blocked + c.unchecked
  if (!project) {
    for (const s of STATIONS) out[s.id] = { text: '', tone: 'faint', alert: false }
    return out
  }
  out.plan = bad ? { text: `${bad}✕`, tone: 'bad', alert: false, ...(md && { detail: md }) }
    : warn ? { text: `${warn}!`, tone: 'warn', alert: false, ...(md && { detail: md }) }
      : total ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  out.calc = (project.calcs || []).length ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  out.wire = (project.circuits || []).length ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  const sp = solderProgress(project)
  const st = solderStale(project)
  out.solder = st.stale ? { text: '!', tone: 'warn', alert: false, detail: `plan outdated: ${[st.missing.length ? `${st.missing.join(', ')} not in the plan` : '', st.gone.length ? `${st.gone.join(', ')} removed` : ''].filter(Boolean).join('; ')}` }
    : !sp.total ? { text: '[ ]', tone: 'faint', alert: false }
    : sp.done >= sp.total ? { text: '[✓]', tone: 'ok', alert: false }
      : { text: `${Math.round((sp.done / sp.total) * 100)}%`, tone: sp.done ? 'active' : 'faint', alert: false }
  const fw = project.firmware || {}
  const flashedThis = fw.last_flash?.ok && (!fw.last_build?.elf_sha256 || fw.last_flash.elf_sha256 === fw.last_build.elf_sha256)
  out.flash = fw.last_build && fw.last_build.ok === false ? { text: 'FAIL', tone: 'bad', alert: false }
    : flashedThis ? { text: '[✓]', tone: 'ok', alert: false }
      : fw.last_build?.ok ? { text: 'BUILT', tone: 'active', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  const pk = panicKey(project)
  out.debug = pk && stagePanicCurrent(project) ? { text: 'PANIC', tone: 'bad', alert: pk !== panicSeen }
    : pk ? { text: '[✓]', tone: 'ok', alert: false } : { text: '[ ]', tone: 'faint', alert: false }
  return out
}

/** Stored panic still current: no successful flash after it (same rule as lib/crash.js projectPanicCurrent). */
function stagePanicCurrent(project) {
  const p = project?.debug?.last_panic
  if (!p) return false
  const f = project?.firmware?.last_flash
  if (!f?.ok || !f.at || !p.at) return true
  return String(p.at) >= String(f.at)
}

/** First solder step that is not done (null when all are done or there is no plan). */
function nextSolderStep(project) {
  const done = new Set(project?.solder?.done || [])
  return (project?.solder?.steps || []).find(s => !done.has(s.id)) || null
}

/** HUD figures: pins counts, solder done/total, build state. */
function hudFigures(project, counts) {
  const fw = project?.firmware || {}
  const b = fw.last_build
  return {
    pins: counts || { ok: 0, caution: 0, blocked: 0, unchecked: 0 },
    solder: solderProgress(project),
    build: !b ? { tone: 'faint', text: '—' } : b.ok ? { tone: 'ok', text: 'OK', ram: b.ram_pct, flash: b.flash_pct }
      : { tone: 'bad', text: 'FAIL' }
  }
}

// --- lib/tokens.js
// Bench Phosphor tokens. Pure data, no SDK. 10-tokens.js turns them into CSS variables.
// Phosphor = fixed dark values, independent of the app theme. Follow = the app's own theme variables.

const PHOSPHOR = {
  bg: '#040806',
  panel: '#07100b',
  raised: '#0b1710',
  fg: '#c9f5d6',
  'fg-dim': '#86b898',
  'fg-faint': '#52775f',
  stroke: '#143322',
  'stroke-strong': '#1f5236',
  ok: '#39ff88',
  active: '#2de2ff',
  warn: '#ffc23d',
  // The design spec says #ff3d6e; that measures 5.89:1 on --cb-bg (< 7:1). Same hue, lifted to 7.44:1.
  bad: '#ff6b8f',
  power: '#b98cff',
  ink: '#040806', // text on filled state colours (buttons, stamps)
  // text in a state colour: in Phosphor the pure colours already reach ≥ 7:1
  'ok-text': '#39ff88',
  'active-text': '#2de2ff',
  'warn-text': '#ffc23d',
  'bad-text': '#ff6b8f',
  'power-text': '#b98cff'
}

/** Share of the state colour in its follow-theme text variant (rest: --ui-text-primary), light app themes only.
 *  55 % is the largest share that keeps every variant ≥ 4.5:1 on Nous light bg, card and raised (violet is the limit). */
const FOLLOW_TEXT_MIX = 55

// Follow + light app theme: Hermes' state colours are tuned for dots and fills (#c08532 amber is 3.1:1 on white),
// so text in a state colour mixes toward the theme's text colour until it reaches ≥ 4.5:1. Dark app themes
// keep the pure colours (all ≥ 5.6:1 on Nous dark). light-dark() follows the color-scheme the app sets on <html>.
const followText = v => `light-dark(color-mix(in oklab, var(${v}) ${FOLLOW_TEXT_MIX}%, var(--ui-text-primary)), var(${v}))`

const FOLLOW = {
  bg: 'var(--dt-background)',
  panel: 'var(--dt-card)',
  raised: 'color-mix(in oklab, var(--dt-card) 92%, var(--ui-text-primary))',
  fg: 'var(--ui-text-primary)',
  'fg-dim': 'var(--ui-text-secondary)',
  'fg-faint': 'var(--ui-text-tertiary)',
  stroke: 'var(--ui-stroke-tertiary)',
  'stroke-strong': 'var(--ui-stroke-secondary)',
  ok: 'var(--ui-green)',
  active: 'var(--ui-cyan)',
  warn: 'var(--ui-yellow)',
  bad: 'var(--ui-red)',
  power: 'var(--ui-purple)',
  ink: 'var(--dt-background)',
  'ok-text': followText('--ui-green'),
  'active-text': followText('--ui-cyan'),
  'warn-text': followText('--ui-yellow'),
  'bad-text': followText('--ui-red'),
  'power-text': followText('--ui-purple')
}

/** Model materials: the board model is an object, so these are fixed values in
 *  both looks. They live outside PHOSPHOR/FOLLOW because FOLLOW holds app variables only (test_ui1_contrast.mjs);
 *  10-tokens.js sets them once on .cb-root and the theme look never overrides them. Rules (test_v0_tokens.mjs):
 *  OKLCH chroma ≤ 0.06 (no state hue), silk on pcb and metal-ink on metal ≥ 4.5:1, state rings on pcb ≥ 3:1.
 *  Start values from the board model design study; pcb darkened from #0f2e1f so the Follow + Nous light red
 *  ring (#cf2d56) also reaches 3:1, pcb-edge desaturated from #1d4a32 (chroma 0.065). */
const MATERIAL = {
  pcb: '#0c281a', // board face (gradient start; artDefs darkens toward the end)
  'pcb-edge': '#204634', // board rim / outline against the bench background
  silk: '#c4d2c7', // silkscreen print
  metal: '#9aa4a0', // shield can, port shells
  'metal-hi': '#d7dedb', // metal highlight (gradient start)
  'metal-ink': '#1f2826', // print on the shield can
  tin: '#aeb6b2', // pads
  plastic: '#151a18', // header strips, IC bodies, button housings
  'plastic-edge': '#36413d', // their outline
  copper: '#9a8a70', // antenna meander
  cavity: '#0b0f0d' // port openings
}

// Theme "Bench Phosphor" mutedForeground: halfway between fg and fg-dim (app icons, status bar)
const THEME_MUTED = '#a8d6b7'

const MONO = '"JetBrains Mono", "Fira Code", "Cascadia Code", var(--dt-font-mono), ui-monospace, "DejaVu Sans Mono", monospace'

/** Contrast pairs checked by tests (name, foreground, background, minimum ratio). */
const CONTRAST_PAIRS = [
  ['fg on bg', PHOSPHOR.fg, PHOSPHOR.bg, 7],
  ['fg-dim on bg', PHOSPHOR['fg-dim'], PHOSPHOR.bg, 7],
  ['ok on bg', PHOSPHOR.ok, PHOSPHOR.bg, 7],
  ['active on bg', PHOSPHOR.active, PHOSPHOR.bg, 7],
  ['warn on bg', PHOSPHOR.warn, PHOSPHOR.bg, 7],
  ['bad on bg', PHOSPHOR.bad, PHOSPHOR.bg, 7],
  ['power on bg', PHOSPHOR.power, PHOSPHOR.bg, 7],
  ['ok on panel', PHOSPHOR.ok, PHOSPHOR.panel, 7],
  ['power on panel', PHOSPHOR.power, PHOSPHOR.panel, 7],
  ['fg-faint on bg (decoration)', PHOSPHOR['fg-faint'], PHOSPHOR.bg, 3],
  ['fg on panel', PHOSPHOR.fg, PHOSPHOR.panel, 7],
  ['fg-dim on panel', PHOSPHOR['fg-dim'], PHOSPHOR.panel, 7],
  ['fg-dim on raised', PHOSPHOR['fg-dim'], PHOSPHOR.raised, 7],
  ['bad on panel', PHOSPHOR.bad, PHOSPHOR.panel, 7],
  ['warn on panel', PHOSPHOR.warn, PHOSPHOR.panel, 7],
  ['active on panel', PHOSPHOR.active, PHOSPHOR.panel, 7],
  ['fg-faint on panel (decoration)', PHOSPHOR['fg-faint'], PHOSPHOR.panel, 3],
  ['ink on ok (primary button)', PHOSPHOR.ink, PHOSPHOR.ok, 7],
  ['ink on active (selected segment, used tag)', PHOSPHOR.ink, PHOSPHOR.active, 7],
  ['ink on bad (stamp, danger button)', PHOSPHOR.ink, PHOSPHOR.bad, 7],
  ['ink on warn', PHOSPHOR.ink, PHOSPHOR.warn, 7],
  ['theme mutedForeground on bg', THEME_MUTED, PHOSPHOR.bg, 7],
  ['theme mutedForeground on sidebar', THEME_MUTED, '#030604', 7]
]

// --- lib/units.js
// Quantity input for the calculators: '4k7', '4.7 kΩ', '10mA', '3V3' → SI value. Pure, no SDK.
// Mirrors circuit_bench/bench_core/units.py (the backend parses again and stays authoritative); the UI uses it to
// show the parsed value and an error next to the field before anything is sent.
//   number [exponent] [SI prefix] [unit]   10 mA, 4.7e3, 100nF, 2.2 µF
//   U_RKM code (letter = decimal point)       4k7, 1R5, R47, 3V3, 2u2
// Prefixes are case-sensitive (m milli, M mega; K is accepted as kilo). Units are case-insensitive. Decimal point only.

const UNIT_HINT = 'examples: 4k7, 4.7 kΩ, 10mA, 3V3, 100nF, 2.2e-6'

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
function parseRaw(text) {
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
function parseQuantity(text, unit = null) {
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

// --- lib/wire.js
// Station 03 WIRE helpers: building blocks (mirror of bench_core/schematic.blocks(), the backend validates again),
// SVG safety check, part ↔ wiring-row coupling, GPIO of a stored circuit. Pure.

const WIRE_BLOCKS = [
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
function wireBlock(id, list = null) {
  return (list || []).find(b => b.block === id) || WIRE_BLOCKS.find(b => b.block === id) || WIRE_EXTRA_BLOCKS.find(b => b.block === id) || null
}

const WIRE_NET_RE = /^[A-Za-z0-9_+.-]{1,32}$/

/** Form → {ok, params, errors}. Ohm/volt fields go as SI numbers (schematic params are numbers), parsed with `parse`. */
function buildWireParams(block, form, parse) {
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
function wireForm(block, stored = {}, fmt = v => String(v)) {
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
function sanitizeSvg(text) {
  const s = String(text || '').trim()
  if (!/^<svg[\s>]/.test(s) || !/<\/svg>\s*$/.test(s)) return { ok: false, reason: 'not an SVG document' }
  if (s.length > 400_000) return { ok: false, reason: 'SVG too large' }
  const bad = [/<script/i, /<foreignObject/i, /\son[a-z]+\s*=/i, /javascript:/i, /<iframe/i, /<image/i, /\b(?:xlink:)?href\s*=/i, /<!ENTITY/i, /<style/i]
  for (const re of bad) if (re.test(s)) return { ok: false, reason: `unsafe SVG content (${re.source})` }
  return { ok: true, svg: s }
}

/** "R1.2" → "R1", "J1-20 · IO14" → "J1", "Q1.B" → "Q1". */
function refOfEnd(end) {
  const m = /^([A-Z][A-Z_]*\d+)/.exec(String(end || '').trim())
  return m ? m[1] : null
}

/** Board rails and ground as bench_core/wiring.py names them (RAILS, GROUND); a test keeps them equal. */
const WIRE_RAILS = ['3V3', '5V']
const WIRE_GROUND = 'GND'

/** Meaning of a net for its colour: board supply → power, ground → ground, else signal. */
function wireNetClass(net) {
  return WIRE_RAILS.includes(net) ? 'power' : net === WIRE_GROUND ? 'ground' : 'signal'
}

/** Wiring rows with the part refs at both ends (hover coupling part ↔ row) and the net's class. */
function wiringRows(wiring) {
  return (wiring || []).map((w, i) => ({ i, from: w.from, to: w.to, net: w.net, netClass: wireNetClass(w.net),
    refs: [...new Set([refOfEnd(w.from), refOfEnd(w.to)].filter(Boolean))] }))
}

/** Refs in an SVG (data-ref attributes, single or double quoted), first occurrence order. */
function svgRefs(svg) {
  return [...new Set([...String(svg || '').matchAll(/data-ref=(["'])([A-Z][A-Z0-9_]*)\1/g)].map(m => m[2]))]
}

/** viewBox of the backend SVG → {x, y, w, h} or null. The plan never draws below scale 1, so its smallest text
 *  (pin markers, font-size 10) stays ≥ 10 px. */
function svgViewBox(svg) {
  const m = /<svg\b[^>]*\sviewBox=(["'])([^"']+)\1/.exec(String(svg || ''))
  const n = m ? m[2].trim().split(/[\s,]+/).map(Number) : []
  return n.length === 4 && n.every(Number.isFinite) && n[2] > 0 && n[3] > 0 ? { x: n[0], y: n[1], w: n[2], h: n[3] } : null
}

/** Highlight in the plan and the tables: {refs: [...], net} (either may be empty). */
function wireHl(refs = [], net = null) {
  const r = (refs || []).filter(x => /^[A-Z][A-Z0-9_]*$/.test(x))
  const n = typeof net === 'string' && /^[A-Za-z0-9_+.-]{1,32}$/.test(net) ? net : null
  return r.length || n ? { refs: r, net: n } : null
}

/** Identity of a highlight (null → ''), for "nothing changed" checks. */
function wireHlKey(hl) {
  return hl ? `${hl.refs.join(',')}|${hl.net || ''}` : ''
}

/** Is an SVG element (its data-ref / data-net / data-pin) part of the highlight? */
function wireHlHas(hl, { ref = null, net = null, pin = null } = {}) {
  if (!hl) return false
  const pinRef = pin ? refOfEnd(pin) : null
  return Boolean((net && hl.net === net) || (ref && hl.refs.includes(ref)) || (pinRef && hl.refs.includes(pinRef)))
}

/** Hover target under the pointer: walk from the element up to (not including) `stop` and take the first
 *  data-ref (a part) or data-net (a net: wire, port, net label). `attr(node, name)` reads an attribute. */
function wireHoverTarget(node, stop, attr = (n, k) => n?.getAttribute?.(k) ?? null) {
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
function wireRowOn(hl, row) {
  if (!hl) return false
  return hl.net ? row.net === hl.net : row.refs.some(r => hl.refs.includes(r))
}

/** Highlight of a hovered row: its net and the parts at its ends. Only refs of `parts` count (a board header such
 *  as J1 in "J1-20 · IO14" is a port of the plan, not a part). */
function wireRowHl(row, parts = []) {
  const own = new Set((parts || []).map(p => p.ref))
  return wireHl(row.refs.filter(r => own.has(r)), row.net)
}

/** Warnings split for the inspector: danger/caution as warning cards, the rest (info) in the list. */
function wireWarnings(warnings) {
  const ws = warnings || []
  return { cards: ws.filter(w => w.severity === 'danger' || w.severity === 'caution'), notes: ws.filter(w => w.severity !== 'danger' && w.severity !== 'caution') }
}

/** GPIO of a stored circuit: the assignment on the circuit's net, else the role named like the circuit id. */
function circuitGpio(project, circuit) {
  const as = project?.assignments || []
  const net = circuit?.params?.net
  const hit = (net && as.find(a => a.net === net)) || as.find(a => a.role === String(circuit?.id || '').toUpperCase())
  return hit ? hit.pin : null
}

/** Safe file name for "Save SVG". */
function svgFileName(project, circuitId) {
  const clean = x => String(x || '').toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)
  return `${clean(project?.id) || 'bench'}-${clean(circuitId) || 'circuit'}.svg`
}

// more blocks (module, level_shifter) only when the backend names them.

/** Local forms beyond the base set; `module` draws a module part of the project (params.part = its ref). */
const WIRE_EXTRA_BLOCKS = [
  { block: 'module', title: 'Module part of the project', params: [{ name: 'part', label: 'Module part', part: true, required: true, def: '' }] },
  { block: 'level_shifter', title: 'Level shifter (BSS138 channel)', params: [] }
]

/** Groups of the block pick; unknown blocks go to `more`. */
const WIRE_GROUPS = [['basic', ['npn_low_side', 'led', 'button_pullup', 'divider']], ['modules', ['module', 'level_shifter']]]

const WIRE_TYPE = { ohm: { unit: 'Ω' }, volt: { unit: 'V' }, text: { text: true }, net: { net: true }, choice: {} }
const WIRE_ID_RE = /^[a-z0-9_]{1,32}$/

/** A backend catalogue entry ({block, title, params: [{name, type, default, required, choices}]}) as a form; null if unusable. */
function wireBlockOf(b) {
  if (!b || !WIRE_ID_RE.test(b.block)) return null
  const params = (Array.isArray(b.params) ? b.params : []).filter(p => p && typeof p.name === 'string' && WIRE_TYPE[p.type]).map(p => ({
    name: p.name, label: p.name.replace(/_/g, ' '), required: Boolean(p.required), ...WIRE_TYPE[p.type],
    ...(p.type === 'choice' && Array.isArray(p.choices) ? { choice: p.choices.map(String) } : {}), def: p.default == null ? '' : String(p.default) }))
  return { block: b.block, title: typeof b.title === 'string' ? b.title : b.block.replace(/_/g, ' '), params }
}

/** Block names of the backend: result.blocks, or the hint of a render without a block ("blocks: led, …"); else null. */
function wireBlockNames(env) {
  const list = env?.result?.blocks
  if (Array.isArray(list)) return list.map(b => (typeof b === 'string' ? b : b?.block)).filter(n => WIRE_ID_RE.test(n))
  const m = env && !env.ok ? /blocks:\s*([a-z0-9_, ]+)/.exec(String(env.error?.hint || '')) : null
  const names = m ? m[1].split(',').map(x => x.trim()).filter(x => WIRE_ID_RE.test(x)) : []
  return names.length ? names : null
}

/** Offered blocks: the base set without names, else exactly the named ones (local form, backend table, or no fields). */
function wireBlockList(names, env = null) {
  if (!Array.isArray(names) || !names.length) return WIRE_BLOCKS
  const remote = (Array.isArray(env?.result?.blocks) ? env.result.blocks : []).map(wireBlockOf).filter(Boolean)
  return names.map(n => [...WIRE_BLOCKS, ...remote, ...WIRE_EXTRA_BLOCKS].find(b => b.block === n) || { block: n, title: n.replace(/_/g, ' '), params: [] })
}

/** The block pick in groups [{id, blocks}], empty groups left out, `more` last. */
function wireGroups(blocks) {
  const known = WIRE_GROUPS.flatMap(([, ids]) => ids)
  return [...WIRE_GROUPS, ['more', null]].map(([id, ids]) => ({ id, blocks: (blocks || []).filter(b => (ids ? ids.includes(b.block) : !known.includes(b.block))) }))
    .filter(g => g.blocks.length)
}

/** Module parts of the project (parts with `module`), by ref: [{ref, label, title}]. */
function wireModuleParts(project) {
  const key = r => { const m = /^([A-Z]+)(\d+)$/.exec(r); return m ? [m[1], Number(m[2])] : [r, 0] }
  return (project?.parts || []).filter(p => p && typeof p.module === 'string' && p.module && typeof p.ref === 'string')
    .sort((a, b) => { const [pa, na] = key(a.ref); const [pb, nb] = key(b.ref); return pa < pb ? -1 : pa > pb ? 1 : na - nb })
    .map(p => ({ ref: p.ref, label: `${p.ref} ${p.value || p.module}`, title: `${p.module}${p.variant ? ` · ${p.variant}` : ''}` }))
}

// --- 05-h.js
// h(type, props, ...children): small helper over jsx/jsxs (no JSX syntax in disk plugins).
// Falsy children (null, undefined, false, true) are dropped; nested arrays are flattened.
// Give list items an explicit `key`; it is passed to jsx() as the key argument, never spread inside props.
function h(type, props, ...children) {
  const p = {}
  let key
  if (props) {
    for (const k of Object.keys(props)) {
      if (k === 'key') key = props[k] === undefined || props[k] === null ? undefined : String(props[k])
      else p[k] = props[k]
    }
  }
  const kids = children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false && c !== true)
  if (kids.length === 1) p.children = kids[0]
  else if (kids.length > 1) p.children = kids
  return kids.length > 1 ? jsxs(type, p, key) : jsx(type, p, key)
}

// --- 10-tokens.js
// Tokens → CSS variables on the own root only. Look "phosphor" = fixed values, "theme" = app vars.
// Model materials (MATERIAL) are set once on .cb-root and are the same in both looks.

function tokenVars(map) {
  return Object.entries(map).map(([k, v]) => `--cb-${k}:${v};`).join('')
}

const CB_TOKEN_CSS = `
.cb-root{--cb-mono:${MONO};${tokenVars(PHOSPHOR)}
${tokenVars(MATERIAL)}
--cb-glow-ok:0 0 10px color-mix(in oklab,var(--cb-ok) 55%,transparent);
--cb-glow-active:0 0 10px color-mix(in oklab,var(--cb-active) 50%,transparent);
--cb-glow-bad:0 0 12px color-mix(in oklab,var(--cb-bad) 60%,transparent);
--cb-glow-warn:0 0 10px color-mix(in oklab,var(--cb-warn) 45%,transparent);
--cb-grid:color-mix(in oklab,var(--cb-ok) 3%,transparent);
--cb-scan:rgba(0,0,0,.18);
--cb-cons-bg:color-mix(in oklab,black 25%,var(--cb-bg));
--cb-ok-fill:var(--cb-ok);--cb-active-fill:var(--cb-active);--cb-warn-fill:var(--cb-warn);--cb-bad-fill:var(--cb-bad);}
.cb-root[data-cb-look=theme]{${tokenVars(FOLLOW)}
--cb-glow-ok:none;--cb-glow-active:none;--cb-glow-bad:none;--cb-glow-warn:none;
--cb-grid:color-mix(in oklab,var(--cb-fg) 4%,transparent);--cb-scan:transparent;
--cb-cons-bg:var(--cb-panel);
--cb-ok-fill:var(--cb-ok-text);--cb-active-fill:var(--cb-active-text);--cb-warn-fill:var(--cb-warn-text);--cb-bad-fill:var(--cb-bad-text);}
`
// --cb-cons-bg: the console is darker than the bench only in Phosphor; Follow uses the card colour (no black).
// --cb-*-fill: fills that carry --cb-ink text (buttons, stamps, tags). Follow uses the text variants there, so ink
// (= the app background) on the fill has the same ≥ 4.5:1 as the text variant on the background.

// Style registration: every 13-…–19-styles-*.js makes exactly one
// CB_CSS_PARTS.push(<template literal>). Styles() (12-styles.js) appends them at render time in file order; later files win.
const CB_CSS_PARTS = []

// --- 11-styles-ui2.js
// Station styles: stations 02–06, dialogs, directive card, media card, settings page. Same rules as 12-styles.js:
// every selector under .cb-root, information ≥ 11 px, uppercase labels ≥ 10 px, fg-faint only for decoration.

const CB_CSS_UI2 = `
/* shared station parts */
.cb-root .cb-push{margin-left:auto}
.cb-root .cb-ellip{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-sec{display:flex;flex-direction:column;gap:8px;min-width:0}
.cb-root .cb-sec--active{border-color:color-mix(in oklab,var(--cb-active) 55%,var(--cb-stroke-strong))}
.cb-root .cb-sec--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,var(--cb-stroke-strong));
  background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-ok) 6%,var(--cb-panel)),var(--cb-panel) 55%)}
.cb-root .cb-fixed{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:4px}
.cb-root .cb-sec--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,var(--cb-stroke-strong));
  background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-bad) 6%,var(--cb-panel)),var(--cb-panel) 50%)}
.cb-root .cb-secn{flex:none;min-width:22px;height:18px;padding:0 4px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--cb-stroke-strong);
  color:var(--cb-fg-dim);font-size:10px;letter-spacing:.06em;font-variant-numeric:tabular-nums}
.cb-root .cb-sec--active .cb-secn{border-color:var(--cb-active);color:var(--cb-active-text)}
.cb-root .cb-sec-aside{margin-left:auto;font-size:11px;white-space:nowrap}
.cb-root .cb-kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;align-items:baseline;min-width:0}
.cb-root .cb-kv > span{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-kv > b{font-weight:600;color:var(--cb-fg);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-kv--dialog{gap:7px 14px}.cb-root .cb-kv--dialog > b{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-jobline{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11px;min-width:0}
.cb-root .cb-jobline .cb-bar{flex:1 1 80px;max-width:180px}
.cb-root .cb-hintline{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;color:var(--cb-fg-dim);font-size:11px;margin-top:6px}
.cb-root .cb-linkbtn{color:var(--cb-active-text);font-size:11px;white-space:nowrap}
.cb-root .cb-linkbtn:hover{text-decoration:underline}
.cb-root .cb-pre{margin:6px 0 0;padding:8px 10px;background:var(--cb-cons-bg);border:1px solid var(--cb-stroke);
  color:var(--cb-fg-dim);font:inherit;font-size:11px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto}
.cb-root [data-cb-focus=true]{outline:2px solid var(--cb-active);outline-offset:3px;box-shadow:var(--cb-glow-active);animation:cb-pulse 1.2s ease-in-out 3}
.cb-root .cb-bar{position:relative;height:6px;background:color-mix(in oklab,var(--cb-fg) 8%,transparent);border:1px solid var(--cb-stroke);overflow:hidden;min-width:40px}
.cb-root .cb-bar i{position:absolute;inset:0 auto 0 0;background:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-bar--ok i{background:var(--cb-ok);box-shadow:var(--cb-glow-ok)}.cb-root .cb-bar--warn i{background:var(--cb-warn);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-bar--ind i{width:30%;animation:cb-indet 1.1s ease-in-out infinite alternate}
.cb-root .cb-checks{display:grid;gap:3px;margin-top:4px}
.cb-root .cb-chk{display:grid;grid-template-columns:14px minmax(0,1fr);gap:6px;font-size:11px;line-height:1.45}
.cb-root .cb-assume{margin-top:4px}.cb-root .cb-assume summary,.cb-root .cb-formula summary{cursor:pointer;list-style:none;display:inline-flex;align-items:center;gap:6px}
.cb-root .cb-assume summary::-webkit-details-marker,.cb-root .cb-formula summary::-webkit-details-marker{display:none}
.cb-root .cb-assume summary::before,.cb-root .cb-formula summary::before{content:"▸";color:var(--cb-fg-dim);font-size:10px}
.cb-root .cb-assume[open] summary::before,.cb-root .cb-formula[open] summary::before{content:"▾"}
.cb-root .cb-assume ul{margin:6px 0 0;padding:0 0 0 14px;display:grid;gap:3px;font-size:11px;line-height:1.45}
.cb-root .cb-assume b{color:var(--cb-fg);font-weight:600}
.cb-root .cb-simban{display:inline-flex;align-items:center;gap:2px;color:var(--cb-active-text);letter-spacing:.14em;font-size:10px;font-weight:700;white-space:nowrap}
.cb-root .cb-simrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:8px 0 10px;padding:6px 10px;
  border:1px dashed color-mix(in oklab,var(--cb-active) 50%,transparent);background:color-mix(in oklab,var(--cb-active) 5%,transparent);font-size:11px}
.cb-root .cb-field{display:grid;grid-template-rows:auto auto auto;gap:3px;min-width:0}
.cb-root .cb-field label{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-field input,.cb-root .cb-field select{width:100%;padding:5px 7px}
.cb-root .cb-field--err input{border-color:var(--cb-bad)}
.cb-root .cb-fhint{font-size:11px;color:var(--cb-fg-dim);min-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-field--wide .cb-fhint{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-textarea{width:100%;font:inherit;font-size:11px;color:var(--cb-fg);background:var(--cb-bg);border:1px solid var(--cb-stroke-strong);border-radius:2px;
  padding:6px 8px;resize:vertical;margin-top:4px}
.cb-root .cb-textarea:focus{outline:none;border-color:var(--cb-active)}
.cb-root .cb-inline-in{width:170px;padding:4px 7px;font-size:11px}

/* 05 FLASH */
.cb-root .cb-flashgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:10px}
.cb-root .cb-ports{display:grid;gap:4px}
.cb-root .cb-port{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:4px 6px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-port--sim{border-style:dashed}
.cb-root .cb-port--sel{border-color:color-mix(in oklab,var(--cb-active) 60%,var(--cb-stroke-strong));background:color-mix(in oklab,var(--cb-active) 6%,var(--cb-bg))}
.cb-root .cb-port-pick{display:flex;align-items:center;gap:8px;min-width:0;font-size:11px;overflow:hidden;text-align:left}
.cb-root .cb-port-pick > .cb-radio{flex:none}
.cb-root .cb-port-txt{display:grid;gap:1px;min-width:0;flex:1 1 auto}
.cb-root .cb-port-l1,.cb-root .cb-port-l2{display:flex;align-items:baseline;gap:8px;min-width:0}
.cb-root .cb-port-l1 > .cb-tagx,.cb-root .cb-port-l2 > .cb-ok{flex:none}
.cb-root .cb-port-pick b{font-weight:600;white-space:nowrap}
.cb-root .cb-radio{width:10px;height:10px;border-radius:50%;border:1px solid var(--cb-fg-dim);flex:none}
.cb-root .cb-port--sel .cb-radio{border-color:var(--cb-active);background:radial-gradient(circle,var(--cb-active) 0 3px,transparent 3.5px)}
.cb-root .cb-tagx{flex:none;padding:0 5px;border:1px solid var(--cb-stroke-strong);font-size:10px;letter-spacing:.12em;color:var(--cb-fg-dim)}
.cb-root .cb-detect{border-top:1px dashed var(--cb-stroke-strong);padding-top:8px}
.cb-root .cb-fwgrid{display:grid;grid-template-columns:minmax(0,1fr) 72px;gap:8px}
.cb-root .cb-meter{display:grid;grid-template-columns:44px minmax(0,1fr) 52px;gap:8px;align-items:center;font-size:11px}
.cb-root .cb-meter b{text-align:right;font-variant-numeric:tabular-nums}
.cb-root .cb-build{display:grid;gap:5px}

/* 06 DEBUG */
.cb-root .cb-debuggrid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);grid-template-rows:auto 1fr;gap:12px;margin-top:10px;align-items:start;
  grid-template-areas:"mon panic" "loop panic"}
.cb-root .cb-debuggrid > [data-cb=monitor]{grid-area:mon}.cb-root .cb-debuggrid > [data-cb=fix-loop]{grid-area:loop}
.cb-root .cb-debuggrid > [data-cb=panic-analysis],.cb-root .cb-debuggrid > [data-cb=debug-calm]{grid-area:panic}
.cb-root .cb-monrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.cb-root .cb-monrow select{min-width:0;flex:1 1 160px}
.cb-root .cb-bootok{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding:8px 10px;border:1px solid color-mix(in oklab,var(--cb-ok) 50%,transparent);
  background:color-mix(in oklab,var(--cb-ok) 6%,transparent)}
.cb-root .cb-bootok code{color:var(--cb-ok-text);font:inherit;font-weight:700}
.cb-root .cb-frames-t td{font-size:11px}
.cb-root .cb-frames-t td:nth-child(2){max-width:220px;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-interp{margin:2px 0 0;padding:0 0 0 14px;display:grid;gap:3px;line-height:1.5}
.cb-root .cb-draft{color:var(--cb-fg)}
.cb-root .cb-loop{margin:2px 0 0;padding:0;list-style:none;display:grid;gap:5px}
.cb-root .cb-loop-step{display:grid;grid-template-columns:14px max-content minmax(0,1fr);gap:8px;align-items:baseline;font-size:11px}
.cb-root .cb-loop-step b{font-weight:600;text-transform:uppercase;letter-spacing:.1em;font-size:10px;color:var(--cb-fg-dim)}
.cb-root .cb-loop-step--done b{color:var(--cb-fg)}.cb-root .cb-loop-step--cur b{color:var(--cb-active-text)}

/* 02 CALC */
.cb-root .cb-calcgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:10px}
.cb-root .cb-calc-in{margin-top:6px}
.cb-root .cb-kv--calc{grid-template-columns:max-content minmax(0,1fr)}
.cb-root .cb-kv--calc > b{white-space:normal;overflow-wrap:anywhere}

/* 03 WIRE */
.cb-root .cb-wireparams{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:4px 10px;margin:8px 0 2px}
/* the drawing fills the rest of the main area and scales into it (viewBox, meet); in the stacked layout it
   keeps its aspect ratio with a sensible minimum */
.cb-root .cb-main--fill{display:flex;flex-direction:column}
.cb-root .cb-main--fill > *{flex:none}
.cb-root .cb-main--fill > .cb-svgwrap{flex:1 1 auto}
.cb-root .cb-svgwrap{position:relative;border:1px solid var(--cb-stroke-strong);display:flex;
  justify-content:center;min-height:0}
.cb-root .cb-svgwrap .cb-svg{flex:1 1 auto;min-width:0;min-height:0;display:flex}
.cb-root .cb-svgwrap .cb-svg svg{width:100%;height:100%}
.cb-root .cb-svgcap{position:absolute;font-size:11px;color:var(--cb-fg-dim);pointer-events:none}
.cb-root .cb-svg{color:var(--cb-fg);width:100%}
.cb-root .cb-svg svg{display:block;width:100%;height:auto}
.cb-root .cb-svg text{fill:currentColor;stroke:none}
.cb-root .cb-svg [data-ref]{transition:color .12s,fill .12s}
.cb-root .cb-wiretable tr[aria-selected=true] td,.cb-root .cb-table tr[aria-selected=true] td{background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-wiretable td{font-size:11px}

/* 04 SOLDER */
.cb-root .cb-stale{max-width:900px;align-items:center;margin:0 0 12px}
.cb-root .cb-stale-t{display:grid;gap:2px;min-width:0}.cb-root .cb-stale-t b{font-weight:600}
.cb-root .cb-step{display:grid;grid-template-columns:24px 30px minmax(0,1fr);gap:10px;align-items:start;padding:9px 11px;border:1px solid var(--cb-stroke-strong);background:var(--cb-panel)}
.cb-root .cb-step--cur{border-color:var(--cb-active);background:color-mix(in oklab,var(--cb-active) 6%,var(--cb-panel));box-shadow:inset 3px 0 0 var(--cb-active)}
.cb-root .cb-step--cur .cb-check{box-shadow:var(--cb-glow-active)}
.cb-root .cb-step--done{background:color-mix(in oklab,var(--cb-ok) 3%,var(--cb-bg));border-color:var(--cb-stroke)}
.cb-root .cb-step--done .cb-step-n,.cb-root .cb-step--done .cb-step-head b{color:var(--cb-fg-dim)}
.cb-root .cb-step--done .cb-check{width:18px;height:18px;font-size:12px;box-shadow:none}
.cb-root .cb-step:not(.cb-step--done):not(.cb-step--cur) .cb-step-act{color:var(--cb-fg-dim)}
.cb-root .cb-step-refs{color:var(--cb-fg);font-weight:600}
.cb-root .cb-now{padding:0 6px;border:1px solid var(--cb-active);color:var(--cb-active-text);font-size:10px;letter-spacing:.16em;font-weight:700;box-shadow:var(--cb-glow-active)}
.cb-root .cb-check{width:20px;height:20px;border:1px solid var(--cb-fg-dim);border-radius:2px;display:inline-flex;align-items:center;justify-content:center;
  color:var(--cb-ink);font-weight:800;font-size:13px}
.cb-root .cb-check[aria-checked=true]{background:var(--cb-ok-fill);border-color:var(--cb-ok-fill);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-step--cur .cb-check{border-color:var(--cb-active)}
.cb-root .cb-step-n{font-size:15px;font-weight:700;color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;line-height:20px}
.cb-root .cb-step--cur .cb-step-n{color:var(--cb-active-text)}
.cb-root .cb-step-head b{text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--cb-fg)}
.cb-root .cb-step-hints{margin:5px 0 0;padding:0;list-style:none;display:grid;gap:2px;font-size:11px;line-height:1.45}

/* directive card + media card (chat) */
.cb-root.cb-dcard{position:relative;max-width:560px;margin:6px 0;padding:10px 12px;border:1px solid var(--cb-stroke-strong);background:var(--cb-bg);color:var(--cb-fg);
  background-image:linear-gradient(var(--cb-grid) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid) 1px,transparent 1px);background-size:24px 24px}
.cb-root .cb-dcard-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}
.cb-root .cb-brand--sm{font-size:11px;letter-spacing:.16em}
.cb-root .cb-dcard-head b{font-weight:700}
.cb-root .cb-dcard-hl{margin-top:8px;font-size:15px;font-weight:700;letter-spacing:.06em}
.cb-root .cb-kv--dcard{margin-top:6px}.cb-root .cb-kv--dcard > b{white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-svg--media{margin-top:8px}.cb-root .cb-svg--media svg{max-height:300px}
.cb-root .cb-svg--dcard{padding:8px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-panel) 85%,transparent)}
.cb-root .cb-svg--dcard svg{max-height:230px}
/* chat card: crash frames */
.cb-root .cb-dframe{margin-top:8px}.cb-root .cb-dframe:not(.cb-frame--top) .cb-f{color:var(--cb-fg-dim)}

/* settings page (app chrome: follows the app theme) */
.cb-root.cb-settings{max-width:760px;color:var(--cb-fg);font-size:12px}
.cb-root .cb-set-h{margin:0 0 4px;font-size:15px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-setrow{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid var(--cb-stroke)}
.cb-root .cb-settitle{font-weight:700;color:var(--cb-fg)}
.cb-root .cb-setdesc{color:var(--cb-fg-dim);line-height:1.5;margin-top:2px}
.cb-root .cb-setctl{display:flex;justify-content:flex-end}

/* console: timestamps off */
.cb-root .cb-log--nots .cb-line{grid-template-columns:minmax(0,1fr)}.cb-root .cb-log--nots .cb-ts{display:none}
.cb-root .cb-tabs .cb-meta .cb-simban{flex:none}
.cb-root .cb-consmeta{color:var(--cb-fg-dim);font-size:11px;overflow:hidden;text-overflow:ellipsis;min-width:0}
@container cb (max-width:1240px){.cb-root [data-cb=hud-link] .cb-simdev{display:none}}
/* narrow tile beside the chat: brand and project chip give way, the sim marker shrinks, the action stays */
@container cb (max-width:600px){.cb-root .cb-hud [data-cb=hud-brand],.cb-root .cb-hud [data-cb=hud-project]{display:none}
  .cb-root .cb-hud .cb-simban-w{display:none}}
@container cb (max-width:1099px){.cb-root .cb-flashgrid,.cb-root .cb-calcgrid,.cb-root .cb-debuggrid{grid-template-columns:minmax(0,1fr)}
  .cb-root .cb-debuggrid{grid-template-rows:none;grid-template-areas:"mon" "panic" "loop"}}
/* project manager (HUD project pill) */
.cb-root .cb-modal--wide{width:min(640px,100%)}
.cb-root .cb-note--ok{border-color:color-mix(in oklab,var(--cb-ok) 45%,transparent);color:var(--cb-ok-text)}
.cb-root .cb-projlist{list-style:none;margin:0;padding:0;display:grid;gap:6px;max-height:min(52vh,420px);overflow:auto}
.cb-root .cb-projrow{display:flex;align-items:center;gap:12px;padding:8px 10px;border:1px solid var(--cb-stroke-strong);min-width:0}
.cb-root .cb-projrow[aria-current=true]{border-color:color-mix(in oklab,var(--cb-ok) 45%,var(--cb-stroke-strong))}
.cb-root .cb-projmain{flex:1 1 auto;min-width:0;display:grid;gap:3px}
.cb-root .cb-projtitle{display:flex;align-items:center;gap:8px;min-width:0}
.cb-root .cb-projtitle b{color:var(--cb-fg);font-weight:600;white-space:nowrap}
.cb-root .cb-projmeta{font-size:11px;white-space:nowrap}
.cb-root .cb-projact,.cb-root .cb-projconfirm{display:flex;align-items:center;gap:6px;flex:none}
.cb-root .cb-hud-count{min-width:16px;padding:0 4px;border-radius:2px;text-align:center;font-variant-numeric:tabular-nums}
@container cb (max-width:380px){.cb-root .cb-hud [data-cb=hud-projects] .cb-hud-count{display:none}}
/* parts list (02 CALC inspector): remove per row */
.cb-root .cb-part-x{width:1%}
.cb-root .cb-part-x .cb-iconbtn:hover{color:var(--cb-bad-text);border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent)}
.cb-root .cb-part-acts{display:inline-flex;gap:6px;justify-content:flex-end}
.cb-root .cb-part-ask td{background:color-mix(in oklab,var(--cb-warn) 7%,transparent)}
@keyframes cb-indet{from{left:0}to{left:70%}}
/* chips and boards (S2, C6, S3 variants, WT32-ETH01); state never by colour alone */
/* PLAN toolbar selects (DevKit by chip, S3 module by PSRAM kind): same height and frame as the segmented controls */
.cb-root .cb-tsel{height:29px;padding:0 6px;font-size:12px;max-width:200px;border-radius:2px;cursor:pointer}
.cb-root .cb-tsel:hover{border-color:var(--cb-active)}

/* PLAN: compact what-if line and toolbar spacing, so a 2×22 DevKit (S2) fits at 1440×900 in what-if too */
.cb-root .cb-whatif{padding:3px 10px;margin:0 0 8px}
.cb-root [data-cb=plan-toolbar] .cb-whatif{margin:0;flex:none;white-space:nowrap}
.cb-root .cb-whatif .cb-btn--sm{padding:2px 8px}
.cb-root [data-cb=plan-toolbar]{row-gap:6px}
.cb-root [data-cb=station-plan] .cb-legend{margin-bottom:8px}
.cb-root .cb-shell[data-cb-cons=open] [data-cb=station-plan] .cb-board{padding:6px 0 8px}
/* long board labels (WT32 "485_EN") widen their name cell instead of being clipped; names stay aligned to the pads */
.cb-root .cb-col--l .cb-pin{grid-template-columns:minmax(0,1fr) minmax(40px,max-content) 14px}
.cb-root .cb-col--r .cb-pin{grid-template-columns:14px minmax(40px,max-content) minmax(0,1fr)}

/* board-level warnings: one line each above the board (PLAN), a card in the inspector */
.cb-root .cb-bwarns{margin:0 0 8px}
.cb-root .cb-bwarn-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px}
.cb-root .cb-bwarn{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:10px;align-items:baseline;padding:4px 8px;
  border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);font-size:12px;line-height:1.4}
.cb-root .cb-bwarn-k{font-size:10px;font-weight:700;letter-spacing:.14em;padding:1px 6px;border-radius:2px;white-space:nowrap}
.cb-root .cb-bwarn--bad{border-color:color-mix(in oklab,var(--cb-bad) 70%,transparent);border-left:3px solid var(--cb-bad);
  background:color-mix(in oklab,var(--cb-bad) 8%,var(--cb-panel))}
.cb-root .cb-bwarn--bad .cb-bwarn-k{color:var(--cb-ink);background:var(--cb-bad-fill)}
.cb-root .cb-bwarn--bad .cb-bwarn-m{color:var(--cb-fg);font-weight:600}
.cb-root .cb-bwarn--warn{border-color:color-mix(in oklab,var(--cb-warn) 55%,transparent);border-left:3px solid var(--cb-warn)}
.cb-root .cb-bwarn--warn .cb-bwarn-k{color:var(--cb-warn-text);border:1px solid color-mix(in oklab,var(--cb-warn) 60%,transparent)}
.cb-root .cb-bwarn--dim .cb-bwarn-k{color:var(--cb-fg-dim);border:1px solid var(--cb-stroke-strong)}
.cb-root .cb-bwarn-card .cb-bwarn-list{margin-top:8px}
.cb-root .cb-bwarn-card .cb-bwarn{grid-template-columns:minmax(0,1fr);gap:3px}
.cb-root .cb-bwarn-card .cb-bwarn-k{justify-self:start}

/* shared header tables (WT32: PROG then IO on each side) */
.cb-root .cb-hdr-sep{height:14px;display:flex;align-items:center;justify-content:center;color:var(--cb-fg-dim);gap:6px}
.cb-root .cb-hdr-sep::before,.cb-root .cb-hdr-sep::after{content:"";flex:1 1 auto;border-top:1px dashed var(--cb-stroke-strong)}

/* nc and signal pins: own pad shapes, plus the word in the tag */
.cb-root .cb-pin[data-cb-state=nc] .cb-name{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-pin[data-cb-state=nc] .cb-pad{border-style:dashed;border-radius:1px;
  background:linear-gradient(45deg,transparent calc(50% - 1px),var(--cb-fg-dim) calc(50% - 1px) calc(50% + 1px),transparent calc(50% + 1px))}
.cb-root .cb-pin[data-cb-state=nc] .cb-ptag,.cb-root .cb-pin[data-cb-state=signal] .cb-ptag{color:var(--cb-fg-dim);border:1px dashed var(--cb-stroke-strong)}
.cb-root .cb-pin[data-cb-state=nc] .cb-ptag{letter-spacing:.02em}
.cb-root .cb-pin[data-cb-state=signal] .cb-name{color:var(--cb-fg-dim);font-weight:600}
.cb-root .cb-pin[data-cb-state=signal] .cb-pad{border-style:dotted;border-color:var(--cb-fg-dim);border-radius:1px}

/* module drawing: no buttons → nothing drawn */
.cb-root .cb-btns:empty{display:none}
`

// --- 12-styles.js
// Styles: one <style> per surface root, every selector under .cb-root. No Tailwind classes.

const CB_CSS = CB_TOKEN_CSS + `
.cb-root{font-family:var(--cb-mono);font-size:12px;line-height:1.45;color:var(--cb-fg);-webkit-font-smoothing:antialiased;
  font-variant-ligatures:none;text-align:left}
.cb-root *,.cb-root *::before,.cb-root *::after{box-sizing:border-box}
.cb-root button{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer;text-align:inherit;letter-spacing:inherit}
.cb-root button:disabled{cursor:default}
.cb-root :focus-visible{outline:1px solid var(--cb-active);outline-offset:2px}
.cb-root input,.cb-root select{font:inherit;color:var(--cb-fg);background:var(--cb-bg);border:1px solid var(--cb-stroke-strong);
  border-radius:2px;padding:6px 8px;outline:none;min-width:0}
.cb-root input::placeholder{color:var(--cb-fg-dim);opacity:.8}
.cb-root input:focus,.cb-root select:focus{border-color:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-ok{color:var(--cb-ok-text)}.cb-root .cb-warn{color:var(--cb-warn-text)}.cb-root .cb-bad{color:var(--cb-bad-text)}
.cb-root .cb-active{color:var(--cb-active-text)}.cb-root .cb-power{color:var(--cb-power-text)}.cb-root .cb-faint{color:var(--cb-fg-faint)}
.cb-root .cb-dim{color:var(--cb-fg-dim)}.cb-root .cb-fg{color:var(--cb-fg)}
.cb-root .cb-label{text-transform:uppercase;letter-spacing:.14em;font-size:10px;color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cb-root .cb-mono-num{font-variant-numeric:tabular-nums}

/* page shell */
.cb-root.cb-page{position:relative;width:100%;height:100%;min-height:0;overflow:hidden;background:var(--cb-bg);container:cb/size}
.cb-root.cb-page::after,.cb-root.cb-pane::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:40;
  background:repeating-linear-gradient(to bottom,transparent 0 2px,var(--cb-scan) 2px 3px)}
.cb-root .cb-shell{position:absolute;inset:0;display:grid;--cb-rail-w:188px;--cb-insp-w:340px;--cb-cons-h:184px;
  grid-template-rows:52px minmax(0,1fr) var(--cb-cons-h);grid-template-columns:var(--cb-rail-w) minmax(0,1fr) var(--cb-insp-w);
  grid-template-areas:"hud hud hud" "rail main insp" "rail cons cons"}
.cb-root .cb-shell[data-cb-cons=collapsed],.cb-root .cb-shell[data-cb-cons=pane],.cb-root .cb-shell[data-cb-cons=idle]{--cb-cons-h:34px}
/* 06 DEBUG: the log is the subject, the panic block (≈15 lines) needs the room */
.cb-root[data-cb-station=debug] .cb-shell[data-cb-cons=open]{--cb-cons-h:260px}
.cb-root .cb-shell[data-cb-insp=none]{grid-template-columns:var(--cb-rail-w) minmax(0,1fr);grid-template-areas:"hud hud" "rail main" "rail cons"}
.cb-root .cb-work{display:contents}
.cb-root .cb-main{grid-area:main;position:relative;min-width:0;min-height:0;overflow:auto;padding:14px 18px 18px;
  --cb-grid-q:color-mix(in oklab,var(--cb-grid) 60%,transparent);
  background-color:var(--cb-bg);background-image:linear-gradient(var(--cb-grid-q) 1px,transparent 1px),
  linear-gradient(90deg,var(--cb-grid-q) 1px,transparent 1px);background-size:24px 24px;scrollbar-width:thin;
  scrollbar-color:var(--cb-stroke-strong) transparent}
.cb-root .cb-insp{grid-area:insp;min-width:0;min-height:0;overflow:auto;border-left:1px solid var(--cb-stroke);padding:12px 14px;
  display:flex;flex-direction:column;gap:10px;background:var(--cb-bg);scrollbar-width:thin;scrollbar-color:var(--cb-stroke-strong) transparent}
.cb-root .cb-station{animation:cb-fadein .12s ease-out}

/* HUD */
.cb-root .cb-hud{grid-area:hud;display:flex;align-items:center;gap:6px;padding:0 12px;min-width:0;white-space:nowrap;
  border-bottom:1px solid var(--cb-stroke);background:linear-gradient(to bottom,color-mix(in oklab,var(--cb-fg) 3%,var(--cb-bg)),var(--cb-bg));
  overflow:hidden}
.cb-root .cb-brand{display:flex;align-items:baseline;gap:8px;font-weight:700;letter-spacing:.18em;font-size:14px;color:var(--cb-ok-text);
  text-shadow:var(--cb-glow-ok);flex:none}
.cb-root .cb-brand small{font-weight:400;letter-spacing:.1em;font-size:11px;color:var(--cb-fg-dim);text-shadow:none}
.cb-root .cb-sep{width:1px;height:24px;background:var(--cb-stroke-strong);flex:none}
.cb-root .cb-pill{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 8px;border:1px solid var(--cb-stroke-strong);
  background:var(--cb-panel);border-radius:2px;white-space:nowrap;min-width:0;flex:0 0 auto;overflow:hidden}
.cb-root .cb-pill[data-cb=hud-link]{flex:0 1 auto}
.cb-root .cb-pill[data-cb=hud-project]{flex:0 1 auto;min-width:72px}
.cb-root .cb-pill b{color:var(--cb-fg);font-weight:600;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root button.cb-pill:hover{border-color:var(--cb-fg-faint)}
.cb-root .cb-hudsim{display:inline-flex;align-items:center;gap:6px;flex:none;min-width:0}
.cb-root .cb-hudsim .cb-simdev{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--cb-fg-faint)}
/* static */
.cb-root .cb-dot--ok{background:var(--cb-ok);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-dot--active{background:var(--cb-active);box-shadow:var(--cb-glow-active)}
.cb-root .cb-dot--off{background:transparent;border:1px solid var(--cb-fg-dim)}
.cb-root .cb-dot--bad{background:var(--cb-bad);box-shadow:var(--cb-glow-bad)}
.cb-root .cb-kpis{display:flex;gap:0;margin-left:auto;flex:none}
.cb-root .cb-kpi{display:flex;flex-direction:column;gap:1px;padding:0 8px;border-left:1px solid var(--cb-stroke-strong);white-space:nowrap;flex:none}
.cb-root .cb-kpi .cb-v{display:inline-flex;align-items:baseline;font-size:12px;font-weight:400;font-variant-numeric:tabular-nums;line-height:16px;color:var(--cb-fg)}
.cb-root .cb-kpi .cb-v b{font-weight:700}
.cb-root .cb-kpi .cb-v small{font-size:10px;font-weight:400;color:var(--cb-fg-dim);margin-left:6px;text-transform:uppercase;letter-spacing:.06em}
/* key figures as words: symbol + number in the state colour, the word in fg; narrow: symbol + number only */
.cb-root .cb-kpi-i{display:inline-flex;align-items:baseline;gap:3px}
.cb-root .cb-kpi-i + .cb-kpi-i{margin-left:10px}
.cb-root .cb-kpi-i .cb-kpi-w{color:var(--cb-fg);margin-left:1px}
.cb-root .cb-kpi-i.cb-dim .cb-kpi-w{color:var(--cb-fg-dim)}
.cb-root .cb-kpi-bar{margin-left:6px;letter-spacing:-.05em}
.cb-root .cb-hud .cb-btn{flex:none}

/* buttons, segments, chips */
.cb-root .cb-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--cb-ink);background:var(--cb-ok-fill);height:28px;padding:0 12px;line-height:1;border:1px solid transparent;border-radius:2px;
  box-shadow:var(--cb-glow-ok);font-weight:700;white-space:nowrap;flex:none}
.cb-root .cb-btn:hover{background:color-mix(in oklab,var(--cb-ok-fill) 86%,white)}
.cb-root .cb-btn--ghost{background:transparent;color:var(--cb-fg);border-color:var(--cb-fg-faint);box-shadow:none}
.cb-root .cb-btn--ghost:hover{background:var(--cb-panel);border-color:var(--cb-fg-dim)}
.cb-root .cb-btn--quiet{background:transparent;color:var(--cb-fg-dim);border-color:var(--cb-stroke-strong);box-shadow:none;padding:0 10px;font-weight:600}
.cb-root .cb-btn--quiet:hover{color:var(--cb-fg);border-color:var(--cb-fg-faint);background:var(--cb-panel)}
.cb-root .cb-btn--warn{background:var(--cb-warn-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-btn--danger{background:var(--cb-bad-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-bad)}
.cb-root .cb-btn--danger:hover{background:color-mix(in oklab,var(--cb-bad-fill) 86%,white)}
.cb-root .cb-btn--sm{height:24px;padding:0 8px;font-size:10px}
.cb-root .cb-btn--lg{height:32px;padding:0 16px}
.cb-root .cb-btn:disabled{opacity:.45;box-shadow:none;filter:saturate(.4)}
.cb-root .cb-seg{display:inline-flex;border:1px solid var(--cb-stroke-strong);border-radius:2px;flex:none}
.cb-root .cb-seg button{height:26px;padding:0 10px;color:var(--cb-fg-dim);border-right:1px solid var(--cb-stroke-strong);white-space:nowrap}
.cb-root .cb-seg button:last-child{border-right:0}
.cb-root .cb-seg button:hover{color:var(--cb-fg);background:var(--cb-panel)}
.cb-root .cb-seg button[aria-pressed=true]{color:var(--cb-ink);background:var(--cb-active-fill);box-shadow:var(--cb-glow-active);font-weight:700}
.cb-root .cb-chipbtn{padding:4px 9px;border:1px solid color-mix(in oklab,var(--cb-ok) 60%,transparent);color:var(--cb-ok-text);border-radius:2px;
  font-variant-numeric:tabular-nums}
.cb-root .cb-chipbtn:hover,.cb-root .cb-chipbtn[aria-pressed=true]{background:color-mix(in oklab,var(--cb-ok) 14%,transparent);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-tag{display:inline-block;padding:1px 6px;border:1px solid var(--cb-stroke-strong);color:var(--cb-fg-dim);font-size:10px;border-radius:2px;text-transform:uppercase;letter-spacing:.06em}
.cb-root .cb-stamp{display:inline-block;padding:3px 8px;font-weight:800;letter-spacing:.2em;font-size:11px;color:var(--cb-ink);
  background:var(--cb-bad-fill);box-shadow:var(--cb-glow-bad);border-radius:1px;white-space:nowrap}
.cb-root .cb-stamp--warn{background:var(--cb-warn-fill);box-shadow:var(--cb-glow-warn)}
.cb-root .cb-stamp--ok{background:var(--cb-ok-fill);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-stamp--none{background:transparent;color:var(--cb-fg-dim);border:1px solid var(--cb-stroke-strong);box-shadow:none}
.cb-root .cb-stamp--active{background:var(--cb-active-fill);box-shadow:var(--cb-glow-active)}

/* corner brackets */
.cb-root .cb-bracket{position:relative}
.cb-root .cb-bracket::before,.cb-root .cb-bracket::after{content:"";position:absolute;width:10px;height:10px;border-color:var(--cb-ok);opacity:.45;pointer-events:none}
.cb-root .cb-bracket::before{top:-1px;left:-1px;border-top:1px solid;border-left:1px solid}
.cb-root .cb-bracket::after{bottom:-1px;right:-1px;border-bottom:1px solid;border-right:1px solid}
.cb-root .cb-bracket--bad::before,.cb-root .cb-bracket--bad::after{border-color:var(--cb-bad)}

/* rail */
.cb-root .cb-rail{grid-area:rail;border-right:1px solid var(--cb-stroke);padding:14px 10px 12px;display:flex;flex-direction:column;
  gap:0;background:var(--cb-bg);min-height:0;overflow:auto;scrollbar-width:none}
.cb-root .cb-rail-label{margin:0 0 10px 8px}
.cb-root .cb-stage{display:grid;grid-template-columns:16px minmax(0,1fr) auto;align-items:center;gap:8px 6px;padding:6px 8px;min-height:40px;
  border:1px solid transparent;color:var(--cb-fg-dim);border-radius:1px;width:100%;position:relative}
.cb-root .cb-stage:hover{background:var(--cb-panel);color:var(--cb-fg)}
.cb-root .cb-stage-ic{width:16px;height:16px;flex:none;overflow:visible;color:var(--cb-fg-dim)}
.cb-root .cb-stage-txt{display:flex;flex-direction:column;gap:1px;min-width:0}
.cb-root .cb-stage-l1{display:flex;align-items:baseline;gap:6px;min-width:0}
.cb-root .cb-stage .cb-n{color:var(--cb-fg-dim);font-size:10px;font-variant-numeric:tabular-nums;flex:none}
.cb-root .cb-stage .cb-t{letter-spacing:.12em;text-transform:uppercase;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-stage .cb-sw{font-size:10px;letter-spacing:.04em;color:var(--cb-fg-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-stage .cb-s{font-size:11px;font-variant-numeric:tabular-nums;white-space:nowrap;display:inline-flex;align-items:center;gap:3px}
.cb-root .cb-stage .cb-s-g{flex:none;overflow:visible}
.cb-root .cb-stage .cb-s[data-cb-mark=panic]{font-weight:700;letter-spacing:.08em}
/* current station: panel surface, frame and a short green edge (identity accent), no green fill or glow (L8) */
.cb-root .cb-stage[aria-current=page]{border-color:var(--cb-stroke-strong);color:var(--cb-fg);background:var(--cb-panel);box-shadow:inset 2px 0 0 var(--cb-ok)}
.cb-root .cb-stage[aria-current=page] .cb-t{font-weight:700}
.cb-root .cb-stage[aria-current=page] .cb-stage-ic{color:var(--cb-fg)}
.cb-root .cb-stage[data-cb-tone=bad] .cb-stage-ic{color:var(--cb-bad-text)}
.cb-root .cb-stage[data-cb-alert=true] .cb-s{color:var(--cb-bad-text);text-shadow:var(--cb-glow-bad)}
/* Wow 4: the fix loop closed — each station lights up once, top to bottom */
.cb-root .cb-rail[data-cb-sweep=on] .cb-stage{animation:cb-sweep .9s ease-out both;animation-delay:calc(var(--cb-i,0) * 140ms)}
.cb-root .cb-trace{margin:0 0 0 16px;width:2px;flex:0 0 6px;background:var(--cb-stroke-strong)}
.cb-root .cb-trace[data-cb-done=true]{background:color-mix(in oklab,var(--cb-ok) 55%,var(--cb-stroke-strong))}
.cb-root .cb-rail-foot{margin-top:auto;border-top:1px solid var(--cb-stroke);padding:12px 6px 0;display:grid;gap:6px;color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-rail-foot div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* station title + toolbar */
.cb-root .cb-title{display:flex;align-items:baseline;gap:12px;min-width:0;flex-wrap:wrap;row-gap:4px}
.cb-root .cb-title h1{margin:0;font-size:18px;letter-spacing:.24em;font-weight:700;color:var(--cb-fg);
  display:inline-flex;align-items:baseline;white-space:nowrap;line-height:1.2}
.cb-root .cb-title h1 .cb-decode{font-size:18px;letter-spacing:.24em;font-weight:700;color:inherit;font-family:var(--cb-mono)}
.cb-root .cb-cursor{display:inline-block;width:9px;height:15px;background:var(--cb-ok);margin-left:6px;transform:translateY(2px);
  box-shadow:var(--cb-glow-ok);animation:cb-blink 1s steps(2) 3}
.cb-root .cb-toolbar{display:flex;gap:8px;margin:10px 0 8px;align-items:center;flex-wrap:wrap;row-gap:8px}
.cb-root .cb-toolbar .cb-push{margin-left:auto}
.cb-root .cb-group{display:inline-flex;align-items:center;gap:8px;padding-right:10px;border-right:1px solid var(--cb-stroke)}
.cb-root .cb-group > .cb-label{flex:none}
.cb-root .cb-switch{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border:1px solid var(--cb-stroke-strong);
  color:var(--cb-fg-dim);border-radius:2px;white-space:nowrap}
.cb-root .cb-switch[aria-checked=true]{color:var(--cb-active-text);border-color:color-mix(in oklab,var(--cb-active) 55%,transparent)}
.cb-root .cb-switch i{width:22px;height:10px;border:1px solid currentColor;border-radius:6px;position:relative;display:inline-block}
.cb-root .cb-switch i::after{content:"";position:absolute;top:1px;left:1px;width:6px;height:6px;border-radius:50%;background:currentColor}
.cb-root .cb-switch[aria-checked=true] i::after{left:13px}
.cb-root .cb-whatif{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  border:1px dashed color-mix(in oklab,var(--cb-active) 55%,transparent);color:var(--cb-active-text);background:color-mix(in oklab,var(--cb-active) 6%,transparent)}
.cb-root .cb-note{display:flex;align-items:center;gap:10px;margin:0 0 12px;padding:7px 10px;border:1px solid var(--cb-stroke-strong);
  background:var(--cb-panel);color:var(--cb-fg)}
.cb-root .cb-note--warn{border-color:color-mix(in oklab,var(--cb-warn) 50%,transparent);color:var(--cb-warn-text)}
.cb-root .cb-note--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent);color:var(--cb-bad-text)}
.cb-root .cb-note .cb-x{margin-left:auto;color:var(--cb-fg-dim)}

/* inspector + cards + tables */
.cb-root .cb-card{border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);padding:11px 12px;min-width:0}
.cb-root .cb-card-head{display:flex;align-items:center;gap:8px;min-width:0;min-height:24px}
.cb-root .cb-card-head .cb-label:last-child,.cb-root .cb-card-head .cb-push{margin-left:auto}
.cb-root .cb-verdict{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-verdict .cb-big{font-size:22px;font-weight:800;letter-spacing:.08em;font-variant-numeric:tabular-nums}
.cb-root .cb-why{margin:8px 0 0;line-height:1.55;color:var(--cb-fg)}
.cb-root .cb-nowrap{white-space:nowrap}
.cb-root .cb-why b{color:var(--cb-fg);font-weight:700}
.cb-root .cb-why em{color:var(--cb-warn-text);font-style:normal}
.cb-root .cb-fn{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.cb-root .cb-src{margin-top:9px;display:flex;align-items:baseline;gap:8px;color:var(--cb-active-text);font-size:11px;min-width:0}
.cb-root .cb-src .cb-k{color:var(--cb-fg-dim);flex:none}
.cb-root .cb-src button{color:var(--cb-active-text);text-align:left;min-width:0;line-height:1.45}
.cb-root .cb-src button:hover{text-decoration:underline}
.cb-root .cb-alts{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.cb-root .cb-modes-sum{display:flex;gap:10px;align-items:baseline;margin-top:8px;font-size:11px}
.cb-root .cb-modes-sum .cb-label{flex:none}
.cb-root table.cb-table{width:100%;border-collapse:collapse;margin-top:6px}
.cb-root .cb-table td,.cb-root .cb-table th{padding:4px 4px;border-bottom:1px dashed var(--cb-stroke-strong);text-align:left;white-space:nowrap}
.cb-root .cb-table th{font-weight:400}
.cb-root .cb-table td.cb-r,.cb-root .cb-table th.cb-r{text-align:right}
.cb-root .cb-table tr[data-cb-row]{cursor:pointer}
.cb-root .cb-table tr[data-cb-row]:hover td{background:color-mix(in oklab,var(--cb-fg) 5%,transparent)}
.cb-root .cb-table tr[data-cb-pulse=true] td{animation:cb-rowpulse .6s ease-in-out 2}
.cb-root .cb-table .cb-x{color:var(--cb-fg-faint);padding:0 4px}
.cb-root .cb-table .cb-x:hover{color:var(--cb-bad-text)}
.cb-root .cb-hint{color:var(--cb-warn-text);margin-top:10px;line-height:1.5}

/* console + panic card (pane) / panic strip (page) */
.cb-root .cb-cons{grid-area:cons;border-top:1px solid var(--cb-stroke-strong);display:grid;grid-template-columns:minmax(0,1fr) auto;
  background:var(--cb-cons-bg);min-height:0;min-width:0}
.cb-root .cb-cons--page{display:flex;flex-direction:column}
.cb-root .cb-cons--page > .cb-console{flex:1 1 auto}
.cb-root .cb-panicstrip{flex:none;display:flex;align-items:center;gap:12px;min-width:0;height:30px;padding:0 8px 0 12px;
  border-bottom:1px solid var(--cb-stroke);box-shadow:inset 3px 0 0 var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 7%,transparent)}
.cb-root .cb-panicstrip-mark{flex:none;font-weight:800;font-size:11px;letter-spacing:.16em;color:var(--cb-bad-text)}
.cb-root .cb-panicstrip-t{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-panicstrip-at{color:var(--cb-fg-dim)}
.cb-root .cb-panicstrip .cb-panic-actions{flex:none;margin:0}
.cb-root .cb-console{display:flex;flex-direction:column;min-height:0;min-width:0;container:cbcons/inline-size}
.cb-root .cb-tabs{display:flex;align-items:stretch;border-bottom:1px solid var(--cb-stroke);min-width:0;flex:none;height:33px}
.cb-root .cb-tabs [role=tab]{flex:none;padding:0 14px;color:var(--cb-fg-dim);letter-spacing:.14em;font-size:10px;border-right:1px solid var(--cb-stroke);
  display:inline-flex;align-items:center;gap:6px;text-transform:uppercase}
.cb-root .cb-tabs [role=tab]:hover{color:var(--cb-fg)}
.cb-root .cb-tabs [role=tab][aria-selected=true]{color:var(--cb-fg);background:var(--cb-panel);box-shadow:inset 0 -2px 0 var(--cb-ok)}
/* the bar never runs over the tabs: overflow is cut at the meta's own edge (safe end alignment), the port line shrinks
   first, narrow consoles drop the sim chip (the HUD shows it) and shorten the buttons */
.cb-root .cb-tabs .cb-meta{flex:1 1 auto;display:flex;align-items:center;justify-content:safe flex-end;gap:8px;padding:0 8px 0 12px;min-width:0;
  white-space:nowrap;overflow:hidden}
.cb-root .cb-tabs .cb-meta > .cb-consmeta{min-width:0}
/* the SIM badge never gives way (SIMULATED visible wherever a Bench surface is); only its word BOARD */
@container cbcons (max-width:760px){.cb-root .cb-tabs .cb-meta > .cb-simban .cb-simban-w{display:none}.cb-root .cb-tabs [role=tab]{padding:0 10px}
  .cb-root .cb-tabs .cb-meta > .cb-consmeta{display:none}}
@container cbcons (max-width:600px){.cb-root .cb-cmd-long{display:none}}
.cb-root .cb-tabs .cb-meta > .cb-label{overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root .cb-tabs .cb-meta > button{flex:none}
/* tools never give way to the meta */
.cb-root .cb-cons-tools{flex:none;display:flex;align-items:center;gap:8px;padding:0 8px 0 0}
.cb-root .cb-iconbtn{display:inline-flex;align-items:center;justify-content:center;height:24px;color:var(--cb-fg-dim);padding:0 8px;border:1px solid var(--cb-stroke);
  border-radius:2px;font-size:11px;white-space:nowrap;line-height:1}
.cb-root .cb-iconbtn:hover{color:var(--cb-fg);border-color:var(--cb-stroke-strong)}
.cb-root .cb-log-inner{min-height:100%}
.cb-root .cb-log{flex:1 1 auto;min-height:0;overflow:auto;padding:7px 14px 10px;line-height:1.6;font-size:11.5px;color:var(--cb-fg-dim);
  scrollbar-width:thin;scrollbar-color:var(--cb-stroke-strong) transparent;position:relative}
.cb-root .cb-line{display:grid;grid-template-columns:12.5ch minmax(0,1fr);column-gap:8px;min-height:1.6em}
.cb-root .cb-line--blank{min-height:.8em}.cb-root .cb-line--blank .cb-ts{visibility:hidden}
.cb-root .cb-line > span:last-child{white-space:pre-wrap;overflow-wrap:anywhere}
.cb-root .cb-line .cb-ts{color:var(--cb-fg-dim);opacity:.8;font-variant-numeric:tabular-nums}
.cb-root .cb-line--hl{color:var(--cb-fg)}
.cb-root .cb-line--rom{color:var(--cb-fg-dim)}
.cb-root .cb-line--panic{color:var(--cb-bad-text);font-weight:700}
.cb-root .cb-panicblk{position:relative;margin:2px 0 2px -10px;padding:0 0 0 8px;border-left:2px solid var(--cb-bad);
  background:linear-gradient(to right,color-mix(in oklab,var(--cb-bad) 7%,transparent),transparent 70%);overflow-x:auto;scrollbar-width:thin}
/* dump lines never break inside a value */
.cb-root .cb-panicblk .cb-line + .cb-line > span:last-child{white-space:pre;overflow-wrap:normal}
@container cbcons (max-width:820px){.cb-root .cb-panicblk .cb-line + .cb-line{grid-template-columns:minmax(0,1fr)}
  .cb-root .cb-panicblk .cb-line + .cb-line .cb-ts{display:none}}
/* outside 06 DEBUG the strip is the only alarm */
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-panicblk{background:none}
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-line--panic{color:var(--cb-fg)}
.cb-root.cb-page:not([data-cb-station=debug]) .cb-cons--page .cb-line--bt{color:var(--cb-fg-dim)}
.cb-root .cb-panicblk:not(.cb-panicblk--live){border-left-style:dashed}
.cb-root .cb-pjump{flex:none;color:var(--cb-fg-dim)}
.cb-root .cb-pjump--live{color:var(--cb-bad-text);border-color:var(--cb-bad)}
.cb-root .cb-cons-idle{flex:1 1 auto;display:inline-flex;align-items:baseline;gap:8px;min-width:0;color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-cons-idle .cb-linkbtn,.cb-root .cb-cons-empty .cb-linkbtn{flex:none}
.cb-root .cb-line--bt{color:color-mix(in oklab,var(--cb-bad) 72%,var(--cb-fg))}
.cb-root .cb-line--gap,.cb-root .cb-line--epoch{color:var(--cb-warn-text);font-style:normal}
.cb-root .cb-cons-empty{padding:16px 14px;color:var(--cb-fg-dim);display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.cb-root .cb-panic{width:440px;border-left:1px solid var(--cb-stroke-strong);padding:10px 14px;display:flex;flex-direction:column;gap:7px;
  background:linear-gradient(to right,color-mix(in oklab,var(--cb-bad) 9%,transparent),transparent 60%);min-height:0;overflow:hidden;min-width:0}
.cb-root .cb-panic > *{flex:none}
.cb-root .cb-panic > .cb-frames{flex:0 1 auto;min-height:0;overflow:hidden}
.cb-root .cb-panic-hint{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.cb-root .cb-panic-actions{margin-top:auto}
.cb-root .cb-alarm{display:flex;align-items:center;gap:10px;min-width:0;flex-wrap:wrap;row-gap:4px}
/* one pulse */
.cb-root .cb-alarm .cb-stamp{animation:cb-pulse .6s ease-in-out 1}
.cb-root .cb-alarm .cb-label:last-child,.cb-root .cb-alarm .cb-elf{margin-left:auto}
.cb-root .cb-elf{font-size:11px;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.cb-root .cb-elf--ok{color:var(--cb-ok-text)}.cb-root .cb-elf--bad{color:var(--cb-bad-text)}.cb-root .cb-elf--faint{color:var(--cb-fg-dim)}
.cb-root .cb-frames{display:grid;gap:4px}
.cb-root .cb-frame{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:8px;padding:4px 8px;font-size:11px;border:1px solid var(--cb-stroke);background:var(--cb-panel);min-width:0}
.cb-root .cb-frame .cb-i{color:var(--cb-fg-dim)}
.cb-root .cb-frame .cb-f{color:var(--cb-fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.cb-root .cb-frame .cb-l{color:var(--cb-active-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px}
.cb-root .cb-panic .cb-hint{line-height:1.4}
.cb-root .cb-frame--top{border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}
.cb-root .cb-frame--top .cb-f{color:var(--cb-bad-text)}
.cb-root .cb-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}

/* notices as toasts (no layout shift) */
.cb-root .cb-toasts{position:absolute;top:12px;right:18px;z-index:6;display:grid;gap:6px;max-width:min(440px,72%);pointer-events:none}
.cb-root .cb-toasts .cb-note{margin:0;pointer-events:auto;box-shadow:0 8px 24px rgba(0,0,0,.45)}

/* empty / error / loading */
.cb-root .cb-empty{max-width:560px;margin:40px auto 0;padding:24px;border:1px solid var(--cb-stroke-strong);background:var(--cb-panel)}
.cb-root .cb-empty h2{display:flex;align-items:baseline;gap:8px;margin:8px 0;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg)}
.cb-root .cb-empty .cb-actions{margin-top:16px}
.cb-root .cb-empty-mark{flex:none}
.cb-root .cb-empty p{margin:0 0 6px;color:var(--cb-fg-dim);line-height:1.6}
.cb-root .cb-empty code{color:var(--cb-active-text)}
.cb-root .cb-empty--bad h2{color:var(--cb-bad-text)}
.cb-root .cb-empty--warn h2{color:var(--cb-warn-text)}
.cb-root .cb-loading{padding:40px;color:var(--cb-fg-dim);letter-spacing:.14em;text-transform:uppercase;font-size:11px}
.cb-root .cb-loading::after{content:"▌";margin-left:4px;color:var(--cb-ok-text);animation:cb-blink 1s steps(2) infinite}

/* modal (own DOM, inside the page root) */
.cb-root .cb-modal-back{position:absolute;inset:0;z-index:60;background:color-mix(in oklab,black 78%,transparent);backdrop-filter:blur(1.5px);display:flex;align-items:center;justify-content:center;padding:20px}
.cb-root .cb-modal{width:min(440px,100%);border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);padding:16px 18px;
  box-shadow:0 20px 60px rgba(0,0,0,.6)}
.cb-root .cb-modal h2{margin:4px 0 12px;font-size:14px;letter-spacing:.16em;text-transform:uppercase;color:var(--cb-fg)}
.cb-root .cb-form{display:grid;grid-template-columns:72px minmax(0,1fr);gap:9px 12px;align-items:center}
.cb-root .cb-form label{color:var(--cb-fg-dim);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
.cb-root .cb-form .cb-err{grid-column:2;color:var(--cb-bad-text);font-size:11px;margin-top:-4px}
.cb-root .cb-modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.cb-root .cb-modal .cb-preview{margin-top:12px;padding:8px 10px;border:1px dashed var(--cb-stroke-strong);color:var(--cb-fg-dim);line-height:1.5}

/* placeholders */
.cb-root .cb-soon{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-top:8px}
.cb-root .cb-soon .cb-card{color:var(--cb-fg-dim);line-height:1.6}
.cb-root .cb-soon .cb-card b{color:var(--cb-fg);display:block;margin:0 0 4px;letter-spacing:.06em}
.cb-root .cb-soon .cb-card b.cb-ok{color:var(--cb-ok-text)}

/* serial pane */
.cb-root.cb-pane{position:relative;height:100%;width:100%;display:flex;flex-direction:column;background:var(--cb-cons-bg);
  overflow:hidden;container:cbpane/inline-size}
.cb-root.cb-pane .cb-cons{border-top:0;flex:1 1 auto;display:grid}

/* status bar chip (app theme colours, the status bar is app chrome) */
.cb-root.cb-chip{display:inline-flex;align-items:center;gap:6px;height:100%;padding:0 8px;font-size:11px;letter-spacing:.06em;
  color:var(--cb-fg-dim);white-space:nowrap;border-radius:3px}
.cb-root.cb-chip:hover{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-fg) 8%,transparent)}
.cb-root.cb-chip b{font-weight:600;color:var(--cb-fg)}
.cb-root.cb-chip .cb-g{font-weight:700}

/* narrow containers */
@container cb (max-width:1240px){.cb-root .cb-shell{--cb-rail-w:172px;--cb-insp-w:300px}
  .cb-root .cb-kpi .cb-v small,.cb-root [data-cb=hud-board] .cb-label,.cb-root [data-cb=hud-project] .cb-label,.cb-root .cb-kpi-bar,.cb-root .cb-hud .cb-simban-w{display:none}
  .cb-root .cb-brand{font-size:13px;letter-spacing:.14em}}
@container cb (max-width:1180px){.cb-root .cb-brand small{display:none}}
/* low windows (1100×800): denser pin rows and toolbar while the console is open; 06 DEBUG console a little lower */
@container cb (max-height:800px){
  .cb-root .cb-shell[data-cb-cons=open] .cb-toolbar{margin:6px 0 4px;row-gap:6px}
  .cb-root[data-cb-station=debug] .cb-shell[data-cb-cons=open]{--cb-cons-h:230px}
}
/* 1100×800 and smaller: PLAN keeps J1-22/J3-22 above the open console; the log still shows 6 lines */
@container cb (max-height:760px){.cb-root[data-cb-station=plan] .cb-shell[data-cb-cons=open]{--cb-cons-h:150px}}
/* < 1100 px icon rail, inspector beside; stacked only < 800 px */
@container cb (max-width:1099px){
  .cb-root .cb-shell{--cb-rail-w:58px;--cb-insp-w:280px}
  .cb-root .cb-rail{padding:12px 6px}
  .cb-root .cb-stage{grid-template-columns:1fr;justify-items:center;padding:7px 2px;gap:2px}
  .cb-root .cb-stage-txt,.cb-root .cb-rail-label,.cb-root .cb-rail-foot{display:none}.cb-root .cb-stage-ic{display:block}
  .cb-root .cb-trace{margin-left:auto;margin-right:auto}
  .cb-root .cb-hud [data-cb=hud-board]{display:none}
  .cb-root .cb-kpi-w{display:none}.cb-root .cb-kpi-i + .cb-kpi-i{margin-left:8px}
}
@container cb (max-width:899px){.cb-root .cb-shell{--cb-insp-w:256px}.cb-root .cb-main{padding:12px 12px 16px}
  .cb-root .cb-insp{padding:10px 10px}}
@container cb (max-width:799px){
  .cb-root .cb-shell{grid-template-columns:var(--cb-rail-w) minmax(0,1fr);grid-template-areas:"hud hud" "rail main" "rail cons"}
  .cb-root .cb-work{display:block;grid-area:main;min-height:0;overflow:auto;position:relative;background-color:var(--cb-bg);
    --cb-grid-q:color-mix(in oklab,var(--cb-grid) 60%,transparent);
    background-image:linear-gradient(var(--cb-grid-q) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid-q) 1px,transparent 1px);background-size:24px 24px}
  .cb-root .cb-work .cb-main{overflow:visible;background:none}
  .cb-root .cb-work .cb-main--fill{height:100%;min-height:380px}
  .cb-root .cb-work .cb-insp{overflow:visible;border-left:0;border-top:1px solid var(--cb-stroke);display:grid;
    grid-template-columns:repeat(auto-fit,minmax(300px,1fr));align-items:start;background:transparent;padding:14px 18px 18px}
}
@container cb (max-width:960px){.cb-root .cb-kpi[data-cb=kpi-build],.cb-root .cb-kpi[data-cb=kpi-solder]{display:none}
  .cb-root .cb-pill[data-cb=hud-link] b{max-width:150px;text-overflow:ellipsis}}
@container cb (max-width:820px){.cb-root [data-cb=hud-project] .cb-label{display:none}}
@container cb (max-width:700px){
  .cb-root .cb-kpis,.cb-root .cb-brand small,.cb-root .cb-sep,.cb-root [data-cb=hud-link] b{display:none}
  .cb-root .cb-main{padding:12px 12px 16px}
}
@container cbpane (max-width:760px){.cb-root .cb-panic{width:300px}}
@container cbpane (max-width:560px){.cb-root .cb-panic{display:none}}

/* motion */
@keyframes cb-pulse{0%,100%{opacity:1}50%{opacity:.45}}
@keyframes cb-blink{50%{opacity:.35}}
@keyframes cb-fadein{from{opacity:0}to{opacity:1}}
@keyframes cb-sweep{0%,100%{box-shadow:none}30%,45%{background:color-mix(in oklab,var(--cb-ok) 24%,transparent);border-color:var(--cb-ok);
  box-shadow:inset 3px 0 0 var(--cb-ok),var(--cb-glow-ok)}}
@keyframes cb-rowpulse{0%,100%{background:transparent}50%{background:color-mix(in oklab,var(--cb-active) 22%,transparent)}}
@media (prefers-reduced-motion:reduce){
  .cb-root *,.cb-root *::before,.cb-root *::after{animation:none!important;transition:none!important}
  .cb-root.cb-page::after,.cb-root.cb-pane::after{display:none}
}
` + CB_CSS_UI2

/** The own stylesheet: base CSS + the registered parts of 13-…–19-styles-*.js (CB_CSS_PARTS, 10-tokens.js), joined at
 *  render time so every part file has run. */
function Styles() {
  return h('style', { 'data-cb': 'style' }, CB_CSS + CB_CSS_PARTS.join(''))
}

// --- 13-styles-kit.js
// Kit styles: agent button, SIM badge, state glyph and state pill.
// Registered through CB_CSS_PARTS (10-tokens.js); comes after 11/12, so equal specificity wins here.
CB_CSS_PARTS.push(`
/* Hermes action: active (cyan) fill with ink text, never the alarm colour; ◢ in front (aria-hidden) */
.cb-root .cb-btn--agent{background:var(--cb-active-fill);color:var(--cb-ink);box-shadow:var(--cb-glow-active)}
.cb-root .cb-btn--agent:hover{background:color-mix(in oklab,var(--cb-active-fill) 86%,white)}
.cb-root .cb-btn--agent:focus-visible{outline:2px solid var(--cb-active);outline-offset:2px}
.cb-root .cb-btn-mark{font-size:10px;line-height:1;letter-spacing:0;flex:none}

/* SIM badge: solid frame, diagonal stripes, the word SIMULATED always visible */
.cb-root .cb-simbadge{display:inline-flex;align-items:stretch;gap:0;padding:0;border:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  border-radius:2px;color:var(--cb-active-text);font-size:10px;font-weight:700;letter-spacing:.14em;line-height:16px;white-space:nowrap;overflow:hidden;flex:none}
.cb-root .cb-simbadge-s{width:12px;flex:none;border-right:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  background:repeating-linear-gradient(135deg,color-mix(in oklab,var(--cb-active) 80%,transparent) 0 2px,transparent 2px 5px)}
.cb-root .cb-simbadge-t{padding:1px 7px 1px 6px}
.cb-root .cb-simbadge--sm{line-height:14px}
.cb-root .cb-simbadge--sm .cb-simbadge-s{width:9px}
.cb-root .cb-simbadge--sm .cb-simbadge-t{padding:0 5px}
/* port + SIM badge: the port gives way */
.cb-root b.cb-kv-port{display:flex;align-items:center;gap:8px;min-width:0;overflow:visible;text-overflow:clip}
.cb-root b.cb-kv-port .cb-simbadge{font-weight:700}

/* state symbol (inline SVG, 12 px): shape carries the state, colour only adds to it */
.cb-root .cb-glyph{display:inline-block;width:12px;height:12px;flex:none;vertical-align:-2px;overflow:visible}
.cb-root .cb-glyph--free{color:var(--cb-ok-text)}
.cb-root .cb-glyph--assigned{color:var(--cb-active-text)}
.cb-root .cb-glyph--caution{color:var(--cb-warn-text)}
.cb-root .cb-glyph--blocked,.cb-root .cb-glyph--assigned_blocked{color:var(--cb-bad-text)}
.cb-root .cb-glyph--power{color:var(--cb-power-text)}
.cb-root .cb-glyph--ground,.cb-root .cb-glyph--signal{color:var(--cb-fg-dim)}
.cb-root .cb-glyph--nc{color:var(--cb-fg-faint)}

/* ─── shell: frame, HUD, rail, inspector ─── */
/* the project list shows the compact SIM badge (46-dialogs.js) */
.cb-root .cb-projmeta{display:flex;align-items:center;gap:8px;min-width:0;overflow:visible;text-overflow:clip}
.cb-root .cb-projmeta .cb-simban-w{display:none}
.cb-root .cb-projmeta > .cb-ellip{min-width:0}
.cb-root .cb-hud-count{background:color-mix(in oklab,var(--cb-fg) 12%,transparent)}

/* one scale (step 5, 12-styles.js): controls 24 / 28 / 32 px, gaps 4 / 8 / 12 / 16 / 24 px; card head and foot */
.cb-root .cb-card-tools{margin-left:auto;display:flex;gap:4px;flex:none}
.cb-root .cb-card-foot{margin-top:12px;padding-top:8px;border-top:1px dashed var(--cb-stroke-strong)}
.cb-root .cb-card-foot .cb-src{margin-top:0}
.cb-root .cb-card-foot:empty{display:none}

/* inspector: verdict → reason → the way out (chips) → details → source in the foot */
.cb-root .cb-insp-card .cb-verdict{margin-top:8px}
.cb-root .cb-insp-way{margin-top:12px;display:grid;gap:4px}
.cb-root .cb-insp-way .cb-alts{margin-top:0;gap:8px}
.cb-root .cb-altchip{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 8px;color:var(--cb-fg);
  border-color:color-mix(in oklab,var(--cb-ok) 45%,var(--cb-stroke-strong))}
.cb-root .cb-altchip b{font-weight:700}
.cb-root .cb-altchip:hover{background:color-mix(in oklab,var(--cb-ok) 10%,transparent);box-shadow:none;border-color:var(--cb-ok)}
.cb-root .cb-insp-card .cb-actions{margin-top:12px}
.cb-root .cb-insp-card .cb-fn{margin-top:12px}

/* assignment table: fixed columns, never wider than the inspector (WT32 audit: td.cb-r 25 px out) */
.cb-root .cb-table--assign{table-layout:fixed}
/* inspector content ≈ 264 px at 1440: pin 38 + mode 58 + verdict 72 + remove 20 → role keeps ≈ 76 px (10 characters) */
.cb-root .cb-table--assign .cb-col-pin{width:38px}
.cb-root .cb-table--assign .cb-col-mode{width:64px}
.cb-root .cb-table--assign td,.cb-root .cb-table--assign th{padding-left:3px;padding-right:3px}
.cb-root .cb-table--assign .cb-col-verdict{width:72px}
.cb-root .cb-table--assign .cb-col-x{width:20px}
.cb-root .cb-table--assign .cb-cell-ellip{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cb-root .cb-table--assign td.cb-dim,.cb-root .cb-table--assign .cb-verdict-cell{font-size:11px}
.cb-root .cb-table--assign td.cb-r,.cb-root .cb-table--assign th.cb-r{padding-left:0;padding-right:0;text-align:center}
/* narrow inspector (1280/1100 windows): the verdict shows its symbol (the word stays for screen readers and in
   the title), the check time gives way to "+ assign" */
.cb-root .cb-insp{container:cbinsp/inline-size}
@container cbinsp (max-width:300px){
  .cb-root .cb-table--assign .cb-col-verdict{width:26px}.cb-root .cb-table--assign .cb-col-mode{width:64px}
  .cb-root .cb-table--assign .cb-vw{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
  .cb-root [data-cb=assignments] [data-cb=checked-at]{display:none}
  .cb-root [data-cb=assignments] [data-cb=assign-new]{margin-left:auto}
}
`)

// --- 14-styles-board.js
// Board model styles: the DOM layer above the SVG drawing. Every
// measure comes from the CSS variables boardGeomVars() sets on [data-cb=board] (lib/board-geom.js); labels and tags
// sit in fixed columns outside the pcb and use the bench colours, everything printed on the pcb uses the material.
CB_CSS_PARTS.push(`
/* box: exactly the geometry, centred in the main column; no frame (the pcb is the object) */
.cb-root .cb-board-wrap{display:flex;justify-content:center;padding:0;min-width:0;margin:2px 0 0}
.cb-root .cb-board.cb-board[data-cb=board]{position:relative;display:block;flex:none;width:var(--cb-board-w);height:var(--cb-board-h);max-width:none;
  padding:0;margin:0;border:0;background:none}
.cb-root .cb-board-art{position:absolute;inset:0;pointer-events:none}
.cb-root .cb-board-art svg{display:block;overflow:visible}
.cb-root .cb-board-art text{font-family:var(--cb-mono)}

/* header ids printed on the pcb above the strips */
.cb-root .cb-board > .cb-board-hdr{position:absolute;top:1px;width:44px;margin-left:-22px;padding:0;text-align:center;font-size:10px;
  line-height:14px;letter-spacing:.14em;color:var(--cb-silk);font-weight:700;pointer-events:auto}
.cb-root .cb-board > .cb-board-hdr:nth-child(2){left:calc(var(--cb-gutter) + var(--cb-strip-x))}
.cb-root .cb-board > .cb-board-hdr:nth-child(3){left:calc(var(--cb-gutter) + var(--cb-body-w) - var(--cb-strip-x))}

/* pin columns: one row per slot, pitch = row + gap; the row ends with the pad cell over the strip */
.cb-root .cb-board .cb-col{position:absolute;top:var(--cb-top);width:var(--cb-row-w);display:flex;flex-direction:column;gap:var(--cb-row-gap);padding:0;min-width:0}
.cb-root .cb-board .cb-col--l{left:0}
.cb-root .cb-board .cb-col--r{right:0}
.cb-root .cb-board .cb-pin{display:flex;align-items:center;height:var(--cb-row-h);width:100%;padding:0;margin:0;border:0;border-radius:2px;
  background:none;color:inherit;font:inherit;text-align:inherit;position:relative;column-gap:0;cursor:default}
.cb-root .cb-board button.cb-pin{cursor:pointer}
.cb-root .cb-board .cb-col--l .cb-pin{justify-content:flex-end;padding-left:2px}
.cb-root .cb-board .cb-col--r .cb-pin{justify-content:flex-start;padding-right:2px}
.cb-root .cb-board .cb-pin .cb-name{flex:none;width:var(--cb-name-w);font-size:12px;font-weight:600;line-height:var(--cb-row-h);white-space:nowrap;overflow:hidden;
  color:var(--cb-fg-dim);font-variant-numeric:tabular-nums}
.cb-root .cb-board .cb-col--l .cb-name{text-align:right}
.cb-root .cb-board .cb-col--r .cb-name{text-align:left;margin-left:5px}
.cb-root .cb-board .cb-pglyph{flex:none;width:12px;height:12px}
.cb-root .cb-board .cb-col--l .cb-pglyph{margin-left:5px}
.cb-root .cb-board .cb-pin .cb-pad{flex:none;width:12px;height:12px;border:0;border-radius:50%;background:none;box-shadow:none;transform:none}
.cb-root .cb-board .cb-col--l .cb-pad{margin:0 1px 0 13px}
.cb-root .cb-board .cb-col--r .cb-pad{margin:0 13px 0 1px}
.cb-root .cb-board .cb-pin .cb-ptag{flex:0 1 auto;min-width:0;max-width:var(--cb-tag-w);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:10px;line-height:13px;letter-spacing:.04em;text-transform:uppercase;padding:0 5px;border:1px solid transparent;border-radius:2px;color:var(--cb-fg-dim)}
.cb-root .cb-board .cb-col--l .cb-ptag{margin-right:6px}
.cb-root .cb-board .cb-col--r .cb-ptag{margin-left:6px}
.cb-root .cb-board .cb-ptag:empty{padding:0;border:0;margin:0}
/* selection caret in the name gap */
.cb-root .cb-board .cb-mark{flex:none;width:0;height:8px;position:relative;color:var(--cb-active-text)}
.cb-root .cb-board .cb-mark::after{content:"";position:absolute;top:0;width:0;height:0;border-top:4px solid transparent;border-bottom:4px solid transparent}
.cb-root .cb-board .cb-col--l .cb-mark::after{left:0;border-left:4px solid currentColor}
.cb-root .cb-board .cb-col--r .cb-mark::after{right:0;border-right:4px solid currentColor}
.cb-root .cb-board .cb-pin[data-cb-state$=bad] .cb-mark,.cb-root .cb-board .cb-mark[data-cb-mark=req]{color:var(--cb-bad-text)}

/* states on the labels (the pad ring is in the SVG): free/assigned/caution/blocked/power/neutral */
.cb-root .cb-board .cb-pin[data-cb-state=free] .cb-name{color:var(--cb-fg)}
.cb-root .cb-board .cb-pin[data-cb-state=used] .cb-name{color:var(--cb-active-text)}
.cb-root .cb-board .cb-pin[data-cb-state=used] .cb-ptag{color:var(--cb-ink);background:var(--cb-active-fill);border-color:var(--cb-active-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=used-warn] .cb-name{color:var(--cb-warn-text)}
.cb-root .cb-board .cb-pin[data-cb-state=used-warn] .cb-ptag{color:var(--cb-ink);background:var(--cb-warn-fill);border-color:var(--cb-warn-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=warn] .cb-name{color:var(--cb-warn-text)}
.cb-root .cb-board .cb-pin[data-cb-state=warn] .cb-ptag{color:var(--cb-warn-text);border-color:color-mix(in oklab,var(--cb-warn) 60%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-state=bad] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=used-bad] .cb-name{color:var(--cb-bad-text);text-decoration:line-through;
  text-decoration-thickness:1px}
.cb-root .cb-board .cb-pin[data-cb-state=bad] .cb-ptag{color:var(--cb-bad-text);border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-state=used-bad] .cb-ptag{color:var(--cb-ink);background:var(--cb-bad-fill);border-color:var(--cb-bad-fill);font-weight:700}
.cb-root .cb-board .cb-pin[data-cb-state=power] .cb-name{color:var(--cb-power-text)}
.cb-root .cb-board .cb-pin[data-cb-state=ground] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=reset] .cb-name,
.cb-root .cb-board .cb-pin[data-cb-state=nc] .cb-name,.cb-root .cb-board .cb-pin[data-cb-state=unchecked] .cb-name{color:var(--cb-fg-dim);font-weight:400}
.cb-root .cb-board .cb-pin[data-cb-state=signal] .cb-name{color:var(--cb-fg-dim)}
.cb-root .cb-board .cb-pin[data-cb-state=nc] .cb-ptag,.cb-root .cb-board .cb-pin[data-cb-state=signal] .cb-ptag{border:1px dashed var(--cb-stroke-strong);color:var(--cb-fg-dim)}

/* interaction: hover, focus ring, selection (row tint + the SVG ring), suggestion, agent pulse (opacity only) */
.cb-root .cb-board button.cb-pin:hover{background:color-mix(in oklab,var(--cb-fg) 7%,transparent)}
.cb-root .cb-board button.cb-pin:focus-visible{outline:2px solid var(--cb-active);outline-offset:1px}
.cb-root .cb-board .cb-pin[aria-pressed=true]{background:color-mix(in oklab,var(--cb-active) 11%,transparent);outline:1px solid color-mix(in oklab,var(--cb-active) 70%,transparent);
  outline-offset:0;box-shadow:none}
.cb-root .cb-board .cb-pin[aria-pressed=true][data-cb-state$=bad]{background:color-mix(in oklab,var(--cb-bad) 12%,transparent);outline-color:color-mix(in oklab,var(--cb-bad) 75%,transparent)}
.cb-root .cb-board .cb-pin[data-cb-suggest=true]{outline:1px dashed var(--cb-ok);outline-offset:0}
.cb-root .cb-board .cb-pin[data-cb-pulse=true]{animation:none}
.cb-root .cb-board .cb-pin[data-cb-pulse=true]::after{content:"";position:absolute;inset:0;border-radius:2px;pointer-events:none;
  background:color-mix(in oklab,var(--cb-active) 28%,transparent);opacity:0;animation:cb-bpulse .3s ease-in-out 2}
@keyframes cb-bpulse{50%{opacity:1}}
/* the selection ring on the pad: the one permanently animated element, static under reduced motion */
.cb-root .cb-board-art .cb-bsel{transform-box:fill-box;transform-origin:center;animation:cb-bselring 1.6s ease-in-out infinite}
@keyframes cb-bselring{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.45;transform:scale(1.18)}}

/* header separator (WT32: PROG → IO): the id printed at the strip, a dashed rule across the label columns */
.cb-root .cb-board .cb-col .cb-hdr-sep{height:var(--cb-row-h);display:block;position:relative;padding:0;gap:0}
.cb-root .cb-board .cb-col .cb-hdr-sep::before{content:"";position:absolute;top:50%;border-top:1px dashed var(--cb-stroke-strong);flex:none}
.cb-root .cb-board .cb-col .cb-hdr-sep::after{content:none}
.cb-root .cb-board .cb-col--l .cb-hdr-sep::before{left:2px;right:30px}
.cb-root .cb-board .cb-col--r .cb-hdr-sep::before{left:30px;right:2px}
.cb-root .cb-board .cb-hdr-sep > span{position:absolute;top:0;transform:translateX(-50%);font-size:10px;line-height:var(--cb-row-h);letter-spacing:.12em;font-weight:700;color:var(--cb-silk)}
.cb-root .cb-board .cb-col--l .cb-hdr-sep > span{left:calc(100% - 7px)}
.cb-root .cb-board .cb-col--r .cb-hdr-sep > span{left:7px}

/* reservation brackets: transparent anchors in the lane (drawing in the SVG), title = the full text */
.cb-root .cb-board .cb-bbracket{position:absolute;width:15px;pointer-events:auto;cursor:help}
.cb-root .cb-board .cb-col--l .cb-bbracket{left:calc(100% + 2px)}
.cb-root .cb-board .cb-col--r .cb-bbracket{right:calc(100% + 2px)}

/* anchors over the drawing (module, antenna, ports, buttons): transparent, a silk outline on hover */
.cb-root .cb-board .cb-module{position:absolute;inset:0;display:block;padding:0;min-height:0;pointer-events:none}
.cb-root .cb-board .cb-usb,.cb-root .cb-board .cb-btns{display:contents}
.cb-root .cb-board .cb-banchor{position:absolute;display:block;pointer-events:auto;border-radius:3px;border:0;background:none;width:auto;height:auto;margin:0}
.cb-root .cb-board .cb-banchor:hover{outline:1px dashed color-mix(in oklab,var(--cb-silk) 70%,transparent);outline-offset:2px}
.cb-root .cb-board .cb-bport[data-cb-live=true]{outline:2px solid var(--cb-active);outline-offset:3px}
/* notes printed on the pcb (variant unknown, PSRAM reservation): silk on the material, the shape carries the tone */
.cb-root .cb-board .cb-bnote{position:absolute;display:flex;align-items:center;justify-content:center;gap:6px;padding:2px 6px;text-align:center;
  font-size:10px;line-height:13px;font-weight:700;letter-spacing:.06em;color:var(--cb-silk);border:0;
  border-radius:2px;background:none;pointer-events:auto}
/* notes are silk print (no dashed box); caution notes carry the ◇ glyph, a hairline under the
   line keeps them apart from the parts */
.cb-root .cb-board .cb-bnote > span{border-bottom:1px solid color-mix(in oklab,var(--cb-silk) 35%,transparent);padding-bottom:1px}
.cb-root .cb-board .cb-bnote .cb-glyph path{stroke:var(--cb-warn)}

/* legend: the board's symbols with their words */
.cb-root .cb-legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px 14px;margin:0 0 8px;color:var(--cb-fg-dim);font-size:11px;line-height:14px}
.cb-root .cb-legend > span{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
/* PLAN head: title + meta, Suggest pins at the right; the toolbar below stays one line: the group labels give
   way first when the station is narrow */
.cb-root .cb-planhead{display:flex;align-items:center;gap:12px;min-width:0}
.cb-root .cb-planhead > .cb-title{flex:1 1 auto}
.cb-root .cb-planhead > .cb-btn{flex:none}
.cb-root [data-cb=plan-toolbar]{container:cbtool/inline-size;margin:8px 0 6px}
@container cbtool (max-width:760px){.cb-root [data-cb=plan-toolbar] .cb-group > .cb-label{display:none}.cb-root [data-cb=plan-toolbar] .cb-group{padding-right:8px}}
/* legend as caption */
.cb-root .cb-legend--cap{justify-content:center;margin:8px auto 0;max-width:var(--cb-cap-w,100%)}
.cb-root .cb-legend-sug i{display:inline-block;width:12px;height:12px;border:1.5px dashed var(--cb-ok);border-radius:50%}

/* what-if line: one flat row inside the toolbar (S2 fits at 1100×800) */
.cb-root [data-cb=plan-toolbar] .cb-whatif{min-height:0;padding:1px 4px 1px 8px;gap:6px;line-height:16px}
.cb-root [data-cb=plan-toolbar] .cb-whatif .cb-btn--sm{padding:1px 7px;line-height:16px}

.cb-root .cb-board-empty{border:1px dashed var(--cb-stroke-strong);padding:22px;max-width:680px;margin:0 auto}

/* compact model and live twin: the SVG scales with its box, the stamp and caption are DOM */
.cb-root .cb-twin{min-width:0}
.cb-root .cb-twin-box{position:relative}
.cb-root .cb-twin-art svg{display:block;width:100%;height:auto;overflow:visible}
.cb-root .cb-twin-stamp{position:absolute;transform:translate(-50%,-50%);pointer-events:none;white-space:nowrap}
.cb-root .cb-twin-stamp .cb-stamp{font-size:11px;padding:2px 7px;letter-spacing:.14em}
/* chat card hover coupling */
.cb-root .cb-twin-ring{position:absolute;width:14px;height:14px;transform:translate(-50%,-50%);border:2px solid var(--cb-active);border-radius:50%;
  box-shadow:var(--cb-glow-active);pointer-events:none}
.cb-root .cb-dpin[data-cb-hot=true] > *{background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-twin-cap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 10px;margin-top:6px;font-size:10px;line-height:13px;letter-spacing:.06em;
  color:var(--cb-fg-dim)}
.cb-root .cb-twin-cap-t{color:var(--cb-fg);font-weight:700;letter-spacing:.08em}
/* the pulse port → module: opacity only, one 600 ms cycle, only while the job runs (the dots exist only then) */
.cb-root .cb-twin-dot{opacity:.85}
@media (prefers-reduced-motion:no-preference){
  .cb-root .cb-twin-dot{opacity:0;animation:cb-twin-pulse .6s linear infinite}
  .cb-root .cb-twin-dot--1{animation-delay:.15s}.cb-root .cb-twin-dot--2{animation-delay:.3s}.cb-root .cb-twin-dot--3{animation-delay:.45s}
}
@keyframes cb-twin-pulse{0%,100%{opacity:0}25%{opacity:1}55%{opacity:0}}

/* chat card, view pins: model left, figures + assignments right, the legend across */
.cb-root.cb-dcard[data-cb-view=pins]{max-width:700px}
.cb-root.cb-dcard[data-cb-view=pins]{container-type:inline-size}
.cb-root .cb-dpins{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px;align-items:stretch}
.cb-root .cb-dpins-board{flex:1 1 250px;max-width:330px;padding:8px 8px 6px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-panel) 85%,transparent)}
.cb-root .cb-dpins-side{flex:1 1 230px;min-width:0;display:flex;flex-direction:column;gap:8px}
.cb-root .cb-dkpis{margin:0;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;font-size:13px;letter-spacing:.02em;font-weight:400}
.cb-root .cb-dkpis-l{flex:1 1 100%}
.cb-root .cb-dkpi{display:inline-flex;align-items:baseline;gap:4px;white-space:nowrap}
.cb-root .cb-dkpi b{font-weight:700;font-variant-numeric:tabular-nums}
.cb-root .cb-dkpi-w{color:var(--cb-fg)}
.cb-root .cb-dkpi.cb-dim .cb-dkpi-w{color:var(--cb-fg-dim)}
.cb-root .cb-dpins-list{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:12px max-content max-content max-content minmax(0,1fr) max-content;
  column-gap:8px;row-gap:3px;align-items:center;font-size:12px;line-height:18px}
.cb-root .cb-dpin{display:contents}
.cb-root .cb-dpin-role{font-weight:700;color:var(--cb-fg);letter-spacing:.04em}
.cb-root .cb-dpin-io{color:var(--cb-active-text);font-variant-numeric:tabular-nums}
.cb-root .cb-dpin--blocked .cb-dpin-io{color:var(--cb-bad-text)}
.cb-root .cb-dpin--caution .cb-dpin-io{color:var(--cb-warn-text)}
.cb-root .cb-dpin-at,.cb-root .cb-dpin-w,.cb-root .cb-dpin-mode{font-size:11px;white-space:nowrap}
.cb-root .cb-dpin-mode{min-width:0;overflow:hidden}
@container (max-width:600px){
  .cb-root .cb-dpins-list{grid-template-columns:12px max-content max-content minmax(0,1fr) max-content}
  .cb-root .cb-dpin-mode{display:none}
}
.cb-root .cb-dpins-foot{margin-top:auto;display:flex;flex-direction:column;gap:5px;padding-top:8px;border-top:1px dashed var(--cb-stroke);font-size:11px;line-height:15px}
.cb-root .cb-dpins-res,.cb-root .cb-dpins-spec{display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 10px;min-width:0}
.cb-root .cb-dpins-foot .cb-label{flex:none;min-width:56px}
.cb-root .cb-dpins-spec > span{color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-dpins-spec > span:not(:last-child)::after{content:' ·';color:var(--cb-fg-dim)}
.cb-root .cb-dres{display:inline-flex;align-items:center;gap:5px;white-space:nowrap;color:var(--cb-fg-dim)}
.cb-root .cb-dres b{font-weight:700;letter-spacing:.06em}
.cb-root .cb-dres--warn b{color:var(--cb-warn-text)}.cb-root .cb-dres--bad b{color:var(--cb-bad-text)}
.cb-root .cb-dres i{flex:none;width:12px;height:9px;border:1.5px dashed var(--cb-warn);border-radius:1px}
.cb-root .cb-dres--bad i{border-color:var(--cb-bad)}
.cb-root .cb-dpin-w{text-align:right}
.cb-root .cb-dpin--more{display:block;grid-column:1 / -1;font-size:11px}
.cb-root .cb-dpins-legend{flex:1 1 100%;justify-content:flex-start;margin:0;padding-top:8px;border-top:1px solid var(--cb-stroke)}
.cb-root.cb-dcard[data-cb-view=pins] .cb-actions{margin-top:10px;justify-content:flex-end}

/* live twin cards in 05 FLASH (inspector) and 06 DEBUG (monitor card) */
.cb-root .cb-twin-card .cb-twin{margin-top:8px}
.cb-root .cb-twin-note{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;margin:8px 0 0;font-size:11px;line-height:15px;min-width:0}
.cb-root .cb-twin-note b{font-weight:700;color:var(--cb-fg);overflow-wrap:anywhere;min-width:0}
.cb-root .cb-twin-note .cb-active-t{color:var(--cb-active-text)}
.cb-root .cb-twin-row{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid var(--cb-stroke)}
.cb-root .cb-twin-row > .cb-twin{flex:1 1 200px;max-width:280px}
.cb-root .cb-twin-row > .cb-twin-lab{flex:1 1 100%}
.cb-root .cb-twin-leds{flex:1 1 130px;display:flex;flex-direction:column;gap:6px;min-width:0}
.cb-root .cb-twin-led{display:inline-flex;align-items:center;gap:6px;font-size:11px;line-height:14px;white-space:nowrap}
.cb-root .cb-twin-led b{font-weight:700;letter-spacing:.1em;color:var(--cb-fg)}
.cb-root .cb-twin-led i{flex:none;width:9px;height:9px;border-radius:50%;border:1.5px solid var(--cb-stroke-strong);background:none}
.cb-root .cb-twin-led[data-cb-on=true] i{background:var(--cb-ok);border-color:var(--cb-ok);box-shadow:var(--cb-glow-ok)}
.cb-root .cb-twin-led[data-cb-on=true] .cb-dim{color:var(--cb-ok-text)}
`)

// --- 15-styles-wire.js
// WIRE styles: the schematic frame with its header, the fitted plan, stroke widths
// per data-kind (lines 1.5 px, bodies and ports 2 px, selection 2 px plus pulse), net colours per data-net
// (supply power, ground fg-dim, signal fg, hover/selection active), the wiring table with fixed columns and net chips,
// warning cards. Attribute selectors only: the SVG itself stays self-contained (currentColor, no <style>).
// The supply/ground names match lib/wire.js WIRE_RAILS / WIRE_GROUND (tests-js/test_vwire_station.mjs).
CB_CSS_PARTS.push(`
/* MODULES: grouped block pick, wraps */
.cb-root .cb-group--wblocks{flex-wrap:wrap;min-width:0;row-gap:6px}
.cb-root .cb-wblocks{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;min-width:0}
.cb-root .cb-wblocks-g{display:inline-flex;align-items:center;gap:6px}
.cb-root .cb-wblocks-k{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
/* focusable rows */
.cb-root .cb-wiretable tbody tr:focus-visible,.cb-root .cb-wparts tbody tr:focus-visible{outline:2px solid var(--cb-active);outline-offset:-2px}
.cb-root table.cb-wiretable td.cb-fg{white-space:normal;text-overflow:clip;overflow-wrap:break-word}
/* narrow Bench (1100×800 beside the chat): the block name gives way in the schematic head (it is in the parameter card);
   the net chip keeps its letters (thin cell padding) */
@container cb (max-width:899px){.cb-root .cb-svghead-b{display:none}
  .cb-root .cb-wiretable td:last-child{padding-left:3px;padding-right:2px}
  .cb-root table.cb-wiretable .cb-wcol-from{width:26%}.cb-root table.cb-wiretable .cb-wcol-to{width:24%}.cb-root table.cb-wiretable .cb-wcol-net{width:50%}}
/* frame: header bar (title, net legend, Save SVG), the stage that fits and centres the plan, caption */
.cb-root .cb-main--fill > .cb-svgwrap{min-height:auto}
.cb-root .cb-svgwrap{flex-direction:column;align-items:stretch;padding:0;background:color-mix(in oklab,var(--cb-panel) 96%,transparent)}
.cb-root .cb-svghead{display:flex;align-items:center;gap:14px;min-width:0;min-height:34px;padding:4px 8px 4px 12px;border-bottom:1px solid var(--cb-stroke);flex:none}
.cb-root .cb-svghead > .cb-label{white-space:nowrap;min-width:0;overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-netlegend{display:flex;align-items:center;gap:12px;flex:none;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
.cb-root .cb-netkey{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.cb-root .cb-netkey .cb-glyph{width:12px;height:12px;color:inherit}
.cb-root .cb-svghead-act{margin-left:auto;flex:none;display:flex;gap:6px}
.cb-root .cb-svgstage{flex:1 1 auto;display:flex;align-items:stretch;justify-content:center;padding:12px 14px 26px;min-width:0;overflow-x:auto}
.cb-root .cb-svgwrap .cb-svgstage .cb-svg{flex:1 1 auto;align-self:stretch;position:relative}
/* the box takes the whole stage (no auto margins: they would stop the stretch); the SVG adds no intrinsic height
   of its own (width:100% would make it as tall as its aspect ratio): it fills the box, scaled with meet and centred;
   the box's min size (viewBox in px) keeps scale ≥ 1 */
.cb-root .cb-svgwrap .cb-svgstage .cb-svg svg{position:absolute;inset:0;width:100%;height:100%}
.cb-root .cb-svgcap{left:12px;bottom:7px}

/* strokes per role, in screen pixels whatever the scale */
.cb-root .cb-svg svg path,.cb-root .cb-svg svg circle,.cb-root .cb-svg svg polygon,.cb-root .cb-svg svg rect{vector-effect:non-scaling-stroke}
.cb-root .cb-svg svg [data-kind=wire]{stroke-width:1.5px}
.cb-root .cb-svg svg [data-kind=body],.cb-root .cb-svg svg [data-kind=port]{stroke-width:2px}
.cb-root .cb-svg svg [data-kind=junction]{stroke-width:1px;fill:currentColor}
.cb-root .cb-svg svg text[data-kind=pin]{fill:var(--cb-fg-dim)}

/* net colours: supply, ground, signal (default fg) */
.cb-root .cb-svg svg [data-net="3V3"],.cb-root .cb-svg svg [data-net="5V"]{color:var(--cb-power-text)}
.cb-root .cb-svg svg [data-net=GND]{color:var(--cb-fg-dim)}

/* hover / selection: the part or net in active, its lines 2.5 px, everything else's ink steps back (texts stay) */
.cb-root .cb-svg svg [data-cb-on=true]{color:var(--cb-active-text)}
.cb-root .cb-svg svg text[data-cb-on=true]{fill:var(--cb-active-text)}
.cb-root .cb-svg svg [data-kind=wire][data-cb-on=true],.cb-root .cb-svg svg [data-kind=body][data-cb-on=true],
  .cb-root .cb-svg svg [data-kind=port][data-cb-on=true]{stroke-width:2.5px}
.cb-root .cb-svg svg rect[data-cb-on=true]{fill:color-mix(in oklab,var(--cb-active) 9%,transparent)}
.cb-root .cb-svg[data-cb-hl] svg path:not([data-cb-on=true]),.cb-root .cb-svg[data-cb-hl] svg circle:not([data-cb-on=true]){opacity:.4}
.cb-root .cb-svg svg path,.cb-root .cb-svg svg circle{transition:opacity .12s,color .12s}
@media (prefers-reduced-motion:no-preference){
  .cb-root .cb-svg svg [data-kind=wire][data-cb-on=true]{animation:cb-wire-pulse 1.4s ease-in-out infinite}
}
@keyframes cb-wire-pulse{0%,100%{stroke-opacity:1}50%{stroke-opacity:.55}}

/* wiring table: fixed columns with a grid, the net as a chip in its colour */
.cb-root table.cb-wiretable{table-layout:fixed}
.cb-root .cb-wiretable .cb-wcol-from{width:28%}
.cb-root .cb-wiretable .cb-wcol-to{width:26%}
.cb-root .cb-wiretable .cb-wcol-net{width:46%}
.cb-root .cb-wiretable td,.cb-root .cb-wiretable th{padding:3px 5px;border-bottom:1px solid var(--cb-stroke);overflow:hidden;text-overflow:ellipsis}
.cb-root .cb-wiretable td + td,.cb-root .cb-wiretable th + th{border-left:1px solid var(--cb-stroke)}
.cb-root .cb-wiretable thead th{border-bottom-color:var(--cb-stroke-strong)}
.cb-root .cb-netchip{display:inline-flex;align-items:center;max-width:100%;padding:0 5px;border:1px solid color-mix(in oklab,currentColor 55%,transparent);
  border-radius:2px;font-size:11px;line-height:16px;vertical-align:middle;color:var(--cb-fg)}
.cb-root .cb-netchip-t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cb-root .cb-netchip--power{color:var(--cb-power-text);background:color-mix(in oklab,var(--cb-power) 10%,transparent)}
.cb-root .cb-netchip--ground{color:var(--cb-fg-dim)}
.cb-root .cb-netchip--signal{color:var(--cb-fg)}
.cb-root .cb-wiretable tr[aria-selected=true] .cb-netchip{color:var(--cb-active-text);border-color:var(--cb-active)}
.cb-root .cb-wparts tr[data-cb-ref]{cursor:pointer}

/* warning card under the parts (danger: the alarm colour as frame and mark, the text itself unchanged) */
.cb-root .cb-wwarn{border-color:color-mix(in oklab,var(--cb-warn) 60%,transparent);background:color-mix(in oklab,var(--cb-warn) 6%,var(--cb-panel))}
.cb-root .cb-wwarn--danger{border-color:color-mix(in oklab,var(--cb-bad) 70%,transparent);background:color-mix(in oklab,var(--cb-bad) 7%,var(--cb-panel))}
.cb-root .cb-wwarn .cb-card-head{gap:8px}
.cb-root .cb-wwarn-mark{display:inline-grid;place-items:center;width:16px;height:16px;flex:none;border-radius:2px;font-size:11px;font-weight:700;
  background:var(--cb-warn-fill);color:var(--cb-ink)}
.cb-root .cb-wwarn--danger .cb-wwarn-mark{background:var(--cb-bad-fill)}
.cb-root .cb-wwarn--danger .cb-label{color:var(--cb-bad-text)}
.cb-root .cb-wwarn:not(.cb-wwarn--danger) .cb-label{color:var(--cb-warn-text)}
.cb-root .cb-wwarn-t{margin:6px 0 0;font-size:12px;line-height:1.5;color:var(--cb-fg)}
`)

// --- 16-styles-solder.js
// Station 04 SOLDER styles: pictograms, hint lines by kind, done steps that
// fold and open (no ellipsis: overrides 11-styles-ui2.js:151), the progress formula, the height strip, the part list.
CB_CSS_PARTS.push(`
.cb-root .cb-solder-prog{display:flex;align-items:center;gap:14px;margin:10px 0 12px;flex-wrap:wrap}
.cb-root .cb-solder-formula{font-size:13px;color:var(--cb-fg-dim);letter-spacing:.02em;font-variant-numeric:tabular-nums}
.cb-root .cb-solder-formula b{font-size:15px;font-weight:700}
.cb-root .cb-solder-formula .cb-solder-nowrefs{color:var(--cb-active-text)}
.cb-root .cb-solder-prog .cb-bar{flex:1 1 160px;max-width:360px;height:8px}

/* pictograms: side view on the board; annotations (cathode symbol, unclear outline) draw in currentColor */
.cb-root .cb-part-pic{display:inline-flex;flex:none;color:var(--cb-fg-dim);line-height:0}
.cb-root .cb-part-pic svg{display:block;overflow:visible}
.cb-root .cb-part-pic--lg{padding:6px 8px 4px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-fg) 3%,var(--cb-bg))}
.cb-root .cb-part-pic--md{padding:4px 6px 2px;border:1px solid var(--cb-stroke);background:color-mix(in oklab,var(--cb-fg) 2%,var(--cb-bg))}
.cb-root .cb-part-pic--sm{align-self:center}

/* step cards */
.cb-root .cb-steps-list{display:grid;gap:8px;max-width:960px}
.cb-root .cb-step-body{min-width:0}
.cb-root .cb-step-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-height:22px}
.cb-root .cb-step-head .cb-btn{flex:none}
.cb-root .cb-step-main{display:flex;gap:14px;align-items:flex-start;margin-top:8px;flex-wrap:wrap}
.cb-root .cb-step-fig{display:flex;flex-direction:column;align-items:flex-start;gap:6px;flex:none}
.cb-root .cb-step-text{flex:1 1 260px;min-width:0}
.cb-root .cb-step-act{margin-top:0;line-height:1.5;color:var(--cb-fg);white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
.cb-root .cb-step--todo{background:var(--cb-bg);border-color:var(--cb-stroke)}
.cb-root .cb-step--todo .cb-step-act,.cb-root .cb-step--todo .cb-step-head b,.cb-root .cb-step--todo .cb-step-refs{color:var(--cb-fg-dim)}
.cb-root .cb-step--todo .cb-part-pic{opacity:.7}
.cb-root .cb-step--done{padding:5px 11px;align-items:center}
.cb-root .cb-step--done.cb-step--open{align-items:start}
.cb-root .cb-step--done .cb-step-act{white-space:normal;overflow:visible;text-overflow:clip;color:var(--cb-fg-dim);margin-top:0}
.cb-root .cb-step-line{gap:8px}
.cb-root .cb-step-donew{font-size:11px}
.cb-root .cb-step-more{font-size:11px;color:var(--cb-fg-dim);padding:2px 6px;border:1px solid var(--cb-stroke);border-radius:2px;line-height:1.3}
.cb-root .cb-step-more:hover{color:var(--cb-fg);border-color:var(--cb-stroke-strong)}
.cb-root .cb-step-more:focus-visible{outline:2px solid var(--cb-active);outline-offset:1px}
.cb-root .cb-step-detail{margin:6px 0 2px;padding:6px 0 0;border-top:1px dashed var(--cb-stroke)}
.cb-root .cb-step--done .cb-part-pic{opacity:.8}

/* polarity tag: only with a sourced hint; outlined (a tag, not a state fill) */
.cb-root .cb-pol{display:inline-flex;align-items:center;gap:5px;padding:0 6px;border:1px solid var(--cb-stroke-strong);border-radius:2px;
  font-size:10px;line-height:16px;letter-spacing:.1em;text-transform:uppercase;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-pol > span{font-weight:700;letter-spacing:0}

/* hint lines: symbol, category, text + sources; tone by severity, never colour alone (symbol + word) */
.cb-root .cb-shints{margin:8px 0 0;padding:0;list-style:none;display:grid;gap:5px;font-size:11px;line-height:1.5}
.cb-root .cb-shint{display:grid;grid-template-columns:16px 70px minmax(0,1fr);gap:8px;align-items:baseline}
.cb-root .cb-shint-sym{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border:1px solid currentColor;border-radius:2px;
  font-size:11px;font-weight:700;line-height:1;align-self:start;margin-top:1px}
.cb-root .cb-shint-cat{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;padding-top:1px}
.cb-root .cb-shint-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-shint--danger .cb-shint-sym,.cb-root .cb-shint--danger .cb-shint-cat{color:var(--cb-bad-text)}
.cb-root .cb-shint--danger .cb-shint-sym{background:color-mix(in oklab,var(--cb-bad) 14%,transparent)}
.cb-root .cb-shint--caution .cb-shint-sym,.cb-root .cb-shint--caution .cb-shint-cat{color:var(--cb-warn-text)}
.cb-root .cb-shint--info .cb-shint-sym,.cb-root .cb-shint--info .cb-shint-cat{color:var(--cb-fg-dim)}
.cb-root .cb-shint--info .cb-shint-t{color:var(--cb-fg-dim)}
.cb-root .cb-step--todo .cb-shint-t{color:var(--cb-fg-dim)}
.cb-root .cb-shint-src{display:inline-flex;flex-wrap:wrap;gap:0 6px;align-items:baseline;color:var(--cb-fg-dim);font-size:11px;letter-spacing:.02em}
.cb-root .cb-shint-src .cb-k{color:var(--cb-fg-dim)}
.cb-root .cb-shint-src-sep{color:var(--cb-fg-faint)}
.cb-root .cb-shint-src button{color:var(--cb-active-text);font-size:11px}
.cb-root .cb-shint-src button:hover{text-decoration:underline}

/* height strip (rule of thumb) */
.cb-root .cb-heights{margin:0 0 12px;max-width:960px}
.cb-root .cb-heights-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:5px}
.cb-root .cb-heights-why{font-size:11px;color:var(--cb-fg-dim)}
.cb-root .cb-heights-rot{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-fg-dim);padding:0 5px;border:1px dashed var(--cb-stroke-strong);border-radius:2px}
.cb-root .cb-heights-row{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.cb-root .cb-hcell{display:flex;flex-direction:column;align-items:center;gap:2px;padding:3px 4px 2px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-hcell-pic{display:block;line-height:0;color:var(--cb-fg-dim)}
.cb-root .cb-hcell-pic svg{display:block}
.cb-root .cb-hcell-n{font-size:10px;color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;letter-spacing:.06em}
.cb-root .cb-hcell--done .cb-hcell-pic{opacity:.6}
.cb-root .cb-hcell--done .cb-hcell-n{color:var(--cb-ok-text)}
.cb-root .cb-hcell--now{border-color:var(--cb-active);box-shadow:inset 0 -2px 0 var(--cb-active)}
.cb-root .cb-hcell--now .cb-hcell-n{color:var(--cb-active-text);font-weight:700}

/* plan source: part list, reasons for disabled buttons, CSV import folded */
.cb-root .cb-sparts{margin:10px 0 4px;padding:0;list-style:none;display:grid;gap:2px;font-size:11px}
.cb-root .cb-spart{display:grid;grid-template-columns:14px 38px minmax(0,1fr) auto;gap:6px;align-items:baseline;padding:2px 5px;border:1px solid transparent}
.cb-root .cb-spart-mark{color:var(--cb-fg-dim);text-align:center}
.cb-root .cb-spart-ref{color:var(--cb-fg);font-weight:700}
.cb-root .cb-spart-what{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-spart-step{color:var(--cb-fg-dim);font-variant-numeric:tabular-nums;font-size:10px;letter-spacing:.06em}
.cb-root .cb-spart--done .cb-spart-mark{color:var(--cb-ok-text)}
.cb-root .cb-spart--done .cb-spart-what,.cb-root .cb-spart--done .cb-spart-ref{color:var(--cb-fg-dim)}
.cb-root .cb-spart--now{border-color:var(--cb-active);background:color-mix(in oklab,var(--cb-active) 7%,transparent)}
.cb-root .cb-spart--now .cb-spart-mark,.cb-root .cb-spart--now .cb-spart-step{color:var(--cb-active-text);font-weight:700}
.cb-root .cb-spart--none .cb-spart-step{color:var(--cb-warn-text)}
.cb-root .cb-solder-why{margin:4px 0 0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim);white-space:normal}
.cb-root .cb-solder-csv{margin-top:12px;border-top:1px solid var(--cb-stroke);padding-top:8px}
.cb-root .cb-solder-csv > summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px}
.cb-root .cb-solder-csv > summary::-webkit-details-marker{display:none}
.cb-root .cb-solder-csv > summary::before{content:'▸';color:var(--cb-fg-dim);font-size:11px}
.cb-root .cb-solder-csv[open] > summary::before{content:'▾'}
.cb-root .cb-solder-csv > summary:focus-visible{outline:2px solid var(--cb-active);outline-offset:2px}
`)

// --- 17-styles-calc.js
// Station 02 CALC styles: card as an instrument (schematic + readout on top),
// unit inside the field, result bands, check chips, formula table, assumptions drawer, fixed source foot, equal card
// heights per grid row. Registered through CB_CSS_PARTS (10-tokens.js); later than 11/12, so equal specificity wins
// over the old calculator rules there. Only --cb-* tokens.
CB_CSS_PARTS.push(`
/* MODULES: summary line of generic cards; the group pick wraps (narrow Bench) */
.cb-root .cb-group--calc{border-right:0;padding-right:0;min-width:0}
.cb-root .cb-group--calc > .cb-seg{flex:0 1 auto;flex-wrap:wrap;min-width:0}
.cb-root .cb-calc-sum{margin:-2px 0 0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}
/* narrow inspector, the value wraps */
@container cbinsp (max-width:300px){.cb-root [data-cb=project-parts] td:nth-child(2){white-space:normal}}
/* grid: cards of a row share the height; the foot sits at the bottom of every card */
.cb-root .cb-calcgrid{align-items:stretch}
.cb-root .cb-calc{display:flex;flex-direction:column;gap:8px;container:cbcalc/inline-size;min-width:0}
.cb-root .cb-calc > .cb-card-head{min-height:20px}

/* top = the instrument: headline and bands, schematic, checks and readings. Narrow card: result first (it dominates),
   then the schematic, then the readings; wide card: schematic left, result and readings right. */
.cb-root .cb-calc-top{display:grid;grid-template-columns:minmax(0,1fr);grid-template-areas:"read" "fig" "meas";gap:8px;align-items:start}
@container cbcalc (min-width:600px){.cb-root .cb-calc-top{grid-template-columns:auto minmax(0,1fr);grid-template-areas:"fig read" "fig meas";
  grid-template-rows:auto 1fr;column-gap:16px}}
.cb-root .cb-calc-top > .cb-calc-fig{grid-area:fig}
.cb-root .cb-calc-top > .cb-calc-readout{grid-area:read}
.cb-root .cb-calc-top > .cb-calc-meas{grid-area:meas;display:grid;gap:8px;min-width:0;align-content:start}
.cb-root .cb-calc-fig{justify-self:start;padding:6px 4px 4px;border:1px solid var(--cb-stroke);border-radius:2px;line-height:0;
  background:var(--cb-bg);background-image:linear-gradient(var(--cb-grid) 1px,transparent 1px),linear-gradient(90deg,var(--cb-grid) 1px,transparent 1px);
  background-size:12px 12px;background-position:-1px -1px}
.cb-root .cb-calc-svg{display:block;overflow:visible;font-family:var(--cb-mono)}
.cb-root .cb-calc-readout{display:grid;gap:8px;min-width:0;align-content:start}
.cb-root .cb-calc-readout--idle{padding:8px 10px;border:1px dashed var(--cb-stroke-strong);border-radius:2px}
.cb-root .cb-calc-readout--idle p{margin:0;font-size:11px;line-height:1.5;color:var(--cb-fg-dim)}
.cb-root .cb-calc-main{display:flex;align-items:baseline;gap:4px 10px;flex-wrap:wrap}
.cb-root .cb-calc-main > .cb-label{flex:1 0 100%}
.cb-root .cb-calc-big{font-size:24px;line-height:1.1;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:.02em;white-space:nowrap}
.cb-root .cb-calc-verdict{font-size:11px;white-space:nowrap}

/* ruler exact → E series */
.cb-root .cb-calc-ruler{display:grid;grid-template-columns:auto minmax(48px,1fr) auto;align-items:end;gap:8px}
.cb-root .cb-calc-rend{display:grid;gap:1px;min-width:0}
.cb-root .cb-calc-rend--to{text-align:right}
.cb-root .cb-calc-rend small,.cb-root .cb-calc-wscale small,.cb-root .cb-calc-mk{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-calc-rend b{font-size:13px;font-weight:700;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-calc-rend--to b.cb-ok{color:var(--cb-ok-text)}.cb-root .cb-calc-rend--to b.cb-bad{color:var(--cb-bad-text)}
.cb-root .cb-calc-rtrack{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:2px;min-width:0;padding-bottom:5px}
.cb-root .cb-calc-rtrack > i{order:2;position:relative;display:block;width:100%;height:2px;background:var(--cb-fg-dim)}
.cb-root .cb-calc-rtrack > i::before{content:"";position:absolute;left:0;top:-4px;width:2px;height:10px;background:var(--cb-fg-dim)}
.cb-root .cb-calc-rtrack > i::after{content:"";position:absolute;right:-1px;top:-4px;border-left:8px solid var(--cb-fg);border-top:5px solid transparent;border-bottom:5px solid transparent}
.cb-root .cb-calc-ruler--down .cb-calc-rtrack > i::after{right:auto;left:-1px;border-left:0;border-right:8px solid var(--cb-fg)}
.cb-root .cb-calc-rtrack > em{order:1;font-style:normal;font-size:11px;color:var(--cb-fg);white-space:nowrap}

/* meter: a value against its limit */
.cb-root .cb-calc-meter,.cb-root .cb-calc-window{display:grid;gap:4px;min-width:0}
.cb-root .cb-calc-mhead{display:flex;align-items:baseline;gap:4px 8px;flex-wrap:wrap;font-size:11px}
.cb-root .cb-calc-mhead > b{font-size:13px;white-space:nowrap}
.cb-root .cb-calc-mlim{margin-left:auto;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-calc-mlim b{color:var(--cb-fg);font-weight:700}
.cb-root .cb-calc-mtrack,.cb-root .cb-calc-wtrack{position:relative;height:8px;border:1px solid var(--cb-stroke-strong);border-radius:1px;background:
  repeating-linear-gradient(90deg,transparent 0 9px,color-mix(in oklab,var(--cb-fg-faint) 45%,transparent) 9px 10px)}
.cb-root .cb-calc-mtrack::after{content:"";position:absolute;right:-1px;top:-4px;bottom:-4px;width:2px;background:var(--cb-fg)}
.cb-root .cb-calc-mfill{position:absolute;left:0;top:0;bottom:0;display:block}
.cb-root .cb-calc-mfill--fg{background:var(--cb-fg-dim)}
.cb-root .cb-calc-mfill--ok{background:var(--cb-ok)}
.cb-root .cb-calc-mfill--bad{background:var(--cb-bad)}
.cb-root .cb-calc-mscale{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--cb-fg-dim)}
.cb-root .cb-calc-mnote{margin:0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}

/* I²C window: the band between R min and R max, the suggested value as a marker */
.cb-root .cb-calc-wbar{position:absolute;inset:0;display:block;opacity:.35}
.cb-root .cb-calc-wbar.cb-calc-mfill--fg{background:var(--cb-fg-dim)}
.cb-root .cb-calc-wmark{position:absolute;top:-5px;width:2px;height:16px;margin-left:-1px;background:var(--cb-fg)}
.cb-root .cb-calc-wscale{display:flex;justify-content:space-between;align-items:baseline;gap:4px 8px;flex-wrap:wrap;font-size:11px}
.cb-root .cb-calc-wscale b{white-space:nowrap}
.cb-root .cb-calc-wmid b{font-size:13px}

/* input with the unit inside the field */
.cb-root .cb-calc-in{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:4px 10px}
.cb-root .cb-calc-field label{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.3}
.cb-root .cb-calc-box{position:relative;display:block;min-width:0}
.cb-root .cb-calc-box--unit input{padding-right:30px}
.cb-root .cb-calc-unit{position:absolute;right:1px;top:1px;bottom:1px;display:flex;align-items:center;padding:0 7px;font-size:11px;color:var(--cb-fg-dim);
  border-left:1px solid var(--cb-stroke);pointer-events:none}
.cb-root .cb-calc-hint{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:break-word;line-height:1.35}

/* one action row on every card */
.cb-root .cb-calc-acts{margin-top:0;align-items:center}

/* result detail */
.cb-root .cb-calc-out{display:grid;gap:6px;border-top:0;padding-top:0;min-width:0}
.cb-root .cb-calc-checks{display:grid;gap:4px;min-width:0}
.cb-root .cb-calc-chips{display:flex;flex-wrap:wrap;gap:4px}
.cb-root .cb-calc-chip{display:inline-flex;align-items:center;gap:5px;padding:1px 6px;border:1px solid var(--cb-stroke-strong);border-radius:2px;font-size:11px;
  line-height:16px;white-space:nowrap;color:var(--cb-fg)}
.cb-root .cb-calc-chip b{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.cb-root .cb-calc-chip-s{font-weight:700}
.cb-root .cb-calc-chip--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,transparent)}
.cb-root .cb-calc-chip--ok .cb-calc-chip-s,.cb-root .cb-calc-chip--ok b{color:var(--cb-ok-text)}
.cb-root .cb-calc-chip--bad{border-color:var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 12%,transparent)}
.cb-root .cb-calc-chip--bad .cb-calc-chip-s,.cb-root .cb-calc-chip--bad b{color:var(--cb-bad-text)}
.cb-root .cb-calc-chip--dim{border-style:dashed}
.cb-root .cb-calc-chip--dim .cb-calc-chip-s,.cb-root .cb-calc-chip--dim b{color:var(--cb-fg-dim)}
.cb-root .cb-calc-chkd{margin:0;font-size:11px;line-height:1.45;color:var(--cb-fg-dim)}
.cb-root .cb-calc-warnl{margin:0;display:flex;gap:8px;align-items:baseline;font-size:11px;line-height:1.45;padding:3px 0 3px 8px;border-left:2px solid var(--cb-stroke-strong)}
.cb-root .cb-calc-warnl > b{flex:none;font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.cb-root .cb-calc-warnl--bad{border-left-color:var(--cb-bad)}
.cb-root .cb-calc-warnl--warn{border-left-color:var(--cb-warn)}

/* drawers: formula table and assumptions */
.cb-root .cb-calc-drawer{min-width:0;border-top:1px dashed var(--cb-stroke);padding-top:6px}
.cb-root .cb-calc-drawer > summary{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px}
.cb-root .cb-calc-akeys{font-size:11px;color:var(--cb-fg-dim);min-width:0;overflow-wrap:break-word}
.cb-root .cb-calc-eqs{display:grid;gap:2px;margin-top:6px;padding:6px 8px;border-left:2px solid var(--cb-active);background:var(--cb-bg)}
.cb-root .cb-calc-eqs code{font:inherit;font-size:11px;line-height:1.5;color:var(--cb-fg);white-space:normal;overflow-wrap:normal;word-break:normal}
.cb-root table.cb-calc-steps{width:100%;margin-top:6px;border-collapse:collapse;font-size:11px;line-height:1.45}
.cb-root .cb-calc-steps th,.cb-root .cb-calc-steps td{padding:3px 4px;border-bottom:1px dashed var(--cb-stroke);text-align:left;vertical-align:baseline}
.cb-root .cb-calc-steps thead th{font-size:10px;font-weight:400;letter-spacing:.14em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-calc-steps tbody th{font-weight:700;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-calc-steps td{color:var(--cb-fg-dim);white-space:normal;overflow-wrap:normal;word-break:normal}
.cb-root .cb-calc-steps td.cb-r{text-align:right;color:var(--cb-active-text);font-weight:600;white-space:nowrap}
.cb-root .cb-calc-passed{display:grid;gap:2px;margin-top:8px}
.cb-root .cb-calc-alist{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 10px;margin:6px 0 0;font-size:11px;line-height:1.45}
.cb-root .cb-calc-alist dt{color:var(--cb-fg);font-weight:600}
.cb-root .cb-calc-alist dd{margin:0;color:var(--cb-fg-dim);min-width:0;overflow-wrap:break-word}

/* fixed foot with the sources: full labels, wrapping, never cut */
.cb-root .cb-calc-foot{margin-top:auto;display:flex;align-items:baseline;gap:8px;padding-top:8px;border-top:1px solid var(--cb-stroke);font-size:11px;min-width:0}
.cb-root .cb-calc-foot .cb-k{flex:none;color:var(--cb-fg-dim)}
.cb-root .cb-calc-srcs{display:flex;flex-wrap:wrap;gap:2px 12px;min-width:0}
.cb-root .cb-calc-srcs button{color:var(--cb-active-text);text-align:left;line-height:1.45;min-width:0;overflow-wrap:break-word}
.cb-root .cb-calc-srcs button:hover{text-decoration:underline}
.cb-root .cb-calc-src0{color:var(--cb-fg-dim);line-height:1.45}
`)

// --- 18-styles-flash.js
// FLASH styles: flash dialog (target, hash groups with copy, memory bars, check list in
// words), job phase word, flash map (written images on an address axis), port connector symbols.
// Registered through CB_CSS_PARTS (10-tokens.js); comes after 11/12/13, so equal specificity wins here.
CB_CSS_PARTS.push(`
.cb-root .cb-vf-chk-at{white-space:nowrap}
/* dialog: three instrument blocks, each with its comment label */
.cb-root .cb-modal:has([data-cb=flash-hash]){width:min(560px,100%);max-height:calc(100% - 8px);overflow:auto}
.cb-root .cb-vf-dlg{display:grid;gap:10px;min-width:0}
.cb-root .cb-vf-block{display:grid;gap:6px;min-width:0;padding:8px 10px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-vf-block > .cb-label{font-size:10px}
.cb-root .cb-vf-algo{color:var(--cb-fg-dim)}
.cb-root .cb-vf-block .cb-kv--dialog{gap:5px 14px}

/* hash: eight groups of eight in a 4 × 2 grid (gaps instead of spaces: the text stays one hash) */
.cb-root .cb-vf-hashrow{display:flex;align-items:flex-start;gap:10px;min-width:0}
.cb-root .cb-vf-hash{display:grid;grid-template-columns:repeat(4,max-content);gap:3px 12px;font-size:12px;line-height:1.45;letter-spacing:.04em;
  color:var(--cb-fg);min-width:0;flex:1 1 auto}
.cb-root .cb-vf-hg{white-space:nowrap}
.cb-root .cb-vf-hg:nth-child(odd){color:var(--cb-fg)}
.cb-root .cb-vf-hg:nth-child(even){color:var(--cb-fg-dim)}
.cb-root .cb-vf-hashshort{display:inline-flex;gap:6px;white-space:nowrap}
.cb-root .cb-vf-copy{flex:none;font-size:11px;white-space:nowrap}

/* memory: label · bar · percent · optional bytes */
.cb-root .cb-vf-mem{display:grid;gap:5px;margin-top:4px}
.cb-root .cb-vf-meter{display:grid;grid-template-columns:84px minmax(60px,1fr) 52px;gap:8px;align-items:center;font-size:11px;min-width:0}
.cb-root .cb-vf-meter:has(> :nth-child(4)){grid-template-columns:84px minmax(60px,1fr) 52px max-content}
/* a level gauge: 10 px track with quarter ticks (25/50/75 %) */
.cb-root .cb-vf-meter .cb-bar{height:10px;background:
  linear-gradient(90deg,transparent calc(25% - 1px),var(--cb-stroke-strong) calc(25% - 1px) 25%,transparent 25% calc(50% - 1px),var(--cb-stroke-strong) calc(50% - 1px) 50%,
  transparent 50% calc(75% - 1px),var(--cb-stroke-strong) calc(75% - 1px) 75%,transparent 75%),
  color-mix(in oklab,var(--cb-fg) 8%,transparent)}
.cb-root .cb-vf-meter .cb-bar i{z-index:1}
.cb-root .cb-vf-meter > b{text-align:right;font-weight:600}
.cb-root .cb-vf-meter > .cb-label{text-transform:uppercase}

/* check list in words: symbol · state word · sentence */
.cb-root .cb-vf-checks{list-style:none;margin:0;padding:0;display:grid;gap:4px}
.cb-root .cb-vf-chk{display:grid;grid-template-columns:14px 96px minmax(0,1fr);gap:8px;align-items:baseline;font-size:11px;min-width:0}
.cb-root .cb-vf-chk-s{font-weight:700;text-align:center}
.cb-root .cb-vf-chk-w{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap}
.cb-root .cb-vf-chk-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-vf-chk--differs .cb-vf-chk-t{color:var(--cb-bad-text)}

/* job line: kind · phase word · percent */
.cb-root .cb-vf-phase{display:inline-flex;align-items:baseline;gap:6px;min-width:0}
.cb-root .cb-vf-phase > b{font-weight:600}
.cb-root .cb-vf-phase-w{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-active-text)}

/* port list: wrapping description (no ellipsis), connector symbol in front */
.cb-root .cb-port-l2{flex-wrap:wrap;row-gap:1px}
.cb-root .cb-vf-portdesc{min-width:0;white-space:normal;overflow-wrap:anywhere}
.cb-root .cb-vf-portsym{flex:none;width:30px;height:21px;display:block}

/* flash map: address axis with numbered marks, legend below (offsets and names, no sizes) */
.cb-root .cb-vf-map{display:grid;gap:6px;margin-top:8px;padding:8px 10px;border:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-vf-axis{position:relative;height:44px;margin:0 10px}
.cb-root .cb-vf-axis-line{position:absolute;left:0;right:-8px;top:21px;height:2px;background:var(--cb-stroke-strong)}
.cb-root .cb-vf-axis-line::after{content:"";position:absolute;right:-2px;top:-4px;border:5px solid transparent;border-left-color:var(--cb-stroke-strong);border-right:0}
.cb-root .cb-vf-mark{position:absolute;top:0;width:0;height:44px}
.cb-root .cb-vf-mark > i{position:absolute;left:-1px;top:14px;width:2px;height:16px;background:var(--cb-active)}
.cb-root .cb-vf-mark > b{position:absolute;left:-8px;top:0;width:16px;height:13px;line-height:13px;text-align:center;font-size:10px;font-weight:700;
  color:var(--cb-ink);background:var(--cb-active-fill)}
.cb-root .cb-vf-mark--lo > b{top:31px}
.cb-root .cb-vf-legend{list-style:none;margin:0;padding:0;display:grid;gap:3px}
.cb-root .cb-vf-legend li{display:grid;grid-template-columns:16px max-content minmax(0,1fr) max-content;gap:8px;align-items:baseline;font-size:11px}
.cb-root .cb-vf-n{width:16px;line-height:13px;text-align:center;font-size:10px;font-weight:700;color:var(--cb-ink);background:var(--cb-active-fill)}
.cb-root .cb-vf-name{min-width:0;overflow-wrap:anywhere}
/* the backend's refusal under the locked Flash button; detection warnings above the record */
.cb-root .cb-vf-gate{margin:8px 0 0}
.cb-root .cb-vf-gate b{font-weight:600}
.cb-root .cb-vf-gate-hint{display:block;margin-top:2px;color:var(--cb-fg-dim)}
.cb-root .cb-vf-gate .cb-linkbtn{margin-top:2px}
.cb-root .cb-vf-dwarn{margin:0 0 8px}
`)

// --- 19-styles-debug.js
// DEBUG styles: 06 DEBUG panic anchor, panic analysis (ELF line, frames, register
// bank), frame ↔ log mark, console toolbar that gives way step by step instead of cutting (one CB_CSS_PARTS.push).
CB_CSS_PARTS.push(`
/* 06 DEBUG head: the title and the one panic anchor (the cards below do not repeat the stamp) */
.cb-root .cb-dbghead{display:flex;align-items:center;gap:8px 18px;flex-wrap:wrap;min-width:0}
.cb-root .cb-dbghead > .cb-title{flex:0 1 auto;min-width:0}
.cb-root .cb-panicanchor{display:inline-flex;align-items:center;gap:6px 12px;flex-wrap:wrap;min-width:0}
.cb-root .cb-panicanchor .cb-stamp{font-size:13px;padding:5px 12px;letter-spacing:.14em;white-space:nowrap;animation:cb-anchor-in .5s ease-out 1}
.cb-root .cb-anchor-at{font-size:12px;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-anchor-at b{font-weight:700;color:var(--cb-bad-text)}
@keyframes cb-anchor-in{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}

/* card order = reading order: with a panic the analysis leads (left, both rows), monitor and fix loop beside it */
.cb-root .cb-debuggrid[data-cb-panic=true]{grid-template-columns:minmax(0,7fr) minmax(0,5fr);grid-template-areas:"panic mon" "panic loop"}
@container cb (max-width:1099px){.cb-root .cb-debuggrid[data-cb-panic=true]{grid-template-columns:minmax(0,1fr);grid-template-areas:"panic" "mon" "loop"}}

/* panic analysis */
.cb-root .cb-pa-body{display:grid;gap:10px;margin-top:8px;min-width:0}
.cb-root .cb-pa-body > *{margin-top:0}
.cb-root .cb-pa-lead{margin:0;color:var(--cb-fg);font-size:13px;line-height:1.5;font-weight:600}
.cb-root .cb-pa .cb-actions{margin-top:2px}
/* ELF check: its own line, verdict then the reason, in full text colour */
.cb-root .cb-elfline{display:flex;align-items:baseline;gap:4px 10px;flex-wrap:wrap;padding:5px 9px;border:1px solid var(--cb-stroke-strong);
  border-left-width:3px;background:var(--cb-panel);font-size:12px;color:var(--cb-fg)}
.cb-root .cb-elfline-v{font-weight:700;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--cb-fg);white-space:nowrap}
.cb-root .cb-elfline-why{color:var(--cb-fg)}
.cb-root .cb-elfline--ok{border-color:color-mix(in oklab,var(--cb-ok) 55%,transparent)}.cb-root .cb-elfline--ok .cb-elfline-v{color:var(--cb-ok-text)}
.cb-root .cb-elfline--bad{border-color:color-mix(in oklab,var(--cb-bad) 60%,transparent)}.cb-root .cb-elfline--bad .cb-elfline-v{color:var(--cb-bad-text)}
.cb-root .cb-elfline--faint{border-left-color:var(--cb-fg-dim)}

/* frames: #0 carries the alarm bar; a hovered or focused frame marks its PC in the log */
.cb-root .cb-pa .cb-frames-t{margin-top:0}
.cb-root .cb-frames-t tr.cb-frow--top td{background:color-mix(in oklab,var(--cb-bad) 12%,transparent);font-weight:700}
.cb-root .cb-frames-t tr.cb-frow--top td:first-child{box-shadow:inset 3px 0 0 var(--cb-bad)}
.cb-root .cb-frames-t td:last-child{color:var(--cb-fg-dim)}
.cb-root .cb-frames-t tr.cb-frow--link:hover td,.cb-root .cb-frames-t tr.cb-frow--link:focus-visible td{background:color-mix(in oklab,var(--cb-active) 14%,transparent)}
.cb-root .cb-frames-t tr.cb-frow--link:hover td:last-child,.cb-root .cb-frames-t tr.cb-frow--link:focus-visible td:last-child{color:var(--cb-active-text)}
.cb-root .cb-frames-t tr.cb-frow--link:focus-visible{outline:2px solid var(--cb-active);outline-offset:-2px}

/* register bank: key registers as labelled readouts, the whole dump folded below */
.cb-root .cb-regbank{display:grid;gap:6px;min-width:0}
.cb-root .cb-regkeys{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.cb-root .cb-regkey{display:grid;align-content:start;gap:2px;padding:6px 9px 7px;min-width:0;border:1px solid color-mix(in oklab,var(--cb-bad) 45%,transparent);
  border-left:3px solid var(--cb-bad);background:color-mix(in oklab,var(--cb-bad) 6%,var(--cb-panel))}
.cb-root .cb-regkey:hover,.cb-root .cb-regkey:focus-visible{border-color:var(--cb-active);outline:none}
.cb-root .cb-regkey-n{font-size:11px;font-weight:700;letter-spacing:.12em;color:var(--cb-bad-text)}
.cb-root .cb-regkey-v{font-size:14px;font-weight:700;color:var(--cb-fg);letter-spacing:.02em}
.cb-root .cb-regkey-l{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--cb-fg-dim)}
.cb-root .cb-regkey-note{font-size:11px;color:var(--cb-fg);overflow-wrap:anywhere}
.cb-root .cb-regdump > summary{cursor:pointer;width:max-content;max-width:100%}
.cb-root .cb-regdump > summary .cb-label{color:var(--cb-fg-dim)}
.cb-root .cb-reggrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:2px 10px;margin-top:6px;font-size:11px}
.cb-root .cb-regcell{display:flex;justify-content:space-between;gap:8px;padding:1px 6px;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-regcell-n{font-weight:600}
.cb-root .cb-regcell--key{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-bad) 10%,transparent);box-shadow:inset 2px 0 0 var(--cb-bad)}
.cb-root .cb-regcell--key .cb-regcell-n{color:var(--cb-bad-text)}
.cb-root .cb-regcell:hover{color:var(--cb-fg);background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
@container cb (max-width:560px){.cb-root .cb-regkeys{grid-template-columns:minmax(0,1fr)}}

/* the marked address in the raw panic lines of the log */
.cb-root .cb-logmark{background:var(--cb-active-fill);color:var(--cb-ink);font-weight:700;border-radius:1px;box-shadow:0 0 0 1px var(--cb-active-fill)}
.cb-root .cb-panic .cb-frame[tabindex]:hover,.cb-root .cb-panic .cb-frame[tabindex]:focus-visible{border-color:var(--cb-active);outline:none}

/* console toolbar: "▼ N new lines" sits here (no pill over the log corner); items give way step by step, never cut */
.cb-root .cb-followbtn{flex:none;color:var(--cb-active-text);border-color:var(--cb-active)}
.cb-root .cb-followbtn:hover{color:var(--cb-active-text);background:color-mix(in oklab,var(--cb-active) 12%,transparent)}
.cb-root .cb-tabs .cb-meta > .cb-consmeta{flex:0 1 auto;overflow:visible;text-overflow:clip;white-space:nowrap}
@container cbcons (max-width:1000px){.cb-root .cb-consport,.cb-root .cb-tabs .cb-meta .cb-simban-w{display:none}}
@container cbcons (max-width:700px){.cb-root .cb-tbl{display:none}.cb-root .cb-tabs .cb-meta{gap:6px;padding-left:8px}}
@container cbcons (max-width:560px){.cb-root .cb-tbx{display:none}}
@container cbcons (max-width:440px){.cb-root .cb-tabs [role=tab]{padding:0 8px;letter-spacing:.1em}
  .cb-root .cb-tabs .cb-meta{padding:0 6px 0 6px}
  .cb-root .cb-meta:has(.cb-followbtn) .cb-pjump{display:none}}
`)

// --- 19-styles-modules.js
// Module styles: dialog, bus card, module rows; only cb-mod-*, one push
CB_CSS_PARTS.push(`
.cb-root .cb-mod-pad{padding:12px 0}
.cb-root .cb-mod-list{list-style:none;margin:6px 0 0;padding:0;display:grid;gap:4px;min-width:0}
.cb-root .cb-mod-row{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:8px;align-items:baseline;min-width:0;font-size:12px;line-height:1.45;overflow-wrap:anywhere}
.cb-root .cb-mod-row--f{grid-template-columns:14px minmax(0,1fr)}
.cb-root .cb-mod-row--r{grid-template-columns:14px minmax(0,1fr) auto}
.cb-root .cb-mod-row--2{grid-template-columns:64px minmax(0,1fr)}
.cb-root .cb-mod-sym{display:inline-flex;justify-content:center;min-width:12px;font-size:12px;font-weight:700}
.cb-root .cb-mod-row--bad .cb-mod-sym,.cb-root .cb-mod-row--bad b,.cb-root .cb-mod-t-bad{color:var(--cb-bad-text)}
.cb-root .cb-mod-row--warn .cb-mod-sym,.cb-root .cb-mod-row--warn b,.cb-root .cb-mod-t-warn{color:var(--cb-warn-text)}
.cb-root .cb-mod-row--ok .cb-mod-sym,.cb-root .cb-mod-row--ok b,.cb-root .cb-mod-t-ok{color:var(--cb-ok-text)}
.cb-root .cb-mod-row--dim .cb-mod-sym,.cb-root .cb-mod-dim,.cb-root .cb-mod-t-dim,.cb-root .cb-mod-k,.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-open td,.cb-root .cb-mod-sum{color:var(--cb-fg-dim)}
.cb-root .cb-mod-k,.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-nums,.cb-root .cb-mod-open td,.cb-root .cb-mod-grp .cb-mod-dim,.cb-root .cb-mod-pins .cb-mod-dim,.cb-root .cb-mod-railhead .cb-mod-push,.cb-root .cb-mod-grphead span{font-size:11px}
.cb-root .cb-mod-page,.cb-root .cb-mod-catl,.cb-root .cb-mod-ellip{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cb-root .cb-mod-push{margin-left:auto}
.cb-root .cb-mod-link{color:var(--cb-active-text);font-size:12px;padding:0;white-space:nowrap;text-align:left}
.cb-root .cb-mod-link:hover,.cb-root .cb-mod-link:focus-visible{text-decoration:underline}
.cb-root .cb-mod-note{font-size:11px;line-height:1.5;margin:6px 0 0;overflow-wrap:anywhere}
.cb-root .cb-mod-dlg{max-height:min(60vh,540px);overflow:auto;min-width:0;padding-right:2px}
.cb-root .cb-mod-filter{display:grid;grid-template-columns:minmax(0,1fr) 200px;gap:8px}
.cb-root .cb-mod-search,.cb-root .cb-mod-cat{width:100%;min-width:0}
.cb-root .cb-mod-sum{margin:8px 0 6px;font-size:11px}
.cb-root .cb-mod-items{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.cb-root .cb-mod-item{display:grid;gap:5px;width:100%;text-align:left;padding:7px 10px;border:1px solid var(--cb-stroke-strong);min-width:0}
.cb-root .cb-mod-item:hover,.cb-root .cb-mod-item:focus-visible,.cb-root .cb-mod-item[aria-current=true]{border-color:var(--cb-active)}
.cb-root .cb-mod-itemhead{display:flex;gap:8px;align-items:baseline;min-width:0;font-size:12px}
.cb-root .cb-mod-itemhead .cb-mod-ellip{flex:1 1 auto}
.cb-root .cb-mod-tags{display:flex;flex-wrap:wrap;gap:4px 6px;min-width:0}
.cb-root .cb-mod-tag{padding:0 6px;border:1px solid var(--cb-stroke-strong);font-size:11px;line-height:17px;color:var(--cb-fg-dim);white-space:nowrap}
.cb-root .cb-mod-tag--pwr{border-color:color-mix(in oklab,var(--cb-power) 55%,var(--cb-stroke-strong))}
.cb-root .cb-mod-tag--warn{border-color:var(--cb-warn);color:var(--cb-warn-text)}
.cb-root .cb-mod-dhead{display:grid;gap:6px;margin-bottom:10px}
.cb-root .cb-mod-dgrid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:4px 16px}
.cb-root .cb-mod-sec{margin-top:10px;min-width:0}
.cb-root .cb-mod-pins{width:100%;border-collapse:collapse;font-size:12px;margin-top:4px}
.cb-root .cb-mod-pins td{padding:2px 6px 2px 0;vertical-align:baseline;border-bottom:1px dashed var(--cb-stroke);overflow-wrap:anywhere}
.cb-root .cb-mod-pins .cb-mod-nw{white-space:nowrap;overflow-wrap:normal}
.cb-root .cb-mod-dcol,.cb-root .cb-mod-rail{display:grid;gap:2px;align-content:start;min-width:0}
.cb-root .cb-mod-fact{display:grid;grid-template-columns:60px minmax(0,1fr);gap:8px;align-items:baseline;font-size:12px;line-height:1.5;margin-top:3px}
.cb-root .cb-mod-srcrow{margin-top:12px}
.cb-root .cb-mod-addbox{margin:2px 0 4px;padding:10px;border:1px dashed var(--cb-stroke-strong);display:grid;gap:6px}
.cb-root .cb-mod-inline{display:flex;gap:8px;align-items:center;font-size:12px;min-width:0;overflow-wrap:anywhere}
.cb-root .cb-mod-inline select{padding:3px 6px}
.cb-root .cb-mod-addrow{display:flex;align-items:center;gap:12px;justify-content:space-between}
.cb-root .cb-mod-addrow .cb-mod-note{margin:0}
.cb-root .cb-mod-addrow > button{flex:none}
.cb-root .cb-mod-bus{margin-top:12px}
.cb-root .cb-mod-head{flex-wrap:wrap;row-gap:2px}
.cb-root .cb-mod-head > *{white-space:nowrap}
.cb-root .cb-mod-busbox{margin-top:6px;padding-bottom:6px;border-bottom:1px dashed var(--cb-stroke-strong);display:grid;gap:2px}
.cb-root .cb-mod-rails,.cb-root .cb-mod-reqs{margin-top:10px;display:grid;gap:6px}
.cb-root .cb-mod-railhead{display:flex;flex-wrap:wrap;gap:0 8px;align-items:baseline;font-size:12px}
.cb-root .cb-mod-meter{position:relative;height:6px;margin:3px 0;border:1px solid var(--cb-stroke-strong);overflow:hidden}
.cb-root .cb-mod-meter i{position:absolute;inset:0 auto 0 0;background:var(--cb-ok)}
.cb-root .cb-mod-meter--warn i{background:var(--cb-warn)}
.cb-root .cb-mod-meter--bad i{background:var(--cb-bad)}
.cb-root .cb-mod-meter--none{border-style:dashed;background:none}
.cb-root .cb-mod-grp td{padding-top:7px;white-space:normal;cursor:pointer;border-bottom-style:solid}
.cb-root .cb-mod-grp:hover td{background:color-mix(in oklab,var(--cb-fg) 5%,transparent)}
.cb-root .cb-mod-grphead{display:flex;gap:8px;align-items:baseline;min-width:0;font-size:12px}
.cb-root .cb-mod-grphead span{flex:none;margin-left:auto}
.cb-root .cb-mod-grpbtn{flex:1 1 auto;font-weight:700}
.cb-root .cb-mod-fd>summary{cursor:pointer;grid-template-columns:14px minmax(0,1fr) 10px}
.cb-root .cb-mod-fd>summary::after{content:'▸';color:var(--cb-fg-dim)}
.cb-root .cb-mod-fd[open]>summary::after{content:'▾'}
.cb-root .cb-mod-fd .cb-mod-note{margin:2px 0 4px 22px}
`)

// --- 19-styles-notices.js
// Notice styles: the Bench's notice zone (30-ui-bench.js NoticeZone), a grid row under
// the HUD that only exists while a notice is shown (nothing covers the station; without notices the shell is as before).
CB_CSS_PARTS.push(`
.cb-root .cb-shell[data-cb-notes=yes]{grid-template-rows:52px auto minmax(0,1fr) var(--cb-cons-h);
  grid-template-areas:"hud hud hud" "rail note note" "rail main insp" "rail cons cons"}
.cb-root .cb-shell[data-cb-notes=yes][data-cb-insp=none]{grid-template-areas:"hud hud" "rail note" "rail main" "rail cons"}
@container cb (max-width:799px){.cb-root .cb-shell[data-cb-notes=yes]{grid-template-areas:"hud hud" "rail note" "rail main" "rail cons"}}
.cb-root .cb-notes{grid-area:note;display:grid;gap:4px;min-width:0;padding:6px 18px;border-bottom:1px solid var(--cb-stroke);background:var(--cb-bg)}
.cb-root .cb-shell:not([data-cb-notes=yes]) .cb-notes{position:absolute;width:1px;height:1px;padding:0;border:0;overflow:hidden;clip-path:inset(50%)}
.cb-root .cb-notice{display:grid;grid-template-columns:16px 64px minmax(0,1fr) auto;gap:8px;align-items:baseline;min-width:0;padding:4px 6px 4px 8px;
  border:1px solid var(--cb-stroke-strong);background:var(--cb-panel);font-size:12px;line-height:1.45}
.cb-root .cb-notice-sym{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border:1px solid currentColor;border-radius:2px;
  font-size:11px;font-weight:700;line-height:1;align-self:start;margin-top:1px}
.cb-root .cb-notice-w{font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700}
.cb-root .cb-notice-t{color:var(--cb-fg);min-width:0;overflow-wrap:anywhere}
.cb-root .cb-notice-x{align-self:start;padding:0 4px;font-size:14px;line-height:18px;color:var(--cb-fg-dim)}
.cb-root .cb-notice-x:hover,.cb-root .cb-notice-x:focus-visible{color:var(--cb-fg)}
.cb-root .cb-notice--ok .cb-notice-sym,.cb-root .cb-notice--ok .cb-notice-w{color:var(--cb-ok-text)}
.cb-root .cb-notice--info .cb-notice-sym,.cb-root .cb-notice--info .cb-notice-w{color:var(--cb-fg-dim)}
.cb-root .cb-notice--warn{border-color:color-mix(in oklab,var(--cb-warn) 50%,transparent)}
.cb-root .cb-notice--warn .cb-notice-sym,.cb-root .cb-notice--warn .cb-notice-w{color:var(--cb-warn-text)}
.cb-root .cb-notice--bad{border-color:color-mix(in oklab,var(--cb-bad) 55%,transparent)}
.cb-root .cb-notice--bad .cb-notice-sym,.cb-root .cb-notice--bad .cb-notice-w{color:var(--cb-bad-text)}
.cb-root .cb-notice--bad .cb-notice-sym{background:color-mix(in oklab,var(--cb-bad) 14%,transparent)}
`)

// --- 20-api.js
// Data access: wraps ctx.rest for the bench routes. Every call resolves to a result envelope, never throws.
// Fixture mode (development builds only): CB_FIXTURES is embedded AND the ctx.storage switch `useFixtures` is not
// false. The product build has CB_FIXTURES = null and always talks to the backend.

function fixtureModeOn(ctx) {
  if (CB_FIXTURES === null || typeof CB_FIXTURES !== 'object') return false
  try {
    return ctx?.storage?.get?.('useFixtures', true) !== false
  } catch {
    return true
  }
}

function createApi(ctx) {
  const fixtures = fixtureModeOn(ctx) ? createFixtureBackend(CB_FIXTURES) : null

  async function call(method, path, body, action) {
    if (fixtures) {
      const env = await fixtures.handle(method, path, body)
      return isEnvelope(env) ? env : errorEnvelope(action, 'fixture_missing', `No fixture for ${method} ${path}.`, null, 404)
    }
    try {
      const opts = body === undefined || body === null ? { method } : { method, body }
      return asEnvelope(await ctx.rest(path, opts), action)
    } catch (e) {
      return parseRestError(e, action)
    }
  }

  const enc = encodeURIComponent
  return {
    mode: fixtures ? 'fixtures' : 'live',
    fixtures,
    health: () => call('GET', '/health', null, 'health'),
    doctor: () => call('GET', '/doctor', null, 'doctor.run'),
    projects: () => call('GET', '/projects', null, 'project.list'),
    project: id => call('GET', `/projects/${enc(id)}`, null, 'project.get'),
    patchProject: (id, expectedRev, ops) => call('PATCH', `/projects/${enc(id)}`, { expected_rev: expectedRev, ops }, 'project.update'),
    deleteProject: id => call('DELETE', `/projects/${enc(id)}`, null, 'project.delete'),
    demo: () => call('POST', '/projects/demo', {}, 'sim.demo'),
    board: id => call('GET', `/boards/${enc(id)}`, null, 'board.layout'),
    pinsCheck: body => call('POST', '/pins/check', body, 'pins.check'),
    pinsSuggest: body => call('POST', '/pins/suggest', body, 'pins.suggest'),
    pinsInfo: params => call('GET', `/pins/info${query(params)}`, null, 'pins.info'),
    ports: () => call('GET', '/ports', null, 'board.ports'),
    serialTail: (port, after) => call('GET', `/serial/tail${query({ port, after })}`, null, 'serial.tail'),
    crashDecode: body => call('POST', '/crash/decode', body, 'crash.decode'),
    job: id => call('GET', `/jobs/${enc(id)}`, null, 'job.get'),
    // Workshop, board operation (jobs), serial control. Detect/flash/open only ever run from a click.
    createProject: body => call('POST', '/projects', body, 'project.create'),
    calc: (type, body) => call('POST', `/calc/${enc(type)}`, body, `calc.${type}`),
    schematic: body => call('POST', '/schematic', body, 'schematic.render'),
    solderPlan: body => call('POST', '/solder/plan', body, 'solder.plan'),
    solderStep: (id, stepId, done) => call('POST', `/projects/${enc(id)}/solder/${enc(stepId)}`, { done: Boolean(done) }, 'project.update'),
    firmwareExample: (id, overwrite = false) => call('POST', `/projects/${enc(id)}/firmware/example`, { example: 'laser-trigger', ...(overwrite ? { overwrite: true } : {}) }, 'project.update'),
    detect: body => call('POST', '/board/detect', body, 'board.detect'),
    build: body => call('POST', '/board/build', body, 'board.build'),
    flash: body => call('POST', '/board/flash', body, 'board.flash'),
    // would the flash be refused? (no port opened, no tool started)
    flashCheck: (project, port) => call('GET', `/board/flash/check${query({ project, port })}`, null, 'board.flash_check'),
    serialOpen: body => call('POST', '/serial/open', body, 'serial.open'),
    serialClose: port => call('POST', '/serial/close', { port }, 'serial.close'),
    // module catalog: catalog, one module, calculator metadata. `calc(kind, body)`
    // above is already generic (POST /calc/{kind}); the project ops add_module/connect/set_rails go through
    // patchProject (lib/modules.js addModuleOp/connectOp/setRailsOp build them).
    modules: (q, category, iface, { limit, offset } = {}) =>
      call('GET', `/modules${query({ q, category, interface: iface, limit, offset })}`, null, 'modules.list'),
    module: (id, variant) => call('GET', `/modules/${enc(id)}${query({ variant })}`, null, 'modules.info'),
    calcMeta: () => call('GET', '/calc', null, 'calc.list')
  }
}

// --- 25-store.js
// Store: module-wide sdk.atom state shared by every mounted surface (page, workspace tile, pane, status chip),
// actions that talk to the API, gateway events `plugin.circuit-bench.*` and the 3 s polling fallback.

const $nav = sdk.atom({ project: null, station: 'plan', n: 0 })
const $bench = sdk.atom({ phase: 'idle', error: null, health: null, projects: [], projectId: null, mode: 'live' })
const $project = sdk.atom(null)
const $board = sdk.atom({ status: 'idle', id: null, layout: null, error: null, sources: [] })
const $view = sdk.atom({ chip: null, variant: null, devkit: null, wifi: true, selected: null, variantPicked: false })
const $check = sdk.atom({ status: 'idle', key: null, env: null })
const $map = sdk.atom({ status: 'idle', key: null, env: null })
const $info = sdk.atom({ status: 'idle', gpio: null, env: null })
const $suggest = sdk.atom({ status: 'idle', env: null, role: null })
const $ports = sdk.atom({ status: 'idle', ports: [], error: null })
const $serial = sdk.atom({ port: null, buf: emptyBuffer(), status: 'idle', note: null, mode: null, simulated: null })
const $jobs = sdk.atom({ detect: null, build: null, flash: null })
const $panic = sdk.atom({ status: 'idle', env: null, key: null, summary: null, flashAt: null })
const $pulse = sdk.atom({ pins: [], roles: [], at: 0 })
// the Bench's notice zone (30-ui-bench.js NoticeZone): [{id, text, tone ok|info|warn|bad, at}]
const $notices = sdk.atom([])
const $ui = sdk.atom({ tab: 'serial', cons: 'open', consPinned: false, paneOpen: false, modal: null, look: 'phosphor', panicSeen: null, showTs: true,
  celebrated: null, sweepAt: 0 })

const CB = { ctx: null, api: null, mounts: 0, lastEventAt: 0, polling: false, offlineUntil: 0, paneDispose: null, tileClose: null }

function patchAtom(atom, patch) {
  atom.set({ ...atom.get(), ...patch })
}

function store(key, value) {
  try { CB.ctx?.storage?.set?.(key, value) } catch { /* storage is best effort */ }
}

function stored(key, fallback) {
  try { return CB.ctx?.storage?.get?.(key, fallback) ?? fallback } catch { return fallback }
}

const NOTICE_MAX = 3
let NOTICE_N = 0
const noticeFades = n => n.tone === 'ok' || n.tone === 'info'

/** A notice in the zone: ok/info fade after 3 s, warn/bad stay until ✕. The same text again replaces the old one;
 *  at most three, the oldest fading one goes first. */
function setNotice(text, tone = 'info') {
  if (!text) return
  const list = $notices.get().filter(n => !(n.text === text && n.tone === tone))
  list.push({ id: ++NOTICE_N, text: String(text), tone, at: Date.now() })
  while (list.length > NOTICE_MAX) {
    const i = list.findIndex(noticeFades)
    list.splice(i >= 0 ? i : 0, 1)
  }
  $notices.set(list)
}

function dropNotices(pred) {
  const list = $notices.get()
  const keep = list.filter(n => !pred(n))
  if (keep.length !== list.length) $notices.set(keep)
}

/** Board settings the PLAN station checks against: the what-if view or the project's own board. */
function boardOf(project) {
  return {
    chip: project?.board?.chip ?? null,
    variant: project?.board?.variant ?? null,
    devkit: project?.board?.devkit ?? null,
    wifi: project?.options?.wifi !== false
  }
}

function viewBoard() {
  const v = $view.get()
  const chip = chipInfo(v.chip)
  // the DevKit of the view when it belongs to the chip (ESP32: DevKitC V4 or WT32-ETH01), else the chip default
  return { chip: v.chip, variant: chip?.variants.length ? v.variant : null, wifi: Boolean(v.wifi), devkit: resolveDevkit(v.chip, v.devkit) }
}

function isWhatIf() {
  const p = $project.get()
  if (!p) return false
  const b = boardOf(p)
  const v = viewBoard()
  return b.chip !== v.chip || (b.variant ?? null) !== (v.variant ?? null) || b.wifi !== v.wifi || resolveDevkit(b.chip, b.devkit) !== v.devkit
}

function initStore(ctx) {
  CB.ctx = ctx
  CB.api = createApi(ctx)
  patchAtom($bench, { mode: CB.api.mode })
  const station = stored('lastStation', 'plan')
  $nav.set({ project: stored('lastProject', null), station: isStation(station) ? station : 'plan', n: 0 })
  patchAtom($ui, {
    cons: stored('console', 'open') === 'collapsed' ? 'collapsed' : 'open',
    look: stored('look', 'phosphor') === 'theme' ? 'theme' : 'phosphor',
    panicSeen: stored('panicSeen', null),
    celebrated: stored('celebrated', null),
    showTs: stored('timestamps', true) !== false,
    tab: ['serial', 'build', 'flash'].includes(stored('consoleTab', 'serial')) ? stored('consoleTab', 'serial') : 'serial'
  })
  const ev = (name, fn) => ctx.onEvent(`plugin.${PLUGIN_ID}.${name}`, e => {
    CB.lastEventAt = Date.now()
    try { fn(e?.payload ?? e?.data ?? e ?? {}) } catch (err) { console.warn('[circuit-bench] event handler', name, err) }
  })
  ev('project.updated', onProjectUpdated)
  ev('board.changed', () => loadPorts())
  ev('job.updated', onJobUpdated)
  ev('panic.detected', e => { if (!monitorActive(e?.port)) loadSerial({ fresh: false }) })
  ctx.setInterval(pollTick, 3000)
  loadPorts()
}

// ─── loading ───────────────────────────────────────────────────────────

let loadSeq = 0

async function loadBench({ projectId = null } = {}) {
  const my = ++loadSeq
  patchAtom($bench, { phase: 'loading', error: null })
  const health = await CB.api.health()
  if (my !== loadSeq) return
  if (!health.ok) {
    patchAtom($bench, { phase: 'error', error: health, health: null })
    CB.offlineUntil = Date.now() + 30_000
    return
  }
  loadPorts()
  const list = await CB.api.projects()
  if (my !== loadSeq) return
  if (!list.ok) {
    patchAtom($bench, { phase: 'error', error: list, health: health.result })
    return
  }
  const projects = list.result?.projects || []
  patchAtom($bench, { health: health.result, projects })
  if (!projects.length) {
    $project.set(null)
    patchAtom($bench, { phase: 'empty', projectId: null })
    return
  }
  const wanted = projectId || $nav.get().project || stored('lastProject', null)
  const id = projects.some(p => p.id === wanted) ? wanted : projects[0].id
  await loadProject(id, { initial: true })
  if (my !== loadSeq) return
  patchAtom($bench, { phase: $project.get() ? 'ready' : 'error' })
  loadSerial({ fresh: true })
}

function ensureBench() {
  const phase = $bench.get().phase
  if (phase === 'idle') loadBench()
}

async function loadProject(id, { initial = false, pulse = false } = {}) {
  const env = await CB.api.project(id)
  if (!env.ok) {
    if (initial) patchAtom($bench, { phase: 'error', error: env })
    else setNotice(env.error?.message || 'Could not reload the project.', 'bad')
    return null
  }
  const prev = $project.get()
  const next = env.result?.project
  if (!next) return null
  applyProject(next, { initial: initial || prev?.id !== next.id, pulse, prev })
  return next
}

function applyProject(next, { initial = false, pulse = false, prev = null } = {}) {
  const before = prev || $project.get()
  if (before && before.id !== next.id) resetProjectScoped() // 26-live.js: no results of the previous project
  $project.set(next)
  patchAtom($bench, { projectId: next.id })
  if ($nav.get().project !== next.id) patchAtom($nav, { project: next.id })
  store('lastProject', next.id)
  const boardChanged = !prev || prev.board?.chip !== next.board?.chip || prev.board?.variant !== next.board?.variant
    || prev.board?.devkit !== next.board?.devkit || (prev.options?.wifi !== false) !== (next.options?.wifi !== false)
  if (initial || boardChanged) {
    const b = boardOf(next)
    patchAtom($view, { chip: b.chip, variant: b.variant, devkit: b.devkit, wifi: b.wifi, variantPicked: variantPickedOf(b),
      ...(initial ? { selected: null } : {}) })
  }
  if (pulse && prev) pulseDiff(prev.assignments || [], next.assignments || [])
  const devkit = viewBoard().devkit
  if (devkit !== $board.get().id || $board.get().status === 'error') loadBoard(devkit)
  else runChecks()
}

async function loadBoard(id) {
  if (!id) {
    $board.set({ status: 'none', id: null, layout: null, error: null, sources: [] })
    runChecks()
    return
  }
  $board.set({ status: 'loading', id, layout: null, error: null, sources: [] })
  const env = await CB.api.board(id)
  if ($board.get().id !== id) return
  $board.set(env.ok ? { status: 'ready', id, layout: env.result, error: null, sources: env.sources || [] }
    : { status: 'error', id, layout: null, error: env, sources: [] })
  runChecks()
}

function checkKey(b, assignments, extras) {
  return JSON.stringify([b.chip, b.variant, b.wifi, b.devkit, (assignments || []).map(a => [a.role, a.pin, a.mode]),
    extras && extras.parts ? [extras.parts, extras.options] : null])
}

async function runChecks() {
  const p = $project.get()
  if (!p) return
  const b = viewBoard()
  const extras = modCheckExtras(p) // module instances and rails join the check
  const assignments = (p.assignments || []).map(a => (extras.parts && a.net
    ? { role: a.role, mode: a.mode, pin: a.pin, net: a.net } : { role: a.role, mode: a.mode, pin: a.pin }))
  const key = checkKey(b, assignments, extras)
  if ($check.get().key !== key || $check.get().status === 'error') {
    $check.set({ status: 'loading', key, env: $check.get().env })
    const body = { chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit, assignments, ...extras }
    const run = assignments.length ? CB.api.pinsCheck(body) : Promise.resolve(null)
    run.then(env => { if ($check.get().key === key) $check.set({ status: env && !env.ok ? 'error' : 'ready', key, env }) })
  }
  const layout = $board.get().layout
  const mapKeyNow = layout ? checkKey(b, [['map', layout.id]]) : null
  if (!layout) {
    $map.set({ status: 'none', key: null, env: null })
  } else if ($map.get().key !== mapKeyNow || $map.get().status === 'error') {
    $map.set({ status: 'loading', key: mapKeyNow, env: $map.get().env })
    const env = await CB.api.pinsCheck({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit, assignments: mapAssignments(layout) })
    if ($map.get().key === mapKeyNow) $map.set({ status: env.ok ? 'ready' : 'error', key: mapKeyNow, env })
  }
  const sel = $view.get().selected
  if (sel !== null && $info.get().gpio === sel) loadInfo(sel, { force: true })
}

async function loadInfo(gpio, { force = false } = {}) {
  if (!force && $info.get().gpio === gpio && $info.get().status !== 'error') return
  const b = viewBoard()
  $info.set({ status: 'loading', gpio, env: $info.get().gpio === gpio ? $info.get().env : null })
  const env = await CB.api.pinsInfo({ chip: b.chip, pin: gpio, variant: b.variant, devkit: b.devkit })
  if ($info.get().gpio === gpio) $info.set({ status: env.ok ? 'ready' : 'error', gpio, env })
}

async function loadPorts() {
  if (!CB.api) return
  patchAtom($ports, { status: $ports.get().status === 'idle' ? 'loading' : $ports.get().status })
  const env = await CB.api.ports()
  $ports.set(env.ok ? { status: 'ready', ports: env.result?.ports || [], error: null } : { status: 'error', ports: [], error: env })
}

/** Read what the backend already buffered for the project's detected port. Never opens a port:
 *  only sim:// ports are read automatically, real ports wait for the user (06 DEBUG). */
async function loadSerial({ fresh = false } = {}) {
  const p = $project.get()
  const port = p?.board?.detected?.port || null
  if (monitorActive($monitor.get().port)) return // the live monitor (06 DEBUG) owns the buffer
  if (!port || !/^sim:\/\//.test(port)) {
    $serial.set({ port, buf: emptyBuffer(), status: 'closed', note: port ? 'real-port' : 'no-port', mode: null, simulated: null })
    return
  }
  const cur = $serial.get()
  const base = fresh || cur.port !== port ? emptyBuffer() : cur.buf
  patchAtom($serial, { port, status: cur.status === 'idle' ? 'loading' : cur.status })
  const env = await CB.api.serialTail(port, base.lastSeq)
  if (!env.ok) {
    patchAtom($serial, { status: 'error', note: env.error?.message || 'serial tail failed' })
    return
  }
  const r = env.result || {}
  const msgs = [...(r.lines || []), ...(r.panic ? [r.panic] : [])]
  const buf = mergeLines(base, [{ t: 'state', port, state: r.state, epoch: r.epoch }, ...msgs])
  $serial.set({ port, buf, status: r.state || 'open', note: null, mode: null, simulated: r.simulated ?? null })
  watchSerialPanic(buf)
}

async function decodePanic(panic) {
  const p = $project.get()
  const tag = { key: panic.log_ref, summary: panic.summary ?? null, flashAt: p?.firmware?.last_flash?.at ?? null }
  $panic.set({ status: 'loading', env: null, ...tag })
  const env = await CB.api.crashDecode({ log_ref: panic.log_ref, project: p?.id, chip: p?.board?.chip })
  if ($panic.get().key === panic.log_ref) $panic.set({ status: env.ok ? 'ready' : 'error', env, ...tag })
}

// ─── events + polling ──────────────────────────────────────────────────

function onProjectUpdated(payload) {
  const p = $project.get()
  if (!payload?.id) return
  directiveProjectChanged(payload.id)
  if (Array.isArray(payload.changed) && payload.changed.includes('deleted')) {
    forgetProject(payload.id) // 26-live.js
    return
  }
  if (!p || payload.id !== p.id) {
    if ($bench.get().phase === 'empty') loadBench({ projectId: payload.id })
    else if ($bench.get().phase === 'ready' && !($bench.get().projects || []).some(x => x.id === payload.id)) refreshProjects()
    return
  }
  if (Number.isInteger(payload.rev) && payload.rev <= p.rev) return
  loadProject(p.id, { pulse: payload.by === 'agent' })
}

function onJobUpdated(payload) {
  return onJobEvent(payload) // 26-live.js
}

async function pollTick() {
  if (CB.polling || CB.mounts <= 0) return
  if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
  if (Date.now() - CB.lastEventAt < 10_000 || Date.now() < CB.offlineUntil) return
  CB.polling = true
  try {
    const phase = $bench.get().phase
    if (phase === 'error' && isOffline($bench.get().error)) {
      await loadBench()
    } else if (phase === 'ready') {
      const p = $project.get()
      const env = p ? await CB.api.project(p.id) : null
      if (env?.ok && env.result?.project && env.result.project.rev !== p.rev) {
        const next = env.result.project
        const byAgent = (next.assignments || []).some(a => a.updated_by === 'agent')
        applyProject(next, { prev: p, pulse: byAgent })
      } else if (env && !env.ok && isOffline(env)) {
        CB.offlineUntil = Date.now() + 30_000
      }
      await loadPorts()
      if ($serial.get().port && /^sim:\/\//.test($serial.get().port)) await loadSerial()
    }
  } finally {
    CB.polling = false
  }
}

/** Pins and rows whose assignment changed between two project revisions pulse twice. */
function pulseDiff(prevRows, nextRows) {
  const before = new Map(prevRows.map(a => [a.role, a]))
  const pins = new Set()
  const roles = new Set()
  for (const a of nextRows) {
    const b = before.get(a.role)
    if (!b || b.pin !== a.pin || b.mode !== a.mode || b.net !== a.net) {
      roles.add(a.role)
      pins.add(a.pin)
      if (b) pins.add(b.pin)
    }
    before.delete(a.role)
  }
  for (const gone of before.values()) pins.add(gone.pin)
  if (!pins.size && !roles.size) return
  $pulse.set({ pins: [...pins], roles: [...roles], at: Date.now() })
  CB.ctx?.setTimeout?.(() => { if (Date.now() - $pulse.get().at >= 1300) $pulse.set({ pins: [], roles: [], at: 0 }) }, 1400)
}

// ─── PLAN actions ──────────────────────────────────────────────────────

function selectPin(gpio) {
  patchAtom($view, { selected: gpio })
  if (gpio !== null && gpio !== undefined) loadInfo(gpio)
}

/** A stored variant counts as the user's choice when it is not the DevKit's preset (module.variant / chip default). */
function variantPickedOf(b) {
  return b.variant !== null && b.variant !== undefined && b.variant !== defaultVariant(b.chip, resolveDevkit(b.chip, b.devkit))
}

/**
 * What-if change of chip, DevKit, variant or Wi-Fi. A variant chosen in the toolbar is the user's
 * choice and stays across DevKits of the same chip. Otherwise a new DevKit presets its `module.variant` (C6-DevKitC-1
 * → WROOM-1, C6-DevKitM-1 → MINI-1, DevKitC V4 → WROOM-32E); a DevKit whose module variant is unknown (WT32-S1)
 * leaves it empty; a layout without module data (S3-DevKitC-1 v1.1) takes the chip default. A new chip starts from its
 * DevKit's preset. `opts.project`: the patch is the project board (reset), its variant counts as chosen when it is
 * not the preset.
 */
function setWhatIf(patch, opts = {}) {
  const cur = $view.get()
  const v = { ...cur, ...patch }
  const chip = chipInfo(v.chip)
  const before = resolveDevkit(cur.chip, cur.devkit)
  v.devkit = resolveDevkit(v.chip, v.devkit)
  const explicit = 'variant' in patch
  if (!chip?.variants.length) {
    v.variant = null
    v.variantPicked = false
  } else if (explicit) {
    if (v.variant !== null && !chip.variants.some(x => x.id === v.variant)) v.variant = defaultVariant(v.chip, v.devkit)
    v.variantPicked = opts.project ? variantPickedOf(v) : v.variant !== null
  } else if (cur.chip !== v.chip) {
    v.variant = defaultVariant(v.chip, v.devkit)
    v.variantPicked = false
  } else if (v.devkit !== before && !cur.variantPicked) {
    v.variant = defaultVariant(v.chip, v.devkit)
  }
  $view.set(v)
  $suggest.set({ status: 'idle', env: null, role: null })
  const devkit = viewBoard().devkit
  if (devkit !== $board.get().id) loadBoard(devkit)
  else runChecks()
}

function resetWhatIf() {
  const p = $project.get()
  if (p) setWhatIf(boardOf(p), { project: true })
}

async function patchOps(ops, { okText = null } = {}) {
  const p = $project.get()
  if (!p) return null
  const env = await CB.api.patchProject(p.id, p.rev, ops)
  if (env.ok && env.result?.project) {
    applyProject(env.result.project, { prev: p })
    if (okText) setNotice(okText, 'ok')
    return env
  }
  if (env.error?.code === 'project_conflict') {
    await loadProject(p.id)
    setNotice('The project changed meanwhile (agent or another window): reloaded the project, try again.', 'warn')
  } else {
    setNotice(env.error?.message || env.summary || 'The change was not saved.', 'bad')
  }
  return env
}

function assignPin({ role, mode, pin, net }) {
  return patchOps([{ op: 'assign', role, mode, pin, ...(net ? { net } : {}) }], { okText: `${role} → GPIO${pin} saved.` })
}

function unassignRole(role) {
  return patchOps([{ op: 'unassign', role }], { okText: `${role} removed.` })
}

function applyBoardToProject() {
  const b = viewBoard()
  return patchOps([{ op: 'set_board', chip: b.chip, variant: b.variant, devkit: b.devkit, wifi: b.wifi }],
    { okText: 'Board saved to the project.' })
}

/** Suggest replacements for the assignment `role` (or every blocked/caution one). */
async function suggestPins(rows, role = null) {
  const b = viewBoard()
  const targets = rows.filter(r => (role ? r.role === role : r.verdict === 'blocked' || r.verdict === 'caution'))
  if (!targets.length) {
    $suggest.set({ status: 'none', env: null, role: null })
    setNotice('All assigned pins are ok — nothing to replace.', 'ok')
    return
  }
  $suggest.set({ status: 'loading', env: null, role: targets[0].role })
  const taken = rows.filter(r => !targets.includes(r)).map(r => r.pin)
  const env = await CB.api.pinsSuggest({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: b.devkit,
    requests: targets.map(t => ({ role: t.role, mode: t.mode, requested: t.pin })), taken })
  $suggest.set({ status: env.ok ? 'ready' : 'error', env, role: targets[0].role })
  if (!env.ok) setNotice(env.error?.message || 'Suggestion failed.', 'bad')
  if (env.ok && !role) selectPin(targets[0].pin)
}

async function loadDemo() {
  patchAtom($bench, { phase: 'loading' })
  const env = await CB.api.demo()
  if (!env.ok) {
    patchAtom($bench, { phase: 'error', error: env })
    return
  }
  await loadBench({ projectId: env.result?.id || env.result?.project?.id || 'laser-trigger' })
}

// ─── navigation ────────────────────────────────────────────────────────

function goStation(station, project = null) {
  if (!isStation(station)) return
  const cur = $nav.get()
  $nav.set({ project: project || cur.project, station, n: cur.n + 1 })
  if (station !== cur.station) dropNotices(noticeFades) // a confirmation belongs to its station; errors stay
  store('lastStation', station)
  if (station === 'debug') {
    const pk = panicKey($project.get())
    if (pk) { patchAtom($ui, { panicSeen: pk }); store('panicSeen', pk) }
  }
  if (project && $project.get()?.id !== project && $bench.get().phase !== 'idle') loadBench({ projectId: project })
}

/** Open the Bench from palette, status bar or a card: atom first, then a workspace tile beside the chat
 *  when the host has openWorkspace, else the route. Never navigate while a Bench is already on screen. */
function openBench({ station = null, project = null, beside = true } = {}) {
  if (station) goStation(station, project)
  if (CB.mounts > 0) return
  const host = sdk.host
  if (beside && typeof host?.openWorkspace === 'function') {
    try {
      const close = host.openWorkspace('bench', { title: 'Circuit Bench', render: () => h(BenchPage, { surface: 'tile' }),
        dock: { pane: 'workspace', pos: 'right' }, minWidth: '34rem', onClose: () => { CB.tileClose = null } })
      CB.tileClose = typeof close === 'function' ? close : null
      return
    } catch (e) {
      console.warn('[circuit-bench] openWorkspace failed, falling back to the route', e)
    }
  }
  host?.navigate?.('/bench')
}

/** User shows/hides the page console. Showing also pins it open for the session (idle bar → open). */
function setConsole(state) {
  patchAtom($ui, { cons: state, consPinned: state === 'open' })
  store('console', state)
}

/** Switch the console tab (user click, job start, monitor open); the console then stays open for the session. */
function setConsoleTab(tab) {
  patchAtom($ui, { tab, consPinned: true })
  store('consoleTab', tab)
}

// --- 26-live.js
// Live bench: jobs (detect/build/flash) tracked over job.updated + GET /jobs/{id}, the serial monitor
// (POST /serial/open on a click → ctx.socket with the mandatory polling fallback, lib/serial.js), panic decode,
// and the workshop actions of stations 02–05. Nothing here runs on its own: detect, flash and the monitor start
// only from a click; after a reload no port is reopened.

const $detect = sdk.atom({ status: 'idle', port: null, env: null })
const $jobNote = sdk.atom({ detect: null, build: null, flash: null, example: null })
const $monitor = sdk.atom({ port: null, status: 'closed', mode: null, opening: false, error: null, epoch: null })
const $flow = sdk.atom({ port: null, focus: null, at: 0 })
const $calcs = sdk.atom({})
const $wire = sdk.atom({ status: 'idle', key: null, env: null, circuit: null })
const $solderPlan = sdk.atom({ status: 'idle', env: null })
// last GET /board/flash/check answer for the open project and the selected port (lib/flash.js flashGate)
const $flashCheck = sdk.atom({ project: null, port: null, env: null })
let FLASH_CHECK_SEQ = 0

const JOB_POLL_MS = 700
// a failed poll (network, backend busy) is retried; job_not_found ends the watch at once
const JOB_RETRY_MS = 2000
const JOB_RETRY_MAX = 30
const JOB_KINDS = ['detect', 'build', 'flash']
const JOB_WATCH = {}
const JOB_SETTLED = new Set()
let MONITOR = null

function timersOf(ctx) {
  return {
    setTimeout: (fn, ms) => (typeof ctx?.setTimeout === 'function' ? ctx.setTimeout(fn, ms) : setTimeout(fn, ms)),
    clearTimeout: t => { if (typeof t === 'function') t(); else clearTimeout(t) }
  }
}

function noteOf(env) {
  return env && !env.ok ? { code: env.error?.code || 'error', message: env.error?.message || env.summary || 'failed', hint: env.error?.hint || null, http: env.http ?? null, at: Date.now() } : null
}

// ─── jobs ──────────────────────────────────────────────────────────────

async function startJob(kind, call) {
  patchAtom($jobNote, { [kind]: null })
  if (kind === 'detect') $detect.set({ status: 'running', port: $flow.get().port, env: null })
  const env = await call()
  if (!env.ok || !env.result?.job_id) {
    patchAtom($jobNote, { [kind]: noteOf(env.ok ? { ok: false, error: { code: 'bad_response', message: 'no job id' } } : env) })
    if (kind === 'detect') patchAtom($detect, { status: 'error', env })
    return env
  }
  applyJob(env.result)
  if (kind !== 'detect') setConsoleTab(kind)
  watchJob(env.result.job_id, kind)
  return env
}

function watchJob(id, kind) {
  const stop = JOB_WATCH[kind]
  if (typeof stop === 'function') stop()
  let misses = 0
  const tick = async () => {
    JOB_WATCH[kind] = null
    const env = await CB.api.job(id)
    if (!env.ok) {
      if (env.error?.code === 'job_not_found') {
        patchAtom($jobNote, { [kind]: { code: 'job_not_found', message: 'The backend restarted; the job is gone.', hint: 'Reload and start it again.', at: Date.now() } })
        patchAtom($jobs, { [kind]: null })
        if (kind === 'detect') patchAtom($detect, { status: 'idle' })
        return
      }
      misses += 1
      if (misses > JOB_RETRY_MAX) {
        patchAtom($jobNote, { [kind]: { ...noteOf(env), message: 'Lost contact with the job. Reload the Bench.', hint: null } })
        return
      }
      JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, JOB_RETRY_MS)
      return
    }
    misses = 0
    applyJob(env.result)
    if (['queued', 'running'].includes(env.result?.state)) JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, JOB_POLL_MS)
  }
  JOB_WATCH[kind] = timersOf(CB.ctx).setTimeout(tick, 250)
}

function applyJob(job) {
  if (!job?.job_id || !JOB_KINDS.includes(job.kind)) return
  const cur = $jobs.get()[job.kind]
  if (cur && cur.job_id !== job.job_id && cur.started && job.started && job.started < cur.started) return // an older job
  patchAtom($jobs, { [job.kind]: job })
  if (job.state !== 'done' && job.state !== 'failed') return
  if (JOB_SETTLED.has(job.job_id)) return
  JOB_SETTLED.add(job.job_id)
  const res = job.result
  if (job.kind === 'detect') $detect.set({ status: res?.ok ? 'ready' : 'error', port: res?.result?.port || $detect.get().port, env: res })
  if (res && !res.ok) patchAtom($jobNote, { [job.kind]: noteOf(res) })
  // flashed while the monitor watches that port: the boot log is what matters now
  const mon = $monitor.get()
  if (job.kind === 'flash' && res?.ok && mon.port && monitorActive(mon.port) && (!res.result?.port || res.result.port === mon.port)) setConsoleTab('serial')
  // where the new firmware's output starts in the serial buffer (cleanRunAfter, fix loop)
  if (job.kind === 'flash' && res?.ok) {
    const b = $serial.get().buf
    patchAtom($flow, { flashMark: { elf: res.result?.elf_sha256 || null, port: res.result?.port || null, seq: b.lastSeq || 0, epoch: b.epoch ?? null } })
  }
  const p = $project.get()
  if (p) loadProject(p.id)
  loadPorts()
  if ($nav.get().station === 'flash') refreshFlashCheck()
}

/** Ask the backend whether a flash on the selected port (else the detected one) would be refused. Runs when FLASH
 *  opens, on every project revision, port or settings change (44-station-flash.js) and after each job. */
async function refreshFlashCheck() {
  const p = $project.get()
  if (!p) return null
  const port = $flow.get().port || p.board?.detected?.port || null
  const seq = ++FLASH_CHECK_SEQ
  const env = await CB.api.flashCheck(p.id, port)
  if (seq === FLASH_CHECK_SEQ && $project.get()?.id === p.id) $flashCheck.set({ project: p.id, port, env })
  return env
}

/** job.updated (event payload {job_id, kind, state, progress}) → read the job. */
async function onJobEvent(payload) {
  if (!payload?.job_id) return
  const env = await CB.api.job(payload.job_id)
  if (env.ok) applyJob(env.result)
}

function selectPort(port) {
  patchAtom($flow, { port })
}

function detectBoard(port) {
  const p = $project.get()
  if (!port) return null
  selectPort(port)
  return startJob('detect', () => CB.api.detect({ port, ...(p ? { project: p.id } : {}) }))
}

function buildFirmware() {
  const p = $project.get()
  if (!p) return null
  const det = p.board?.detected?.port
  return startJob('build', () => CB.api.build({ project: p.id, ...(isSimPort(det) ? { port: det } : {}) }))
}

function flashFirmware(confirm) {
  const p = $project.get()
  if (!p || !confirm) return null
  return startJob('flash', () => CB.api.flash({ project: p.id, confirm }))
}

async function useExampleFirmware({ overwrite = false } = {}) {
  const p = $project.get()
  if (!p) return null
  patchAtom($jobNote, { example: null })
  const env = await CB.api.firmwareExample(p.id, overwrite)
  if (env.ok && env.result?.project) {
    applyProject(env.result.project, { prev: p })
    setNotice('Example firmware copied into the project (firmware/).', 'ok')
  } else if (env.error?.code === 'project_conflict' && !overwrite) {
    patchAtom($ui, { modal: { type: 'example-overwrite' } })
  } else {
    patchAtom($jobNote, { example: noteOf(env) })
  }
  return env
}

function setFirmwareDir(dir, env) {
  return patchOps([{ op: 'set_firmware', dir, env }], { okText: 'Firmware folder saved.' })
}

function applyVariant(value) {
  const p = $project.get()
  // set_board knows bare ids only: drop the "?" of an unverified guess ("n16r8?" → "n16r8")
  const variant = bareVariant(value)
  if (!p || !variant) return null
  const b = boardOf(p)
  return patchOps([{ op: 'set_board', chip: b.chip, variant, devkit: b.devkit, wifi: b.wifi }], { okText: `Module variant ${String(variant).toUpperCase()} saved to the project.` })
}

// ─── serial monitor ────────────────────────────────────────────────────

/** Open the monitor; reset: pulse EN through RTS with IO0 released (the firmware restarts from flash; this also
 *  leaves the ROM download mode a board stays in after a flash or BOOT). Only on a click. */
async function openMonitor(port, { reset = false } = {}) {
  if (!port || $monitor.get().opening) return null
  patchAtom($monitor, { opening: true, error: null })
  const p = $project.get()
  const env = await CB.api.serialOpen({ port, ...(p ? { project: p.id } : {}), ...(reset ? { reset: true } : {}) })
  if (!env.ok) {
    patchAtom($monitor, { opening: false, error: noteOf(env) })
    return env
  }
  patchAtom($monitor, { port, status: env.result?.state || 'open', opening: false, error: null, epoch: env.result?.epoch ?? null })
  setConsoleTab('serial') // the live log is what the click asked for
  startStream(port)
  return env
}

const SERIAL_FLUSH_MS = 150 // at most ~7 store updates per second from the serial stream

function stopStream() {
  if (!MONITOR) return
  MONITOR.stop()
  MONITOR.coalesce?.cancel()
  MONITOR = null
}

function startStream(port) {
  stopStream()
  const cur = $serial.get()
  let lastEpoch = cur.port === port ? cur.buf.epoch : null
  const fixtures = CB.api.mode === 'fixtures'
  MONITOR = createSerialClient({
    port,
    socket: fixtures || typeof CB.ctx?.socket !== 'function' ? null : (path, fn) => CB.ctx.socket(path, fn),
    tail: (pt, after) => CB.api.serialTail(pt, after),
    timers: timersOf(CB.ctx),
    seq: { mergeLines, emptyBuffer },
    initial: cur.port === port ? cur.buf : null,
    onUpdate: u => { if (!MONITOR || MONITOR.port === port) coalesce.push(u) }
  })
  const coalesce = coalescer(timersOf(CB.ctx), SERIAL_FLUSH_MS, u => {
      if (!MONITOR || MONITOR.port !== port) return
      $serial.set({ port, buf: u.buf, status: u.state || (u.mode === 'stopped' ? 'closed' : 'open'), note: u.error, mode: u.mode, simulated: u.simulated })
      patchAtom($monitor, { mode: u.mode, status: u.mode === 'stopped' ? 'closed' : u.state || 'open' })
      if (u.buf.epoch && lastEpoch && u.buf.epoch !== lastEpoch) {
        // backend restarted: jobs and broker are new, reload project and ports
        const p = $project.get()
        if (p) loadProject(p.id)
        loadPorts()
      }
      lastEpoch = u.buf.epoch || lastEpoch
      watchSerialPanic(u.buf)
  })
  MONITOR.port = port
  MONITOR.coalesce = coalesce
  MONITOR.start()
}

async function closeMonitor() {
  const port = $monitor.get().port
  stopStream()
  patchAtom($monitor, { status: 'closed', mode: null, opening: false })
  patchAtom($serial, { status: 'closed', mode: null })
  if (port) await CB.api.serialClose(port)
}

function monitorActive(port) {
  return Boolean(MONITOR && MONITOR.port === port)
}

/** Decode the newest current panic once (a reboot loop announces one per boot; only the latest is decoded). */
function watchSerialPanic(buf) {
  const pn = buf?.panic
  if (!pn?.log_ref || !serialPanicLive(buf, $project.get())) return
  if (!panicNeedsDecode($panic.get(), pn, $project.get()?.firmware?.last_flash?.at ?? null)) return
  if ($panic.get().status === 'loading') {
    CB.pendingPanic = pn
    return
  }
  decodePanic(pn).then(() => {
    const next = CB.pendingPanic
    CB.pendingPanic = null
    if (next && next.log_ref !== $panic.get().key) watchSerialPanic({ ...$serial.get().buf, panic: next })
  })
}

// ─── workshop: calc, wire, solder, projects, doctor ────────────────────

async function runCalc(type, body) {
  patchAtom($calcs, { [type]: { status: 'loading', env: $calcs.get()[type]?.env || null, body } })
  const env = await CB.api.calc(type, body)
  patchAtom($calcs, { [type]: { status: env.ok ? 'ready' : 'error', env, body } })
  return env
}

function addCalcToProject(type) {
  const p = $project.get()
  const env = $calcs.get()[type]?.env
  if (!p || !env?.ok) return null
  const { id, ops, parts } = calcOps(type, env, p)
  return patchOps(ops, { okText: `${id} saved${parts.length ? ` with ${parts.map(x => `${x.ref} ${x.value}`).join(', ')}` : ''}.` })
}

async function renderSchematic(block, params, { circuit = null, gpio = null } = {}) {
  const p = $project.get()
  const key = JSON.stringify([block, params, gpio])
  $wire.set({ status: 'loading', key, env: $wire.get().env, circuit })
  const env = await CB.api.schematic({ block, params, ...(p ? { project: p.id } : {}), ...(Number.isInteger(gpio) ? { gpio } : {}) })
  if ($wire.get().key === key) $wire.set({ status: env.ok ? 'ready' : 'error', key, env, circuit })
  return env
}

function removePartsFromProject(refs) {
  return patchOps([{ op: 'remove_parts', refs }], { okText: `Removed ${refs.join(', ')} from the project.` })
}

function addCircuitToProject(id, block, params) {
  return patchOps([{ op: 'add_circuit', circuit: { id, block, params } }], { okText: `Circuit ${id} saved to the project.` })
}

async function planSolder(bomText = null) {
  const p = $project.get()
  if (!p) return null
  $solderPlan.set({ status: 'loading', env: null })
  const env = await CB.api.solderPlan({ project: p.id, ...(bomText ? { bom: bomText } : {}) })
  $solderPlan.set({ status: env.ok ? 'ready' : 'error', env })
  if (env.ok) await loadProject(p.id)
  else setNotice(env.error?.message || env.summary || 'The solder plan failed.', 'bad')
  return env
}

async function toggleSolderStep(stepId, done) {
  const p = $project.get()
  if (!p) return null
  const env = await CB.api.solderStep(p.id, stepId, done)
  if (env.ok && env.result?.project) applyProject(env.result.project, { prev: p })
  else setNotice(env.error?.message || 'The check mark was not saved.', 'bad')
  return env
}

async function createProject(form) {
  const env = await CB.api.createProject(form)
  if (env.ok) {
    await loadBench({ projectId: form.id })
    goStation('plan', form.id)
  }
  return env
}

/** Project manager (HUD project pill, palette): refresh the list, open another project, move one to the trash. */
async function refreshProjects() {
  const env = await CB.api.projects()
  if (env.ok) patchAtom($bench, { projects: env.result?.projects || [] })
  return env
}

async function openProject(id) {
  if (!id || $project.get()?.id === id) return null
  await loadBench({ projectId: id })
  return $project.get()
}

async function removeProject(id) {
  const env = await CB.api.deleteProject(id)
  if (!env.ok) return env
  forgetProject(id)
  return env
}

/** A project is gone (deleted here or elsewhere): drop it from the list; if it was open, open the next one. */
function forgetProject(id) {
  if (stored('lastProject', null) === id) store('lastProject', null)
  patchAtom($bench, { projects: ($bench.get().projects || []).filter(p => p.id !== id) })
  if ($project.get()?.id === id) {
    resetProjectScoped()
    $project.set(null)
    patchAtom($nav, { project: null })
    loadBench()
  }
}

/** Per-project results of the stations (calculator answers, drawn schematic, solder plan preview, pin info) and
 *  of the finished jobs (their log, detect result, notes). Running jobs stay; the last panic belongs to the board. */
function resetProjectScoped() {
  $calcs.set({})
  $wire.set({ status: 'idle', key: null, env: null, circuit: null })
  $solderPlan.set({ status: 'idle', env: null })
  $suggest.set({ status: 'idle', env: null, role: null })
  $info.set({ status: 'idle', gpio: null, env: null })
  $flashCheck.set({ project: null, port: null, env: null })
  $notices.set([])
  const jobs = $jobs.get()
  const live = j => Boolean(j) && j.state !== 'done' && j.state !== 'failed'
  $jobs.set(Object.fromEntries(Object.entries(jobs).map(([k, j]) => [k, live(j) ? j : null])))
  if (!live(jobs.detect) && $detect.get().status !== 'running') $detect.set({ status: 'idle', port: null, env: null })
  $jobNote.set({ detect: null, build: null, flash: null, example: null })
}

async function runDoctor() {
  patchAtom($ui, { modal: { type: 'doctor', env: null } })
  const env = await CB.api.doctor()
  if ($ui.get().modal?.type === 'doctor') patchAtom($ui, { modal: { type: 'doctor', env } })
  return env
}

/** Open the Agent settings (config_schema form) of the plugin. */
function openAgentSettings() {
  sdk.host?.navigate?.('/settings?tab=plugins&agent=circuit-bench')
}

// --- 27-modules.js
// Module store: $modCatalog {status, key, env, cats}, $modInfo {[id|variant]: {status, env}}, $calcMeta;
// loaders, hooks, actions

const $modCatalog = sdk.atom({ status: 'idle', key: null, env: null, cats: [] })
const $modInfo = sdk.atom({})
const $calcMeta = sdk.atom({ status: 'idle', env: null, list: [] })
let MOD_CATALOG_SEQ = 0

const modFilterKey = (f = {}) => JSON.stringify([f.q || '', f.category || '', f.interface || ''])

async function loadModuleCatalog(filter = {}, { force = false, more = false } = {}) {
  const key = modFilterKey(filter)
  const cur = $modCatalog.get()
  if (!force && !more && cur.key === key && (cur.status === 'ready' || cur.status === 'loading')) return cur.env
  const seq = ++MOD_CATALOG_SEQ
  const have = more && cur.key === key && cur.env?.ok ? cur.env.result?.items || [] : null // load more: append
  $modCatalog.set({ ...cur, status: 'loading', key })
  const env = await CB.api.modules(filter.q || null, filter.category || null, filter.interface || null, { limit: 200, offset: have?.length || undefined })
  const out = have && env.ok ? { ...env, result: { ...env.result, items: [...have, ...(env.result?.items || [])] } } : have ? cur.env : env
  if (seq === MOD_CATALOG_SEQ) $modCatalog.set({ status: out.ok ? 'ready' : 'error', key, env: out, cats: out.ok ? modCategories(out.result, ...(cur.cats || [])) : cur.cats })
  return env
}

async function loadModuleInfo(id, variant = null) {
  if (!id) return null
  const k = variant ? `${id}|${variant}` : id
  const have = $modInfo.get()[k]
  if (have && have.status !== 'error') return have.env
  $modInfo.set({ ...$modInfo.get(), [k]: { status: 'loading', env: null } })
  const env = await CB.api.module(id, variant)
  $modInfo.set({ ...$modInfo.get(), [k]: { status: env.ok ? 'ready' : 'error', env } })
  return env
}

async function loadCalcMeta() {
  const cur = $calcMeta.get()
  if (cur.status === 'ready' || cur.status === 'loading') return cur.env
  $calcMeta.set({ status: 'loading', env: null, list: [] })
  const env = await CB.api.calcMeta()
  $calcMeta.set({ status: env.ok ? 'ready' : 'error', env, list: calcMetaOf(env) })
  return env
}

function useModuleCatalog(filter = {}) {
  const key = modFilterKey(filter)
  useEffect(() => { loadModuleCatalog(filter) }, [key])
  return sdk.useValue($modCatalog)
}

function useModuleInfo(id, variant = null) {
  useEffect(() => { loadModuleInfo(id, variant) }, [id, variant])
  const all = sdk.useValue($modInfo)
  return all[variant ? `${id}|${variant}` : id] || { status: id ? 'loading' : 'idle', env: null }
}

function useCalcMeta() {
  useEffect(() => { loadCalcMeta() }, [])
  return sdk.useValue($calcMeta)
}

function useProjectModules(project) {
  return useMemo(() => moduleInstances(project), [project])
}

function useModuleCheck() {
  const check = sdk.useValue($check)
  return useMemo(() => ({ modules: modulesResult(check.env), rails: modRails(check.env),
    findings: { ...modFindings(check.env), sources: check.env?.ok ? check.env.sources || [] : [] } }), [check.env])
}

function useModuleInfos(ids) {
  const key = [...new Set(ids)].sort().join(',')
  useEffect(() => { for (const id of key.split(',')) if (id) loadModuleInfo(id) }, [key])
  const all = sdk.useValue($modInfo)
  return useMemo(() => Object.fromEntries(key.split(',').filter(Boolean).map(id => {
    const e = all[id]?.env
    return [id, e?.ok ? e.result?.module ?? e.result : null]
  })), [all, key])
}

// CALC with card calc-<kind> (in the root of `from`) in view
function openCalc(kind, from = null) {
  const root = from ? ownRoot(from) : null
  goStation('calc')
  if (!root || typeof requestAnimationFrame !== 'function') return
  let n = 0
  const look = () => {
    const card = root.querySelector(`[data-cb="calc-${kind}"]`)
    if (card) { card.scrollIntoView?.({ block: 'nearest' }); card.querySelector('input')?.focus?.({ preventScroll: true }) } else if (++n < 20) requestAnimationFrame(look)
  }
  requestAnimationFrame(look)
}

function addModule(payload) {
  const op = addModuleOp(payload)
  return patchOps([op], { okText: `${op.ref || 'Module'} ${op.module} added.` })
}

function connectModule(ref, conn) {
  return patchOps([connectOp(ref, conn)], { okText: `${String(ref).toUpperCase()} connections saved.` })
}

function openModules(init = null) {
  patchAtom($ui, { modal: { type: 'modules', init } })
}

// --- 30-ui-actions.js
// Bench → agent: put a structured prompt into the composer. Never sends; the user presses Enter.

async function composeDraft(text) {
  const host = sdk.host
  const setDraft = host?.composer?.setDraft
  const sleepMs = ms => new Promise(resolve => setTimeout(resolve, ms))
  if (typeof setDraft === 'function') {
    try {
      if (await setDraft(null, text)) return 'draft'
      if (typeof host.newChat === 'function') {
        host.newChat()
        for (let i = 0; i < 20; i++) {
          await sleepMs(150)
          if (await setDraft('new', text)) {
            // the Bench stays visible beside the new chat (only as a tile; the route fallback would hide the chat)
            if (typeof host.openWorkspace === 'function') { await sleepMs(60); if (CB.mounts === 0) openBench({ beside: true }) }
            return 'draft'
          }
        }
      }
    } catch (e) {
      console.warn('[circuit-bench] setDraft failed', e)
    }
  }
  const copied = await CB.ctx?.os?.writeClipboard?.(text).catch?.(() => false)
  host?.notify?.({ kind: copied ? 'info' : 'warning', title: copied ? 'Prompt copied' : 'Could not reach the composer',
    message: copied ? 'Paste it into the chat to ask Hermes.' : 'Open a chat and try again.' })
  return copied ? 'clipboard' : 'failed'
}

function askHermesText(project, station, rows) {
  const s = stationInfo(station)
  const lines = [`Bench question: ${s.title.toLowerCase()} in "${project?.id ?? '?'}"`,  // short first line = session title
    `Circuit Bench — project "${project?.id ?? '?'}", station ${s.n} ${s.title.toUpperCase()}.`]
  if (project) {
    const b = project.board || {}
    lines.push(`Board: ${chipInfo(b.chip)?.label || b.chip || '?'}${b.variant ? ` ${String(b.variant).toUpperCase()}` : ''}${b.devkit ? ` on ${b.devkit}` : ''}, Wi-Fi ${project.options?.wifi === false ? 'off' : 'on'}.`)
  }
  const bad = (rows || []).filter(r => r.verdict === 'blocked' || r.verdict === 'caution')
  if (bad.length) {
    lines.push(`Findings: ${bad.map(findingText).join('; ')}.`)
  }
  lines.push('Use the bench tools (bench_project, bench_pins) to read the project, then help me with the next step. Ask before changing anything.')
  return lines.join('\n')
}

function fixWithHermesText(project, decode) {
  return fixDraftText(project, decode) // lib/crash.js (pure, tested)
}

// --- 30-ui-assign.js
// AssignmentTable and the assign dialog (op assign)

function AssignmentTable({ rows, checkState, onAssign }) {
  const view = sdk.useValue($view)
  const pulse = sdk.useValue($pulse)
  const pulseRoles = new Set(pulse.roles)
  const env = checkState.env
  const [at, setAt] = useState(null)
  useEffect(() => { if (checkState.status === 'ready') setAt(new Date().toISOString()) }, [checkState.key, checkState.status])
  // mod_* findings only in the card // buses
  const warnings = env?.ok ? (env.warnings || []).filter(w => !String(w.code || '').startsWith('mod_')) : []
  const project = sdk.useValue($project)
  const insts = useProjectModules(project)
  const stale = rows.some(r => !r.checked) && checkState.status === 'ready'
  return h('div', { className: 'cb-card', 'data-cb': 'assignments' },
    h('div', { className: 'cb-card-head' }, h(Label, null, '// assignments'),
      h(Label, { 'data-cb': 'checked-at', className: 'cb-push' }, checkState.status === 'loading' ? 'checking…' : checkState.status === 'error' ? 'check failed'
        : at ? `checked ${formatClock(at)}` : ''),
      h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'assign-new', title: 'Assign a role to a pin',
        onClick: () => onAssign({ role: '', mode: 'out', pin: view.selected ?? null, net: '' }) }, '+ assign')),
    // fixed columns (no h-scroll, WT32): role ellipsis + title; verdict symbol + word
    rows.length || insts.length ? h('table', { className: 'cb-table cb-table--assign' },
      h('colgroup', null, h('col', null), h('col', { className: 'cb-col-pin' }), h('col', { className: 'cb-col-mode' }),
        h('col', { className: 'cb-col-verdict' }), h('col', { className: 'cb-col-x' })),
      h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, 'role'), h('th', { className: 'cb-label' }, 'pin'),
        h('th', { className: 'cb-label' }, 'mode'), h('th', { className: 'cb-label' }, h('span', { className: 'cb-vw' }, 'verdict')), h('th', { className: 'cb-label cb-r' }, h('span', { className: 'cb-sr' }, 'remove')))),
      h('tbody', null, rows.map(r => {
        const v = verdictMeta(r.verdict)
        return h('tr', { key: r.role, 'data-cb-row': r.role, 'data-cb': `row-${r.role}`, 'aria-selected': view.selected === r.pin ? 'true' : 'false',
          'data-cb-pulse': pulseRoles.has(r.role) ? 'true' : undefined, onClick: () => selectPin(r.pin),
          title: r.updated_by ? `last change by ${r.updated_by}${r.checked ? '' : ' · stored verdict (not re-checked)'}` : undefined },
        h('td', { className: 'cb-fg cb-cell-ellip', title: r.role, 'data-cb-truncate-ok': 'true' }, r.role),
        h('td', { className: r.verdict === 'blocked' ? 'cb-bad' : 'cb-active' }, `IO${r.pin}`),
        // one mode word; full mode as title (+ label when shortened)
        h('td', { className: 'cb-dim cb-cell-ellip', title: modeLabel(r.mode), 'data-cb-mode': r.mode,
          'aria-label': modeShort(r.mode) !== modeLabel(r.mode) ? modeLabel(r.mode) : undefined }, modeShort(r.mode)),
        h('td', { className: `cb-verdict-cell cb-cell-ellip cb-${v.tone === 'none' ? 'dim' : v.tone}`, 'data-cb-verdict': r.verdict || 'unchecked',
          title: v.text, 'data-cb-truncate-ok': 'true' },
          h('span', { 'aria-hidden': 'true' }, v.symbol), h('span', { className: 'cb-vw' }, ' ', r.verdict ? v.text : 'unchecked')),
        h('td', { className: 'cb-r' }, h('button', { type: 'button', className: 'cb-x', title: `Remove ${r.role}`, 'aria-label': `Remove ${r.role}`,
          onClick: e => { e.stopPropagation(); unassignRole(r.role) } }, '×')))
      }), insts.length ? h(ModuleRows, { key: 'mods', insts, project, env, onAssign }) : null)) : h('p', { className: 'cb-why cb-dim' }, 'No pins assigned yet. Click a free pin on the board, then “Assign role…”.'),
    warnings.map(w => h('div', { key: w.code, className: w.severity === 'danger' ? 'cb-hint cb-bad' : 'cb-hint' }, `⚠ ${w.message}`)),
    stale ? h('div', { className: 'cb-hint cb-dim' }, 'Some verdicts are stored values; the latest check did not cover them.') : null)
}

// module groups: row (button → instance view), open pins (— connect <net> | — assign)
function ModuleRows({ insts, project, env, onAssign }) {
  const infos = useModuleInfos(insts.map(i => i.module))
  const byRef = modRefFindings(modFindings(env).warnings)
  const assigns = project?.assignments || []
  // address from the check if the part has none
  const addr = Object.fromEntries((modulesResult(env)?.buses || []).flatMap(b => (b.segments || []).flatMap(s => s.devices || [])).map(d => [d.ref, d.address]))
  return insts.flatMap(i0 => {
    const inst = i0.address || !addr[i0.ref] ? i0 : { ...i0, address: addr[i0.ref] }
    const info = infos[inst.module]
    const links = modPinLinks(inst, info, assigns)
    const w = byRef[inst.ref]
    const label = modInstanceLabel(inst, info)
    const linked = links.filter(l => l.assignment).map(l => `${l.pin} IO${l.assignment.pin}`).join(' · ')
    const go = e => { e.stopPropagation(); openModules({ ref: inst.ref, address: inst.address }) }
    return [h('tr', { key: inst.ref, className: 'cb-mod-grp', 'data-cb': 'mod-group', 'data-cb-ref': inst.ref, title: `${label}: module details`, onClick: go },
    h('td', { colSpan: 5 }, h('div', { className: 'cb-mod-grphead' },
      h('button', { type: 'button', className: 'cb-mod-grpbtn cb-mod-ellip', 'data-cb': 'mod-group-open', 'data-cb-truncate-ok': 'true', onClick: go }, label),
      w ? h('span', { className: `cb-mod-t-${w.tone}`, title: w.message, 'data-cb': 'mod-group-finding' }, `${w.symbol} ${w.word}`) : null),
    linked ? h('div', { className: 'cb-mod-dim cb-mod-ellip', 'data-cb-truncate-ok': 'true', title: linked }, linked) : null)),
    ...links.filter(l => !l.assignment).map(l => h('tr', { key: `${inst.ref}-${l.pin}`, className: 'cb-mod-open', 'data-cb': 'mod-open', 'data-cb-ref': inst.ref, 'data-cb-pin': l.pin },
      h('td', { className: 'cb-cell-ellip', title: `${inst.ref} ${l.pin} (${l.signal.replace(/_/g, ' ')})`, 'data-cb-truncate-ok': 'true' }, `↳ ${l.pin}`),
      h('td', { colSpan: 4 }, l.bus
        ? h('button', { type: 'button', className: 'cb-mod-link', 'data-cb-act': 'connect', title: `${l.bus.role} · IO${l.bus.pin}`,
          onClick: () => connectModule(inst.ref, { [l.pin]: modAssignNet(l.bus) }) }, `— connect ${modAssignNet(l.bus)}`)
        : h('button', { type: 'button', className: 'cb-mod-link', 'data-cb-act': 'assign',
          onClick: () => onAssign(modAssignInit(inst, l, assigns)) }, `— assign${l.must ? ' · required' : l.optional ? ' · optional' : ''}`))))]
  })
}

function AssignDialog({ init, mapState, onClose }) {
  const [role, setRole] = useState(init.role || '')
  const [mode, setMode] = useState(init.mode || 'out')
  const [pin, setPin] = useState(init.pin === null || init.pin === undefined ? '' : String(init.pin))
  const [net, setNet] = useState(init.net || '')
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState([])
  const [fail, setFail] = useState(null)
  const saved = useRef(null) // assigned pin: focus returns to it
  const pinNum = /^\d{1,2}$/.test(pin) ? Number(pin) : null
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null).get(pinNum)
  const err = f => errors.find(e => e.field === f)?.message
  const submit = async e => {
    e?.preventDefault?.()
    const form = { role: role.trim().toUpperCase(), mode, pin: pinNum, net: net.trim() || null }
    const errs = validateAssign(form)
    setErrors(errs)
    if (errs.length) return
    setBusy(true)
    setFail(null)
    const link = init.link // module pin: assign + connect in one PATCH
    const env = link ? await patchOps([{ op: 'assign', ...form, net: form.net || undefined }, connectOp(link.ref, { [link.pin]: form.net || `GPIO${form.pin}` })],
      { okText: `${form.role} → GPIO${form.pin}, ${link.ref} ${link.pin} connected.` }) : await assignPin(form)
    setBusy(false)
    if (env?.ok) { saved.current = form.pin; selectPin(form.pin); onClose() } else setFail(env?.error?.message || 'Not saved.')
  }
  const field = (id, label, control, error) => [
    h('label', { key: `${id}-l`, htmlFor: `cb-f-${id}` }, label), control,
    error ? h('div', { key: `${id}-e`, className: 'cb-err' }, error) : null
  ]
  const returnFocus = root => (saved.current !== null && root ? root.querySelector(`[data-cb="pin-${saved.current}"]`) : null)
  return h(Modal, { title: init.link ? `Assign ${init.link.ref} ${init.link.pin}` : init.role ? `Edit ${init.role}` : 'Assign role', onClose, dataCb: 'assign-dialog', returnFocus,
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 's', onClick: submit, disabled: busy, 'data-cb': 'assign-submit', kind: base && base.verdict !== 'ok' ? 'warn' : 'primary',
        title: base && base.verdict === 'blocked' ? 'The pin is blocked; it is saved as a request so the bench can suggest a free pin' : undefined },
      busy ? 'Saving…' : base && base.verdict === 'blocked' ? 'Assign anyway ›' : 'Assign ›')] },
  h('form', { className: 'cb-form', onSubmit: submit },
    field('role', 'Role', h('input', { key: 'role', id: 'cb-f-role', value: role, placeholder: 'BUTTON', maxLength: 24, autoComplete: 'off', spellCheck: false,
      'data-cb': 'assign-role', onChange: e => setRole(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '')) }), err('role')),
    field('mode', 'Mode', h('select', { key: 'mode', id: 'cb-f-mode', value: mode, 'data-cb': 'assign-mode', onChange: e => setMode(e.target.value) },
      MODES.map(([m, l]) => h('option', { key: m, value: m }, l))), err('mode')),
    field('pin', 'GPIO', h('input', { key: 'pin', id: 'cb-f-pin', value: pin, inputMode: 'numeric', maxLength: 2, 'data-cb': 'assign-pin',
      onChange: e => setPin(e.target.value.replace(/\D/g, '')) }), err('pin')),
    field('net', 'Net', h('input', { key: 'net', id: 'cb-f-net', value: net, placeholder: 'optional, e.g. BTN', maxLength: 32, autoComplete: 'off',
      spellCheck: false, onChange: e => setNet(e.target.value) }), err('net')),
    h('button', { type: 'submit', className: 'cb-sr', tabIndex: -1 }, 'submit')),
  init.link ? h('p', { className: 'cb-mod-dim cb-mod-note', 'data-cb': 'assign-link' }, `Connects module pin ${init.link.ref} ${init.link.pin} to this net.`) : null,
  pinNum !== null && base ? h('div', { className: 'cb-preview', 'data-cb': 'assign-preview' },
    h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '4px' } },
      h(Stamp, { tone: base.verdict === 'blocked' ? 'bad' : base.verdict === 'caution' ? 'warn' : 'ok' }, `${verdictMeta(base.verdict).stamp} ${verdictMeta(base.verdict).symbol}`),
      h('b', { className: 'cb-fg' }, `GPIO${pinNum}`)),
    mainReason(base) ? mainReason(base).message : 'No findings for this board as a plain input.',
    h('div', { className: 'cb-dim', style: { marginTop: '6px' } }, 'Preview for a plain input. The backend re-checks the pin for the chosen mode when you assign.')) : null,
  fail ? h('div', { className: 'cb-note cb-note--bad', style: { marginTop: '12px', marginBottom: 0 } }, fail) : null)
}

// --- 30-ui-bench.js
// Bench page (route /bench, or a workspace tile beside the chat): HUD, rail, station, inspector, console.

let BENCH_MOUNTS = 0

function BenchPage({ surface = 'route' }) {
  const bench = sdk.useValue($bench)
  const project = sdk.useValue($project)
  const nav = sdk.useValue($nav)
  const ui = sdk.useValue($ui)
  const check = sdk.useValue($check)
  const map = sdk.useValue($map)
  const notices = sdk.useValue($notices)
  useEffect(() => {
    BENCH_MOUNTS++
    CB.mounts = BENCH_MOUNTS
    BENCH_SURFACES.set(surface, (BENCH_SURFACES.get(surface) || 0) + 1)
    // one Bench at a time: the full page replaces the tile docked beside the chat
    if (surface === 'route' && typeof CB.tileClose === 'function') {
      const close = CB.tileClose
      CB.tileClose = null
      try { close() } catch (e) { console.warn('[circuit-bench] closing the docked Bench failed', e) }
    }
    ensureBench()
    return () => {
      BENCH_MOUNTS--; CB.mounts = BENCH_MOUNTS
      BENCH_SURFACES.set(surface, Math.max(0, (BENCH_SURFACES.get(surface) || 1) - 1))
    }
  }, [])
  const rows = useMemo(() => mergeAssignments(project?.assignments, check.env?.ok ? check.env.result?.pins : null), [project, check.env])
  const view = STATION_VIEWS[nav.station]
  const hasInsp = Boolean(view?.inspector) && bench.phase === 'ready'
  let body
  if (bench.phase === 'idle' || (bench.phase === 'loading' && !project)) {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-loading' }, h('div', { className: 'cb-loading' }, 'connecting bench'))
  } else if (bench.phase === 'error') {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-error' }, h(BenchError, { env: bench.error }))
  } else if (bench.phase === 'empty') {
    body = h('main', { className: 'cb-main', 'data-cb': 'bench-empty' }, h(BenchEmpty, null))
  } else if (view) {
    body = h(view.component, { project, rows, key: `${project?.id || ''}:${nav.station}` }) // another project: fresh station state
  } else {
    body = h(StationSoon, { station: nav.station, project, key: `${project?.id || ''}:${nav.station}` })
  }
  const health = bench.health
  const consMode = useConsoleMode(project)
  const claim = () => { BENCH_ACTIVE.surface = surface }
  return h('div', { className: 'cb-root cb-page', 'data-cb': 'bench-root', 'data-cb-audit-root': 'bench', 'data-cb-look': ui.look, 'data-cb-surface': surface,
    'data-cb-sim': project ? (project.simulated ? 'true' : 'false') : undefined,
    'data-cb-phase': bench.phase, 'data-cb-station': nav.station, onPointerDownCapture: claim, onKeyDownCapture: claim },
  h(Styles, null),
  h('div', { className: 'cb-shell', 'data-cb': 'shell', 'data-cb-insp': hasInsp ? 'yes' : 'none',
    'data-cb-cons': consMode, 'data-cb-notes': notices.length ? 'yes' : undefined },
  h(Hud, { project, rows, health }),
  h(NoticeZone, { list: notices }),
  h(StageRail, { project, rows, health, checkEnv: check.env?.ok ? check.env : map.env }),
  h('div', { className: 'cb-work', 'data-cb': 'work' }, body),
  h(ConsoleRow, { project, mode: consMode }),
  h(BenchModal, { modal: ui.modal, map, surface })))
}

// one notice zone for the whole Bench (a row under the HUD, so it never covers the station): symbol + word +
// text, tone by severity (alarm colour only for errors), no motion. ok/info fade after 3 s (paused while the pointer or
// the focus is in the zone, WCAG 2.2.1), warn/bad stay until ✕; status for ok/info, alert for warn/bad.
const NOTICE_LOOK = { ok: ['✓', 'ok'], info: ['i', 'info'], warn: ['!', 'warning'], bad: ['✕', 'error'] }
const NOTICE_FADE_MS = 3000

function NoticeZone({ list }) {
  const [hold, setHold] = useState(false)
  const fading = list.filter(noticeFades)
  useEffect(() => {
    if (hold || !fading.length) return undefined
    const due = Math.min(...fading.map(n => n.at)) + NOTICE_FADE_MS - Date.now()
    const t = timersOf(CB.ctx).setTimeout(() => dropNotices(n => noticeFades(n) && n.at + NOTICE_FADE_MS <= Date.now() + 50), Math.max(0, due))
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [hold, fading.map(n => `${n.id}:${n.at}`).join(',')])
  // leaving the zone gives the fading notices their 3 s again
  const release = () => { setHold(false); $notices.set($notices.get().map(n => (noticeFades(n) ? { ...n, at: Date.now() } : n))) }
  return h('div', { className: 'cb-notes', 'data-cb': 'notices', 'aria-label': 'Notices', 'aria-live': 'polite',
    onMouseEnter: () => setHold(true), onMouseLeave: release, onFocus: () => setHold(true), onBlur: release },
  list.map(n => {
    const [sym, word] = NOTICE_LOOK[n.tone] || NOTICE_LOOK.info
    return h('div', { key: n.id, className: `cb-notice cb-notice--${NOTICE_LOOK[n.tone] ? n.tone : 'info'}`, role: noticeFades(n) ? 'status' : 'alert',
      'data-cb': `notice-${n.tone}`, 'data-cb-notice': n.id },
    h('span', { className: 'cb-notice-sym', 'aria-hidden': 'true' }, sym),
    h('span', { className: 'cb-notice-w' }, word),
    h('span', { className: 'cb-notice-t' }, n.text),
    h('button', { type: 'button', className: 'cb-notice-x', title: 'Dismiss', 'aria-label': `Dismiss: ${n.text}`, 'data-cb': 'notice-dismiss',
      onClick: () => dropNotices(x => x.id === n.id) }, '×'))
  }))
}

// Route and tile can be mounted at once (Bench beside the chat): a dialog belongs to the surface the user last
// touched, otherwise to the route, otherwise to the tile — never to both.
const BENCH_SURFACES = new Map()
const BENCH_ACTIVE = { surface: null }

const MODAL_OWNER = new WeakMap()

function modalSurface(modal) {
  const live = k => (BENCH_SURFACES.get(k) || 0) > 0
  const pinned = MODAL_OWNER.get(modal)
  if (pinned && live(pinned)) return pinned
  const owner = BENCH_ACTIVE.surface && live(BENCH_ACTIVE.surface) ? BENCH_ACTIVE.surface : live('route') ? 'route' : 'tile'
  MODAL_OWNER.set(modal, owner)
  return owner
}

function BenchModal({ modal, map, surface }) {
  const close = () => patchAtom($ui, { modal: null })
  const t = modal?.type
  if (!t || modalSurface(modal) !== surface) return null
  if (t === 'assign') return h(AssignDialog, { init: modal.init, mapState: map, onClose: close })
  if (t === 'flash') return h(FlashDialog, { confirm: modal.confirm, onClose: close })
  if (t === 'variant') return h(VariantDialog, { variant: modal.variant, onClose: close })
  if (t === 'example-overwrite') return h(ExampleOverwriteDialog, { onClose: close })
  if (t === 'new-project') return h(NewProjectDialog, { onClose: close })
  if (t === 'projects') return h(ProjectsDialog, { onClose: close })
  if (t === 'doctor') return h(DoctorDialog, { env: modal.env, onClose: close })
  if (t === 'modules') return h(ModulesDialog, { init: modal.init ?? null, onClose: close }) // 47-dialog-modules.js
  return null
}

function BenchError({ env }) {
  const code = env?.error?.code
  const offline = code === 'backend_unavailable' || code === 'network_error'
  return h(EmptyBox, { tone: offline ? 'warn' : 'bad', kicker: `// bench · ${code || 'error'}`, dataCb: offline ? 'bench-offline' : 'bench-failed',
    title: offline ? 'Bench backend not available' : 'The bench could not load',
    actions: [h(Btn, { key: 'r', kind: 'ghost', onClick: () => loadBench(), 'data-cb': 'retry' }, 'Retry')] },
  h('p', null, env?.error?.message || env?.summary || 'Unknown error.'),
  env?.error?.hint ? h('p', null, env.error.hint) : null,
  offline ? h('p', null, 'The page retries on its own every 30 s while it is open.') : null)
}

function BenchEmpty() {
  const [busy, setBusy] = useState(false)
  return h(EmptyBox, { kicker: '// bench · no project', title: 'No bench project yet', dataCb: 'no-project',
    actions: [h(Btn, { key: 'd', onClick: async () => { setBusy(true); await loadDemo(); setBusy(false) }, disabled: busy, 'data-cb': 'load-demo' },
      busy ? 'Loading…' : 'Load demo project'),
    h(Btn, { key: 'n', kind: 'ghost', onClick: () => patchAtom($ui, { modal: { type: 'new-project' } }), 'data-cb': 'new-project' }, 'New project'),
    h(Btn, { key: 'a', kind: 'agent', onClick: () => composeDraft('Start a Circuit Bench project for an ESP32-S3-DevKitC-1 (N16R8). Use bench_project to create it.'),
      'data-cb': 'ask-create' }, 'Ask Hermes to create one')] },
  h('p', null, 'A bench project holds the board, pin assignments, calculations, wiring, solder steps and firmware.'),
  h('p', null, 'Try the demo project ', h('code', null, 'laser-trigger'), ' (simulated board, no hardware needed) or let Hermes create one from the chat.'))
}

// --- 30-ui-board.js
// BoardView: the board model. An SVG layer (lib/art-board.js, aria-hidden)
// draws the pcb, module, header strips with pads and state rings, reservation brackets, ports, buttons and on-board
// parts; the DOM above it carries the meaning: one button.cb-pin per GPIO (data-cb="pin-<gpio>", data-cb-state,
// aria-pressed, aria-label with the state word), labels and tags in fixed columns outside the pcb, and transparent
// anchors over ports, buttons, antenna and brackets (title + screen-reader text). Both layers take their numbers from
// boardGeom() (lib/board-geom.js), the DOM through the CSS variables on [data-cb=board].
// Any layout from data/boards, with or without `drawing` (without: generic placement, data-cb-schematic="true").

let BOARD_VIEW_SEQ = 0

/** State symbol for the board labels and legend: the kit Glyph's shapes (lib/art.js), without data-cb-state, so the
 *  E2E and tests that count [data-cb-state=…] see one element per pin row (the row itself). Always decorative. */
function BoardGlyph({ state, className }) {
  if (!ART_STATE_WORDS[state]) return null
  return h('svg', { className: cx('cb-glyph', `cb-glyph--${state}`, className), width: 12, height: 12, viewBox: '0 0 12 12', focusable: 'false', 'aria-hidden': 'true',
    'data-cb-glyph': state },
  artGlyphShapes(state, 6, 6, 'currentColor', state === 'assigned_blocked' ? 'var(--cb-bad-fill)' : 'var(--cb-ink)').map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}

/** Nearest scrolling ancestor inside the own root (the PLAN main column, or the work area when stacked). */
function boardScroller(el) {
  for (let p = el?.parentElement; p; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY
    if (oy === 'auto' || oy === 'scroll') return p
    if (p.classList?.contains('cb-root')) return null
  }
  return null
}

/** Room for the board: width of the wrap, height from the board top to the visible end of the scroll area. */
function useBoardBox(ref) {
  const [box, setBox] = useState(null)
  const [, setTick] = useState(0)
  // loop breaker: a size change that moves a scrollbar or wraps the toolbar can feed back; at most 4 updates / 0.5 s
  const burst = useRef({ n: 0, t: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const sc = boardScroller(el)
    const r = el.getBoundingClientRect()
    let hh = null
    if (sc) {
      const sr = sc.getBoundingClientRect()
      const pad = parseFloat(getComputedStyle(sc).paddingBottom) || 0
      hh = Math.floor(sc.clientHeight - (r.top - sr.top + sc.scrollTop) - Math.min(pad, 10))
      // room for the legend caption
      const cap = el.nextElementSibling
      if (cap && cap.classList.contains('cb-legend--cap')) hh -= Math.ceil(cap.getBoundingClientRect().height + (parseFloat(getComputedStyle(cap).marginTop) || 0))
    }
    const w = Math.floor(el.clientWidth)
    if (box && box.w === w && box.h === hh) return
    const now = Date.now()
    if (now - burst.current.t > 500) burst.current = { n: 0, t: now }
    if (++burst.current.n > 4) return
    setBox({ w, h: hh })
  })
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(() => setTick(t => t + 1))
    ro.observe(el)
    const sc = boardScroller(el)
    if (sc) ro.observe(sc)
    return () => ro.disconnect()
  }, [])
  return box
}

function BoardPin({ slot, side, selected, suggested, pulse, requested, onSelect }) {
  const { hp, view, art } = slot
  const interactive = view.gpio !== null
  const word = pinStateWord(view.state)
  const cut = Boolean(view.tag) && !slot.tagFits
  const tag = h('span', { className: 'cb-ptag', title: cut ? view.tag : undefined, 'data-cb-truncate-ok': cut ? 'true' : undefined }, view.tag)
  const name = h('span', { className: 'cb-name' }, view.name)
  const glyph = art ? h(BoardGlyph, { state: art, className: 'cb-pglyph' }) : h('span', { className: 'cb-pglyph cb-pglyph--none', 'aria-hidden': 'true' })
  const pad = h('span', { className: 'cb-pad', 'aria-hidden': 'true' })
  // caret between name and glyph; req = requested blocked pin
  const mark = selected ? h('span', { className: 'cb-mark', 'aria-hidden': 'true', 'data-cb-mark': requested ? 'req' : 'sel', title: requested ? 'requested' : 'selected' }) : null
  const parts = side === 'l' ? [tag, name, mark, glyph, pad] : [pad, glyph, mark, name, tag]
  const props = {
    className: 'cb-pin', 'data-cb': interactive ? `pin-${view.gpio}` : `pin-${hp.header}-${hp.n}`, 'data-cb-state': view.state, 'data-cb-art': art || 'unchecked',
    'data-cb-suggest': suggested ? 'true' : undefined, 'data-cb-pulse': pulse ? 'true' : undefined, title: `${hp.header}-${hp.n} · ${word} · ${view.title}`
  }
  if (!interactive) return h('div', props, parts, h('span', { className: 'cb-sr' }, view.title))
  return h('button', { ...props, type: 'button', 'aria-pressed': selected ? 'true' : 'false',
    'aria-label': `${view.name}, ${word}${suggested ? ', suggested' : ''}: ${view.title}, header ${hp.header} pin ${hp.n}`,
    onClick: () => onSelect(view.gpio) }, parts)
}

// data-cb anchors of the pcb notes (boardArtModel note ids)
const BOARD_NOTE_CB = { unknown: 'board-variant-unknown', spi: 'board-reserve', quad: 'board-quad' }
const BOARD_PORT_WORD = { usb_serial_jtag: 'USB Serial/JTAG', usb_uart_bridge: 'USB-to-UART bridge', usb_otg: 'USB OTG', rj45: 'RJ45 Ethernet jack' }
const BOARD_PART_WORD = { micro_usb: 'Micro-USB', usb_c: 'USB-C', generic_usb: 'connector form not quoted', rj45: 'RJ45' }

/** The anchors over the drawing (module name, antenna, ports, buttons, notes): transparent, title + sr text. */
function BoardAnchors({ layout, model, plan, g, detected }) {
  const ports = boardPorts(layout)
  const at = (x, y, w, hh) => ({ left: `${g.gutterL + x}px`, top: `${y}px`, width: `${w}px`, height: `${hh}px` })
  const partBox = p => {
    const fp = p.fp
    const bx = p.x + (fp.labelPos === 'right' ? 0 : (fp.w - fp.body.w) / 2)
    const by = fp.labelPos === 'above' ? p.y + fp.h - fp.body.h : p.y
    return at(bx, by, fp.body.w, fp.body.h)
  }
  const m = plan.module
  const drawnPort = u => plan.parts.find(p => (p.part.kind === 'usb_port' || p.part.kind === 'rj45') && (p.part.ref === u.label || (u.connector && p.part.kind === u.kind)))
  const drawnBtn = b => plan.parts.find(p => p.part.kind === 'button' && p.part.label === b)
  const live = u => Boolean(!u.connector && detected && /usb|jtag/i.test(u.kind) && /ACM|usbmodem/i.test(detected.port || ''))
  return h('div', { className: 'cb-module', 'data-cb': 'board-module' },
    h('span', { className: 'cb-banchor', style: at(m.can.x, m.can.y, m.can.w, m.can.h), title: [model.module.chip, model.module.name,
      model.module.flash_mb ? `${model.module.flash_mb} MB flash` : null, model.module.psram_mb ? `${model.module.psram_mb} MB PSRAM` : null].filter(Boolean).join(' · ') },
    h('span', { className: 'cb-sr' }, `${model.module.chip} module `), h('span', { className: 'cb-sr', 'data-cb': 'board-module-name' }, model.module.name)),
    // antenna: null in the layout → no antenna is drawn or named (nothing invented)
    model.module.antennaText ? h('span', { className: 'cb-banchor', 'data-cb': 'board-antenna', style: at(m.x, m.y, m.w, Math.max(m.antH, 18)),
      title: model.module.antenna === 'pcb' ? 'PCB antenna: keep metal clear (no ground plane, no metal case above it)' : 'Antenna connector (IPEX/U.FL): external antenna' },
    h('span', { className: 'cb-sr' }, model.module.antennaText)) : null,
    plan.notes.map((n, i) => {
      const note = model.notes[i]
      return h('div', { key: note.id, className: `cb-bnote cb-bnote--${note.tone}`, 'data-cb': BOARD_NOTE_CB[note.id], title: note.title, style: at(n.x, n.y, n.w, n.h) },
        note.tone === 'warn' ? h(BoardGlyph, { state: 'caution' }) : null, h('span', null, note.text))
    }),
    // USB ports, then connectors (WT32: RJ45 LAN instead of USB), in data order
    h('div', { className: 'cb-usb', 'data-cb': 'board-ports' }, ports.map(u => {
      const p = drawnPort(u)
      return h('span', { key: `${u.kind}-${u.label}`, 'data-cb-port': u.kind, className: 'cb-banchor cb-bport', 'data-cb-live': live(u) ? 'true' : 'false',
        'data-cb-schematic': p?.part.schematic || p?.part.connector === 'generic_usb' ? 'true' : undefined, style: p ? partBox(p) : { display: 'none' },
        title: `${u.title}${p ? ` · ${BOARD_PART_WORD[p.part.connector] || ''}` : ''}` }, h('span', { className: 'cb-sr' }, `${u.label} ${BOARD_PORT_WORD[u.kind] || ''}`))
    })),
    h('div', { className: 'cb-btns', 'data-cb': 'board-buttons' }, model.buttons.map(b => {
      const p = drawnBtn(b)
      return h('span', { key: b, className: 'cb-banchor', style: p ? partBox(p) : { display: 'none' }, title: `${b} button`,
        'data-cb-schematic': p?.part.schematic ? 'true' : undefined }, h('span', { className: 'cb-sr' }, `[${b}]`))
    })))
}

function boardRowsOf(layout, side) {
  return headerRows(layout)[side]
}

function BoardView({ layoutState, mapState, rows, board, selected, suggestPins, onSelect }) {
  const pulse = sdk.useValue($pulse)
  const wrapRef = useRef(null)
  const prefix = useRef(null)
  if (!prefix.current) prefix.current = `board-${++BOARD_VIEW_SEQ}`
  const box = useBoardBox(wrapRef)
  const layout = layoutState.layout
  const ready = layoutState.status === 'ready' && layout
  const chip = chipInfo(board.chip)
  const variant = variantInfo(board.chip, board.variant)
  const detected = $project.get()?.board?.detected
  // the detected chip revision belongs to the detected chip only (not to a what-if board of another chip)
  const sameChip = detected?.chip && /^(ESP32(?:-[A-Z0-9]+)?)/i.exec(detected.chip)?.[1]?.toUpperCase() === String(chip?.label || '').toUpperCase()
  const rev = sameChip ? /revision\s+(v[\d.]+)/i.exec(detected.chip)?.[1] : null
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null)
  const used = new Map(rows.map(r => [r.pin, r]))
  const liveRefs = (Array.isArray(layout?.usb) ? layout.usb : [])
    .filter(u => detected && /usb|jtag/i.test(u.kind) && /ACM|usbmodem/i.test(detected.port || '')).map(u => String(u.label))
  const model = ready ? boardArtModel({ layout, chip, variant, base, used, selected, suggest: suggestPins, live: liveRefs, rev }) : null
  const tags = model ? [...model.views.left, ...model.views.right].filter(s => s.view).map(s => boardTagW(s.view.tag)) : []
  // the console counts as open only when it really takes its height (an idle or collapsed bar leaves the room
  // to the board: pitch up to 28 instead of 20)
  const consMode = useConsoleMode(sdk.useValue($project))
  const g = ready ? boardGeom({ layout, consoleOpen: consMode === 'open', width: box?.w, height: box?.h, tagWidth: Math.ceil(Math.max(0, ...tags) / 8) * 8 }) : null
  // the SVG string only changes with what it draws (hooks run on every render, before the early returns)
  const svgKey = model ? JSON.stringify([layout.id, model.sides, model.brackets, model.module, model.parts, model.notes.map(n => n.text), model.ledState, model.live, g]) : ''
  const svg = useMemo(() => (model ? artBoard(model, g, { prefix: prefix.current }) : ''), [svgKey])
  if (layoutState.status === 'loading' || layoutState.status === 'idle') return h('div', { className: 'cb-loading', 'data-cb': 'board-loading' }, 'loading board layout')
  if (layoutState.status === 'none') {
    return h('div', { className: 'cb-board-empty', 'data-cb': 'board-none' },
      h(Label, null, '// board view'),
      h('p', { className: 'cb-why' }, `No DevKit header map for ${chipInfo(board.chip)?.label || board.chip} yet. The assignments below are still checked against the chip's pin rules.`),
      h('p', { className: 'cb-dim' }, `Header maps exist for: ${DEVKITS.map(devkitTitle).join(', ')}.`))
  }
  if (layoutState.status === 'error' || !model) {
    return h(EmptyBox, { tone: 'bad', kicker: '// board view', title: 'Board layout unavailable', dataCb: 'board-error',
      actions: [h(Btn, { key: 'r', kind: 'ghost', onClick: () => loadBoard(layoutState.id) }, 'Retry')] },
    h('p', null, layoutState.error?.error?.message || 'The backend did not return the header layout.'))
  }
  const plan = artBoardPlan(model, g)
  const pulsePins = new Set(pulse.pins)
  const all = [...boardRowsOf(layout, 'left'), ...boardRowsOf(layout, 'right')]
  const col = side => {
    const s = side === 'left' ? 'l' : 'r'
    const out = []
    for (const slot of model.views[side]) {
      if (slot.sep !== undefined) {
        out.push(h('div', { key: `sep-${slot.sep}-${slot.slot}`, className: 'cb-hdr-sep cb-label', 'data-cb': 'header-sep' }, h('span', null, slot.sep)))
        continue
      }
      const { hp, view } = slot
      const u = Number.isInteger(hp.gpio) ? used.get(hp.gpio) : null
      out.push(h(BoardPin, { key: `${hp.header}-${hp.n}`, slot: { ...slot, mark: g.markW > 0, tagFits: g.tagFits }, side: s,
        selected: view.gpio !== null && view.gpio === selected, suggested: view.gpio !== null && suggestPins.includes(view.gpio),
        pulse: view.gpio !== null && pulsePins.has(view.gpio), requested: Boolean(u && u.verdict === 'blocked'), onSelect }))
    }
    // reservation brackets: transparent anchors in the lane with the full text (title + screen reader); the octal
    // PSRAM run keeps its anchor name psram-bracket
    for (const br of model.brackets[side]) {
      const gp = model.views[side].filter(v => v.view && v.slot >= br.from && v.slot <= br.to).map(v => v.hp.gpio).filter(Number.isInteger).sort((a, b) => a - b)
      const octal = br.label === 'OCTAL PSRAM'
      const missing = octal ? [33, 34, 35, 36, 37].filter(x => !all.some(r => r.gpio === x)) : []
      const text = octal
        ? `Octal PSRAM: GPIO33–37 are wired to the PSRAM bus on this module; IO${gp[0]}–${gp[gp.length - 1]} reserved${missing.length ? `; GPIO${missing.join('/')} not on the header` : ''}`
        : `${br.label}: GPIO${gp.join('/')} reserved (${br.tone === 'bad' ? 'blocked' : 'caution'})`
      out.push(h('span', { key: `br-${br.from}`, className: 'cb-bbracket', 'data-cb': octal ? 'psram-bracket' : 'board-bracket', 'data-cb-tone': br.tone, title: text,
        style: { top: `${br.from * g.pitch - 2}px`, height: `${(br.to - br.from + 1) * g.pitch - g.rowGap + 4}px` } }, h('span', { className: 'cb-sr' }, text)))
    }
    return h('div', { className: `cb-col cb-col--${s}`, 'data-cb': `header-${side}` }, out)
  }
  const ids = side => headerIds(boardRowsOf(layout, side))
  return h('div', { className: 'cb-board-wrap', ref: wrapRef },
    h('div', { className: 'cb-board', 'data-cb': 'board', 'data-cb-map': mapState.status, 'data-cb-board': layout.id, role: 'group',
      'data-cb-audit-root': 'board', 'data-cb-pitch': g.pitch, 'data-cb-schematic': model.schematic ? 'true' : undefined,
      'aria-label': `${layout.title}${layout.revision ? ` ${layout.revision}` : ''} header map, schematic, not to scale`, style: boardGeomVars(g) },
    h('div', { className: 'cb-board-art', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: svg } }),
    h('div', { className: 'cb-board-hdr cb-label', title: ids('left').join(' · ') }, boardRowsOf(layout, 'left')[0]?.header || 'J1'),
    h('div', { className: 'cb-board-hdr cb-label', title: ids('right').join(' · ') }, boardRowsOf(layout, 'right')[0]?.header || 'J3'),
    h(BoardAnchors, { layout, model, plan, g, detected }),
    col('left'), col('right')))
}

/** Board-level warnings of the layout (e.g. WT32 "Feed either 3V3 or 5V, never both."):
 *  danger first, each with symbol and word, never colour only. `compact` = one line each above the board (PLAN). */
function BoardWarnings({ layout, sources = [], compact = false }) {
  const ws = boardWarnings(layout)
  if (!ws.length) return null
  const title = devkitTitle(devkitInfo(layout?.id)) || layout?.title || 'board'
  const list = h('ul', { className: 'cb-bwarn-list' }, ws.map(w => h('li', { key: w.id, className: `cb-bwarn cb-bwarn--${w.tone}`, 'data-cb': 'board-warning',
    'data-cb-severity': w.severity, title: w.id },
  h('span', { className: 'cb-bwarn-k' }, h('span', { 'aria-hidden': 'true' }, w.symbol), ` ${w.word}`),
  h('span', { className: 'cb-bwarn-m' }, w.message))))
  if (compact) {
    return h('div', { className: 'cb-bwarns', 'data-cb': 'board-warnings', role: 'note', 'aria-label': `${title}: board warnings` }, list)
  }
  const ids = ws.map(w => w.source_id).filter(Boolean)
  return h('div', { className: `cb-card cb-bracket cb-bwarn-card${ws.some(w => w.severity === 'danger') ? ' cb-bracket--bad' : ''}`, 'data-cb': 'insp-board-warnings',
    role: 'note', 'aria-label': `${title}: board warnings` },
  h(Label, null, `// board · ${title}`), list, h(SourceLine, { sources: (sources || []).filter(s => ids.includes(s.id)) }))
}

/** Legend with the same symbols as the board: shape + word, colour only adds to it. */
function Legend({ suggesting = false, kinds = [], dataCb = 'legend', className }) {
  const item = (state, word, cb) => h('span', { key: state, 'data-cb': cb, 'data-cb-legend': state, role: 'listitem' }, h(BoardGlyph, { state }), word)
  return h('div', { className: cx('cb-legend', className), 'data-cb': dataCb, role: 'list', 'aria-label': 'Pin states' },
    item('assigned', 'assigned'), item('free', 'free'), item('caution', 'caution'), item('blocked', 'blocked'),
    item('power', 'power'), item('ground', 'GND · RST'),
    kinds.includes('signal') ? item('signal', 'signal', 'legend-signal') : null,
    kinds.includes('nc') ? item('nc', 'not connected', 'legend-nc') : null,
    suggesting ? h('span', { key: 'sug', className: 'cb-legend-sug', 'data-cb': 'legend-suggested', role: 'listitem' }, h('i', { 'aria-hidden': 'true' }), 'suggested') : null)
}

// ─── Compact model and live twin ──────────────────────────────────────────────────────────────────────────────────
// One compact board model (lib/art-board.js artBoardTwin) for the chat card and the twins in 05 FLASH / 06 DEBUG.
// Every instance has its own SVG id prefix. The twin only shows store events: the lit port, the flash job, a panic,
// arriving serial lines. Reduced motion: the pulse dots stand still (14-styles-board.js).

let BOARD_TWIN_SEQ = 0

/** Stable id prefix of one instance (`chat-3`, `flash-4` …): several models on one page never share an id. */
function useTwinPrefix(kind) {
  const ref = useRef(null)
  if (!ref.current) ref.current = `${kind}-${++BOARD_TWIN_SEQ}`
  return ref.current
}

/** Pins in words for the model's aria-label: "LASER on GPIO14 (ok), …". */
function twinPinsText(project) {
  return (project?.assignments || []).map(a => `${a.role} on GPIO${a.pin} (${a.verdict || 'not checked'})`).join(', ') || 'no assignments'
}

/**
 * The compact model: pcb, module, strips, pads with their state, ports; no text in the drawing (it scales), the
 * stamp on the module and the caption are DOM. port = GET /ports entry (lights only when its kind leads to exactly
 * one drawn usb port), flash = running | done | failed | null, stamp = { tone, text } | null.
 */
function BoardTwin({ layout, project, base = null, prefix, port = null, flash = null, stamp = null, turn = true, dataCb = 'board-twin', label, caption, className, hot = null }) {
  const b = project?.board || {}
  const model = boardArtModel({ layout, chip: chipInfo(b.chip), variant: variantInfo(b.chip, b.variant), base: base || new Map(),
    used: new Map((project?.assignments || []).map(a => [a.pin, a])) })
  const g = boardGeom({ layout, mode: 'compact' })
  const ref = twinPortRef(port, model, FLASH_PORT_USB)
  const key = JSON.stringify([layout.id, prefix, model.sides, model.brackets, model.module, model.ledState, ref, flash, turn])
  const art = useMemo(() => artBoardTwin(model, g, { prefix, turn, port: ref, flash }), [key])
  // chat card hover coupling: DOM ring on the pad
  const ring = Number.isInteger(hot) ? artBoardTwinPad(model, g, hot, turn) : null
  return h('div', { className: cx('cb-twin', className), 'data-cb': dataCb, 'data-cb-board': layout.id, 'data-cb-flash': flash || undefined,
    'data-cb-port-lit': art.port || undefined, 'data-cb-turn': turn ? 'true' : undefined },
  h('div', { className: 'cb-twin-box', role: 'img', 'aria-label': label || `${layout.title} board model: ${twinPinsText(project)}` },
    h('div', { className: 'cb-twin-art', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: art.svg } }),
    stamp ? h('span', { className: 'cb-twin-stamp', 'data-cb': `${dataCb}-stamp`, 'data-cb-tone': stamp.tone, 'aria-hidden': 'true',
      style: { left: `${art.module.x}%`, top: `${art.module.y}%` } }, h(Stamp, { tone: stamp.tone }, stamp.text)) : null,
    ring ? h('span', { className: 'cb-twin-ring', 'data-cb': `${dataCb}-hot`, 'data-cb-gpio': hot, 'aria-hidden': 'true',
      style: { left: `${ring.x}%`, top: `${ring.y}%` } }) : null),
  caption === false ? null : h('div', { className: 'cb-twin-cap' },
    h('span', { className: 'cb-twin-cap-t' }, caption || devkitTitle(devkitInfo(layout.id)) || layout.title),
    h('span', { className: 'cb-dim' }, 'schematic · not to scale')))
}

/** Pin map of the project's own board for a twin in the Bench: the loaded map, unless PLAN shows a what-if board. */
function twinBase(project, layout) {
  const map = $map.get()
  if (!layout || isWhatIf() || map.status !== 'ready' || !map.env?.ok || $board.get().id !== layout.id || project?.board?.devkit !== layout.id) return null
  return mapByGpio(map.env.result)
}

const TWIN_FLASH_STAMP = { running: { tone: 'active', text: '◴ FLASHING' }, done: { tone: 'ok', text: '✓ FLASHED' }, failed: { tone: 'bad', text: '✕ FAILED' } }

/** Live twin in 05 FLASH (inspector): the port of the selected serial port lights; during the flash job of this
 *  session the pulse runs from the flash target's port to the module, then the result stamp. */
function FlashTwin({ project }) {
  const flow = sdk.useValue($flow)
  const ports = sdk.useValue($ports)
  const jobs = sdk.useValue($jobs)
  sdk.useValue($map)
  const prefix = useTwinPrefix('flash')
  const layout = useBoardLayout(project?.board?.devkit)
  if (!layout || !project) return null
  const flash = twinFlashState(jobProgress(jobs.flash))
  const device = flash ? project.board?.detected?.port || flow.port : flow.port
  const entry = (ports.ports || []).find(p => p.device === device) || null
  const stamp = flash ? TWIN_FLASH_STAMP[flash] : null
  const lit = entry && !entry.simulated && twinPortRef(entry, boardArtModel({ layout }), FLASH_PORT_USB)
  const portWord = !entry ? 'no port selected' : entry.simulated ? 'simulated · no port lit' : lit ? `on the ${lit} port` : 'port kind unknown · none lit'
  const portText = entry ? `${device}: ${portWord}` : portWord
  return h('div', { className: 'cb-card cb-twin-card', 'data-cb': 'flash-twin' },
    h(Label, null, '// live twin'),
    h(BoardTwin, { layout, project, base: twinBase(project, layout), prefix, port: entry, flash, stamp, dataCb: 'flash-twin-model',
      label: `${layout.title} board model. ${portText}.${flash ? ` Flash ${flash}.` : ''}` }),
    h('p', { className: 'cb-twin-note', 'data-cb': 'flash-twin-port', 'data-cb-lit': lit ? 'true' : 'false' },
      h(Label, null, 'port'), entry ? h('b', { title: device }, device) : null, h('span', { className: lit ? 'cb-active-t' : 'cb-dim' }, portWord)))
}

/** TX/RX of the board while the monitor is open: TX (board → Bench) lights only while serial lines arrive; the Bench
 *  never writes to the port, so RX stays dark. */
function TwinSerialLeds({ tx, open }) {
  const led = (id, on, word, title) => h('span', { key: id, className: 'cb-twin-led', 'data-cb': `twin-${id}`, 'data-cb-on': on ? 'true' : 'false', title },
    h('i', { 'aria-hidden': 'true' }), h('b', null, id.toUpperCase()), h('span', { className: 'cb-dim' }, word))
  return h('div', { className: 'cb-twin-leds', role: 'status', 'aria-label': `TX ${tx ? 'lines arriving' : 'idle'}, RX idle` },
    led('tx', tx, tx ? 'lines arriving' : open ? 'idle' : 'monitor closed', 'Board transmits: lights while serial lines arrive'),
    led('rx', false, 'nothing sent', 'The Bench only reads the port, nothing is sent to the board'))
}

/** Arriving serial lines (sequence grows) → active for TWIN_RX_WINDOW_MS, then a re-render turns the dot off. */
function useSerialActivity(buf) {
  const ref = useRef(null)
  const [, setTick] = useState(0)
  const now = Date.now()
  const st = twinSerialTrack(ref.current, buf, now)
  ref.current = st
  useEffect(() => {
    if (!st.active) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => setTick(x => x + 1), Math.max(50, st.until - Date.now() + 30))
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [st.until])
  return st.active
}

/** Live twin in 06 DEBUG (monitor card): the monitor's port lights, the panic stamp sits on the module while the
 *  panic is current, TX lights while lines arrive. */
function DebugTwin({ project }) {
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const ports = sdk.useValue($ports)
  sdk.useValue($map)
  const prefix = useTwinPrefix('debug')
  const layout = useBoardLayout(project?.board?.devkit)
  const { data } = usePanicData(project)
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const tx = useSerialActivity(open ? serial.buf : null) && open
  if (!layout || !project) return null
  const entry = open ? (ports.ports || []).find(p => p.device === mon.port) || null : null
  const stamp = data ? { tone: 'bad', text: 'PANIC' } : null
  return h('div', { className: 'cb-twin-row', 'data-cb': 'debug-twin', 'data-cb-panic': data ? 'true' : 'false' },
    h(Label, { className: 'cb-twin-lab' }, '// live twin'),
    h(BoardTwin, { layout, project, base: twinBase(project, layout), prefix, port: entry, stamp, dataCb: 'debug-twin-model',
      label: `${layout.title} board model.${data ? ` Panic: ${data.title}.` : ''}${open ? ` Monitor open on ${mon.port}.` : ''}` }),
    h(TwinSerialLeds, { tx, open }))
}

// --- 30-ui-bus.js
// Card `// buses`: devices (+N); findings one line (symbol, word, refs; text folded, 3 + "show all");
// passed/not checked folded; rails as bars; required parts; one agent button

const modSym = s => h('span', { className: 'cb-mod-sym', 'aria-hidden': 'true' }, s)
const modCalcLink = (calc, pre, onClick) => h('button', { type: 'button', className: 'cb-mod-link', 'data-cb': `${pre}-calc-${calc}`,
  title: `Open the ${calc.replace(/_/g, ' ')} calculator in CALC`, onClick }, 'calc ›')
const modRailLook = f => (f === null ? null : f > 1 ? ['bad', '⊗', 'over limit'] : f > 0.8 ? ['warn', '◇', 'near limit'] : ['ok', '✓', 'ok'])
// folded row: symbol, word, rest; body on open
const modFold = (tone, sym, word, rest, body) => h('details', { className: 'cb-mod-fd' },
  h('summary', { className: `cb-mod-row cb-mod-row--f cb-mod-row--${tone}` }, modSym(sym),
    h('span', { className: 'cb-mod-ellip', 'data-cb-truncate-ok': 'true', title: rest ? `${word} ${rest}` : word }, h('b', null, word), rest ? h('span', { className: 'cb-mod-dim' }, ` ${rest}`) : null)),
  body)
const modFindingRow = (w, i) => h('li', { key: `${w.code}-${i}`, 'data-cb': 'mod-finding', 'data-cb-code': w.code },
  modFold(w.tone, w.symbol, w.word, (w.refs || []).join(' '), h('p', { className: 'cb-mod-note cb-mod-dim' }, w.message)))

function BusCard({ modules, findings = null }) {
  const buses = Array.isArray(modules?.buses) ? modules.buses : []
  const railsRaw = Array.isArray(modules?.rails) ? modules.rails : []
  if (!modules || (!buses.length && !railsRaw.length)) return null
  const shown = findings?.warnings || []
  const c = modules.counts || {}
  const seen = new Set([...shown.map(w => w.code), ...(c.hidden || []).map(x => String(x).split(' ')[0])])
  const checks = (findings?.checks || []).filter(x => !seen.has(`mod_${String(x.id).slice(8).replace(/\./g, '_')}`))
  const more = (c.findings ?? 0) - (c.shown ?? shown.length)
  const hidden = modHidden(c.hidden)
  const ids = [...new Set(shown.flatMap(w => w.source_ids || []))]
  const rails = modRails({ ok: true, result: { modules } })
  const nf = c.findings ?? shown.length
  return h('section', { className: 'cb-card cb-bracket cb-mod-bus', 'data-cb': 'insp-buses', 'aria-label': 'Buses' },
    h('div', { className: 'cb-card-head cb-mod-head' }, h(Label, null, '// buses'),
      h(Label, { className: 'cb-push' }, `${c.modules ?? '?'} module${c.modules === 1 ? '' : 's'} · ${nf} finding${nf === 1 ? '' : 's'}`)),
    buses.map(b => {
      const segs = (b.segments || []).length ? b.segments : b.more ? [{ id: 'main', devices: [], more: b.more }] : []
      return h('div', { key: b.id, className: 'cb-mod-busbox', 'data-cb': 'mod-bus', 'data-cb-bus': b.id },
        h('div', { className: 'cb-mod-row cb-mod-row--2' }, h('b', null, modInterfaceLabel(b.type)),
          h('span', null, Object.entries(b.gpios || {}).map(([k, v]) => `${k} IO${v}`).join(' · '),
            b.f_max_hz ? h('span', { className: 'cb-mod-dim' }, ` · ≤ ${modSI(b.f_max_hz, 'Hz')}`) : null)),
        segs.map(s => h('div', { key: s.id, className: 'cb-mod-row cb-mod-row--2', 'data-cb': 'mod-seg' },
          h('span', { className: 'cb-mod-k' }, (segs.length > 1 || s.id !== 'main') ? `seg ${s.id}` : 'devices'),
          h('span', { 'data-cb': 'mod-devices' }, [...(s.devices || []).map(d => [d.ref, d.address].filter(Boolean).join(' ')),
            s.more ? `+${s.more} device${s.more === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ')))))
    }),
    h('ul', { className: 'cb-mod-list', 'data-cb': 'mod-findings' },
      shown.slice(0, 3).map(modFindingRow),
      shown.length > 3 ? h('li', { key: 'all', 'data-cb': 'mod-all' }, modFold('dim', '+', `show all ${shown.length}`, '',
        h('ul', { className: 'cb-mod-list' }, shown.slice(3).map((w, i) => modFindingRow(w, i + 3))))) : null,
      more > 0 ? h('li', { key: 'more', className: 'cb-mod-row cb-mod-row--f cb-mod-row--dim', 'data-cb': 'mod-hidden' }, modSym('+'),
        h('span', null, h('b', null, `${more} more`), hidden.length ? ` hidden: ${hidden.join(' · ')}` : ' not listed')) : null,
      [['ok', '✓', 'passed'], ['dim', '○', 'not checked']].map(([tone, sym, word]) => {
        const list = checks.filter(x => x.tone === tone)
        return list.length ? h('li', { key: tone, 'data-cb': `mod-${tone === 'ok' ? 'passed' : 'open'}` },
          modFold(tone, sym, `${list.length} ${word}`, '', h('p', { className: 'cb-mod-note cb-mod-dim' },
            list.map(x => modWarningWord(x.id)).join(' · ')))) : null
      })),
    rails.length ? h('div', { className: 'cb-mod-rails', 'data-cb': 'mod-rails' }, h(Label, null, '// rails'), rails.map(r => {
      const look = modRailLook(r.frac)
      const miss = railsRaw.find(x => x.net === r.net)?.missing || []
      const ge = miss.length ? '≥\u00a0' : ''
      return h('div', { key: r.net, className: 'cb-mod-rail', 'data-cb': 'mod-rail', 'data-cb-net': r.net },
        h('div', { className: 'cb-mod-railhead' }, h('b', null, r.net), h('span', { className: 'cb-mod-dim' }, r.volts),
          h('span', { className: `cb-mod-push${look ? ` cb-mod-t-${look[0]}` : ' cb-mod-dim'}` },
            look ? `${look[1]} ${Math.round(r.frac * 100)} % · ${look[2]}` : 'no limit known')),
        h('div', { className: `cb-mod-meter${look ? ` cb-mod-meter--${look[0]}` : ' cb-mod-meter--none'}`, role: look ? 'meter' : undefined,
          'aria-label': look ? `${r.net} peak ${r.peak} of ${r.limit}: ${look[2]}` : `${r.net}: no limit known`, 'aria-valuenow': look ? Math.round(r.frac * 100) : undefined },
        look ? h('i', { style: { width: `${Math.min(100, r.frac * 100)}%` } }) : null),
        h('div', { className: 'cb-mod-dim cb-mod-nums' }, modKeep([['typ', r.typ], ['max', r.max], ['peak', r.peak]].filter(([, v]) => v && v !== '—').map(([k, v]) => `${k}\u00a0${ge}${v}`)
          .concat(r.limit ? [`limit ${r.limit}${r.limitSource ? ` (${r.limitSource})` : ''}`] : []).join(' · '))),
        miss.length ? h('div', { className: 'cb-mod-dim cb-mod-nums', 'data-cb': 'mod-rail-missing' }, `? partial: ${miss.join(', ')} ${miss.length === 1 ? 'has' : 'have'} no data`) : null)
    })) : null,
    h(BusRequires, { refs: buses.flatMap(b => (b.segments || []).flatMap(s => (s.devices || []).map(d => d.module))), checks: findings?.checks || [], warns: shown }),
    shown.some(w => w.severity !== 'info') ? h(BusAsk, { shown }) : null,
    ids.length ? h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources: findings?.sources || [], ids })) : null)
}

// required parts; tone of the strongest mod_required_parts warning, else of the check
function BusRequires({ refs, checks, warns = [] }) {
  const project = sdk.useValue($project)
  const ids = [...new Set([...refs, ...moduleInstances(project).map(i => i.module)].filter(Boolean))]
  const infos = useModuleInfos(ids)
  const w = warns.find(x => x.code === 'mod_required_parts')
  const st0 = modStatusMeta(checks.find(x => x.id === 'modules.required_parts')?.status)
  const st = w ? { symbol: w.symbol, word: w.level, tone: w.tone } : st0.tone === 'bad' ? { symbol: '◇', word: 'finding', tone: 'warn' } : st0
  const reqs = []
  for (const id of ids) for (const r of infos[id]?.requires || []) {
    if (!reqs.some(x => x.r.code === r.code && x.id === id)) reqs.push({ id, r, calc: modRequireCalc(r, infos[id]) })
  }
  if (!reqs.length) return null
  // folded by default: the module rows of the table stay in view
  return h('details', { className: 'cb-mod-reqs', 'data-cb': 'mod-requires' },
    h('summary', { className: 'cb-card-head cb-mod-head' }, h(Label, null, `// required parts · ${reqs.length}`), h(Label, { className: `cb-push cb-mod-t-${st.tone}` }, `${st.symbol} ${st.word}`)),
    h('ul', { className: 'cb-mod-list' }, reqs.map(({ id, r, calc }) => h('li', { key: `${id}-${r.code}`, className: 'cb-mod-row cb-mod-row--r', title: modEvidence(r) || undefined },
      modSym('+'),
      h('span', null, h('b', null, id), ` ${modRequireText(r)}`, r.page != null ? h('span', { className: 'cb-mod-page' }, ` p. ${r.page}`) : null),
      calc ? modCalcLink(calc, 'mod', e => openCalc(calc, e.currentTarget)) : h('span')))))
}

// agent action: findings as a composer draft (not sent)
function BusAsk({ shown }) {
  const project = sdk.useValue($project)
  const ask = () => composeDraft(`Bench project ${project?.id}: fix these module findings (bench_project connect/add_module, then bench_pins check):\n${shown.map(w => `- ${w.word}: ${w.message}`).join('\n')}`)
  return h('div', { className: 'cb-actions' }, h(Btn, { kind: 'agent', size: 'sm', 'data-cb': 'mod-ask', title: 'Draft a fix request in the chat (not sent)', onClick: ask }, 'Fix with Hermes'))
}

function BusPanel() {
  const { modules, findings } = useModuleCheck()
  return h(BusCard, { modules, findings })
}

// --- 30-ui-chip.js
// BoardChip in the status bar (STATUSBAR_AREAS.right): ● LINK ttyACM0 / ◌ SIM / ○ NO BOARD. App chrome, so it uses
// the app theme colours (look "theme"). Click opens the Bench.

function BoardChip() {
  const ports = sdk.useValue($ports)
  const link = linkState(ports, null)
  const glyph = link.kind === 'link' ? '●' : link.kind === 'sim' ? '◌' : '○'
  const tone = link.kind === 'link' ? 'cb-ok' : link.kind === 'sim' ? 'cb-active' : 'cb-dim'
  const short = link.device ? link.device.replace(/^\/dev\//, '') : ''
  const label = link.kind === 'unknown' ? 'BENCH' : link.kind === 'offline' ? 'BENCH OFFLINE' : link.label
  return h(Fragment, null, h(Styles, null), h('button', { type: 'button', className: 'cb-root cb-chip', 'data-cb': 'board-chip', 'data-cb-look': 'theme', 'data-cb-link': link.kind,
    title: link.device ? `Circuit Bench · ${link.label} ${link.device} — open the Bench` : 'Circuit Bench — open the Bench',
    onClick: () => openBench() },
  h('span', { className: `cb-g ${tone}`, 'aria-hidden': 'true' }, glyph),
  h('span', null, label),
  short ? h('b', null, short) : null))
}

// --- 30-ui-hud.js
// HUD: brand, project, board + variant, link, key figures, primary action.

/** Link state from the port list (listing never opens a port): real ESP port → LINK, sim → SIM, none → NO BOARD.
 *  The words are information, so the quiet states use fg-dim, never the decoration colour fg-faint. */
function linkState(ports, project = null) {
  const list = ports?.ports || []
  if (ports?.status === 'error') return { kind: 'offline', label: 'OFFLINE', device: '', tone: 'dim', dot: 'off' }
  if (ports?.status === 'idle' || ports?.status === 'loading') return { kind: 'unknown', label: '…', device: '', tone: 'dim', dot: 'off' }
  // HUD: the port the project was detected on, if any (status chip: whatever is plugged in)
  const detected = project?.board?.detected?.port || null
  if (detected) {
    const hit = list.find(p => p.device === detected)
    if (!hit) return { kind: 'lost', label: 'LOST', device: detected, tone: 'warn', dot: 'off' }
    return hit.simulated ? { kind: 'sim', label: 'SIM', device: detected, tone: 'active', dot: 'active' }
      : { kind: 'link', label: 'LINK', device: detected, tone: 'ok', dot: 'ok' }
  }
  const real = list.find(p => !p.simulated && p.likely_esp)
  const sim = list.find(p => p.simulated)
  if (real) return { kind: 'link', label: 'LINK', device: real.device, tone: 'ok', dot: 'ok' }
  if (sim) return { kind: 'sim', label: 'SIM', device: sim.device, tone: 'active', dot: 'active' }
  return { kind: 'none', label: 'NO BOARD', device: '', tone: 'dim', dot: 'off' }
}

function Hud({ project, rows, health }) {
  const ports = sdk.useValue($ports)
  const nProjects = (sdk.useValue($bench).projects || []).length
  const nav = sdk.useValue($nav)
  const check = sdk.useValue($check)
  const counts = countVerdicts(rows)
  const fig = hudFigures(project, counts)
  const link = linkState(ports, project)
  const b = project?.board || {}
  const chip = chipInfo(b.chip)
  const variant = variantInfo(b.chip, b.variant)
  const [busy, setBusy] = useState(false)
  const ask = async () => {
    setBusy(true)
    try { await composeDraft(askHermesText(project, nav.station, rows)) } finally { setBusy(false) }
  }
  const version = health?.version ? `v${String(health.version).replace(/\.0$/, '')}` : 'v0.1'
  const kpi = shellKpis(counts, fig.solder, fig.build, modCountWords(stageModCounts(check.env)))
  return h('header', { className: 'cb-hud', 'data-cb': 'hud', 'data-cb-audit-root': 'hud' },
    h('div', { className: 'cb-brand', 'data-cb': 'hud-brand' }, '◢ CIRCUIT//BENCH', h('small', null, version)),
    h('div', { className: 'cb-sep', 'aria-hidden': 'true' }),
    // own button for the project manager (a clickable project chip was not recognisable as a control)
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'hud-projects', 'aria-haspopup': 'dialog', 'aria-label': `Projects (${nProjects})`,
      title: 'Open, create or delete bench projects', onClick: () => patchAtom($ui, { modal: { type: 'projects' } }) },
      h('span', { 'aria-hidden': 'true' }, '▤'), h('span', { className: 'cb-hud-btxt' }, 'Projects'),
      nProjects ? h('span', { className: 'cb-hud-count', 'aria-hidden': 'true' }, String(nProjects)) : null),
    project ? h('div', { className: 'cb-pill', 'data-cb': 'hud-project', title: project.title || project.id },
      // the project id is the one HUD text that may end in an ellipsis (full id + title in the tooltip)
      h(Label, null, 'prj'), h('b', { title: project.id, 'data-cb-truncate-ok': 'true' }, project.id)) : null,
    project ? h('div', { className: 'cb-pill', 'data-cb': 'hud-board', title: b.devkit || 'no DevKit layout' },
      h(Label, null, 'board'), h('b', null, devkitInfo(b.devkit)?.label || chip?.label || b.chip || '—'),
      variant ? h('span', { className: variant.psram === 'octal' ? 'cb-warn' : 'cb-fg',
        title: variant.psram === 'octal' ? 'Octal PSRAM: GPIO33–37 are reserved' : `${variant.label}` }, variant.label) : null) : null,
    // simulated link: the SIM badge is the only frame (no pill border around it); the device name may give way
    link.kind === 'sim'
      ? h('div', { className: 'cb-hudsim', 'data-cb': 'hud-link', 'data-cb-link': 'sim', title: `${link.device} — simulated board, nothing physical is read or written` },
        h(SimBadge, { dataCb: 'sim-banner-hud' }), h('b', { className: 'cb-simdev' }, link.device.replace(/^sim:\/\//, '')))
      : h('div', { className: 'cb-pill', 'data-cb': 'hud-link', 'data-cb-link': link.kind, title: link.device || link.label },
        h('span', { className: `cb-dot cb-dot--${link.dot}`, 'aria-hidden': 'true' }),
        h('span', { className: `cb-${link.tone}` }, link.label), link.device ? h('b', null, link.device) : null),
    project ? h('div', { className: 'cb-kpis', 'data-cb': 'hud-kpis' },
      h(HudKpi, { dataCb: 'kpi-pins', label: 'pins', aria: kpi.pins.label },
        // no zero groups
        (kpi.pins.items.some(i => !i.quiet) ? kpi.pins.items.filter(i => !i.quiet) : kpi.pins.items.slice(0, 1)).map(it =>
          h('span', { key: it.key, className: `cb-kpi-i cb-${it.tone}`, 'data-cb-kpi': it.key },
            h('span', { 'aria-hidden': 'true' }, it.symbol), h('b', null, String(it.n)), it.word ? h('span', { className: 'cb-kpi-w' }, it.word) : null))),
      h(HudKpi, { dataCb: 'kpi-solder', label: 'solder', aria: kpi.solder.label },
        h('b', { className: fig.solder.total ? 'cb-fg' : 'cb-dim' }, kpi.solder.text),
        fig.solder.total ? h('span', { className: 'cb-kpi-bar cb-active', 'aria-hidden': 'true' }, cellBar(fig.solder.done, fig.solder.total, 8)) : null),
      h(HudKpi, { dataCb: 'kpi-build', label: 'build', aria: kpi.build.label },
        h('span', { className: `cb-${kpi.build.tone}` }, kpi.build.word),
        kpi.build.ram !== null ? h('small', null, `ram ${formatPct(kpi.build.ram)}`) : null)) : h('div', { style: { marginLeft: 'auto' } }),
    h(Btn, { kind: 'agent', onClick: ask, disabled: busy || !project, 'data-cb': 'ask-hermes', title: 'Put a prompt about this project into the chat composer (not sent)' }, 'Ask Hermes'))
}

/** One HUD key figure: label above, value line below; the whole sentence as aria-label and title (the narrow HUD
 *  keeps only symbol + number). */
function HudKpi({ dataCb, label, aria, children }) {
  return h('div', { className: 'cb-kpi', 'data-cb': dataCb, role: 'group', 'aria-label': aria, title: aria },
    h(Label, { 'aria-hidden': 'true' }, label), h('span', { className: 'cb-v' }, children))
}

// --- 30-ui-inspector.js
// Inspector: verdict + stamp, one sentence of reason, the way out (alternatives as chips), pin functions, modes and
// the src › line in the card foot. The audit root
// "inspector" is the station's aside [data-cb=insp] (fallback of the visual audit script), so every card in it counts.

function entrySources(envs, ids) {
  const seen = new Map()
  for (const env of envs) for (const s of env?.sources || []) if (!seen.has(s.id)) seen.set(s.id, s)
  const want = [...new Set(ids.filter(Boolean))] // the rule's source may be the DevKit guide itself
  const list = want.length ? want.map(id => seen.get(id)).filter(Boolean) : []
  return list.length ? list : [...seen.values()].filter(s => /gpio|devkit/i.test(`${s.id} ${s.title}`)).slice(0, 1)
}

function Inspector({ rows, board, layoutState, mapState, checkState, onAssign }) {
  const view = sdk.useValue($view)
  const info = sdk.useValue($info)
  const sug = sdk.useValue($suggest)
  const gpio = view.selected
  const base = mapByGpio(mapState.env?.ok ? mapState.env.result : null)
  if (gpio === null || gpio === undefined) return h(InspectorIdle, { rows, checkState })
  const used = rows.find(r => r.pin === gpio) || null
  const entry = used && used.checked ? used : base.get(gpio) || null
  const infoRes = info.gpio === gpio && info.env?.ok ? info.env.result : null
  const verdict = used ? used.verdict : entry?.verdict ?? null
  const v = verdictMeta(verdict)
  const header = entry?.header || infoRes?.header || null
  const hs = splitHeader(header)
  const reason = mainReason(used && used.checked ? used : entry) || (infoRes?.rules || []).find(r => r.applies) || null
  const functions = infoRes?.functions || entry?.functions || []
  const sources = entrySources([checkState.env, mapState.env, info.env], [reason?.source_id, layoutState.layout?.source_id])
  const alts = used && verdict !== 'ok'
    ? (sug.role === used.role && sug.env?.ok ? suggestionChips(sug.env.result, used.role).map(s => s.gpio) : used.alternatives || [])
    : []
  const stampTone = verdict === 'blocked' ? 'bad' : verdict === 'caution' ? 'warn' : verdict === 'ok' ? (used ? 'active' : 'ok') : 'none'
  const stampText = verdict === 'ok' && !used ? 'FREE' : verdict === 'ok' ? 'ASSIGNED' : v.stamp
  const modes = infoRes?.modes && typeof infoRes.modes === 'object' ? Object.entries(infoRes.modes) : []
  const move = a => assignPin({ role: used.role, mode: used.mode, pin: a, net: used.net }).then(env => { if (env?.ok) selectPin(a) })
  // order: verdict, one sentence of reason, then the way out (alternatives as chips), then the details;
  // the source sits in the card foot
  return h('div', { className: `cb-card cb-insp-card cb-bracket${verdict === 'blocked' ? ' cb-bracket--bad' : ''}`, 'data-cb': 'inspector', 'data-cb-gpio': gpio },
    h('div', { className: 'cb-card-head' }, h(Label, null, `// inspector${hs ? ` · ${/^J\d+$/.test(hs.header) ? hs.header : `${hs.header} header,`} pin ${hs.n}` : ''}`),
      h('span', { className: 'cb-card-tools' },
        used ? [
          h('button', { key: 'e', type: 'button', className: 'cb-iconbtn', 'data-cb': 'edit-assignment', title: `Edit ${used.role}`,
            onClick: () => onAssign({ role: used.role, mode: used.mode, pin: used.pin, net: used.net || '' }) }, 'edit'),
          h('button', { key: 'u', type: 'button', className: 'cb-iconbtn', 'data-cb': 'unassign', title: `Remove ${used.role} from GPIO${gpio}`,
            onClick: () => unassignRole(used.role) }, 'unassign')
        ] : null,
        h('button', { type: 'button', className: 'cb-iconbtn', title: 'Close inspector', 'aria-label': 'Clear selection',
          onClick: () => selectPin(null) }, '✕'))),
    h('div', { className: 'cb-verdict' },
      h('span', { className: `cb-big cb-${verdict === 'ok' && used ? 'active' : v.tone === 'none' ? 'dim' : v.tone}` }, gpioName(gpio)),
      h(Stamp, { tone: stampTone, 'data-cb': 'verdict-stamp' }, `${stampText}${verdict && verdict !== 'ok' ? ` ${v.symbol}` : ''}`)),
    h('p', { className: 'cb-why', 'data-cb': 'inspector-why' },
      used ? [h('span', { key: 'a' }, verdict === 'blocked' ? 'Requested for ' : 'Assigned to '), h('b', { key: 'b' }, used.role), ' ',
        h('span', { key: 'm', className: 'cb-nowrap' }, `(${modeLabel(used.mode)}${used.net ? `, net ${used.net}` : ''}).`), ' ']
        : verdict === null ? 'Not checked yet. ' : verdict === 'ok' ? 'Free pin. ' : 'Free pin, with a finding. ',
      reason ? reason.message : verdict === 'ok' ? 'No findings for this board.' : verdict === null ? 'The pin map is not available.' : ''),
    alts.length ? h('div', { className: 'cb-insp-way', 'data-cb': 'insp-way' },
      h(Label, null, `use instead · ${modeLabel(used.mode)}`),
      h('div', { className: 'cb-alts', 'data-cb': 'alternatives' }, alts.map(a => h('button', { key: a, type: 'button', className: 'cb-chipbtn cb-altchip',
        'data-cb': `alt-${a}`, title: `Move ${used.role} to GPIO${a}`, 'aria-label': `Use GPIO${a} for ${used.role}`, onClick: () => move(a) },
      h(Glyph, { state: 'free', decorative: true }), h('span', null, 'Use '), h('b', null, `GPIO${a}`)))))
      : null,
    used && verdict !== 'ok' && !alts.length ? h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'suggest-one', title: `Find free pins for ${used.role} (pin rules, no hardware)`, onClick: () => suggestPins(rows, used.role) }, 'Suggest pins')) : null,
    used ? null : h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'assign-open', onClick: () => onAssign({ role: '', mode: 'out', pin: gpio, net: '' }) }, 'Assign role')),
    functions.length ? h('div', { className: 'cb-fn', 'data-cb': 'pin-functions' }, functions.map(f => h('span', { key: f, className: 'cb-tag' }, f))) : null,
    modes.length ? h(ModeSummary, { modes }) : null,
    h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources })))
}

/** Modes on this board, compact: one line when every mode has the same verdict, else only the exceptions. */
function ModeSummary({ modes }) {
  const groups = { ok: [], caution: [], blocked: [], other: [] }
  for (const [m, v] of modes) (groups[v] || groups.other).push(m)
  const line = (tone, sym, text, key) => h('div', { key, className: `cb-${tone}` }, `${sym} ${text}`)
  const all = (v, n) => n === modes.length
  const out = []
  if (all('blocked', groups.blocked.length)) out.push(line('bad', '✕', 'blocked in every mode', 'b'))
  else if (all('ok', groups.ok.length)) out.push(line('ok', '✓', 'ok in every mode', 'o'))
  else {
    if (groups.blocked.length) out.push(line('bad', '✕', groups.blocked.map(modeLabel).join(' · '), 'b'))
    if (groups.caution.length) out.push(line('warn', '!', groups.caution.map(modeLabel).join(' · '), 'c'))
    if (groups.ok.length) out.push(line('ok', '✓', groups.ok.length > 6 ? `${groups.ok.length} other modes ok` : groups.ok.map(modeLabel).join(' · '), 'o'))
  }
  return h('div', { className: 'cb-modes-sum', 'data-cb': 'pin-modes' }, h(Label, null, 'modes'), h('div', null, out))
}

function InspectorIdle({ rows, checkState }) {
  const env = checkState.env
  const c = countVerdicts(rows)
  return h('div', { className: 'cb-card cb-insp-card cb-bracket', 'data-cb': 'inspector-idle' },
    h('div', { className: 'cb-card-head' }, h(Label, null, '// inspector')),
    h('p', { className: 'cb-why' }, 'Select a pin on the board to see its verdict, functions and source.'),
    env?.ok ? h('p', { className: 'cb-dim', style: { margin: '8px 0 0', lineHeight: 1.6 } }, env.summary) : null,
    rows.length && !c.blocked && !c.caution ? h('p', { className: 'cb-ok', style: { margin: '8px 0 0' } }, `✓ All ${rows.length} assignments are ok for this board.`) : null,
    env?.ok ? h('div', { className: 'cb-card-foot' }, h(SourceLine, { sources: env.sources?.slice(0, 1) })) : null)
}

// --- 30-ui-kit.js
// Small UI primitives in own DOM (Bench Phosphor look; SDK components carry the app theme).

function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

function Label({ children, className, ...rest }) {
  return h('span', { className: cx('cb-label', className), ...rest }, children)
}

/** Button. kind: primary | ghost | quiet | warn | danger | agent. `agent` = an action Hermes carries out: active
 *  fill, the Hermes mark ◢ in front (aria-hidden), at most one per surface as the primary button. */
function Btn({ kind = 'primary', size, className, children, ...rest }) {
  return h('button', { type: 'button', className: cx('cb-btn', kind !== 'primary' && `cb-btn--${kind}`, size && `cb-btn--${size}`, className), ...rest },
    kind === 'agent' ? h('span', { className: 'cb-btn-mark', 'aria-hidden': 'true' }, '◢') : null, children)
}

/** Segmented control: options [{id, label, title?}] */
function Seg({ options, value, onChange, label, dataCb }) {
  return h('div', { className: 'cb-seg', role: 'group', 'aria-label': label, 'data-cb': dataCb },
    options.map(o => h('button', { key: o.id, type: 'button', 'aria-pressed': o.id === value ? 'true' : 'false', title: o.title,
      'data-cb-opt': o.id, onClick: () => { if (o.id !== value) onChange(o.id) } }, o.label)))
}

function Toggle({ checked, onChange, children, dataCb, title }) {
  return h('button', { type: 'button', role: 'switch', className: 'cb-switch', 'aria-checked': checked ? 'true' : 'false',
    'data-cb': dataCb, title, onClick: () => onChange(!checked) }, h('i', { 'aria-hidden': 'true' }), children)
}

function Stamp({ tone = 'bad', children, ...rest }) {
  return h('span', { className: cx('cb-stamp', tone !== 'bad' && `cb-stamp--${tone}`), ...rest }, children)
}

/** Station title: Hermes' DecodeText once per station change, plain text when the SDK lacks it. */
function DecodeTitle({ text, meta }) {
  const Decode = typeof sdk.DecodeText === 'function' ? sdk.DecodeText : null
  return h('div', { className: 'cb-title' },
    h('h1', { 'data-cb': 'station-title', 'aria-label': text },
      Decode ? h(Decode, { key: text, text, prefix: Math.max(0, text.indexOf('//') + 3), className: 'cb-decode', 'aria-hidden': 'true' })
        : h('span', { className: 'cb-decode' }, text),
      h('span', { className: 'cb-cursor', 'aria-hidden': 'true' })),
    meta ? h(Label, null, meta) : null)
}

/** Empty or error state: a clear sentence and the next step. One form for every station: kicker,
 *  title (with ✕ / ! for bad / warn, so the state is never colour alone), text, actions. */
function EmptyBox({ tone, kicker, title, children, actions, dataCb = 'empty' }) {
  const mark = tone === 'bad' ? '✕' : tone === 'warn' ? '!' : null
  return h('div', { className: cx('cb-empty', 'cb-bracket', tone && `cb-empty--${tone}`, tone === 'bad' && 'cb-bracket--bad'), 'data-cb': dataCb,
    role: tone === 'bad' ? 'alert' : undefined },
  kicker ? h(Label, null, kicker) : null,
  h('h2', null, mark ? h('span', { className: 'cb-empty-mark', 'aria-hidden': 'true' }, mark) : null, title),
  children,
  actions ? h('div', { className: 'cb-actions' }, actions) : null)
}

/** In-root modal (own DOM): focus moves into the dialog and stays there (Tab / Shift+Tab cycle), Escape closes
 *  it (document keydown, capture phase; only for keys inside the own Bench root or while the focus is lost to
 *  <body>, so the app's own keys keep working), the backdrop closes on a click. On close the
 *  focus returns to `returnFocus(root)` (e.g. the pin the dialog was about), else to the element that opened
 *  it, else to the station title — never to <body>. */
const MODAL_STACK = []

function focusablesIn(el) {
  if (!el) return []
  return [...el.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[href],[tabindex]:not([tabindex="-1"])')]
    .filter(n => n.tabIndex !== -1 && n.getClientRects().length > 0)
}

/** The own .cb-root around a node of ours (walks parentNode; never looks at app markup). */
function ownRoot(node) {
  for (let n = node; n; n = n.parentNode) if (n.classList?.contains('cb-root')) return n
  return null
}

function Modal({ title, onClose, children, footer, dataCb = 'modal', returnFocus = null, wide = false }) {
  const ref = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  const backRef = useRef(returnFocus)
  backRef.current = returnFocus
  useEffect(() => {
    if (typeof document === 'undefined') return undefined
    const prev = document.activeElement
    const dialog = ref.current
    const root = ownRoot(dialog) // own root (the dialog is rendered inside it)
    const token = {}
    MODAL_STACK.push(token)
    const first = dialog?.querySelector('input,select,textarea') || focusablesIn(dialog)[0]
    first?.focus?.()
    const onKey = e => {
      if (MODAL_STACK[MODAL_STACK.length - 1] !== token || !ref.current) return
      // only keys inside the own Bench root, or with the focus lost to <body>; the app's keys (chat composer) pass
      const active = document.activeElement
      const lost = !active || active === document.body
      const own = root ? ownRoot(e.target) === root : ref.current.contains(e.target)
      if (!own && !lost) return
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        closeRef.current?.()
        return
      }
      if (e.key !== 'Tab') return
      const list = focusablesIn(ref.current)
      if (!list.length) { e.preventDefault(); return }
      const inside = ref.current.contains(document.activeElement)
      const i = list.indexOf(document.activeElement)
      if (!inside || (e.shiftKey && i <= 0) || (!e.shiftKey && i === list.length - 1)) {
        e.preventDefault()
        ;(e.shiftKey ? list[list.length - 1] : list[0]).focus()
      }
    }
    // focus that leaves the dialog by a click elsewhere in the Bench comes back on the next Tab (above)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      const at = MODAL_STACK.indexOf(token)
      if (at >= 0) MODAL_STACK.splice(at, 1)
      const back = () => {
        const wanted = typeof backRef.current === 'function' ? backRef.current(root) : null
        const target = [wanted, prev && prev.isConnected && prev.tagName !== 'BODY' ? prev : null,
          root?.querySelector?.('[data-cb=station-title]')].find(n => n && n.isConnected && typeof n.focus === 'function')
        if (target) {
          if (target.matches?.('h1') && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
          try { target.focus({ preventScroll: true }) } catch { /* element gone */ }
        }
      }
      // after the re-render that follows the close (the opener may have been replaced)
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(back)
      else setTimeout(back, 0)
    }
  }, [])
  return h('div', { className: 'cb-modal-back', 'data-cb': 'modal-back', onMouseDown: e => { if (e.target === e.currentTarget) onClose() } },
    h('div', { className: `cb-modal cb-bracket${wide ? ' cb-modal--wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title, ref, 'data-cb': dataCb },
      h(Label, null, '// circuit bench'),
      h('h2', null, title),
      children,
      footer ? h('div', { className: 'cb-modal-foot' }, footer) : null))
}

/** Open a URL through the plugin OS door (ctx.os), never window.open on app markup. */
function openLink(url) {
  if (!url) return
  const os = CB.ctx?.os
  if (typeof os?.openExternal === 'function') os.openExternal(url)
  else if (typeof sdk.host?.openExternal === 'function') sdk.host.openExternal(url)
}

function sourceLabel(src) {
  if (!src) return ''
  const t = String(src.title || src.id || '').replace(/,?\s*GPIO & RTC GPIO/, ' · GPIO').replace(/\s*\(([^)]+)\)\s*$/, ' · $1')
  const cut = t.indexOf(', ')
  if (t.length <= 36 || cut < 0) return t
  // never cut an enumeration (E6, E12, E24)
  if (/^[A-Z]{0,2}\d+\b/.test(t.slice(cut + 2))) { const dot = t.indexOf(' · '); return dot > 0 ? t.slice(0, dot) : t }
  return t.slice(0, cut)
}

function SourceLine({ sources, ids }) {
  const list = (sources || []).filter(s => !ids || ids.includes(s.id))
  if (!list.length) return null
  return h('div', { className: 'cb-src', 'data-cb': 'src' },
    h('span', { className: 'cb-k' }, 'src ›'),
    h('span', { style: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 } },
      list.slice(0, 3).map(s => h('button', { key: s.id, type: 'button', title: `${s.title}\n${s.url || 'no URL (rule of thumb)'}\nretrieved ${s.retrieved || '—'}`,
        onClick: () => openLink(s.url) }, `${sourceLabel(s)}${s.url ? ' ↗' : ''}`))))
}

// ─── Station primitives ───────────────────────────────────────────────

/** Card with a comment-style label, optional step number and a right-side slot. */
function Section({ n, title, aside, children, tone, dataCb, className }) {
  return h('section', { className: cx('cb-card cb-sec', tone === 'bad' && 'cb-sec--bad', tone === 'active' && 'cb-sec--active', tone === 'ok' && 'cb-sec--ok', className), 'data-cb': dataCb },
    h('div', { className: 'cb-card-head' }, n ? h('span', { className: 'cb-secn', 'aria-hidden': 'true' }, n) : null, h(Label, null, `// ${title}`),
      aside ? h('span', { className: 'cb-sec-aside' }, aside) : null),
    children)
}

/** Labelled input with parsed-value hint or error (calculators, wiring parameters). */
function Field({ id, label, value, onChange, hint, error, placeholder, choice, dataCb, wide, onEnter, tail }) {
  const ref = useRef(null)
  useEffect(() => { // paths: show the end (the project folder), not the common prefix
    const el = ref.current
    if (tail && el && typeof document !== 'undefined' && document.activeElement !== el) el.scrollLeft = el.scrollWidth
  }, [tail, value])
  const control = choice
    ? h('select', { id, value, 'data-cb': dataCb, onChange: e => onChange(e.target.value) }, choice.map(c => h('option', { key: c, value: c }, c)))
    : h('input', { id, ref, value, placeholder, onBlur: tail ? e => { e.target.scrollLeft = e.target.scrollWidth } : undefined, 'data-cb': dataCb, autoComplete: 'off', spellCheck: false, 'aria-invalid': error ? 'true' : 'false', title: String(value || '').length > 24 ? value : undefined,
      onChange: e => onChange(e.target.value), onKeyDown: e => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter() } } })
  return h('div', { className: cx('cb-field', wide && 'cb-field--wide', error && 'cb-field--err') },
    h('label', { htmlFor: id }, label), control,
    h('span', { className: error ? 'cb-fhint cb-bad' : 'cb-fhint' }, error || hint || '\u00a0'))
}

/** Horizontal level bar (RAM/flash use, progress); pct null = indeterminate. */
function Bar({ pct, tone = 'active', label, dataCb }) {
  const ind = pct === null || pct === undefined
  return h('div', { className: cx('cb-bar', `cb-bar--${tone}`, ind && 'cb-bar--ind'), 'data-cb': dataCb, role: 'progressbar', 'aria-label': label,
    'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': ind ? undefined : Math.round(pct) },
  h('i', { style: ind ? undefined : { width: `${Math.max(0, Math.min(100, pct))}%` } }))
}

/** check status → symbol and tone (only `passed` counts as checked). */
function checkMark(status) {
  return status === 'passed' ? { s: '✓', t: 'ok' } : status === 'failed' ? { s: '✕', t: 'bad' } : status === 'skipped' ? { s: '○', t: 'dim' } : { s: '?', t: 'dim' }
}

function ChecksList({ checks, warnings, dataCb }) {
  const cs = checks || []
  const ws = warnings || []
  if (!cs.length && !ws.length) return null
  return h('div', { className: 'cb-checks', 'data-cb': dataCb },
    cs.map(c => { const m = checkMark(c.status); return h('div', { key: c.id, className: `cb-chk cb-${m.t}`, title: c.id }, h('span', { 'aria-hidden': 'true' }, m.s), h('span', null, c.detail || c.id)) }),
    ws.map(w => h('div', { key: w.code, className: `cb-chk ${w.severity === 'danger' ? 'cb-bad' : w.severity === 'caution' ? 'cb-warn' : 'cb-dim'}` },
      h('span', { 'aria-hidden': 'true' }, w.severity === 'info' ? 'i' : '!'), h('span', null, w.message))))
}

/** SIM badge: solid frame, diagonal stripes, the word SIMULATED always visible. The class
 *  cb-simban stays for the layout rules of HUD and console; ' BOARD' may give way in narrow tiles (cb-simban-w). */
function SimBadge({ compact, short, dataCb = 'sim-banner', title, className }) {
  // short: without BOARD
  return h('span', { className: cx('cb-simban', 'cb-simbadge', compact && 'cb-simbadge--sm', className), 'data-cb': dataCb, title: title || 'Simulated board: nothing physical is read or written' },
    h('span', { className: 'cb-simbadge-s', 'aria-hidden': 'true' }),
    h('span', { className: 'cb-simbadge-t' }, 'SIMULATED', short ? null : h('span', { className: 'cb-simban-w' }, ' BOARD')))
}

/** Former name; every call site gets the badge unchanged (same props, same data-cb defaults). */
const SimBanner = SimBadge

/** art attribute names (stroke-width …) → React SVG props (strokeWidth …). */
function kitSvgProps(attrs) {
  const out = {}
  for (const [k, v] of Object.entries(attrs)) out[/^(data|aria)-/.test(k) ? k : k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v
  return out
}

/** State symbol as inline SVG (lib/art.js shapes, colour = currentColor from .cb-glyph--<state>). role=img with the
 *  state word as label; `decorative` hides it when the word stands next to it. Unknown state → nothing. */
function Glyph({ state, size = 12, decorative = false, knock = 'var(--cb-ink)', className }) {
  const word = ART_STATE_WORDS[state]
  if (!word) return null
  return h('svg', { className: cx('cb-glyph', `cb-glyph--${state}`, className), width: size, height: size, viewBox: '0 0 12 12', focusable: 'false',
    'data-cb-state': state, ...(decorative ? { 'aria-hidden': 'true' } : { role: 'img', 'aria-label': word }) },
  artGlyphShapes(state, 6, 6, 'currentColor', knock).map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}

// --- 30-ui-panic.js
// PanicCard: stamp PANIC CAUGHT, reason, frames (#0 red), interpretation, Fix with Hermes / Open.
// Page console outside 06 DEBUG: PanicStrip.
// Shown while a panic is current: the serial stream shows no reboot into other firmware after it, or the project's
// stored panic is newer than the last successful flash (lib/crash.js, lib/serial.js).

function usePanicData(project) {
  const panic = sdk.useValue($panic)
  const serial = sdk.useValue($serial)
  const serialLive = serial.port && serial.buf.panic ? serialPanicLive(serial.buf, project) : false
  const projectLive = projectPanicCurrent(project)
  const live = serialLive || projectLive
  const last = project?.debug?.last_panic || null
  // a decode belongs to the serial panic it was made for, or to the stored panic (same log_ref)
  const env = panic.env?.ok && (panic.key === serial.buf.panic?.log_ref || panic.key === last?.log_ref || !last?.log_ref) ? panic.env : null
  const data = live ? panicCardData(env, projectLive ? last : null, serialLive ? serial.buf.panic : null) : null
  return { data, env, status: panic.status, live }
}

/** "Open src/main.cpp:44": reveal the source file of frame #0 in the file manager (ctx.os.revealPath).
 *  Only project-relative paths inside the firmware folder; core paths (~/.platformio, /…) are never opened. */
function sourceTarget(project, top) {
  const fwDir = project?.firmware?.dir || null
  const show = Boolean(top && top.file && top.file !== '??')
  const rel = show && !/^~|^\//.test(top.file) && !/(^|\/)\.\.(\/|$)/.test(top.file)
  const can = Boolean(rel && fwDir && typeof CB.ctx?.os?.revealPath === 'function')
  return { show, can, path: can ? `${fwDir.replace(/\/$/, '')}/${top.file}` : null, label: show ? `Open ${top.file}:${top.line ?? '?'}` : '',
    title: can ? `Show ${top.file} in the file manager` : !rel ? 'Only files inside the project firmware folder open from here' : 'Firmware folder unknown' }
}

async function openSource(src) {
  if (!src?.can) return false
  const ok = await CB.ctx.os.revealPath(src.path)
  if (ok === false) sdk.host?.notify?.({ kind: 'warning', title: 'Could not show the file', message: src.path })
  return ok !== false
}

async function fixWithHermes(project, data, env) {
  patchAtom($flow, { fixDraftAt: Date.now() })
  const decode = env || { summary: data?.summary || '', result: { reason: data?.reason, core: data?.core, frames: (data?.frames || []).map(f => ({ i: f.i, function: f.fn, file: f.file, line: f.line })) } }
  return composeDraft(fixWithHermesText(project, decode))
}

// Frame ↔ log coupling: a hovered or focused frame / register marks its address in the raw
// panic lines of the console log (lib/crash.js logMarkRanges). One mark for every surface; null = none.
const $logMark = sdk.atom(null)

function setLogMark(mark) {
  const cur = $logMark.get()
  if (!mark) { if (cur) $logMark.set(null); return }
  if (cur && cur.kind === mark.kind && cur.value === mark.value && cur.name === mark.name) return
  $logMark.set(mark)
}

/** Handlers for an element that marks `mark` in the log while hovered or focused. */
function logMarkProps(mark) {
  if (!mark?.value) return {}
  return { onMouseEnter: () => setLogMark(mark), onMouseLeave: () => setLogMark(null), onFocus: () => setLogMark(mark), onBlur: () => setLogMark(null) }
}

const frameMark = f => (f?.pc ? { kind: 'pc', value: f.pc } : null)

/** ELF check of the decode as text pieces (verdict, then the reason right behind it). */
function elfWords(elf) {
  return elf ? { sym: elf.symbol, word: elf.word || elf.status, reason: elf.reason || elf.detail || '' } : null
}

function PanicCard({ project }) {
  const { data, env, status } = usePanicData(project)
  const [busy, setBusy] = useState(false)
  if (!data) return null
  const src = sourceTarget(project, data.top)
  const fix = async () => {
    setBusy(true)
    try { await fixWithHermes(project, data, env) } finally { setBusy(false) }
  }
  return h('div', { className: 'cb-panic', 'data-cb': 'panic-card', 'data-cb-audit-root': 'panic', role: 'region', 'aria-label': 'Panic' },
    h('div', { className: 'cb-alarm' },
      h(Stamp, { tone: 'bad' }, 'PANIC CAUGHT'),
      h('span', { className: 'cb-bad' }, data.title),
      data.elf ? h('span', { className: `cb-elf cb-elf--${data.elf.tone}`, 'data-cb': 'elf-check', 'data-cb-status': data.elf.status, title: `elf check ${data.elf.word || data.elf.status} · ${data.elf.reason || data.elf.detail || ''}` },
        h('span', { 'aria-hidden': 'true' }, data.elf.symbol), ` elf ${elfWords(data.elf).word}`)
        : h(Label, null, status === 'loading' ? 'decoding…' : 'not decoded')),
    // no SIM tag of its own: the console bar beside the card carries the SIM badge
    data.frames.length ? h('div', { className: 'cb-frames', 'data-cb': 'panic-frames' }, data.frames.slice(0, 3).map((f, i) =>
      h('div', { key: f.i ?? i, className: `cb-frame${i === 0 ? ' cb-frame--top' : ''}`, title: `${f.pc} ${f.fn} — ${f.file}:${f.line ?? '?'}`,
        tabIndex: f.pc ? 0 : undefined, 'data-cb': `panic-card-frame-${f.i ?? i}`, ...logMarkProps(frameMark(f)) },
        h('span', { className: 'cb-i' }, `#${f.i ?? i}`), h('span', { className: 'cb-f' }, f.short),
        h('span', { className: 'cb-l' }, `${f.base}:${f.line ?? '?'}`)))) : null,
    data.interpretation.slice(-1).map(x => h('div', { key: x.code, className: 'cb-hint cb-panic-hint', style: { marginTop: 0 },
      title: [x.text, data.resetReason?.name ? `reset reason: ${data.resetReason.name} (${data.resetReason.code}, ${String(data.resetReason.when || '').replace(/_/g, ' ')})` : null].filter(Boolean).join('\n') }, x.text)),
    h('div', { className: 'cb-row cb-panic-actions' },
      h(Btn, { kind: 'agent', size: 'sm', onClick: fix, disabled: busy, 'data-cb': 'fix-with-hermes', title: 'Put a fix request into the chat composer (not sent)' }, busy ? 'Opening chat…' : 'Fix with Hermes'),
      src.show ? h(Btn, { kind: 'quiet', size: 'sm', disabled: !src.can, 'data-cb': 'open-source', title: src.title,
        onClick: () => openSource(src) }, `Open ${data.top.base}:${data.top.line ?? '?'}`) : null))
}

/** One-line panic strip, no agent button. Keeps data-cb=panic-card + .cb-panic-actions (smoke). */
function PanicStrip({ project }) {
  const { data } = usePanicData(project)
  if (!data) return null
  const top = data.top
  const at = top ? `${top.base}:${top.line ?? '?'}` : null
  return h('div', { className: 'cb-panicstrip', 'data-cb': 'panic-card', 'data-cb-form': 'strip', 'data-cb-audit-root': 'panic', role: 'status',
    'aria-label': `Panic: ${data.title}${at ? ` at ${at}` : ''}` },
  h('span', { className: 'cb-panicstrip-mark' }, h('span', { 'aria-hidden': 'true' }, '▲ '), 'PANIC'),
  h('span', { className: 'cb-panicstrip-t', title: [data.title, top ? `${top.fn} — ${top.file}:${top.line ?? '?'}` : ''].filter(Boolean).join('\n'), 'data-cb-truncate-ok': 'true' }, data.title,
    top ? h('span', { className: 'cb-panicstrip-at' }, ` · ${top.short} · ${at}`) : null),
  h('div', { className: 'cb-panic-actions' },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'panic-open-debug', title: 'Open 06 DEBUG: frames, registers, Fix with Hermes',
      onClick: () => goStation('debug') }, 'Open Debug ›')))
}

// --- 30-ui-rail.js
// StageRail: stations 01–06 with status, trace lines between them, provenance footer.

function StageRail({ project, rows, health, checkEnv }) {
  const nav = sdk.useValue($nav)
  const ui = sdk.useValue($ui)
  const bench = sdk.useValue($bench)
  const counts = countVerdicts(rows)
  const status = stageStatus(project, counts, ui.panicSeen, modCountWords(stageModCounts(checkEnv)))
  const solder = solderProgress(project)
  // Wow 4: one sweep over the stations when the fix loop closes (06 DEBUG sets sweepAt); reduced motion: no animation
  const sweeping = Boolean(ui.sweepAt) && Date.now() - ui.sweepAt < 2400
  useEffect(() => {
    if (!ui.sweepAt) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => patchAtom($ui, { sweepAt: 0 }), 2400)
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [ui.sweepAt])
  const tools = health?.tools || {}
  const toolNames = ['pio', 'esptool', 'addr2line']
  const toolsOk = toolNames.filter(t => tools[t]).length
  const rulesSrc = (checkEnv?.sources || []).find(s => /ESP-IDF/i.test(s.title || ''))
  const rules = rulesSrc ? (/ESP-IDF\s+v?[\d.]+/i.exec(rulesSrc.title) || [rulesSrc.title])[0] : null
  return h('nav', { className: 'cb-rail', 'aria-label': 'Bench stations', 'data-cb': 'rail', 'data-cb-audit-root': 'rail', 'data-cb-sweep': sweeping ? 'on' : undefined },
    h(Label, { className: 'cb-rail-label' }, '// workflow'),
    STATIONS.map((s, i) => {
      const st = status[s.id] || {}
      const word = shellRailWord(s.id, st, { project, counts, solder })
      return [
        // the trace between two stations lights up once the station above is done (state, not decoration)
        i ? h('div', { key: `t${s.id}`, className: 'cb-trace', 'aria-hidden': 'true', 'data-cb-done': status[STATIONS[i - 1].id]?.text === '[✓]' ? 'true' : undefined }) : null,
        h('button', { key: s.id, type: 'button', className: 'cb-stage', 'data-cb': `stage-${s.id}`, style: { '--cb-i': i },
          'aria-current': nav.station === s.id ? 'page' : undefined, 'data-cb-alert': st.alert ? 'true' : 'false', 'data-cb-tone': st.tone || 'faint',
          title: `${s.n} ${s.title}${word ? ` · ${word}` : ''}${st.detail ? ` · ${st.detail}` : ''}`, onClick: () => goStation(s.id) },
        h(StationIcon, { id: s.id }),
        h('span', { className: 'cb-stage-txt' },
          h('span', { className: 'cb-stage-l1' }, h('span', { className: 'cb-n' }, s.n), h('span', { className: 'cb-t' }, s.title)),
          word ? h('span', { className: 'cb-sw', 'data-cb': `stage-word-${s.id}` }, word) : null),
        h(RailMark, { text: st.text || '', tone: st.tone || 'faint' }))
      ]
    }),
    h('div', { className: 'cb-rail-foot', 'data-cb': 'rail-foot' },
      health ? h('div', { title: `circuit-bench ${health.version || ''} · Hermes ${health.hermes || ''}` },
        h('span', { className: 'cb-ok' }, '● '), `backend ${health.version || 'ok'}`)
        : h('div', null, h('span', { className: 'cb-bad' }, '○ '), 'backend offline'),
      health ? h('div', { title: toolNames.map(t => `${t}: ${tools[t] === true ? 'found' : tools[t] || 'missing'}`).join('\n') },
        h('span', { className: toolsOk === toolNames.length ? 'cb-ok' : 'cb-warn' }, '● '), `tools ${toolsOk}/${toolNames.length}`) : null,
      rules ? h('div', { title: `Pin rules: ${rulesSrc.title}` }, h('span', { className: 'cb-active' }, '● '), rules) : null,
      bench.mode === 'fixtures' ? h('div', { title: 'Development build with embedded fixtures' }, h('span', { className: 'cb-warn' }, '◌ '), 'fixture data') : null))
}

/** Rail status: glyph + number; the stageStatus text stays in the DOM (shellRailMark). */
function RailMark({ text, tone }) {
  const m = shellRailMark(text)
  const shapes = m.glyph === 'blocked' || m.glyph === 'caution' ? artGlyphShapes(m.glyph, 6, 6, 'currentColor') : shellMarkShapes(m.glyph, m.pct ?? 0)
  return h('span', { className: `cb-s cb-${tone}`, 'data-cb-mark': m.glyph || undefined },
    shapes.length ? h('svg', { className: 'cb-s-g', width: 12, height: 12, viewBox: '0 0 12 12', focusable: 'false', 'aria-hidden': 'true' },
      shapes.map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) }))) : null,
    m.num ? h('span', { className: 'cb-s-n' }, m.num) : null,
    m.code ? h('span', { className: 'cb-sr', 'aria-hidden': 'true' }, m.code) : null)
}

/** Station symbol (lib/art-shell.js shapes, 16 px, currentColor); decorative, the station name stands beside it. */
function StationIcon({ id }) {
  const shapes = shellStationShapes(id)
  if (!shapes.length) return h('span', { className: 'cb-stage-ic', 'aria-hidden': 'true' })
  return h('svg', { className: 'cb-stage-ic', width: 16, height: 16, viewBox: '0 0 16 16', focusable: 'false', 'aria-hidden': 'true', 'data-cb-icon': id },
    shapes.map(([tag, a], i) => h(tag, { key: i, ...kitSvgProps(a) })))
}

// --- 30-ui-stations.js
// Station registry + calm placeholders for 02–06 (later files set STATION_VIEWS.<id>).
//   STATION_VIEWS[id] = { component, inspector }  component({project, rows, ...}) renders main (+ aside when inspector)

const STATION_VIEWS = {}

const STATION_SOON = {
  calc: { what: 'LED, NPN switch, voltage divider and I²C pull-up calculators with formula, E-series value, assumptions and source.',
    next: 'Ask Hermes: “size the base resistor for an NPN switch”.' },
  wire: { what: 'Schematic per building block (SVG in bench colours) and the wiring table board ↔ part with net names.',
    next: 'Ask Hermes: “draw an NPN low-side switch on GPIO4”.' },
  solder: { what: 'One card per solder step, in order (flat → tall, robust → sensitive, connectors last), with polarity and heat warnings.',
    next: 'Ask Hermes: “plan the solder order for this project”.' },
  flash: { what: 'Board detection, build result (RAM/flash) and flashing with a confirmation dialog (port, MAC, firmware hash).',
    next: 'Nothing is flashed without your confirmation.' },
  debug: { what: 'Live serial stream, automatic panic detection, decoded frames (function, file:line) and the interpretation.',
    next: 'The console below already shows what the backend buffered.' }
}

function soonFacts(id, project) {
  if (!project) return []
  if (id === 'calc') return (project.calcs || []).map(c => ({ k: c.id, title: `${c.type} · ${c.id}`,
    text: Object.values(c.result || {}).map(q => formatQty(q)).join(' · ') || '—' }))
  if (id === 'wire') return (project.circuits || []).map(c => ({ k: c.id, title: `${c.block} · ${c.id}`,
    text: Object.entries(c.params || {}).map(([k, v]) => `${k} ${typeof v === 'number' ? formatSI(v, k.startsWith('r_') ? 'Ω' : '') : v}`).join(' · ') }))
  if (id === 'solder') {
    const sp = solderProgress(project)
    const done = new Set(project.solder?.done || [])
    return sp.total ? (project.solder.steps || []).slice(0, 8).map(s => ({ k: s.id, title: `${done.has(s.id) ? '[✓]' : '[ ]'} ${s.n} · ${s.kind}`,
      text: nbspUnits(s.action), tone: done.has(s.id) ? 'ok' : null })) : []
  }
  if (id === 'flash') {
    const fw = project.firmware || {}
    return [fw.last_build && { k: 'b', title: `build ${fw.last_build.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_build.at)}`,
      text: `RAM ${formatPct(fw.last_build.ram_pct)} · flash ${formatPct(fw.last_build.flash_pct)} · ${shortHash(fw.last_build.elf_sha256)}` },
    fw.last_flash && { k: 'f', title: `flash ${fw.last_flash.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_flash.at)}`,
      text: `${fw.last_flash.port} · ${shortHash(fw.last_flash.elf_sha256)}` }].filter(Boolean)
  }
  if (id === 'debug') {
    const p = project.debug?.last_panic
    return p ? [{ k: 'p', title: `last panic · ${formatClock(p.at)}`, text: `${p.reason} on core ${p.core} · ${p.top_frame}` }] : []
  }
  return []
}

function StationSoon({ station, project }) {
  const s = stationInfo(station)
  const soon = STATION_SOON[station] || { what: '', next: '' }
  const facts = soonFacts(station, project)
  return h('main', { className: 'cb-main cb-station', 'data-cb': `station-${station}`, key: station },
    h(DecodeTitle, { text: `${s.n} // ${s.heading}`, meta: 'read-only preview' }),
    h('p', { className: 'cb-why cb-dim', style: { maxWidth: '640px' } }, soon.what),
    station === 'solder' && solderProgress(project).total ? h('div', { className: 'cb-note', style: { marginTop: '14px', maxWidth: '640px' }, 'data-cb': 'solder-progress' },
      h(Label, null, 'progress'), h('b', { className: 'cb-fg' }, `${solderProgress(project).done}/${solderProgress(project).total}`),
      h('span', { className: 'cb-active', style: { letterSpacing: '-.05em' } }, cellBar(solderProgress(project).done, solderProgress(project).total, 12))) : null,
    facts.length ? [h(Label, { key: 'l', style: { display: 'block', marginTop: '16px' } }, '// from the project'),
      h('div', { key: 'g', className: 'cb-soon', 'data-cb': 'station-facts' }, facts.map(f => h('div', { key: f.k, className: 'cb-card' },
        h('b', { className: f.tone ? `cb-${f.tone}` : undefined }, f.title), f.text)))]
      : h(EmptyBox, { kicker: `// ${s.n} ${s.title.toLowerCase()}`, title: 'Nothing here yet', dataCb: 'station-empty' }, h('p', null, soon.next)))
}

// --- 40-station-plan.js
// Station 01 PLAN: chip/variant/DevKit/Wi-Fi → POST /pins/check, pin → inspector, suggest pins, assign via dialog,
// agent changes pulse the affected pins twice.

/** Native select for the toolbar, grouped (optgroups); the closed state shows the short label, the title the detail. */
function ToolSelect({ dataCb, label, value, groups, onChange, placeholder = null, title }) {
  return h('select', { className: 'cb-tsel', 'data-cb': dataCb, 'data-cb-kind': 'select', 'aria-label': label, value: value ?? '', title,
    onChange: e => { if (e.target.value) onChange(e.target.value) } },
  placeholder && !value ? h('option', { key: '-', value: '', disabled: true }, placeholder) : null,
  groups.map(g => h('optgroup', { key: g.label, label: g.label },
    g.options.map(o => h('option', { key: o.id, value: o.id, title: o.title }, o.label)))))
}

/** Module variant choice: a segmented control for up to three variants (ESP32, C6), else a dropdown grouped by PSRAM
 *  kind (S3: no / quad / octal PSRAM, 9 entries). Nothing chosen = "variant unknown" (WT32-S1, unconfirmed module). */
function VariantPicker({ chip, value, onChange }) {
  if (chip.variants.length <= 3) {
    return h(Seg, { label: 'Module variant', dataCb: 'seg-variant', value, options: chip.variants.map(v => ({ id: v.id, label: v.label, title: variantTitle(v) })), onChange })
  }
  const cur = variantInfo(chip.id, value)
  return h(ToolSelect, { dataCb: 'seg-variant', label: 'Module variant', value: cur?.id ?? null, placeholder: '? unknown', onChange,
    title: cur ? `${cur.label}: ${variantTitle(cur)}` : 'Module variant unknown',
    groups: variantGroups(chip.id).map(g => ({ label: g.label, options: g.variants.map(v => ({ id: v.id, label: v.label, title: variantTitle(v) })) })) })
}

/** "Suggest pins" (Hermes action): in the station's title row, so the toolbar fits one line. */
function SuggestPinsBtn({ rows }) {
  const sug = sdk.useValue($suggest)
  const problems = rows.filter(r => r.verdict === 'blocked' || r.verdict === 'caution')
  return h(Btn, { kind: 'agent', className: 'cb-push', 'data-cb': 'suggest-pins', disabled: sug.status === 'loading',
    title: problems.length ? `Find free pins for ${problems.map(p => p.role).join(', ')}` : 'All assigned pins are ok',
    onClick: () => suggestPins(rows) }, sug.status === 'loading' ? 'Suggesting…' : 'Suggest pins')
}

function PlanToolbar({ view }) {
  const chip = chipInfo(view.chip)
  const devkit = resolveDevkit(view.chip, view.devkit)
  const kit = devkitInfo(devkit)
  // CHIP, DEVKIT and MODULE in one line; short chip names, the full name is the title
  // DEVKIT: only the layouts in data/boards (DEVKITS), a dropdown grouped by chip (seven layouts); a DevKit
  // selects its chip and module variant (module.variant), a chip its default DevKit (CHIPS[].devkit)
  return [h('div', { key: 'tb', className: 'cb-toolbar', 'data-cb': 'plan-toolbar' },
    h('div', { className: 'cb-group', 'data-cb': 'group-chip' }, h(Label, null, 'chip'),
      h(Seg, { label: 'Chip', dataCb: 'seg-chip', value: view.chip, options: CHIPS.map(c => ({ id: c.id, label: c.label.replace(/^ESP32-/, ''), title: c.label })),
        onChange: id => setWhatIf({ chip: id }) })),
    h('div', { className: 'cb-group', 'data-cb': 'group-devkit' }, h(Label, null, 'devkit'),
      h(ToolSelect, { dataCb: 'seg-devkit', label: 'DevKit layout', value: devkit, placeholder: 'none',
        title: kit ? `${devkitTitle(kit)} header map (${chipInfo(kit.chip)?.label || kit.chip})` : 'No DevKit layout',
        groups: CHIPS.filter(c => devkitsOf(c.id).length).map(c => ({ label: c.label,
          options: devkitsOf(c.id).map(d => ({ id: d.id, label: d.label, title: `${devkitTitle(d)} header map (${c.label})` })) })),
        onChange: id => setWhatIf({ chip: devkitInfo(id)?.chip ?? view.chip, devkit: id }) })),
    chip?.variants.length ? h('div', { className: 'cb-group', 'data-cb': 'group-module' }, h(Label, null, 'module'),
      h(VariantPicker, { chip, value: view.variant, onChange: id => setWhatIf({ variant: id }) })) : null,
    h(Toggle, { checked: view.wifi, dataCb: 'toggle-wifi', title: 'Wi-Fi changes which ADC rules apply', onChange: on => setWhatIf({ wifi: on }) }, 'Wi-Fi'),
    // what-if line inside the toolbar: it shares a row with the controls when there is room, so a 2×22
    // DevKit stays above the console at 1280×800 too
    h(WhatIfLine, null))]
}

/** The view differs from the project board: say what the project has, apply or reset. */
function WhatIfLine() {
  const project = sdk.useValue($project)
  sdk.useValue($view)
  if (!isWhatIf()) return null
  const b = boardOf(project)
  const kit = devkitInfo(b.devkit)
  // compact: the project board stands in the HUD (board pill); the full text is the title and screen-reader text
  const text = `Project board: ${kit ? `${devkitTitle(kit)}, ` : ''}${chipInfo(b.chip)?.label || b.chip}${b.variant ? ` ${b.variant.toUpperCase()}` : ''}, Wi-Fi ${b.wifi ? 'on' : 'off'}.`
  return h('div', { className: 'cb-whatif', 'data-cb': 'whatif', role: 'status', title: `The pin map shows a what-if board. ${text}` },
  h('span', null, '◇ WHAT-IF'),
  h('span', { className: 'cb-sr', 'data-cb': 'whatif-project' }, text),
  h('span', { style: { marginLeft: 'auto', display: 'flex', gap: '8px' } },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'whatif-apply', title: 'Save this board to the project', onClick: () => applyBoardToProject() }, 'Apply to project'),
    h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'whatif-reset', title: 'Back to the project board', onClick: () => resetWhatIf() }, 'Reset')))
}

function StationPlan({ project, rows }) {
  const view = sdk.useValue($view)
  const board = sdk.useValue($board)
  const map = sdk.useValue($map)
  const check = sdk.useValue($check)
  const sug = sdk.useValue($suggest)
  const auto = useRef(null)
  useEffect(() => {
    if (check.status !== 'ready' || auto.current === check.key) return
    auto.current = check.key
    if (view.selected === null) {
      const first = rows.find(r => r.verdict === 'blocked') || rows.find(r => r.verdict === 'caution')
      if (first) selectPin(first.pin)
    }
  }, [check.key, check.status])
  const opts = project?.options || {}
  const meta = [`wi-fi ${view.wifi ? 'on' : 'off'}`, opts.framework, opts.logic_v ? `${opts.logic_v} v logic` : null].filter(Boolean).join(' · ')
  const suggestPinsList = sug.status === 'ready' && sug.env?.ok ? suggestionChips(sug.env.result, sug.role).map(s => s.gpio) : []
  const onAssign = init => patchAtom($ui, { modal: { type: 'assign', init } })
  const b = viewBoard()
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-plan' },
      h('div', { className: 'cb-planhead' }, h(DecodeTitle, { text: '01 // PIN MAP', meta }),
        h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'add-module', 'aria-haspopup': 'dialog', title: 'Add a sensor, display or driver module from the catalog',
          onClick: () => openModules() }, '+ Add module'), h(SuggestPinsBtn, { rows })),
      h(PlanToolbar, { view }),
      board.status === 'ready' ? h(BoardWarnings, { layout: board.layout, sources: board.sources, compact: true }) : null,
      h(BoardView, { layoutState: board, mapState: map, rows, board: b, selected: view.selected, suggestPins: suggestPinsList, onSelect: selectPin }),
      // legend as the board's caption
      board.status === 'ready' ? h(Legend, { key: 'lg', className: 'cb-legend--cap', suggesting: suggestPinsList.length > 0, kinds: layoutKinds(board.layout) }) : null,
      map.status === 'error' ? h('div', { className: 'cb-note cb-note--warn', style: { marginTop: '12px' }, 'data-cb': 'map-error' },
        '! Pin map unavailable — free pins show as “not checked”.', h('span', { className: 'cb-dim' }, map.env?.error?.message || '')) : null),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' },
      board.status === 'ready' ? h(BoardWarnings, { layout: board.layout, sources: board.sources }) : null,
      h(Inspector, { rows, board: b, layoutState: board, mapState: map, checkState: check, onAssign }),
      h(BusPanel, null),
      h(AssignmentTable, { rows, checkState: check, onAssign }))
  ]
}

/** Pin kinds present on the layout (legend entries for signal / nc only where they exist). */
function layoutKinds(layout) {
  const { left, right } = headerRows(layout)
  return [...new Set([...left, ...right].map(p => p.kind))]
}

STATION_VIEWS.plan = { component: StationPlan, inspector: true }

// --- 41-station-calc.js
// Station 02 CALC: calculator cards; inputs parse as you type (4k7, 10mA, 3V3), the backend computes, every number is
// a `display` text of the answer. Card: mini schematic (art-calc), headline in its worst check's tone, bands
// (calcBands), check chips, formula steps, assumptions drawer, sources foot; same action row, equal row heights.
// Module catalog: groups from GET /calc (`basics` default; others generic cards).

/** Calculator input with the unit inside the field (V, A, Ω, F, °C) and the parsed value as the hint below. */
function CalcField({ def, f, value, onChange, hint, error, onEnter }) {
  const id = `cb-${def.type}-${f.name}`
  // the unit shows in the field unless the typed text already carries it (10mA, 3V3, 100pF): never twice
  const unit = f.suffix || (f.unit && !calcTypedUnit(value, f.unit) ? f.unit : '')
  const control = f.choice
    ? h('select', { id, value, 'data-cb': `in-${def.type}-${f.name}`, onChange: e => onChange(e.target.value) }, f.choice.map(c => h('option', { key: c, value: c }, c || '—')))
    : h('input', { id, value, 'data-cb': `in-${def.type}-${f.name}`, autoComplete: 'off', spellCheck: false, 'aria-invalid': error ? 'true' : 'false',
      'aria-describedby': unit ? `${id}-u` : undefined, title: String(value || '').length > 12 ? value : undefined,
      onChange: e => onChange(e.target.value), onKeyDown: e => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter() } } })
  return h('div', { className: cx('cb-field', 'cb-calc-field', error && 'cb-field--err') },
    h('label', { htmlFor: id }, f.label),
    h('span', { className: cx('cb-calc-box', unit && !f.choice && 'cb-calc-box--unit') }, control,
      unit && !f.choice ? h('span', { className: 'cb-calc-unit', id: `${id}-u` }, unit) : null),
    h('span', { className: error ? 'cb-fhint cb-calc-hint cb-bad' : 'cb-fhint cb-calc-hint' }, error || hint || '\u00a0'))
}

/** Ruler exact → chosen E-series value, the deviation on the arrow. */
function CalcRuler({ b, type, tone }) {
  return h('div', { className: cx('cb-calc-ruler', b.down && 'cb-calc-ruler--down'), 'data-cb': `calc-ruler-${type}` },
    h('span', { className: 'cb-calc-rend' }, h('small', null, b.from.label), h('b', null, nbspUnits(b.from.display))),
    h('span', { className: 'cb-calc-rtrack' }, h('i', { 'aria-hidden': 'true' }),
      b.delta ? h('em', { 'data-cb': 'calc-dev', title: 'deviation of the chosen value from the exact one' }, nbspUnits(b.delta)) : null),
    h('span', { className: 'cb-calc-rend cb-calc-rend--to' }, h('small', null, b.to.label), h('b', { className: `cb-${tone}` }, nbspUnits(b.to.display))))
}

/** A value against its limit: label, value, limit, track (only when the position can be drawn), note from the answer. */
function CalcMeter({ b, type }) {
  return h('div', { className: 'cb-calc-meter', 'data-cb': `calc-meter-${type}-${b.id}`, 'data-cb-check': b.status || undefined },
    h('div', { className: 'cb-calc-mhead' },
      h('span', { className: 'cb-calc-mk' }, b.label),
      h('b', { className: `cb-${b.tone}` }, nbspUnits(b.value)),
      h('span', { className: 'cb-calc-mlim' }, `${b.limitLabel} `, h('b', null, nbspUnits(b.limit)))),
    b.frac !== null && b.frac !== undefined ? h('div', { className: 'cb-calc-mtrack', 'aria-hidden': 'true' },
      h('i', { className: `cb-calc-mfill cb-calc-mfill--${b.tone}`, style: { width: `${(b.frac * 100).toFixed(1)}%` } })) : null,
    b.start ? h('div', { className: 'cb-calc-mscale' }, h('span', null, `from T_A ${b.start}`.replace(/(\d) (?=°C)/g, '$1\u00a0')), h('span', null, `max ${b.limit}`.replace(/(\d) (?=°C)/g, '$1\u00a0'))) : null,
    b.note ? h('p', { className: 'cb-calc-mnote' }, h('span', { className: 'cb-fg' }, `${b.note.lead} ${nbspUnits(b.note.value)}`),
      b.note.reason ? h('span', null, ` · ${b.note.reason}`) : null) : null)
}

/** I²C window R_min … R_max with the suggested value marked on the track. */
function CalcWindow({ b, type }) {
  return h('div', { className: 'cb-calc-window', 'data-cb': `calc-window-${type}`, 'data-cb-check': b.status || undefined },
    h('div', { className: 'cb-calc-wtrack', 'aria-hidden': 'true' }, h('i', { className: `cb-calc-wbar cb-calc-mfill--${b.tone}` }),
      b.frac !== null && b.frac !== undefined ? h('span', { className: 'cb-calc-wmark', style: { left: `${(b.frac * 100).toFixed(1)}%` } }) : null),
    h('div', { className: 'cb-calc-wscale' },
      h('span', null, h('small', null, `${b.min.label} `), h('b', null, nbspUnits(b.min.display))),
      h('span', { className: 'cb-calc-wmid' }, h('small', null, '▲ '), h('b', { className: `cb-${b.tone}` }, nbspUnits(b.mark))),
      h('span', { className: 'cb-calc-wend' }, h('small', null, `${b.max.label} `), h('b', null, nbspUnits(b.max.display)))))
}

/** Headline: label, the big value in the tone of its worst check, the verdict as symbol + words, the bands. */
function CalcReadout({ def, v, env, bands }) {
  const worst = worstCheck(env.checks)
  const tone = valueTone(env.checks)
  const verdict = calcVerdict(env.checks)
  return h('div', { className: 'cb-calc-readout', 'data-cb': `calc-result-${def.type}` },
    h('div', { className: 'cb-calc-main' },
      h(Label, null, v.mainLabel),
      h('b', { className: `cb-calc-big cb-${tone}`, 'data-cb': `calc-value-${def.type}`, 'data-cb-check': worst || 'none',
        title: { failed: 'A check failed: see below', not_checked: 'Not every check could be made: see below', passed: 'All checks passed' }[worst] || 'No checks for this value' }, nbspUnits(v.main.display)),
      verdict ? h('span', { className: `cb-calc-verdict cb-${verdict[2]}` }, h('span', { 'aria-hidden': 'true' }, verdict[0]), ` ${verdict[1]}`) : null),
    bands.map(b => b.kind === 'ruler' ? h(CalcRuler, { key: b.id, b, type: def.type, tone })
      : b.kind === 'meter' ? h(CalcMeter, { key: b.id, b, type: def.type })
        : b.kind === 'window' ? h(CalcWindow, { key: b.id, b, type: def.type }) : null))
}

/** Checks as chips; failed and not-checked ones also with their detail line (the passed details are in the formula
 *  drawer). Warnings below with their severity word. */
function CalcChecks({ def, chips, warnings }) {
  const ws = (Array.isArray(warnings) ? warnings : []).filter(w => w && w.message)
  const open = chips.filter(c => c.status !== 'passed' && c.detail)
  if (!chips.length && !ws.length) return null
  const sev = w => (w.severity === 'danger' ? ['!', 'danger', 'bad'] : w.severity === 'caution' ? ['!', 'caution', 'warn'] : ['i', 'note', 'dim'])
  return h('div', { className: 'cb-calc-checks', 'data-cb': `calc-checks-${def.type}` },
    chips.length ? h('div', { className: 'cb-calc-chips' }, chips.map(c => h('span', { key: c.id, className: `cb-calc-chip cb-calc-chip--${c.tone}`,
      'data-cb-check-status': c.status, title: c.detail || c.id },
    h('span', { className: 'cb-calc-chip-s', 'aria-hidden': 'true' }, c.sym), h('span', null, c.name), h('b', null, c.word)))) : null,
    open.map(c => h('p', { key: c.id, className: `cb-calc-chkd cb-${c.tone === 'dim' ? 'dim' : c.tone}` }, h('span', { 'aria-hidden': 'true' }, `${c.sym} `), `${c.name}: `, nbspUnits(c.detail))),
    ws.map((w, i) => {
      const [s, word, tone] = sev(w)
      return h('p', { key: w.code || i, className: `cb-calc-warnl cb-calc-warnl--${tone}` }, h('b', { className: `cb-${tone}` }, h('span', { 'aria-hidden': 'true' }, `${s} `), word), h('span', null, nbspUnits(w.message)))
    }))
}

/** Formula drawer: the equations one per line, the steps as a table (name, expression, value), the passed checks. */
function CalcFormula({ def, v, chips, open, setOpen }) {
  const lines = calcFormulaLines(v.formula)
  const steps = calcSteps(v.steps)
  const passed = chips.filter(c => c.status === 'passed' && c.detail)
  if (!lines.length && !steps.length) return null
  return h('details', { className: 'cb-formula cb-calc-drawer', open, onToggle: e => setOpen(e.currentTarget.open), 'data-cb': `calc-formula-${def.type}` },
    h('summary', null, h(Label, null, steps.length ? `formula · ${steps.length} steps` : 'formula')),
    lines.length ? h('div', { className: 'cb-calc-eqs' }, lines.map((l, i) => h('code', { key: i }, nbspUnits(l)))) : null,
    steps.length ? h('table', { className: 'cb-calc-steps', 'data-cb': `calc-steps-${def.type}` },
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'step'), h('th', { scope: 'col' }, 'expression'), h('th', { scope: 'col', className: 'cb-r' }, 'value'))),
      h('tbody', null, steps.map((s, i) => h('tr', { key: i }, h('th', { scope: 'row' }, s.name), h('td', null, nbspUnits(s.expr)), h('td', { className: 'cb-r' }, nbspUnits(s.value)))))) : null,
    passed.length ? h('div', { className: 'cb-calc-passed' }, h(Label, null, 'checks passed'),
      passed.map(c => h('p', { key: c.id, className: 'cb-calc-chkd' }, h('span', { className: 'cb-ok', 'aria-hidden': 'true' }, '✓ '), h('span', { className: 'cb-fg' }, `${c.name}: `), nbspUnits(c.detail)))) : null)
}

/** Assumptions drawer: the keys already in the summary, key / value / reason inside. */
function CalcAssumptions({ def, items }) {
  const list = (Array.isArray(items) ? items : []).filter(a => a && a.key)
  if (!list.length) return null
  return h('details', { className: 'cb-assume cb-calc-drawer', 'data-cb': `calc-assume-${def.type}` },
    h('summary', null, h(Label, null, `assumptions · ${list.length}`), h('span', { className: 'cb-calc-akeys' }, list.map(a => a.key).join(' · '))),
    h('dl', { className: 'cb-calc-alist' }, list.map(a => [
      h('dt', { key: `${a.key}-k` }, a.key),
      h('dd', { key: `${a.key}-v` }, h('span', { className: 'cb-fg' }, nbspUnits(a.value ?? '')), a.reason ? h('span', null, ` — ${a.reason}`) : null)])))
}

/** Fixed card foot: the sources of the answer, full labels (never cut), a link where the source has a URL. */
function CalcFoot({ sources, state }) {
  const list = (Array.isArray(sources) ? sources : []).filter(s => s && s.id)
  return h('footer', { className: 'cb-calc-foot', 'data-cb': 'calc-src' },
    h('span', { className: 'cb-k' }, 'src ›'),
    list.length
      ? h('span', { className: 'cb-calc-srcs' }, list.map(s => s.url
        ? h('button', { key: s.id, type: 'button', title: `${s.title}\n${s.url}\nretrieved ${s.retrieved || '—'}`, onClick: () => openLink(s.url) }, `${sourceLabel(s)} ↗`)
        : h('span', { key: s.id, className: 'cb-calc-src0', title: `${s.title}\nretrieved ${s.retrieved || '—'}` }, sourceLabel(s))))
      : h('span', { className: 'cb-dim' }, state === 'stored' ? 'stored result · Calculate again for its sources' : 'the sources come with the result'))
}

function CalcCard({ def, project, stored }) {
  const st = sdk.useValue($calcs)[def.type] || { status: 'idle', env: null }
  const [form, setForm] = useState(() => initialForm(def, stored))
  const [errors, setErrors] = useState({})
  const [open, setOpen] = useState(false)
  const env = st.env || (stored ? { ok: true, summary: stored.result?.summary || '', result: { ...stored.result, inputs: stored.inputs }, checks: stored.result?.checks || [],
    warnings: [], assumptions: stored.assumptions || [], sources: [], fromProject: true } : null)
  const v = calcView(def, env)
  const run = () => {
    const b = buildCalcBody(def, form, parseQuantity)
    setErrors(b.errors)
    if (b.ok) runCalc(def.type, b.body)
  }
  const set = name => val => { setForm(f => ({ ...f, [name]: val })); if (errors[name] || errors._need) setErrors(e => ({ ...e, [name]: null, _need: null })) }
  const hintOf = f => {
    if (f.choice || f.text) return ''
    if (f.temp) {
      const t = parseTempC(form[f.name])
      return t.ok ? `= ${t.value} °C` : t.empty ? 'optional' : ''
    }
    const q = parseQuantity(calcPlainText(f, form[f.name]), f.unit)
    return q.ok ? `= ${formatSI(q.value, f.unit)}${f.suffix ? ` ${f.suffix}` : ''}` : q.empty ? (f.required ? 'required' : 'optional') : ''
  }
  const live = env && !env.fromProject
  const savedAs = live && env.ok ? null : stored?.id
  const tone = v.ok ? valueTone(env.checks) : 'fg'
  const art = calcArt(def.type, v.ok ? env : null, { tone })
  const bands = v.ok ? calcBands(def, env) : []
  const shown = new Set([...(art?.shown || []), ...bands.flatMap(b => b.keys)])
  const rows = v.ok ? v.rows.filter(r => !shown.has(r.k)) : []
  const chips = v.ok ? calcChips(env.checks) : []
  const loading = st.status === 'loading'
  return h('section', { className: cx('cb-card cb-calc', def.generic && 'cb-calc--gen'), 'data-cb': `calc-${def.type}`, 'data-cb-status': st.status,
    'data-cb-generic': def.generic ? 'true' : undefined },
    h('div', { className: 'cb-card-head' }, h('span', { className: 'cb-secn' }, def.short), h(Label, null, `// ${def.title}`),
      savedAs ? h('span', { className: 'cb-tag cb-push', title: 'Stored in the project' }, savedAs) : null),
    def.summary ? h('p', { className: 'cb-calc-sum', 'data-cb': `calc-sum-${def.type}` }, nbspUnits(def.summary)) : null,
    h('div', { className: 'cb-calc-top' },
      art ? h('div', { className: 'cb-calc-fig', role: 'img', 'aria-label': art.label, 'data-cb': `calc-art-${def.type}`, dangerouslySetInnerHTML: { __html: art.svg } }) : null,
      v.ok ? h(CalcReadout, { def, v, env, bands })
        : h('div', { className: 'cb-calc-readout cb-calc-readout--idle', 'data-cb': `calc-idle-${def.type}` },
          h(Label, null, v.mainLabel || 'result'),
          h('p', null, loading ? 'Calculating…' : 'Not calculated yet. Set the values and press Calculate.')),
      v.ok ? h('div', { className: 'cb-calc-meas', 'data-cb': `calc-meas-${def.type}` },
        h(CalcChecks, { def, chips, warnings: env.warnings }),
        rows.length || v.hfe ? h('div', { className: 'cb-kv cb-kv--calc' }, rows.map(r => [h('span', { key: `${r.k}l` }, r.label), h('b', { key: `${r.k}v` }, nbspUnits(r.q.display))]),
          v.hfe ? [h('span', { key: 'hl' }, 'hFE min'), h('b', { key: 'hv', title: v.hfe.conditions || '' }, `${v.hfe.value}${v.hfe.part ? ` (${v.hfe.part} datasheet)` : ''}`)] : null) : null) : null),
    h('div', { className: 'cb-calc-in' }, def.fields.map(f => h(CalcField, { key: f.name, def, f, value: form[f.name], onChange: set(f.name), hint: hintOf(f),
      error: errors[f.name] && errors[f.name] !== 'required' ? errors[f.name] : errors[f.name] ? 'required' : null, onEnter: run }))),
    def.oneOf ? h('div', { className: cx('cb-jobline', errors._need ? 'cb-bad' : 'cb-dim'), role: errors._need ? 'alert' : undefined,
      'data-cb': `calc-need-${def.type}` }, `${errors._need ? '✕ ' : ''}${calcNeedText(def)}`) : null,
    h('div', { className: 'cb-actions cb-calc-acts' },
      h(Btn, { size: 'sm', 'data-cb': `calc-run-${def.type}`, disabled: loading, onClick: run }, loading ? 'Calculating…' : 'Calculate'),
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': `calc-add-${def.type}`, disabled: !(live && env.ok && v.ok) || !project,
        title: live && env.ok ? 'Store the calculation and its parts in the project' : 'Calculate first, then store the result in the project',
        onClick: () => addCalcToProject(def.type) }, 'Add to project')),
    env && !env.ok ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': `calc-error-${def.type}` }, `✕ ${env.error?.message || env.summary}`,
      env.error?.hint ? h('span', { className: 'cb-dim' }, env.error.hint) : null) : null,
    v.ok ? h('div', { className: 'cb-calc-out', 'data-cb': `calc-detail-${def.type}` },
      h(CalcFormula, { def, v, chips, open, setOpen }),
      h(CalcAssumptions, { def, items: env.assumptions })) : null,
    h(CalcFoot, { sources: v.ok ? env.sources : null, state: v.ok && env.fromProject ? 'stored' : 'idle' }))
}

/** Group pick only with more than one group. */
function StationCalc({ project }) {
  const calcs = project?.calcs || []
  const storedOf = type => [...calcs].reverse().find(c => c.type === type) || null
  const meta = useCalcMeta()
  const groups = calcGroups(meta.list, meta.env?.result?.groups)
  const [groupId, setGroup] = useState('basics')
  const group = groups.find(g => g.id === groupId) || groups[0]
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-calc', 'data-cb-audit-root': 'station' },
      h(DecodeTitle, { text: '02 // CALCULATORS', meta: 'computed by the bench backend · units like 4k7, 10mA, 3V3' }),
      groups.length > 1 ? h('div', { className: 'cb-toolbar' }, h('div', { className: 'cb-group cb-group--calc' }, h(Label, null, 'group'),
        h(Seg, { label: 'Calculator group', dataCb: 'seg-calc-group', value: group.id, onChange: setGroup,
          options: groups.map(g => ({ id: g.id, label: `${g.id} · ${g.defs.length}`, title: g.defs.map(d => d.title).join(', ') })) }))) : null,
      h('div', { className: 'cb-calcgrid', 'data-cb': 'calc-grid', 'data-cb-group': group.id },
        group.defs.map(d => h(CalcCard, { key: `${d.type}-${project?.id || ''}`, def: calcApplyMeta(d, calcRawMeta(meta.env, d.type)), project, stored: storedOf(d.type) })))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'data-cb-audit-root': 'inspector', 'aria-label': 'Inspector' }, h(BomCard, { project }))
  ]
}

/** Calculations and parts in the project (BOM). A part is removed in two clicks (✕, then Remove in the row);
 *  its calculation stays, a solder plan that names it shows as out of date in 04 SOLDER. */
function BomCard({ project }) {
  const parts = project?.parts || []
  const calcs = project?.calcs || []
  const [asking, setAsking] = useState(null)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const remove = async ref => {
    setBusy(true)
    setFail(null)
    const env = await removePartsFromProject([ref])
    setBusy(false)
    setAsking(null)
    if (env && !env.ok) {
      setFail(env.error?.code === 'project_conflict' ? 'The project changed meanwhile and was reloaded. Check the list and try again.'
        : env.error?.message || env.summary || 'Not removed.')
    }
  }
  const partRow = p => asking === p.ref
    ? h('tr', { key: p.ref, 'data-cb': 'part-row', 'data-cb-ref': p.ref, className: 'cb-part-ask' },
      h('td', { className: 'cb-warn', colSpan: 2 }, `Remove ${p.ref}?`),
      h('td', { className: 'cb-r', colSpan: 2 },
        h('span', { className: 'cb-part-acts' },
          h(Btn, { kind: 'quiet', size: 'sm', onClick: () => setAsking(null), disabled: busy }, 'Keep'),
          h(Btn, { kind: 'danger', size: 'sm', 'data-cb': 'part-remove-confirm', disabled: busy, onClick: () => remove(p.ref) }, busy ? 'Removing…' : 'Remove'))))
    : h('tr', { key: p.ref, 'data-cb': 'part-row', 'data-cb-ref': p.ref },
      h('td', { className: 'cb-fg' }, p.ref), h('td', null, nbspUnits(p.value)), h('td', { className: 'cb-r cb-dim' }, p.from_calc || p.kind),
      h('td', { className: 'cb-r cb-part-x' }, h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'part-remove', disabled: busy,
        'aria-label': `Remove ${p.ref} from the project`, title: `Remove ${p.ref} from the project`, onClick: () => setAsking(p.ref) }, '✕')))
  return [
    h('div', { key: 'c', className: 'cb-card', 'data-cb': 'project-calcs' },
      h('div', { className: 'cb-card-head' }, h(Label, null, '// calculations'), h(Label, null, `${calcs.length}`)),
      calcs.length ? h('table', { className: 'cb-table' }, h('tbody', null, calcs.map(c => {
        const r = c.result || {}
        const main = r.r_chosen || r.i_b || r.v_out_max || r.suggested || r.p_loss || r.p_total || calcResultRows(r)[0]?.q
        const tone = valueTone(r.checks)
        return h('tr', { key: c.id }, h('td', { className: 'cb-fg' }, c.id), h('td', { className: 'cb-dim' }, c.type),
          h('td', { className: `cb-r cb-${tone}`, title: { bad: 'a check failed', ok: 'all checks passed' }[tone] || 'not every check made' },
            tone === 'bad' ? h('span', { 'aria-hidden': 'true' }, '✕ ') : null, nbspUnits(main?.display || '—')))
      }))) : h('p', { className: 'cb-why cb-dim' }, 'No calculations stored yet. “Add to project” keeps one with its parts.')),
    h('div', { key: 'p', className: 'cb-card', 'data-cb': 'project-parts' },
      h('div', { className: 'cb-card-head' }, h(Label, null, '// parts'), h(Label, null, `${parts.length}`)),
      parts.length ? h('table', { className: 'cb-table' }, h('tbody', null, parts.map(partRow))) : h('p', { className: 'cb-why cb-dim' }, 'No parts yet.'),
      fail ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'part-remove-error' }, `✕ ${fail}`) : null)
  ]
}

STATION_VIEWS.calc = { component: StationCalc, inspector: true }

// --- 42-station-wire.js
// Station 03 WIRE: building block + parameters → POST /schematic, the SVG inline in bench colours (currentColor),
// wiring table; hovering a part, a net (wire, port, net label) or a table row highlights the same thing in the plan
// and in the tables; Save SVG via ctx.files (when the host has it) or a Blob download.
// Stroke widths and net colours come from the backend's data-kind / data-net attributes
// (15-styles-wire.js); the plan is fitted and centred, never below scale 1 (text ≥ 10 px), Save SVG sits in the
// plan's header, danger/caution warnings are warning cards under the parts.
// Module catalog: grouped block pick; the module block draws a module part of the project.

function fmtParam(v, unit) {
  return formatSI(v, '').replace(/\s+/g, '')
}

async function saveSvg(svg, name) {
  const files = CB.ctx?.files
  if (files && typeof files.requestFolder === 'function' && typeof files.writeText === 'function') {
    const pick = await files.requestFolder()
    if (!pick?.ok || !pick.folder) return pick?.ok ? 'cancelled' : 'failed'
    const res = await files.writeText(pick.folder.id, name, svg)
    if (res?.ok) { setNotice(`Saved ${name} in ${pick.folder.name}.`, 'ok'); return 'files' }
    setNotice(res?.message || 'Could not save the SVG.', 'bad')
    return 'failed'
  }
  if (typeof Blob === 'undefined' || typeof URL?.createObjectURL !== 'function' || typeof document === 'undefined') return 'failed'
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.rel = 'noopener'
  a.click() // a detached anchor with `download` saves the file (own element, no app markup)
  timersOf(CB.ctx).setTimeout(() => URL.revokeObjectURL(url), 2000)
  return 'download'
}

// the blocks the backend knows, asked once (catalogue route if the API has one, else the hint of a
// render without a block); no names (fixtures, older backends) = the four base blocks.
const $wireBlocks = sdk.atom({ status: 'idle', names: null, env: null })

async function loadWireBlocks() {
  if ($wireBlocks.get().status !== 'idle') return
  $wireBlocks.set({ status: 'loading', names: null, env: null })
  const env = typeof CB.api?.schematicBlocks === 'function' ? await CB.api.schematicBlocks() : await CB.api.schematic({})
  $wireBlocks.set({ status: 'ready', names: wireBlockNames(env), env: env?.ok && Array.isArray(env.result?.blocks) ? env : null })
}

/** Block pick: one Seg per group inside [data-cb=seg-block]; one group = the plain Seg as before. */
function WireBlockPick({ groups, value, onChange }) {
  const seg = (g, dataCb) => h(Seg, { key: g.id, label: groups.length > 1 ? `Building block · ${g.id}` : 'Building block', dataCb, value,
    options: g.blocks.map(b => ({ id: b.block, label: b.block.replace(/_/g, ' '), title: b.title })), onChange })
  if (groups.length < 2) return seg(groups[0] || { id: 'basic', blocks: [] }, 'seg-block')
  return h('div', { className: 'cb-wblocks', 'data-cb': 'seg-block', role: 'group', 'aria-label': 'Building block' },
    groups.map(g => h('span', { key: g.id, className: 'cb-wblocks-g', 'data-cb-group': g.id }, h('span', { className: 'cb-wblocks-k' }, g.id), seg(g, undefined))))
}

const WIRE_NET_GLYPH = { power: 'power', ground: 'ground', signal: 'signal' }
const WIRE_NET_WORD = { power: 'supply', ground: 'ground', signal: 'signal' }

/** Net name as a chip in its net colour (supply tinted, ground dashed): the name carries the meaning, the colour
 *  matches the net in the plan. A long name is cut with the full name as title. */
function WireNetChip({ net, cls }) {
  return h('span', { className: `cb-netchip cb-netchip--${cls}`, 'data-cb': 'net-chip', 'data-cb-net-class': cls, title: `${net} · ${WIRE_NET_WORD[cls]} net`, 'data-cb-truncate-ok': '' },
    h('span', { className: 'cb-netchip-t' }, net))
}

/** The schematic: header (title, net legend, actions), the backend SVG fitted and centred, caption. `hl` is
 *  {refs, net} (lib/wire.js wireHl); matching SVG elements get data-cb-on="true" (own DOM, attribute only). */
function SchematicView({ svg, hl, onHover, caption = null, title = '// schematic', actions = null }) {
  const ref = useRef(null)
  const safe = sanitizeSvg(svg)
  const vb = safe.ok ? svgViewBox(safe.svg) : null
  // one object per SVG text: a new {__html} object makes React write innerHTML again (and drop data-cb-on)
  const html = useMemo(() => ({ __html: safe.ok ? safe.svg : '' }), [safe.ok ? safe.svg : ''])
  // after every commit (cheap: a few dozen elements), so the marks always match `hl`
  useEffect(() => {
    const root = ref.current
    if (!root || typeof root.querySelectorAll !== 'function') return
    for (const el of root.querySelectorAll('[data-ref],[data-net],[data-pin]')) {
      const on = wireHlHas(hl, { ref: el.getAttribute('data-ref'), net: el.getAttribute('data-net'), pin: el.getAttribute('data-pin') })
      if (on) el.setAttribute('data-cb-on', 'true'); else el.removeAttribute('data-cb-on')
    }
  })
  if (!safe.ok) return h('div', { className: 'cb-jobline cb-bad', role: 'alert' }, `✕ Schematic not shown: ${safe.reason}`)
  // the plan fills the stage (meet, centred) and never shrinks below scale 1: the stage grows instead
  const size = vb ? { minWidth: `${vb.w}px`, minHeight: `${vb.h}px` } : undefined
  return h('div', { className: 'cb-svgwrap cb-bracket', 'data-cb': 'schematic', 'data-cb-audit-root': 'schematic' },
    h('div', { className: 'cb-svghead', 'data-cb': 'schematic-head' },
      h(Label, null, '// schematic', title !== '// schematic' ? h('span', { className: 'cb-svghead-b' }, title.replace(/^\/\/ schematic/, '')) : null),
      h('span', { className: 'cb-netlegend', 'data-cb': 'net-legend' },
        ['power', 'ground', 'signal'].map(c => h('span', { key: c, className: `cb-netkey cb-netchip--${c}` },
          h(Glyph, { state: WIRE_NET_GLYPH[c], decorative: true }), WIRE_NET_WORD[c]))),
      actions ? h('span', { className: 'cb-svghead-act' }, actions) : null),
    h('div', { className: 'cb-svgstage', style: vb ? { minHeight: `${vb.h}px` } : undefined },
      h('div', { className: 'cb-svg', ref, style: size, 'data-cb-hl': hl ? (hl.net ? 'net' : 'part') : undefined, role: 'img',
        onMouseOver: e => onHover(wireHoverTarget(e.target, ref.current)), onMouseLeave: () => onHover(null),
        dangerouslySetInnerHTML: html })),
    caption ? h('span', { className: 'cb-svgcap', 'data-cb': 'schematic-caption' }, caption) : null)
}

function StationWire({ project }) {
  const wire = sdk.useValue($wire)
  const wb = sdk.useValue($wireBlocks)
  useEffect(() => { loadWireBlocks() }, [])
  const blocks = wireBlockList(wb.names, wb.env)
  const mods = wireModuleParts(project)
  const circuits = project?.circuits || []
  // a project without circuits starts empty: nothing is drawn until a block is picked (no example circuit)
  const [blockId, setBlockId] = useState(circuits[0]?.block || null)
  const [circuitId, setCircuitId] = useState(circuits[0]?.id || null)
  const block = blockId ? wireBlock(blockId, blocks) || WIRE_BLOCKS[0] : null
  const stored = circuits.find(c => c.id === circuitId) || null
  const [form, setForm] = useState(() => block ? wireForm(block, stored?.block === block.block ? stored.params : {}, fmtParam) : {})
  const [errors, setErrors] = useState({})
  const [hl, setHlRaw] = useState(null)
  // the same highlight again (mouseover bubbles from every child) keeps the old state: no re-render per event
  const setHl = next => setHlRaw(prev => wireHlKey(prev) === wireHlKey(next) ? prev : next)
  const [newId, setNewId] = useState('')
  const gpio = stored ? circuitGpio(project, stored) : null
  const partless = Boolean(block?.params.some(p => p.part)) && !mods.length
  const render = (b = block, f = form, cId = circuitId) => {
    if (!b) return
    const r = buildWireParams(b, f, parseQuantity)
    setErrors(r.errors)
    if (!r.ok) return
    const c = circuits.find(x => x.id === cId)
    renderSchematic(b.block, r.params, { circuit: cId, gpio: c ? circuitGpio(project, c) : null })
  }
  useEffect(() => { if (wire.status === 'idle' && stored) render() }, [])
  const pickCircuit = id => {
    const c = circuits.find(x => x.id === id)
    if (!c) return
    const b = wireBlock(c.block, blocks) || WIRE_BLOCKS[0]
    const f = wireForm(b, c.params, fmtParam)
    setCircuitId(id); setBlockId(b.block); setForm(f)
    render(b, f, id)
  }
  const pickBlock = id => {
    const b = wireBlock(id, blocks)
    const f = wireForm(b, {}, fmtParam)
    if (b.params.some(p => p.part) && !f.part) f.part = mods[0]?.ref || ''
    setBlockId(id); setCircuitId(null); setForm(f); setErrors({})
    if (!b.params.some(p => p.part) || f.part) render(b, f, null)
    else $wire.set({ status: 'idle', key: null, env: null, circuit: null }) // no module part: nothing to draw
  }
  const env = wire.env
  const res = env?.ok ? env.result : null
  const rows = wiringRows(res?.wiring)
  const warn = wireWarnings(env?.warnings)
  const fileName = svgFileName(project, circuitId || block?.block || 'circuit')
  const gpioRole = gpio !== null ? project.assignments.find(a => a.pin === gpio)?.role || '' : ''
  // the drawing gets the whole main area (toolbar above, nothing below); parameters live in the inspector
  return [
    h('main', { key: 'main', className: 'cb-main cb-station cb-main--fill', 'data-cb': 'station-wire' },
      h(DecodeTitle, { text: '03 // WIRING', meta: res ? env.summary : 'schematic per building block' }),
      h('div', { className: 'cb-toolbar' },
        circuits.length ? h('div', { className: 'cb-group' }, h(Label, null, 'project'),
          h(Seg, { label: 'Project circuits', dataCb: 'seg-circuit', value: circuitId, options: circuits.map(c => ({ id: c.id, label: c.id, title: c.block })), onChange: pickCircuit })) : null,
        h('div', { className: 'cb-group cb-group--wblocks' }, h(Label, null, 'block'),
          h(WireBlockPick, { groups: wireGroups(blocks), value: circuitId ? null : blockId, onChange: pickBlock }))),
      env && !env.ok ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'wire-error', 'data-cb-code': env.error?.code || undefined },
        h('span', null, `✕ ${env.error?.message || env.summary}`), env.error?.hint ? h('span', { className: 'cb-dim' }, env.error.hint) : null) : null,
      res ? h(SchematicView, { svg: res.svg, hl, onHover: setHl, title: `// schematic · ${String(res.block || block?.block || '').replace(/_/g, ' ')}`,
        actions: h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'wire-save',
          title: typeof CB.ctx?.files?.writeText === 'function' ? 'Save into a folder you pick' : `Download ${fileName}`, onClick: () => saveSvg(res.svg, fileName) }, 'Save SVG'),
        caption: gpio !== null ? `drawn on GPIO${gpio}${gpioRole ? ` · ${gpioRole}` : ''}`
          : circuitId ? null : 'preview · not in the project until you add it' })
        : wire.status === 'loading' ? h('div', { className: 'cb-loading' }, 'drawing schematic')
          : !block ? h(EmptyBox, { kicker: '// wiring · no circuit', title: 'No circuit in this project yet', dataCb: 'wire-empty' },
            h('p', null, 'Pick a building block above to draw a preview with its wiring table. Nothing is stored until you click Add to project.'),
            h('p', null, 'Or ask Hermes, e.g. “draw an LED on GPIO4”.')) : null),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' },
      h('div', { className: 'cb-card', 'data-cb': 'wire-params-card' },
        // only "// parameters"; the block is the selected tab above and in the schematic title
        h('div', { className: 'cb-card-head' }, h(Label, null, '// parameters'),
          circuitId ? h('span', { className: 'cb-tag cb-push', title: 'Stored in the project' }, circuitId) : null),
        h('div', { className: 'cb-wireparams', 'data-cb': 'wire-params' },
          !block ? h('p', { className: 'cb-why cb-dim' }, 'Pick a building block to set its parameters.')
            : partless ? h('p', { className: 'cb-why', 'data-cb': 'wire-no-module' }, 'No module part in this project yet. Add one, then pick it here.')
              : !block.params.length ? h('p', { className: 'cb-why cb-dim' }, 'No parameters: the backend draws its defaults.')
                : block.params.map(p => p.part ? h(Field, { key: p.name, id: `cb-w-${p.name}`, label: p.label, value: form[p.name], choice: mods.map(m => m.ref), error: errors[p.name],
                  hint: mods.find(m => m.ref === form[p.name])?.label.replace(/^\S+ /, '') || 'required', dataCb: `w-${p.name}`, onChange: v => setForm(f => ({ ...f, [p.name]: v })) }) : h(Field, { key: p.name, id: `cb-w-${p.name}`, label: p.label, value: form[p.name], choice: p.choice, error: errors[p.name],
            hint: p.unit && parseQuantity(form[p.name], p.unit).ok ? `= ${formatSI(parseQuantity(form[p.name], p.unit).value, p.unit)}` : p.required ? 'required' : '',
            onChange: v => setForm(f => ({ ...f, [p.name]: v })), dataCb: `w-${p.name}`, onEnter: () => render() }))),
        block ? h('div', { className: 'cb-actions', style: { marginTop: '2px' } },
          partless ? h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'wire-add-module', onClick: () => openModules() }, 'Add a module…')
            : h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'wire-render', disabled: wire.status === 'loading', onClick: () => render() }, wire.status === 'loading' ? 'Drawing…' : 'Draw'),
          res && !circuitId ? [h('input', { key: 'i', className: 'cb-inline-in', value: newId, placeholder: 'circuit id, e.g. led', maxLength: 32, 'data-cb': 'wire-new-id',
            'aria-label': 'Circuit id', onChange: e => setNewId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '')) }),
          h(Btn, { key: 'a', kind: 'quiet', size: 'sm', disabled: !/^[a-z0-9][a-z0-9_-]{0,31}$/.test(newId) || circuits.some(c => c.id === newId), 'data-cb': 'wire-add',
            onClick: async () => { const r = buildWireParams(block, form, parseQuantity); if (r.ok) { const e2 = await addCircuitToProject(newId, block.block, r.params); if (e2?.ok) setCircuitId(newId) } } }, 'Add to project')] : null) : null),
      h('div', { className: 'cb-card', 'data-cb': 'wiring-table' },
        h('div', { className: 'cb-card-head' }, h(Label, null, '// wiring'), h(Label, null, `${rows.length} wires`)),
        rows.length ? h('table', { className: 'cb-table cb-wiretable' },
          h('colgroup', null, h('col', { className: 'cb-wcol-from' }), h('col', { className: 'cb-wcol-to' }), h('col', { className: 'cb-wcol-net' })),
          h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, 'from'), h('th', { className: 'cb-label' }, 'to'), h('th', { className: 'cb-label' }, 'net'))),
          h('tbody', null, rows.map(r => h('tr', { key: r.i, 'data-cb-row': r.i, 'data-cb-net': r.net, 'data-cb-net-class': r.netClass, 'aria-selected': wireRowOn(hl, r) ? 'true' : 'false',
            // the net highlight also follows the keyboard (focus = hover)
            tabIndex: 0, onMouseEnter: () => setHl(wireRowHl(r, res?.parts)), onMouseLeave: () => setHl(null),
            onFocus: () => setHl(wireRowHl(r, res?.parts)), onBlur: () => setHl(null) },
          h('td', { className: 'cb-fg', title: r.from, 'data-cb-truncate-ok': '' }, r.from), h('td', { className: 'cb-fg', title: r.to, 'data-cb-truncate-ok': '' }, r.to),
          h('td', null, h(WireNetChip, { net: r.net, cls: r.netClass })))))) : h('p', { className: 'cb-why cb-dim' }, 'Draw a block to see its wiring.')),
      res?.parts?.length ? h('div', { className: 'cb-card', 'data-cb': 'wire-parts' },
        h(Label, null, '// parts'),
        h('table', { className: 'cb-table cb-wparts' }, h('tbody', null, res.parts.map(p => h('tr', { key: p.ref, 'data-cb-ref': p.ref, 'aria-selected': hl?.refs.includes(p.ref) ? 'true' : 'false',
          tabIndex: 0, onMouseEnter: () => setHl(wireHl([p.ref])), onMouseLeave: () => setHl(null), onFocus: () => setHl(wireHl([p.ref])), onBlur: () => setHl(null) },
          h('td', { className: 'cb-fg' }, p.ref), h('td', null, nbspUnits(p.value)), h('td', { className: 'cb-r cb-dim' }, p.kind)))))) : null,
      res ? warn.cards.map(w => h('div', { key: w.code, className: `cb-card cb-wwarn cb-wwarn--${w.severity}`, role: 'note', 'data-cb': 'wire-warning', 'data-cb-code': w.code, 'data-cb-severity': w.severity },
        h('div', { className: 'cb-card-head' }, h('span', { className: 'cb-wwarn-mark', 'aria-hidden': 'true' }, '!'), h(Label, null, w.severity === 'danger' ? '// danger' : '// caution')),
        h('p', { className: 'cb-wwarn-t' }, w.message))) : null,
      res ? h(ChecksList, { checks: [], warnings: warn.notes }) : null,
      res ? h(SourceLine, { sources: env.sources }) : null)
  ]
}

STATION_VIEWS.wire = { component: StationWire, inspector: true }

// --- 43-station-solder.js
// Station 04 SOLDER: plan from the project's parts or a pasted BOM (CSV), one card per step in order, check marks →
// POST /projects/{id}/solder/{step}; key n (or the button "Mark done (N)") = mark the current step done.
// Every step shows its part (lib/art-parts.js), a polarity mark only with a sourced polarity hint, hint
// lines by kind (polarity, heat, safety, tip) with symbol + tone by severity and their sources, done steps fold to one
// line and open again (nothing is cut), one progress formula in the head, a height strip (rule of thumb).

const HINT_TONE = { danger: 'bad', caution: 'warn', info: 'dim' }
const SOLDER_HINT_SYMBOL = { danger: '✕', caution: '!', info: 'i' }

const solderKindWord = k => String(k || '').replace(/_/g, ' ')
const solderN = n => String(n).padStart(2, '0')

/** Source label of an id: the title from the plan answer when known (sourceLabel), else the id itself. */
function solderSourceOf(id, sources) {
  const s = (sources || []).find(x => x && x.id === id)
  if (s) return { id, text: sourceLabel(s), title: `${s.title}\n${s.url || 'no URL (rule of thumb)'}\nretrieved ${s.retrieved || '—'}`, url: s.url || null }
  if (id === 'rule-of-thumb') return { id, text: 'rule of thumb', title: 'Practice rule, not a standard', url: null }
  return { id, text: String(id).replace(/^solder-/, ''), title: `source ${id} (details in the plan answer: re-plan to load the titles)`, url: null }
}

function SolderSrc({ ids, sources }) {
  const list = [...new Set(ids || [])].map(id => solderSourceOf(id, sources))
  if (!list.length) return null
  return h('span', { className: 'cb-shint-src', 'data-cb': 'hint-src' }, h('span', { className: 'cb-k' }, 'src ›'),
    list.map((s, i) => [i ? h('span', { key: `d${i}`, className: 'cb-shint-src-sep', 'aria-hidden': 'true' }, '·') : null, s.url
      ? h('button', { key: s.id, type: 'button', title: s.title, onClick: () => openLink(s.url) }, `${s.text} ↗`)
      : h('span', { key: s.id, title: s.title }, s.text)]))
}

/** One hint line: symbol + category tag (state never by colour alone), text, sources. */
function SolderHintRow({ hint, sources }) {
  const sev = HINT_TONE[hint.severity] ? hint.severity : 'info'
  const cat = solderArtHintKind(hint)
  return h('li', { className: cx('cb-shint', `cb-shint--${sev}`), 'data-cb': `hint-${hint.code}`, 'data-cb-hint-kind': cat, 'data-cb-severity': sev },
    h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, SOLDER_HINT_SYMBOL[sev]),
    h('span', { className: 'cb-shint-cat' }, h('span', { className: 'cb-sr' }, `${sev}: `), cat),
    h('span', { className: 'cb-shint-t' }, nbspUnits(hint.text), ' ', h(SolderSrc, { ids: hint.source_ids, sources })))
}

function SolderHints({ hints, sources }) {
  if (!hints?.length) return null
  return h('ul', { className: 'cb-shints', 'data-cb': 'step-hints' }, hints.map((x, i) => h(SolderHintRow, { key: `${x.code}-${i}`, hint: x, sources })))
}

/** Pictogram of a step's part (side view on the board). size: lg (open step) | md (later step) | sm (done line). */
function SolderPic({ step, parts, size = 'lg', polarity }) {
  const dims = { lg: [132, 88], md: [84, 56], sm: [36, 24] }[size] || [96, 64]
  const label = size === 'sm' ? '' : `${solderKindWord(step.kind)}${polarity ? `, ${polarity.label}` : ''} (side view, schematic)`
  const safe = sanitizeSvg(solderArtPart(step.kind, { polarity: size === 'sm' ? null : polarity, pkg: solderArtPackage(step, parts), w: dims[0], h: dims[1], label }))
  if (!safe.ok) return null
  return h('span', { className: cx('cb-part-pic', `cb-part-pic--${size}`), 'data-cb': `step-pic-${step.n}`, dangerouslySetInnerHTML: { __html: safe.svg } })
}

/** Polarity tag under the pictogram: only with a sourced hint (solderArtPolarity), with its sources in the title. */
function SolderPolTag({ polarity }) {
  if (!polarity) return null
  return h('span', { className: 'cb-pol', 'data-cb': 'step-polarity', 'data-cb-mark': polarity.mark, title: `from the ${polarity.code} hint · src ${polarity.source_ids.join(', ')}` },
    h('span', { 'aria-hidden': 'true' }, polarity.mark === 'pinout-datasheet' ? '?' : '±'), polarity.label)
}

function SolderStepCard({ step, done, current, onToggle, onMark, busy, parts, sources }) {
  const ref = useRef(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!current || !ref.current?.scrollIntoView) return
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ref.current.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  }, [current])
  const polarity = solderArtPolarity(step)
  const later = !done && !current
  const detailId = `cb-step-detail-${step.id}`
  const check = h('button', { type: 'button', role: 'checkbox', 'aria-checked': done ? 'true' : 'false', className: 'cb-check', disabled: busy, 'data-cb': `step-check-${step.n}`,
    title: done ? 'Mark as not done' : 'Mark as done', 'aria-label': `step ${step.n} ${solderKindWord(step.kind)} ${done ? 'done' : 'not done'}`, onClick: () => onToggle(step, !done) }, done ? '✓' : '')
  const num = h('div', { className: 'cb-step-n' }, solderN(step.n))
  const refs = h('span', { className: 'cb-step-refs' }, step.refs.join(' · '))
  if (done) {
    return h('div', { ref, className: cx('cb-step', 'cb-step--done', open && 'cb-step--open'), 'data-cb': `step-${step.n}`, 'data-cb-step': step.id },
      check, num,
      h('div', { className: 'cb-step-body' },
        h('div', { className: 'cb-step-head cb-step-line' }, h(SolderPic, { step, parts, size: 'sm' }), h('b', null, solderKindWord(step.kind)), refs,
          h('span', { className: 'cb-ok cb-step-donew' }, '✓ done'),
          h('button', { type: 'button', className: 'cb-step-more cb-push', 'data-cb': `step-expand-${step.n}`, 'aria-expanded': open ? 'true' : 'false', 'aria-controls': detailId,
            onClick: () => setOpen(!open) }, open ? 'hide ▴' : 'details ▾')),
        open ? h('div', { id: detailId, className: 'cb-step-detail', 'data-cb': `step-detail-${step.n}` },
          h('div', { className: 'cb-step-act' }, nbspUnits(step.action)), h(SolderHints, { hints: step.hints, sources })) : null))
  }
  return h('div', { ref, className: cx('cb-step', current && 'cb-step--cur', later && 'cb-step--todo'), 'data-cb': `step-${step.n}`, 'data-cb-step': step.id,
    'aria-current': current ? 'step' : undefined },
  check, num,
  h('div', { className: 'cb-step-body' },
    h('div', { className: 'cb-step-head' }, h('b', null, solderKindWord(step.kind)), refs,
      current ? h('span', { className: 'cb-now' }, 'NOW') : null,
      current ? h(Btn, { kind: 'ghost', size: 'sm', className: 'cb-push cb-mark-done', disabled: busy, 'data-cb': 'solder-mark-done', 'aria-keyshortcuts': 'n',
        title: 'Mark this step done (key n)', onClick: () => onMark(step) }, 'Mark done (N)') : null),
    h('div', { className: 'cb-step-main' },
      h('div', { className: 'cb-step-fig' }, h(SolderPic, { step, parts, size: current ? 'lg' : 'md', polarity }), h(SolderPolTag, { polarity })),
      h('div', { className: 'cb-step-text' }, h('div', { className: 'cb-step-act' }, nbspUnits(step.action)), h(SolderHints, { hints: step.hints, sources })))))
}

/** Height strip (S): the parts in solder order as silhouettes on one board line, current step framed. */
function SolderHeights({ steps, done, currentId, parts }) {
  if (steps.length < 2) return null
  return h('div', { className: 'cb-heights', 'data-cb': 'solder-heights' },
    h('div', { className: 'cb-heights-head' }, h(Label, null, '// part height in solder order'),
      h('span', { className: 'cb-heights-why' }, 'low before tall · mechanical parts last'), h('span', { className: 'cb-heights-rot' }, 'rule of thumb')),
    h('ol', { className: 'cb-heights-row' }, steps.map(s => {
      const st = done.has(s.id) ? 'done' : s.id === currentId ? 'now' : 'todo'
      const cls = SOLDER_ART_HEIGHT[s.kind] ?? 4
      return h('li', { key: s.id, className: cx('cb-hcell', `cb-hcell--${st}`), 'data-cb': `height-${s.n}`, 'data-cb-state': st,
        title: `${solderN(s.n)} ${solderKindWord(s.kind)} · ${SOLDER_ART_HEIGHT_WORDS[cls]} (rule of thumb)` },
      h('span', { className: 'cb-hcell-pic', 'aria-hidden': 'true', dangerouslySetInnerHTML: { __html: solderArtPart(s.kind, { pkg: solderArtPackage(s, parts), w: 48, h: 32 }) } }),
      h('span', { className: 'cb-hcell-n' }, solderN(s.n), ' ', h('span', { 'aria-hidden': 'true' }, st === 'done' ? '✓' : st === 'now' ? '●' : '○'),
        h('span', { className: 'cb-sr' }, ` ${solderKindWord(s.kind)}, ${SOLDER_ART_HEIGHT_WORDS[cls]}, ${st === 'now' ? 'current step' : st}`)))
    })))
}

function StationSolder({ project }) {
  const steps = project?.solder?.steps || []
  const done = new Set(project?.solder?.done || [])
  const parts = project?.parts || []
  const sp = solderProgress(project)
  const next = nextSolderStep(project)
  const plan = sdk.useValue($solderPlan)
  const sources = plan.env?.ok ? plan.env.sources || [] : []
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const toggle = async (step, on) => {
    setBusy(true)
    try { await toggleSolderStep(step.id, on) } finally { setBusy(false) }
  }
  useEffect(() => { ref.current?.focus?.({ preventScroll: true }) }, [])
  useEffect(() => {
    const el = ref.current?.querySelector?.('[aria-current=step]')
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [next?.id])
  const onKey = e => {
    if (e.key !== 'n' || e.ctrlKey || e.metaKey || e.altKey || busy) return
    const t = e.target
    if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '')) return
    e.preventDefault()
    if (next) toggle(next, true)
  }
  // after the button: focus back on the station, so n keeps working without a click
  const mark = async step => { await toggle(step, true); ref.current?.focus?.({ preventScroll: true }) }
  const all = sp.total > 0 && sp.done >= sp.total
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-solder', 'data-cb-audit-root': 'station', ref, tabIndex: -1, onKeyDown: onKey },
      h(DecodeTitle, { text: '04 // SOLDER ORDER', meta: 'flat → tall, robust → sensitive, connectors last' }),
      sp.total ? h('div', { className: 'cb-solder-prog', 'data-cb': 'solder-progress' },
        h('span', { className: 'cb-solder-formula', 'data-cb': 'solder-formula' }, h('b', { className: all ? 'cb-ok' : 'cb-fg' }, `${sp.done}/${sp.total}`), ' done',
          next ? [' · now ', h('b', { key: 'r', className: 'cb-solder-nowrefs' }, next.refs.join(' · '))] : [' · ', h('span', { key: 'a', className: 'cb-ok' }, '✓ all steps done')]),
        h(Bar, { pct: (sp.done / sp.total) * 100, tone: all ? 'ok' : 'active', label: 'solder progress' })) : null,
      h(SolderStale, { project }),
      steps.length ? h(SolderHeights, { steps, done, currentId: next?.id, parts }) : null,
      steps.length ? h('div', { className: 'cb-steps-list', 'data-cb': 'solder-steps' }, steps.map(s => h(SolderStepCard, { key: s.id, step: s, done: done.has(s.id),
        current: next?.id === s.id, onToggle: toggle, onMark: mark, busy, parts, sources })))
        : h(EmptyBox, { kicker: '// 04 solder', title: 'No solder plan yet', dataCb: 'solder-empty',
          actions: [h(Btn, { key: 'p', kind: 'ghost', disabled: !parts.length, onClick: () => planSolder(), 'data-cb': 'solder-plan-parts' }, 'Plan from project parts')] },
        h('p', null, parts.length ? `Press Plan from project parts to order the ${parts.length === 1 ? 'part' : `${parts.length} parts`}. A plan Hermes makes with this project also shows up here.`
          : 'Add parts in 02 CALC, or open import bom (csv) in the plan source panel.'))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'data-cb-audit-root': 'inspector', 'aria-label': 'Inspector' }, h(SolderSource, { project }))
  ]
}

/** Parts added after planning (02 CALC → Add to project) or removed since — say so and offer the re-plan. */
function SolderStale({ project }) {
  const plan = sdk.useValue($solderPlan)
  const st = solderStale(project)
  if (!st.stale) return null
  const n = st.missing.length
  const parts = [n ? `${n} new part${n === 1 ? '' : 's'} not in the plan (${st.missing.join(', ')})` : null,
    st.gone.length ? `${st.gone.length} planned part${st.gone.length === 1 ? '' : 's'} no longer in the project (${st.gone.join(', ')})` : null].filter(Boolean)
  const reopen = st.reopen.map(r => `step ${String(r.n).padStart(2, '0')} (${r.kind.replace(/_/g, ' ')}) reopens${r.gains.length ? ` for ${r.gains.join(', ')}` : ''}`)
  return h('div', { className: 'cb-note cb-note--warn cb-stale', 'data-cb': 'solder-stale', role: 'status' },
    h('span', { 'aria-hidden': 'true' }, '!'),
    h('span', { className: 'cb-stale-t' }, h('b', null, parts.join('; ')),
      h('span', { className: 'cb-dim' }, reopen.length ? `Re-plan keeps the other check marks; ${reopen.join('; ')}.`
        : 'Re-planning keeps the check marks of unchanged steps.')),
    h(Btn, { kind: 'warn', size: 'sm', className: 'cb-push', 'data-cb': 'solder-stale-replan', disabled: plan.status === 'loading', onClick: () => planSolder() },
      plan.status === 'loading' ? 'Planning…' : 'Re-plan ›'))
}

/** All parts of the project with their step; the current step's refs are marked (NOW + frame, not colour alone). */
function SolderPartList({ project }) {
  const parts = (project?.parts || []).filter(p => p && p.ref)
  if (!parts.length) return null
  const steps = project?.solder?.steps || []
  const done = new Set(project?.solder?.done || [])
  const next = nextSolderStep(project)
  const stepOf = new Map()
  for (const s of steps) for (const r of s.refs || []) stepOf.set(r, s)
  // in solder order (step number), parts without a step at the end; the project order inside a step
  const ordered = parts.map((p, i) => ({ p, i, n: stepOf.get(p.ref)?.n ?? Infinity })).sort((a, b) => a.n - b.n || a.i - b.i).map(x => x.p)
  return h('ul', { className: 'cb-sparts', 'data-cb': 'solder-parts' }, ordered.map(p => {
    const s = stepOf.get(p.ref)
    const st = !s ? 'none' : done.has(s.id) ? 'done' : next?.id === s.id ? 'now' : 'todo'
    return h('li', { key: p.ref, className: cx('cb-spart', `cb-spart--${st}`), 'data-cb': `part-${p.ref}`, 'data-cb-state': st, 'aria-current': st === 'now' ? 'true' : undefined },
      h('span', { className: 'cb-spart-mark', 'aria-hidden': 'true' }, st === 'done' ? '✓' : st === 'now' ? '●' : st === 'none' ? '–' : '○'),
      h('b', { className: 'cb-spart-ref' }, p.ref),
      h('span', { className: 'cb-spart-what' }, solderKindWord(p.kind), p.value ? h('span', { className: 'cb-dim' }, ` · ${p.value}`) : null),
      h('span', { className: 'cb-spart-step' }, s ? solderN(s.n) : 'not planned', st === 'now' ? h('span', { className: 'cb-sr' }, ' current step') : null))
  }))
}

function SolderSource({ project }) {
  const plan = sdk.useValue($solderPlan)
  const [csv, setCsv] = useState('')
  const env = plan.env
  const r = env?.ok ? env.result : null
  const n = (project?.parts || []).length
  const loading = plan.status === 'loading'
  const partsWhy = loading ? 'planning…' : !n ? 'no parts in the project yet: 02 CALC adds them, or import a BOM below' : null
  const csvWhy = loading ? 'planning…' : !csv.trim() ? 'paste a BOM first (one part per line: ref,value,package)' : null
  return [
    h('div', { key: 's', className: 'cb-card', 'data-cb': 'solder-source' },
      h(Label, null, '// plan source'),
      h('p', { className: 'cb-why' }, `From the project's parts (${n}) or from a pasted BOM. Re-planning keeps the check marks of unchanged steps.`),
      h(SolderPartList, { project }),
      h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', disabled: Boolean(partsWhy), 'data-cb': 'solder-replan',
        'aria-describedby': partsWhy ? 'cb-solder-parts-why' : undefined, onClick: () => planSolder() }, loading ? 'Planning…' : 'Plan from project parts')),
      partsWhy ? h('p', { id: 'cb-solder-parts-why', className: 'cb-solder-why', 'data-cb': 'solder-replan-why' }, partsWhy) : null,
      h('details', { className: 'cb-solder-csv', 'data-cb': 'solder-csv-box' },
        h('summary', null, h(Label, null, 'import bom (csv)')),
        h('label', { className: 'cb-label', htmlFor: 'cb-bom', style: { display: 'block', marginTop: '8px' } }, 'bom (csv)'),
        h('textarea', { id: 'cb-bom', className: 'cb-textarea', rows: 5, value: csv, placeholder: 'ref,value,package\nR1,1k,0805\nC1,10uF 16V,radial', spellCheck: false,
          'data-cb': 'solder-csv', onChange: e => setCsv(e.target.value.slice(0, 60000)) }),
        h('div', { className: 'cb-actions' }, h(Btn, { kind: 'quiet', size: 'sm', disabled: Boolean(csvWhy), 'data-cb': 'solder-plan-csv',
          'aria-describedby': csvWhy ? 'cb-solder-csv-why' : undefined, onClick: () => planSolder(csv) }, 'Plan from CSV')),
        csvWhy ? h('p', { id: 'cb-solder-csv-why', className: 'cb-solder-why', 'data-cb': 'solder-csv-why' }, csvWhy) : null)),
    // a failed plan is a notice in the Bench's zone (26-live.js planSolder)
    r && (r.unknown_parts?.length || r.unclear_parts?.length) ? h('div', { key: 'u', className: 'cb-card', 'data-cb': 'solder-unclear' },
      h(Label, null, '// check these parts'),
      h('ul', { className: 'cb-step-hints' }, [...(r.unknown_parts || []).map(x => ({ x, t: 'unknown kind' })), ...(r.unclear_parts || []).map(x => ({ x, t: 'unclear' }))].map((u, i) =>
        h('li', { key: i, className: 'cb-warn' }, `! ${typeof u.x === 'string' ? u.x : u.x.ref || JSON.stringify(u.x)} — ${u.t}`)))) : null,
    env?.ok ? h(SourceLine, { key: 'src', sources: env.sources }) : null
  ]
}

STATION_VIEWS.solder = { component: StationSolder, inspector: true }

// --- 44-station-flash.js
// Station 05 FLASH: ports (real first, sim below, nothing opens on its own), detect job + variant takeover, firmware
// folder (own folder or the example), build job, flash only through the confirmation dialog.

function nextFlashStep(project, ports) {
  const det = project?.board?.detected
  const fw = project?.firmware || {}
  const listed = det?.port && (ports.ports || []).some(p => p.device === det.port)
  if (!det?.port || !listed) return 'detect'
  if (!fw.dir) return 'firmware'
  const conf = flashConfirm(project)
  if (!conf.ok) return 'build'
  return conf.alreadyFlashed ? 'done' : 'flash'
}

function JobLine({ job, note, kind }) {
  const pr = jobProgress(job)
  if (note) {
    return h('div', { className: 'cb-jobline cb-bad', 'data-cb': `job-${kind}-error`, role: 'alert' },
      h('span', null, `✕ ${note.message}`), note.hint ? h('span', { className: 'cb-dim' }, note.hint) : null,
      note.code === 'flash_disabled' ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'agent-settings-link', onClick: () => openAgentSettings() }, 'Agent settings ›') : null)
  }
  if (!job) return null
  // while the job runs: phase word from its log (writing, verifying …) and the progress of job.progress
  const phase = flashJobPhase(job)
  return h('div', { className: `cb-jobline cb-${pr.failed ? 'bad' : pr.done ? 'ok' : 'active'}`, 'data-cb': `job-${kind}`, 'data-cb-state': job.state, 'data-cb-job': job.job_id,
    'data-cb-phase': phase ? phase.word : undefined },
  h('span', { 'aria-hidden': 'true' }, pr.running ? '◴' : pr.failed ? '✕' : '✓'),
  phase ? h('span', { className: 'cb-vf-phase' }, h('b', null, kind), h('span', { className: 'cb-vf-phase-w' }, phase.word),
    phase.pct !== null ? h('span', { className: 'cb-mono-num' }, `${phase.pct} %`) : null)
    : h('span', null, `${kind} ${pr.text}`),
  pr.running ? h(Bar, { pct: pr.indeterminate ? null : pr.pct, label: `${kind} progress${phase ? ` · ${phase.word}` : ''}` }) : null,
  h('span', { className: 'cb-dim cb-push' }, job.job_id))
}

/** Connector symbol of a port (artPort, the same shape as on the board model); nothing when the kind is unknown. */
function FlashPortSymbol({ kind, board }) {
  if (!kind || !ART_PORT_SIZE[kind]) return null
  const [w, ht] = ART_PORT_SIZE[kind]
  const what = { micro_usb: 'Micro-USB', usb_c: 'USB-C', generic_usb: 'USB (connector type not in the board data)' }[kind] || kind
  return h('svg', { className: 'cb-vf-portsym', viewBox: `-2 -2 ${w + 4} ${ht + 4}`, role: 'img', 'aria-label': `${what} on ${board || 'the board'}`,
    'data-cb': 'port-symbol', 'data-cb-port': kind, focusable: 'false', dangerouslySetInnerHTML: { __html: artPort(kind, 0, 0) } })
}

function PortList({ ports, project, flow, health }) {
  const det = project?.board?.detected?.port || null
  const rows = portRows(ports.ports, { detectedPort: det, selected: flow.port })
  const jobs = sdk.useValue($jobs)
  const layout = sdk.useValue($board).layout
  const running = jobProgress(jobs.detect).running
  const byDevice = new Map((ports.ports || []).map(p => [p.device, p]))
  if (ports.status === 'error') return h('p', { className: 'cb-why cb-warn' }, '! Port list unavailable: ', ports.error?.error?.message || 'backend error')
  return h('div', { className: 'cb-ports', 'data-cb': 'port-list', role: 'radiogroup', 'aria-label': 'Serial ports' },
    rows.length ? rows.map(r => h('div', { key: r.device, className: cx('cb-port', r.simulated && 'cb-port--sim', r.selected && 'cb-port--sel'),
      'data-cb': `port-${r.simulated ? 'sim' : 'real'}`, 'data-cb-device': r.device },
    h('button', { type: 'button', role: 'radio', 'aria-checked': r.selected ? 'true' : 'false', className: 'cb-port-pick', onClick: () => selectPort(r.device),
      title: `${r.device} · ${r.description}` },
    h('span', { className: 'cb-radio', 'aria-hidden': 'true' }),
    h(FlashPortSymbol, { kind: flashPortConnector(byDevice.get(r.device), layout, det), board: layout?.title }),
    h('span', { className: 'cb-port-txt' },
      h('span', { className: 'cb-port-l1' }, h('b', { className: 'cb-ellip', title: r.device, 'data-cb-truncate-ok': '' }, r.device), r.simulated ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-port' }) : h('span', { className: 'cb-tagx' }, r.label)),
      h('span', { className: 'cb-port-l2' }, h('span', { className: 'cb-dim cb-vf-portdesc' }, r.simulated ? r.description : `${r.kind}${r.description ? ` · ${r.description}` : ''}`),
        r.detected ? h('span', { className: 'cb-ok', title: 'Detected for this project' }, '✓ detected') : null))),
    h(Btn, { kind: 'ghost', size: 'sm', disabled: running, 'data-cb': `detect-${r.simulated ? 'sim' : 'real'}`, 'data-cb-focus': flow.focus === 'detect' && r.selected ? 'true' : undefined,
      title: r.simulated ? 'Read the simulated chip (no hardware)' : 'Run esptool on this port (the board may reset)', onClick: () => detectBoard(r.device) },
    running && $detect.get().port === r.device ? 'Detecting…' : 'Detect')))
      : h('p', { className: 'cb-why cb-dim', 'data-cb': 'no-ports' }, 'No serial ports. Plug in a board or use the simulated board (sim://).'),
    health && health.hardware_access === false ? h('div', { className: 'cb-hintline', 'data-cb': 'hw-off' },
      h('span', { className: 'cb-active' }, '◌'), 'Hardware access is off: only simulated boards are listed.',
      h('button', { type: 'button', className: 'cb-linkbtn', onClick: () => openAgentSettings() }, 'Agent settings ›')) : null)
}

function DetectResult({ project }) {
  const d = sdk.useValue($detect)
  const det = project?.board?.detected
  const res = d.env?.ok ? d.env.result : det
  const s = detectSummary(res, project)
  if (!s) return null
  // the detection's caution/danger warnings (e.g. no auto reset, unknown chip) as warning lines
  const warns = (d.env?.ok ? d.env.warnings || [] : []).filter(w => w && (w.severity === 'caution' || w.severity === 'danger'))
  return h('div', { className: 'cb-detect', 'data-cb': 'detect-result' },
    warns.length ? h('ul', { className: 'cb-shints cb-vf-dwarn', 'data-cb': 'detect-warnings' }, warns.map((w, i) => h('li', { key: `${w.code}-${i}`,
      className: `cb-shint cb-shint--${w.severity}`, 'data-cb': `detect-warning-${w.code}`, 'data-cb-severity': w.severity },
    h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, SOLDER_HINT_SYMBOL[w.severity]),
    h('span', { className: 'cb-shint-cat' }, w.severity), h('span', { className: 'cb-shint-t' }, w.message)))) : null,
    h('div', { className: 'cb-kv' },
      h('span', null, 'chip'), h('b', null, s.chip),
      h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, s.mac),
      h('span', null, 'flash'), h('b', null, `${s.flash} · PSRAM ${s.psram}`),
      s.usb ? [h('span', { key: 'u' }, 'usb'), h('b', { key: 'v' }, s.usb)] : null),
    s.variantDiffers ? h('div', { className: 'cb-note cb-note--warn', style: { margin: '8px 0 0' }, 'data-cb': 'variant-differs' },
      h('span', null, '!'), `Detected ${String(s.suggestion).toUpperCase()}${s.unverified ? ' (unverified)' : ''}, the project says ${String(project.board.variant).toUpperCase()}.`,
      h(Btn, { kind: 'ghost', size: 'sm', className: 'cb-push', 'data-cb': 'variant-take', onClick: () => patchAtom($ui, { modal: { type: 'variant', variant: s.suggestion } }) },
        `Use ${String(s.suggestion).toUpperCase()}`))
      : s.suggestion ? h('div', { className: 'cb-ok', style: { marginTop: '6px' }, 'data-cb': 'variant-matches', 'data-cb-unverified': s.unverified ? 'true' : null },
        `✓ module variant ${String(s.suggestion).toUpperCase()} matches the project`,
        s.unverified ? ' (unverified: esptool cannot tell octal from quad PSRAM; check the module marking)' : '') : null)
}

function FirmwareCard({ project, n }) {
  const fw = project?.firmware || {}
  const note = sdk.useValue($jobNote).example
  const [dir, setDir] = useState(fw.dir || '')
  const [env, setEnv] = useState(fw.env || '')
  useEffect(() => { setDir(fw.dir || ''); setEnv(fw.env || '') }, [fw.dir, fw.env])
  const changed = (dir.trim() && dir.trim() !== (fw.dir || '')) || (env.trim() && env.trim() !== (fw.env || ''))
  const dirShort = fw.dir ? fw.dir.replace(/^.*\/projects\/([^/]+)\/firmware\/?$/, 'projects/$1/firmware/') : null
  return h(Section, { n, title: 'firmware', dataCb: 'flash-firmware', aside: fw.dir ? h('span', { className: 'cb-ok' }, '✓ set') : h('span', { className: 'cb-warn' }, '! not set') },
    h('div', { className: 'cb-fwgrid' },
      h(Field, { id: 'cb-fw-dir', label: 'Folder', value: dir, onChange: setDir, placeholder: '/path/to/platformio/project', dataCb: 'fw-dir', wide: true, tail: true,
        hint: dirShort && dirShort !== fw.dir ? `in the bench project: ${dirShort}` : fw.dir ? 'PlatformIO project folder' : 'a folder with platformio.ini' }),
      h(Field, { id: 'cb-fw-env', label: 'Env', value: env, onChange: setEnv, placeholder: 's3', dataCb: 'fw-env', hint: '[env:…]' })),
    h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'quiet', size: 'sm', disabled: !changed || !dir.trim() || !env.trim(), 'data-cb': 'fw-save', onClick: () => setFirmwareDir(dir.trim(), env.trim()) }, 'Save folder'),
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'fw-example', title: 'Copy the laser-trigger example into this bench project (firmware/)',
        onClick: () => useExampleFirmware() }, 'Use example project')),
    note ? h('div', { className: 'cb-jobline cb-bad', role: 'alert' }, `✕ ${note.message}`, note.hint ? h('span', { className: 'cb-dim' }, note.hint) : null) : null)
}

function BuildCard({ project, n, primary }) {
  const jobs = sdk.useValue($jobs)
  const note = sdk.useValue($jobNote).build
  const flow = sdk.useValue($flow)
  const fw = project?.firmware || {}
  const b = fw.last_build
  const job = jobs.build
  const pr = jobProgress(job)
  const res = job?.state === 'done' ? job.result?.result : null
  const sim = job ? Boolean(job.result?.simulated) : Boolean(project?.simulated)
  return h(Section, { n, title: 'build', dataCb: 'flash-build', tone: pr.running ? 'active' : undefined,
    aside: b ? h('span', { className: b.ok ? 'cb-ok' : 'cb-bad' }, b.ok ? `✓ ${formatClock(b.at)}` : '✕ failed') : h('span', { className: 'cb-dim' }, 'not built') },
  b?.ok ? h('div', { className: 'cb-build', 'data-cb': 'build-result' },
    h('div', { className: 'cb-meter' }, h(Label, null, 'ram'), h(Bar, { pct: b.ram_pct, tone: b.ram_pct > 85 ? 'warn' : 'ok', label: 'RAM' }), h('b', null, formatPct(b.ram_pct))),
    h('div', { className: 'cb-meter' }, h(Label, null, 'flash'), h(Bar, { pct: b.flash_pct, tone: b.flash_pct > 85 ? 'warn' : 'ok', label: 'Flash' }), h('b', null, formatPct(b.flash_pct))),
    h('div', { className: 'cb-kv', style: { marginTop: '6px' } },
      h('span', null, sim ? 'firmware hash' : 'elf sha256'), h('b', null, h(FlashHashShort, { hash: b.elf_sha256 })),
      h('span', null, 'duration'), h('b', null, res?.duration_s ? formatDuration(res.duration_s) : '—')),
    sim ? h('div', { className: 'cb-hintline' }, h('span', { className: 'cb-active' }, '◌'), 'Simulated build: the hash covers the sources, no ELF is produced.') : null)
    : h('p', { className: 'cb-why cb-dim' }, fw.dir ? 'Build the firmware before flashing. The build never uploads.' : 'Set a firmware folder first.'),
  h(JobLine, { job, note, kind: 'build' }),
  h('div', { className: 'cb-actions' },
    h(Btn, { kind: primary ? 'primary' : 'ghost', size: 'sm', disabled: !fw.dir || pr.running, 'data-cb': 'build-start',
      'data-cb-focus': flow.focus === 'build' ? 'true' : undefined, onClick: () => buildFirmware() }, pr.running ? 'Building…' : b?.ok ? 'Build again' : 'Build firmware')))
}

/** The backend's answer why the flash would be refused (GET /board/flash/check), under the locked button. */
function FlashGateNote({ gate }) {
  const settings = gate.code === 'flash_disabled' || gate.code === 'sim_only'
  return h('div', { id: 'cb-flash-gate', className: 'cb-shints cb-vf-gate', 'data-cb': 'flash-gate', 'data-cb-code': gate.code, role: 'status' },
    h('div', { className: 'cb-shint cb-shint--danger' }, h('span', { className: 'cb-shint-sym', 'aria-hidden': 'true' }, '⊗'),
      h('span', { className: 'cb-shint-cat' }, 'locked'),
      h('span', { className: 'cb-shint-t' }, h('b', { 'data-cb': 'flash-gate-msg' }, gate.message),
        gate.hint ? h('span', { className: 'cb-vf-gate-hint', 'data-cb': 'flash-gate-hint' }, gate.hint) : null,
        settings ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'agent-settings-link', onClick: () => openAgentSettings() }, 'Agent settings ›') : null)))
}

function FlashCard({ project, n, primary }) {
  const jobs = sdk.useValue($jobs)
  const note = sdk.useValue($jobNote).flash
  const fc = sdk.useValue($flashCheck)
  const conf = flashConfirm(project)
  const pr = jobProgress(jobs.flash)
  const f = project?.firmware?.last_flash
  const gate = flashGate(fc.project === project?.id ? fc.env : null)
  const locked = gate.state === 'locked'
  const solderHint = flashSolderHint(project, conf.confirm?.port || project?.board?.detected?.port)
  return h(Section, { n, title: 'flash', dataCb: 'flash-flash', tone: pr.running ? 'active' : undefined,
    aside: f ? h('span', { className: f.ok ? 'cb-ok' : 'cb-bad' }, f.ok ? `✓ ${formatClock(f.at)}` : '✕ failed') : h('span', { className: 'cb-dim' }, 'not flashed') },
  conf.ok ? h('div', { className: 'cb-kv', 'data-cb': 'flash-preview' },
    h('span', null, 'port'), h('b', { className: 'cb-kv-port' }, h('span', { className: 'cb-ellip', title: conf.confirm.port, 'data-cb-truncate-ok': '' }, conf.confirm.port),
      conf.simulated ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-confirm' }) : null),
    h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, conf.confirm.mac),
    h('span', null, 'firmware'), h('b', null, h(FlashHashShort, { hash: conf.confirm.elf_sha256 })),
    conf.alreadyFlashed ? [h('span', { key: 'a' }, 'state'), h('b', { key: 'b', className: 'cb-ok' }, '✓ this build is on the board')] : null)
    : locked ? null : h('p', { className: 'cb-why cb-dim', 'data-cb': 'flash-missing' }, `Needs ${conf.missing.includes('detect') ? 'a detected board' : ''}${conf.missing.includes('detect') && conf.missing.includes('build') ? ' and ' : ''}${conf.missing.includes('build') ? 'a successful build' : ''}${!conf.missing.includes('detect') && conf.missing.includes('mac') ? 'the board MAC (detect again)' : ''}.`),
  solderHint ? h('div', { className: 'cb-hintline cb-warn', 'data-cb': 'flash-solder-hint', title: 'Only a hint: flashing stays possible' }, `! ${solderHint}`,
    h('button', { type: 'button', className: 'cb-linkbtn', onClick: () => goStation('solder') }, '04 SOLDER ›')) : null,
  h(JobLine, { job: jobs.flash, note, kind: 'flash' }),
  h(FlashMap, { job: jobs.flash }),
  h('div', { className: 'cb-actions' },
    h(Btn, { kind: primary && !locked ? 'warn' : 'ghost', size: 'sm', disabled: !conf.ok || pr.running || locked, 'data-cb': 'flash-start',
      'data-cb-gate': gate.state, 'aria-describedby': locked ? 'cb-flash-gate' : undefined,
      title: locked ? `Locked: ${gate.message}` : 'Opens the confirmation dialog; nothing is written before you confirm', onClick: () => patchAtom($ui, { modal: { type: 'flash', confirm: conf.confirm } }) },
    pr.running ? 'Flashing…' : locked ? '⊗ Flash locked' : 'Flash ›')),
  locked ? h(FlashGateNote, { gate }) : null)
}

/** The first two groups of a hash (the dialog shows all eight); the full hash in the title. */
function FlashHashShort({ hash }) {
  const g = flashHashGroups(hash)
  if (g.length !== 8) return h('span', { className: 'cb-mono-num', title: hash || '' }, hash ? shortHash(hash, 16) : '—')
  return h('span', { className: 'cb-vf-hashshort cb-mono-num', title: hash, 'data-cb-truncate-ok': '' }, h('span', null, g[0]), h('span', null, g[1]), h('span', { className: 'cb-dim', 'aria-hidden': 'true' }, '…'))
}

/** Flash map after a real flash: the written images (result.images) as marks on an address axis, offsets and names
 *  only. The simulated flash reports no images: then nothing is drawn (nothing is estimated). */
function FlashMap({ job }) {
  const res = job?.state === 'done' && job.result?.ok ? job.result.result : null
  const map = flashMapMarks(res?.images)
  if (!map) return null
  return h('div', { className: 'cb-vf-map', 'data-cb': 'flash-map' },
    h(Label, null, `// written · ${map.marks.length} image${map.marks.length === 1 ? '' : 's'}`),
    h('div', { className: 'cb-vf-axis', role: 'img', 'aria-label': `Address axis: ${map.marks.map(m => `${m.name} at ${m.offset}`).join(', ')}` },
      h('span', { className: 'cb-vf-axis-line', 'aria-hidden': 'true' }),
      map.marks.map((m, i) => h('span', { key: m.offset, className: cx('cb-vf-mark', i % 2 && 'cb-vf-mark--lo'), style: { left: `${m.frac * 100}%` }, 'aria-hidden': 'true',
        'data-cb-offset': m.offset }, h('i', null), h('b', null, m.n)))),
    h('ol', { className: 'cb-vf-legend' }, map.marks.map(m => h('li', { key: m.offset, 'data-cb': 'flash-map-image', 'data-cb-offset': m.offset },
      h('b', { className: 'cb-vf-n', 'aria-hidden': 'true' }, m.n), h('span', { className: 'cb-mono-num' }, m.offset), h('span', { className: 'cb-vf-name' }, m.name),
      m.sha256 ? h('span', { className: 'cb-dim cb-mono-num', title: m.sha256 }, shortHash(m.sha256, 8)) : null))))
}

function StationFlash({ project }) {
  const ports = sdk.useValue($ports)
  const flow = sdk.useValue($flow)
  const bench = sdk.useValue($bench)
  const health = bench.health
  const note = sdk.useValue($jobNote).detect
  const jobs = sdk.useValue($jobs)
  useEffect(() => {
    if (!flow.port || !(ports.ports || []).some(p => p.device === flow.port)) {
      const d = defaultPort(ports.ports, project?.board?.detected?.port)
      if (d && d !== flow.port) selectPort(d)
    }
  }, [ports.ports, project?.board?.detected?.port])
  useEffect(() => {
    if (!flow.focus) return undefined
    const t = timersOf(CB.ctx).setTimeout(() => patchAtom($flow, { focus: null }), 4000)
    return () => timersOf(CB.ctx).clearTimeout(t)
  }, [flow.focus, flow.at])
  // ask again on open, per project revision (agent, jobs), port and settings change; jobs ask too (26-live.js)
  useEffect(() => { refreshFlashCheck() }, [project?.id, project?.rev, flow.port, health?.epoch, health?.allow_flash, health?.hardware_access])
  const step = nextFlashStep(project, ports)
  const det = project?.board?.detected
  const simulated = isSimPort(flow.port) || isSimPort(det?.port)
  return [
    h('main', { key: 'main', className: 'cb-main cb-station', 'data-cb': 'station-flash', 'data-cb-next': step },
      h(DecodeTitle, { text: '05 // BUILD & FLASH', meta: 'nothing is flashed without your confirmation' }),
      simulated ? h('div', { className: 'cb-simrow' }, h(SimBanner, null), h('span', { className: 'cb-dim' }, 'Nothing physical is written. The dialog still checks port, MAC and firmware.')) : null,
      h('div', { className: 'cb-flashgrid' },
        h(Section, { n: '1', title: 'board', dataCb: 'flash-board', tone: jobProgress(jobs.detect).running ? 'active' : undefined,
          aside: det ? h('span', { className: 'cb-ok', title: det.description || '' }, `✓ ${formatClock(det.at)}`) : h('span', { className: 'cb-dim' }, 'not detected') },
        h(PortList, { ports, project, flow, health }),
        h(JobLine, { job: jobs.detect, note, kind: 'detect' }),
        h(DetectResult, { project })),
        h(FirmwareCard, { project, n: '2' }),
        h(BuildCard, { project, n: '3', primary: step === 'build' }),
        h(FlashCard, { project, n: '4', primary: step === 'flash' }))),
    h('aside', { key: 'insp', className: 'cb-insp', 'data-cb': 'insp', 'aria-label': 'Inspector' }, h(FlashInspector, { project, step }))
  ]
}

function FlashInspector({ project, step }) {
  const fw = project?.firmware || {}
  const det = project?.board?.detected
  const jobs = sdk.useValue($jobs)
  const STEP_TEXT = { detect: 'Pick a port and press Detect. Detection reads the chip, MAC and flash size.',
    firmware: 'Set a PlatformIO folder or copy the example project.', build: 'Build the firmware. The ELF hash becomes part of the flash confirmation.',
    flash: 'Flash opens a dialog with board, MAC, port and firmware hash. Nothing is written before you confirm.',
    done: 'This build is on the board. Open 06 DEBUG to watch the serial output.' }
  const tail = (jobs.detect?.log_tail || []).slice(-6)
  return [
    h('div', { key: 'n', className: 'cb-card cb-bracket', 'data-cb': 'flash-next' },
      h(Label, null, '// next step'),
      h('p', { className: 'cb-why' }, STEP_TEXT[step]),
      step === 'done' ? h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'goto-debug', onClick: () => goStation('debug') }, 'Open 06 DEBUG ›')) : null),
    // the live twin of the board (30-ui-board.js FlashTwin)
    h(FlashTwin, { key: 't', project }),
    h('div', { key: 'r', className: 'cb-card', 'data-cb': 'flash-records' },
      h(Label, null, '// records'),
      h('div', { className: 'cb-kv', style: { marginTop: '8px' } },
        h('span', null, 'board'), h('b', null, det ? `${det.chip?.replace(/\s*\(revision.*$/, '') || '—'}` : '—'),
        h('span', null, 'port'), h('b', null, det?.port || '—'),
        h('span', null, 'build'), h('b', { className: fw.last_build?.ok ? 'cb-ok' : fw.last_build ? 'cb-bad' : 'cb-dim' }, fw.last_build ? `${fw.last_build.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_build.at)}` : '—'),
        h('span', null, 'flash'), h('b', { className: fw.last_flash?.ok ? 'cb-ok' : fw.last_flash ? 'cb-bad' : 'cb-dim' }, fw.last_flash ? `${fw.last_flash.ok ? 'ok' : 'failed'} · ${formatClock(fw.last_flash.at)}` : '—'),
        h('span', null, 'env'), h('b', null, fw.env || '—'))),
    tail.length ? h('div', { key: 'l', className: 'cb-card', 'data-cb': 'detect-log' }, h(Label, null, '// detect log'),
      h('pre', { className: 'cb-pre' }, tail.join('\n'))) : null
  ]
}

/** Hash in eight groups of eight with a copy button; the text stays one contiguous hash (title, search, e2e). */
function FlashHash({ hash, label }) {
  const [copied, setCopied] = useState(null)
  const groups = flashHashGroups(hash)
  const canCopy = typeof CB.ctx?.os?.writeClipboard === 'function' && groups.length > 0
  const copy = async () => {
    let ok = false
    try { ok = (await CB.ctx.os.writeClipboard(String(hash))) !== false } catch { ok = false }
    setCopied(ok ? 'ok' : 'fail')
    timersOf(CB.ctx).setTimeout(() => setCopied(null), 1600)
  }
  return h('div', { className: 'cb-vf-hashrow' },
    h('div', { className: 'cb-vf-hash cb-mono-num', 'data-cb': 'flash-hash', title: hash || '', 'aria-label': `${label} ${hash || 'none'}` },
      groups.length ? groups.map((g, i) => h('span', { key: i, className: 'cb-vf-hg' }, g)) : '—'),
    canCopy ? h('button', { type: 'button', className: 'cb-iconbtn cb-vf-copy', 'data-cb': 'flash-hash-copy', onClick: copy,
      'aria-label': copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : `Copy the ${label}`, title: `Copy the full ${label} to the clipboard` },
    copied === 'ok' ? '✓ copied' : copied === 'fail' ? '✕ not copied' : '⧉ copy') : null)
}

const FLASH_CHECK_MARK = { match: { s: '✓', t: 'ok' }, differs: { s: '✕', t: 'bad' }, unchecked: { s: '○', t: 'dim' } }

/** Flash confirmation (own modal in the Bench look): target, firmware hash, memory use, check list in words, warning.
 *  The confirm object (port, mac, elf_sha256) goes to the backend unchanged; the primary button only starts it. */
function FlashDialog({ confirm, onClose }) {
  const project = sdk.useValue($project)
  const jobs = sdk.useValue($jobs)
  const [busy, setBusy] = useState(false)
  const wrap = useRef(null)
  const det = project?.board?.detected || {}
  const b = project?.firmware?.last_build || {}
  const sim = isSimPort(confirm?.port)
  const hashLabel = sim ? 'firmware hash' : 'elf sha256'
  const buildRes = jobs.build?.state === 'done' && jobs.build.result?.ok ? jobs.build.result.result : null
  const mem = flashMemRows(b, buildRes)
  const checks = flashCheckRows(confirm, project)
  // the first focus stays on Cancel as before (Modal focuses the first focusable; the copy button comes earlier).
  // Modal renders the content box straight into the dialog element, so its parent is the dialog.
  useEffect(() => {
    const dialog = wrap.current?.parentNode
    dialog?.querySelector?.('[data-cb=flash-cancel]')?.focus?.()
  }, [])
  const go = async () => {
    setBusy(true)
    const env = await flashFirmware(confirm)
    setBusy(false)
    if (env) onClose()
  }
  const kib = n => `${(n / 1024).toFixed(1)} KiB`
  return h(Modal, { title: 'Flash firmware', onClose, dataCb: 'flash-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose, 'data-cb': 'flash-cancel' }, 'Cancel'),
      h(Btn, { key: 'f', kind: 'warn', onClick: go, disabled: busy, 'data-cb': 'flash-confirm' }, busy ? 'Starting…' : sim ? 'Flash simulated board ›' : 'Flash board ›')] },
  h('div', { className: 'cb-vf-dlg', ref: wrap },
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-target' },
      h(Label, null, '// target'),
      h('div', { className: 'cb-kv cb-kv--dialog' },
        h('span', null, 'board'), h('b', null, det.description || det.chip || '—'),
        h('span', null, 'port'), h('b', { className: 'cb-kv-port' }, h('span', { className: 'cb-ellip', title: confirm?.port || '', 'data-cb-truncate-ok': '' }, confirm?.port || '—'),
          sim ? h(SimBadge, { compact: true, short: true, dataCb: 'sim-badge-dialog' }) : null),
        h('span', null, 'mac'), h('b', { className: 'cb-mono-num' }, confirm?.mac || '—'))),
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-firmware-block' },
      h(Label, null, `// ${hashLabel}`, flashHashGroups(confirm?.elf_sha256).length === 8 ? h('span', { className: 'cb-vf-algo' }, ' · sha-256 · 8 × 8') : null),
      h(FlashHash, { hash: confirm?.elf_sha256, label: hashLabel }),
      mem.length ? h('div', { className: 'cb-vf-mem', 'data-cb': 'flash-mem' }, mem.map(m => h('div', { key: m.id, className: 'cb-vf-meter', 'data-cb': `flash-mem-${m.id}` },
        h(Label, null, `${m.id} used`), h(Bar, { pct: m.pct, tone: m.pct > 85 ? 'warn' : 'ok', label: `${m.label} used` }), h('b', { className: 'cb-mono-num' }, formatPct(m.pct)),
        m.used !== null ? h('span', { className: 'cb-dim cb-mono-num' }, `${kib(m.used)} of ${kib(m.total)}`) : null))) : null),
    h('div', { className: 'cb-vf-block', 'data-cb': 'flash-checks' },
      h(Label, null, '// checks'),
      h('ul', { className: 'cb-vf-checks' }, checks.map(c => {
        const m = FLASH_CHECK_MARK[c.state]
        return h('li', { key: c.id, className: `cb-vf-chk cb-vf-chk--${c.state}`, 'data-cb': `flash-check-${c.id}`, 'data-cb-state': c.state },
          h('span', { className: `cb-vf-chk-s cb-${m.t}`, 'aria-hidden': 'true' }, m.s),
          h('span', { className: `cb-vf-chk-w cb-${m.t}` }, c.word),
          // the build time wraps as one unit
          h('span', { className: 'cb-vf-chk-t' }, c.text, c.at ? ' ' : null, c.at ? h('span', { className: 'cb-dim cb-mono-num cb-vf-chk-at' }, `· built ${formatStamp(c.at)}`) : null))
      }))),
    !sim && flashSolderHint(project, confirm?.port) ? h('div', { className: 'cb-hintline cb-warn', 'data-cb': 'flash-dialog-solder' }, `! ${flashSolderHint(project, confirm?.port)}`) : null,
    h('div', { className: `cb-note ${sim ? '' : 'cb-note--warn'}`, style: { marginTop: '12px', marginBottom: 0, alignItems: 'flex-start' } },
      h('span', null, sim ? '◌' : '!'),
      h('span', null, sim ? 'Simulated board: nothing physical is written. Port, MAC and firmware are still checked against the detection and the last build.'
        : 'This writes the firmware to the board and restarts it. Keep loads such as a laser module unpowered while flashing. Circuit Bench never erases flash.'))))
}

function VariantDialog({ variant, onClose }) {
  const project = sdk.useValue($project)
  return h(Modal, { title: 'Use the detected module variant', onClose, dataCb: 'variant-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 'o', 'data-cb': 'variant-confirm', onClick: async () => { await applyVariant(variant); onClose() } }, `Use ${String(variant).toUpperCase()} ›`)] },
  h('p', { className: 'cb-why' }, `The board reports ${String(variant).toUpperCase()}; the project uses ${String(project?.board?.variant || '—').toUpperCase()}. `,
    'Switching re-checks every pin assignment against the new module (PSRAM pins differ).'))
}

function ExampleOverwriteDialog({ onClose }) {
  return h(Modal, { title: 'Replace the firmware folder?', onClose, dataCb: 'example-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Keep my files'),
      h(Btn, { key: 'o', kind: 'warn', 'data-cb': 'example-overwrite', onClick: async () => { await useExampleFirmware({ overwrite: true }); onClose() } }, 'Replace with the example ›')] },
  h('p', { className: 'cb-why' }, 'The project already has a firmware folder. Copying the example replaces it, including changes from a fix (for example in src/main.cpp).'))
}

STATION_VIEWS.flash = { component: StationFlash, inspector: true }

// --- 45-station-debug.js
// Station 06 DEBUG: the serial monitor opens only on a click (POST /serial/open → socket, polling fallback after
// 3 s), panic analysis from crash.decode, "Fix with Hermes" as a composer draft (never sent).

function MonitorCard({ project }) {
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const ports = sdk.useValue($ports)
  const det = project?.board?.detected?.port || null
  const rows = portRows(ports.ports, { detectedPort: det })
  const [port, setPort] = useState(mon.port || det || defaultPort(ports.ports, det))
  useEffect(() => { if (!port) setPort(mon.port || det || defaultPort(ports.ports, det)) }, [ports.ports, det])
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const buf = open ? serial.buf : null
  const nLines = buf ? buf.lines.filter(l => l.k === 'line').length : 0
  const modeText = mon.mode === 'socket' ? 'live stream' : mon.mode === 'poll' ? 'polling fallback (1 s)' : mon.mode === 'connecting' ? 'connecting…' : '—'
  const sim = isSimPort(open ? mon.port : port)
  return h(Section, { title: 'serial monitor', dataCb: 'monitor', tone: open ? 'active' : undefined,
    aside: h('span', { className: open ? 'cb-ok' : 'cb-dim', 'data-cb': 'monitor-state' }, open ? `● ${String(mon.status).toUpperCase()}` : '○ CLOSED') },
  h('div', { className: 'cb-monrow' },
    h('label', { className: 'cb-label', htmlFor: 'cb-mon-port' }, 'port'),
    h('select', { id: 'cb-mon-port', value: open ? mon.port : port || '', disabled: open, 'data-cb': 'monitor-port', onChange: e => setPort(e.target.value) },
      rows.map(r => h('option', { key: r.device, value: r.device, title: r.simulated ? 'simulated board' : r.description }, r.device))),
    open ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'monitor-close', onClick: () => closeMonitor() }, 'Close monitor')
      : h(Btn, { size: 'sm', disabled: !port || mon.opening, 'data-cb': 'monitor-open', title: sim ? 'Open the simulated board' : 'Open the port (DTR/RTS stay inactive; some boards still restart)',
        onClick: () => openMonitor(port) }, mon.opening ? 'Opening…' : 'Open monitor ›'),
    open && !sim ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'monitor-restart', disabled: mon.opening,
      title: 'Pulse EN (RTS) with BOOT released: the firmware restarts from flash; also leaves the download mode',
      onClick: () => openMonitor(mon.port, { reset: true }) }, 'Restart board') : null,
    sim && !open ? h(SimBanner, { compact: true }) : null),
  open && !sim && waitsForDownload(buf) ? h('div', { className: 'cb-jobline cb-warn', role: 'status', 'data-cb': 'monitor-download' },
    '! The board waits in download mode (after a flash or BOOT).',
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'monitor-download-restart', onClick: () => openMonitor(mon.port, { reset: true }) }, 'Restart board ›')) : null,
  h('div', { className: 'cb-kv', style: { marginTop: '10px' } },
    h('span', null, 'stream'), h('b', { className: mon.mode === 'poll' ? 'cb-warn' : mon.mode === 'socket' ? 'cb-ok' : 'cb-dim', 'data-cb': 'monitor-mode' }, open ? modeText : '—'),
    h('span', null, 'lines'), h('b', { className: 'cb-mono-num' }, open ? `${nLines} · next seq ${(buf?.lastSeq || 0) + 1}` : '—'),
    h('span', null, 'reset'), h('b', null, 'no reset on open (DTR/RTS inactive)')),
  mon.error ? h('div', { className: 'cb-jobline cb-bad', role: 'alert', 'data-cb': 'monitor-error' }, `✕ ${mon.error.message}`, mon.error.hint ? h('span', { className: 'cb-dim' }, mon.error.hint) : null) : null,
  !open && !mon.error ? h('p', { className: 'cb-why cb-dim' }, 'Nothing is opened automatically. The console below shows the live log once the monitor is open.') : null,
  // the live twin of the board (30-ui-board.js DebugTwin)
  h(DebugTwin, { project }))
}

/** Long core paths (…/cores/esp32/main.cpp) keep their last two segments; the full path is the title. */
function shortFramePath(file) {
  const f = String(file || '?')
  if (f.length <= 26) return f
  const parts = f.split('/')
  return parts.length > 2 ? `…/${parts.slice(-2).join('/')}` : f
}

/** The newest output is the ROM waiting in download mode ("waiting for download"): the firmware does not run. */
function waitsForDownload(buf) {
  const lines = buf?.lines || []
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i]
    if (l.k !== 'line' || !String(l.text || '').trim()) continue
    return /waiting for download/i.test(l.text)
  }
  return false
}

/** The fix loop of the demo as a checklist: panic → draft → build → flash → boot ok (state from project + log). */
function fixLoopSteps(project, serial, flow) {
  const panic = project?.debug?.last_panic
  if (!panic?.at) return null
  const t = iso => (iso ? Date.parse(iso) : NaN)
  const pAt = t(panic.at)
  const b = project.firmware?.last_build
  const f = project.firmware?.last_flash
  // a reboot loop keeps reporting the panic while the fix is built: a flash of the current build after the last panic
  // also proves the rebuild (the panic record carries no firmware hash)
  const flashedAfter = Boolean(b?.ok && f?.ok && t(f.at) > pAt && f.elf_sha256 === b.elf_sha256)
  const built = Boolean(b?.ok && (t(b.at) > pAt || flashedAfter))
  const flashed = built && flashedAfter
  const boot = lastLineMatching(serial.buf, /\bboot ok\b/i)
  const mark = flow?.flashMark
  const clean = flashed && mark && mark.elf === f.elf_sha256 && (mark.epoch ?? null) === (serial.buf.epoch ?? null) ? cleanRunAfter(serial.buf, mark.seq) : null
  const live = serialPanicLive(serial.buf, project)
  const booted = Boolean(flashed && (boot || clean) && !live)
  const drafted = Boolean(flow.fixDraftAt) || built
  const steps = [
    { id: 'panic', label: 'panic caught', done: true, detail: `${panic.reason || 'panic'} · ${formatClock(panic.at)}` },
    { id: 'draft', label: 'fix drafted', done: drafted, detail: built ? 'fix in the source' : drafted ? 'composer draft (you send it)' : 'use Fix with Hermes' },
    { id: 'build', label: 'firmware rebuilt', done: built, detail: built ? `${project.simulated ? 'firmware hash' : 'elf'} ${String(b.elf_sha256 || '').slice(0, 12)}…` : 'after the fix' },
    { id: 'flash', label: 'flashed', done: flashed, detail: flashed ? `${formatClock(f.at)} · ${f.port || ''}` : 'with confirmation' },
    { id: 'boot', label: 'boot ok', done: booted, detail: booted ? (boot ? boot.text : `runs without panic · ${clean.n} lines`) : 'serial log' }
  ]
  const cur = steps.findIndex(s => !s.done)
  return steps.map((s, i) => ({ ...s, current: i === cur }))
}

function FixLoopCard({ project }) {
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const steps = fixLoopSteps(project, serial, flow)
  if (!steps) return null
  const done = steps.filter(s => s.done).length
  const cur = steps.find(s => s.current)
  const all = done === steps.length
  return h(Section, { title: 'fix loop', dataCb: 'fix-loop', tone: all ? undefined : 'active',
    aside: h('span', { className: all ? 'cb-ok' : 'cb-active', 'data-cb': 'fix-loop-count', 'aria-label': `fix loop: ${done} of ${steps.length} steps done`,
      title: `${done} of ${steps.length} steps done` }, all ? '✓ CLOSED' : `${done}/${steps.length} done`) },
  h('ol', { className: 'cb-loop' }, steps.map(s => h('li', { key: s.id, className: cx('cb-loop-step', s.done && 'cb-loop-step--done', s.current && 'cb-loop-step--cur'), 'data-cb': `loop-${s.id}`,
    'data-cb-done': s.done ? 'true' : 'false' },
  h('span', { className: s.done ? 'cb-ok' : s.current ? 'cb-active' : 'cb-dim', 'aria-hidden': 'true' }, s.done ? '✓' : s.current ? '▸' : '○'),
  h('b', null, s.label), h('span', { className: 'cb-dim cb-ellip', title: s.detail }, s.detail)))),
  cur && (cur.id === 'build' || cur.id === 'flash')
    ? h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'loop-goto-flash', onClick: () => goStation('flash') }, '05 FLASH ›')) : null)
}

function PanicAnalysis({ project }) {
  const { data, env, status } = usePanicData(project)
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const [busy, setBusy] = useState(false)
  const [showDraft, setShowDraft] = useState(false)
  if (!data) {
    const bootOk = lastLineMatching(serial.buf, /\bboot ok\b/i)
    const mark = flow?.flashMark
    const clean = !bootOk && mark && (mark.epoch ?? null) === (serial.buf.epoch ?? null) ? cleanRunAfter(serial.buf, mark.seq) : null
    const stale = project?.debug?.last_panic && !projectPanicCurrent(project)
    const fixed = fixLoopFixed(project, serial, flow)
    return h(Section, { title: bootOk || clean ? 'firmware status' : 'panic', dataCb: 'debug-calm', tone: fixed ? 'ok' : undefined,
      aside: h('span', { className: bootOk || clean ? 'cb-ok' : 'cb-dim' }, bootOk || clean ? '✓ RUNNING' : 'no panic') },
    fixed ? h('div', { className: 'cb-fixed', 'data-cb': 'fixed-row' }, h(Stamp, { tone: 'ok', 'data-cb': 'fixed-stamp' }, bootOk ? '✓ FIXED · boot ok' : '✓ FIXED · runs'),
      h('span', { className: 'cb-dim' }, `${project.debug.last_panic.reason || 'panic'} gone after the flash at ${formatClock(project.firmware.last_flash.at)}`)) : null,
    bootOk ? h('div', { className: 'cb-bootok', 'data-cb': 'boot-ok' }, h('span', { className: 'cb-ok' }, '✓'), h('code', null, bootOk.text),
      h('span', { className: 'cb-dim' }, `seq ${bootOk.seq}${bootOk.ts ? ` · ${bootOk.ts}` : ''}`))
      : clean ? h('div', { className: 'cb-bootok', 'data-cb': 'run-ok' }, h('span', { className: 'cb-ok' }, '✓'), h('code', null, clean.last.text),
        h('span', { className: 'cb-dim' }, `${clean.n} lines since the flash, no panic`)) : null,
    fixed ? null : h('p', { className: 'cb-why cb-dim' }, stale ? `The last panic (${project.debug.last_panic.reason}, ${formatClock(project.debug.last_panic.at)}) happened before the last flash.`
      : 'No panic on the current firmware. Panics are caught from the serial log and decoded automatically.'))
  }
  const fix = async () => {
    setBusy(true)
    try { await fixWithHermes(project, data, env) } finally { setBusy(false) }
  }
  const draft = fixWithHermesText(project, env || { summary: data.summary, result: { reason: data.reason, core: data.core, frames: data.frames.map(f => ({ i: f.i, function: f.fn, file: f.file, line: f.line })) } })
  const extra = data.decoded ? data.extra : data.interpretation
  const srcs = (env?.sources || []).filter(s => data.interpretation.some(x => x.source_id === s.id))
  const src = sourceTarget(project, data.top)
  const elf = elfWords(data.elf)
  // no stamp here: the panic anchor in the station head carries "PANIC · reason · core" once
  return h(Section, { title: 'panic analysis', dataCb: 'panic-analysis', tone: 'bad', className: 'cb-bracket cb-bracket--bad cb-pa',
    // no SIM badge here: HUD and console carry it; the ELF line says "simulated build"
    aside: data.decoded ? null : h(Label, null, status === 'loading' ? 'decoding…' : 'not decoded') },
  h('div', { 'data-cb-audit-root': 'panic', className: 'cb-pa-body' },
    data.decoded && data.summary ? h('p', { className: 'cb-pa-lead', 'data-cb': 'panic-summary' }, data.summary) : null,
    elf ? h('div', { className: `cb-elfline cb-elfline--${data.elf.tone}`, 'data-cb': 'elf-check', 'data-cb-status': data.elf.status, title: data.elf.detail || undefined },
      h('span', { className: 'cb-label' }, 'elf check'),
      h('span', { className: 'cb-elfline-v' }, h('span', { 'aria-hidden': 'true' }, elf.sym), ` ${elf.word}`),
      h('span', { className: 'cb-elfline-why' }, `· ${elf.reason}`)) : null,
    // the Hermes action right under the verdict (visible without scrolling, catalog 06)
    h('div', { className: 'cb-actions' },
      h(Btn, { kind: 'agent', onClick: fix, disabled: busy, 'data-cb': 'fix-with-hermes-main', title: 'Put a fix request into the chat composer (not sent)' }, busy ? 'Opening chat…' : 'Fix with Hermes'),
      src.show ? h(Btn, { kind: 'quiet', size: 'sm', disabled: !src.can, 'data-cb': 'open-source-main', title: src.title, onClick: () => openSource(src) }, src.label) : null,
      h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'draft-toggle', 'aria-expanded': showDraft ? 'true' : 'false', onClick: () => setShowDraft(!showDraft) }, showDraft ? 'Hide prompt' : 'Show prompt'),
      data.logRef ? h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'decode-again', onClick: () => decodePanic({ log_ref: data.logRef }) }, 'Decode again') : null),
    showDraft ? h('pre', { className: 'cb-pre cb-draft', 'data-cb': 'fix-draft' }, draft) : null,
    h('p', { className: 'cb-why cb-dim', style: { margin: '8px 0 0' } }, 'The prompt goes into the chat composer. Nothing is sent until you press Enter.'),
    data.frames.length ? h('table', { className: 'cb-table cb-frames-t', 'data-cb': 'panic-frames-full' },
      h('thead', null, h('tr', null, h('th', { className: 'cb-label' }, '#'), h('th', { className: 'cb-label' }, 'function'), h('th', { className: 'cb-label' }, 'file:line'), h('th', { className: 'cb-label cb-r' }, 'pc'))),
      h('tbody', null, data.frames.slice(0, 8).map((f, i) => h('tr', { key: f.i ?? i, className: cx(i === 0 && 'cb-frow--top', f.pc && 'cb-frow--link'), 'data-cb': `panic-frame-${f.i ?? i}`,
        tabIndex: f.pc ? 0 : undefined, title: f.pc ? `${f.pc}: marks this address in the Backtrace line of the log` : undefined, ...logMarkProps(frameMark(f)) },
        h('td', { className: 'cb-dim' }, `#${f.i}`), h('td', { className: i === 0 ? 'cb-bad' : 'cb-fg', title: f.fn }, f.short),
        h('td', { className: 'cb-active', title: `${f.file}:${f.line ?? '?'}` }, `${shortFramePath(f.file)}:${f.line ?? '?'}`), h('td', { className: 'cb-r cb-mono-num' }, f.pc))))) : null,
    data.bank?.key.length ? h(RegisterBank, { bank: data.bank }) : null,
    extra.length ? h('ul', { className: 'cb-interp', 'data-cb': 'panic-interp' }, extra.map(x => h('li', { key: x.code }, x.text))) : null,
    srcs.length ? h(SourceLine, { sources: srcs }) : null))
}

/** Key registers as labelled readouts (PC, EXCCAUSE, EXCVADDR or MEPC, MCAUSE, MTVAL) and the whole dump below,
 *  key registers highlighted there too. Hover or focus marks the register in the log's dump. */
function RegisterBank({ bank }) {
  return h('div', { className: 'cb-regbank', 'data-cb': 'panic-regs', 'data-cb-arch': bank.arch },
    h('div', { className: 'cb-regkeys' }, bank.key.map(r => h('div', { key: r.k, className: 'cb-regkey', 'data-cb': `reg-${r.k}`, tabIndex: 0,
      title: `${r.k}: ${r.label}${r.note ? ` (${r.note})` : ''}`, ...logMarkProps({ kind: 'reg', name: r.k, value: r.v }) },
    h('span', { className: 'cb-regkey-n' }, r.k), h('span', { className: 'cb-regkey-l' }, r.label),
    h('b', { className: 'cb-regkey-v cb-mono-num' }, r.v), r.note ? h('span', { className: 'cb-regkey-note' }, `= ${r.note}`) : null))),
    bank.all.length > bank.key.length ? h('details', { className: 'cb-regdump', 'data-cb': 'panic-regdump' },
      h('summary', null, h(Label, null, `register dump · ${bank.all.length}`)),
      h('div', { className: 'cb-reggrid' }, bank.all.map(r => h('span', { key: r.k, className: cx('cb-regcell', r.key && 'cb-regcell--key'), ...logMarkProps({ kind: 'reg', name: r.k, value: r.v }) },
        h('span', { className: 'cb-regcell-n' }, r.k), h('span', { className: 'cb-mono-num' }, r.v))))) : null)
}

/** Station-head anchor: the one PANIC statement of 06 DEBUG (reason · core, where it stopped). */
function PanicAnchor({ data }) {
  const top = data.top
  return h('div', { className: 'cb-panicanchor', 'data-cb': 'panic-anchor', role: 'status' },
    h(Stamp, { tone: 'bad', 'data-cb': 'panic-anchor-stamp' }, `PANIC · ${data.title}`),
    top && top.file && top.file !== '??' ? h('span', { className: 'cb-anchor-at' }, h('span', { className: 'cb-dim' }, 'in '), h('b', null, top.short),
      h('span', { className: 'cb-active' }, ` ${shortFramePath(top.file)}:${top.line ?? '?'}`)) : null)
}

/** The demo fix loop is closed: panic → (draft) → build → flash → boot ok on the new firmware (Wow 4). */
function fixLoopFixed(project, serial, flow) {
  const steps = fixLoopSteps(project, serial, flow)
  return Boolean(steps && steps.every(s => s.done))
}

function StationDebug({ project }) {
  const mon = sdk.useValue($monitor)
  const ui = sdk.useValue($ui)
  const serial = sdk.useValue($serial)
  const flow = sdk.useValue($flow)
  const open = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const pk = panicKey(project)
  // a panic that arrives while 06 is open counts as seen (the rail stops blinking)
  useEffect(() => {
    if (pk && ui.panicSeen !== pk) { patchAtom($ui, { panicSeen: pk }); store('panicSeen', pk) }
  }, [pk])
  const fixed = fixLoopFixed(project, serial, flow)
  const fixedKey = fixed ? `${pk}|${project.firmware?.last_flash?.at || ''}` : null
  // Wow 4: the rail lights up once, station after station, when the loop closes (static with reduced motion)
  useEffect(() => {
    if (fixedKey && ui.celebrated !== fixedKey) { patchAtom($ui, { celebrated: fixedKey, sweepAt: Date.now() }); store('celebrated', fixedKey) }
  }, [fixedKey])
  const { data } = usePanicData(project)
  const meta = fixed ? `firmware running${open ? ` · ${mon.port}` : ''}` : open ? `monitor open · ${mon.port}` : 'monitor opens only on your click'
  // reading order = DOM order: with a panic the analysis comes first, else the monitor
  const cards = data ? [h(PanicAnalysis, { key: 'p', project }), h(MonitorCard, { key: 'm', project }), h(FixLoopCard, { key: 'l', project })]
    : [h(MonitorCard, { key: 'm', project }), h(PanicAnalysis, { key: 'p', project }), h(FixLoopCard, { key: 'l', project })]
  return h('main', { className: 'cb-main cb-station', 'data-cb': 'station-debug', 'data-cb-audit-root': 'station' },
    h('div', { className: 'cb-dbghead' }, h(DecodeTitle, { text: '06 // SERIAL & PANIC', meta }), data ? h(PanicAnchor, { data }) : null),
    h('div', { className: 'cb-debuggrid', 'data-cb-panic': data ? 'true' : 'false' }, cards))
}

STATION_VIEWS.debug = { component: StationDebug, inspector: false }

// --- 46-dialogs.js
// Dialogs opened from the palette, the HUD or the empty state: new bench project, project manager, bench doctor.

const NEW_PROJECT_ID_RE = /^[a-z0-9-]{1,48}$/

function NewProjectDialog({ onClose }) {
  const [id, setId] = useState('')
  const [title, setTitle] = useState('')
  const [chip, setChip] = useState('esp32s3')
  const [devkit, setDevkit] = useState('esp32-s3-devkitc-1')
  const [variant, setVariant] = useState('n16r8')
  const [picked, setPicked] = useState(false) // the user chose the module (kept across boards of the same chip)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const info = chipInfo(chip)
  const kits = devkitsOf(chip)
  const kit = devkitInfo(resolveDevkit(chip, devkit))
  const okId = NEW_PROJECT_ID_RE.test(id)
  // board → module variant: the layout's module.variant unless the user chose one; empty on a board
  // with an unknown module (WT32-S1); a new chip starts from its default board's preset
  const pickChip = c => { const d = chipInfo(c)?.devkit ?? null; setChip(c); setDevkit(d); setVariant(defaultVariant(c, d) || ''); setPicked(false) }
  const pickDevkit = d => { setDevkit(d); if (!picked) setVariant(defaultVariant(chip, d) || '') }
  const pickVariant = v => { setVariant(v); setPicked(Boolean(v)) }
  const submit = async e => {
    e?.preventDefault?.()
    if (!okId || busy) return
    setBusy(true)
    setFail(null)
    const env = await createProject({ id, title: title.trim() || id, chip, ...(info?.variants?.length ? { variant: variant || null } : {}), ...(kit ? { devkit: kit.id } : {}) })
    setBusy(false)
    if (env?.ok) onClose()
    else setFail(env?.error?.message || 'Not created.')
  }
  return h(Modal, { title: 'New bench project', onClose, dataCb: 'new-project-dialog',
    footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Cancel'),
      h(Btn, { key: 's', onClick: submit, disabled: !okId || busy, 'data-cb': 'new-project-submit' }, busy ? 'Creating…' : 'Create ›')] },
  h('form', { className: 'cb-form', onSubmit: submit },
    h('label', { htmlFor: 'cb-np-id' }, 'Id'), h('input', { id: 'cb-np-id', value: id, placeholder: 'my-project', maxLength: 48, 'data-cb': 'new-project-id', autoComplete: 'off', spellCheck: false,
      onChange: e => setId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')) }),
    h('label', { htmlFor: 'cb-np-title' }, 'Title'), h('input', { id: 'cb-np-title', value: title, placeholder: 'optional', maxLength: 80, onChange: e => setTitle(e.target.value) }),
    h('label', { htmlFor: 'cb-np-chip' }, 'Chip'), h('select', { id: 'cb-np-chip', value: chip, 'data-cb': 'new-project-chip', onChange: e => pickChip(e.target.value) },
      CHIPS.map(c => h('option', { key: c.id, value: c.id }, c.label))),
    kits.length ? [h('label', { key: 'l', htmlFor: 'cb-np-kit' }, 'Board'), h('select', { key: 's', id: 'cb-np-kit', value: kit?.id || '', 'data-cb': 'new-project-devkit',
      onChange: e => pickDevkit(e.target.value) }, kits.map(d => h('option', { key: d.id, value: d.id }, devkitTitle(d))))] : null,
    info?.variants?.length ? [h('label', { key: 'l', htmlFor: 'cb-np-var' }, 'Module'), h('select', { key: 's', id: 'cb-np-var', value: variant || '', 'data-cb': 'new-project-variant',
      onChange: e => pickVariant(e.target.value) },
    h('option', { key: '-', value: '' }, kit?.module && !kit.variant ? `${kit.module} · variant not stated, set it later if you know it` : 'not set · set it later'),
    variantGroups(chip).map(g => h('optgroup', { key: g.label, label: g.label }, g.variants.map(v => h('option', { key: v.id, value: v.id }, `${v.label} · ${variantTitle(v)}`)))))] : null,
    h('button', { type: 'submit', className: 'cb-sr', tabIndex: -1 }, 'submit')),
  h('p', { className: 'cb-dim', style: { margin: '10px 0 0' } }, kit ? `Board view: ${devkitTitle(kit)}.` : 'No DevKit header map for this chip; pins are still checked.'),
  fail ? h('div', { className: 'cb-note cb-note--bad', style: { marginTop: '12px', marginBottom: 0 } }, fail) : null)
}

/** Project manager: every bench project with board and last change; open one, or move one to the trash (two clicks:
 *  Delete, then "Move to trash" in the row). The backend keeps the folder under trash/, nothing is erased. */
function ProjectsDialog({ onClose }) {
  const bench = sdk.useValue($bench)
  const current = sdk.useValue($project)?.id || null
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    let live = true
    refreshProjects().then(env => {
      if (!live) return
      setLoaded(true)
      if (!env.ok) setMsg({ tone: 'bad', text: env.error?.message || 'Could not list the projects.' })
    })
    return () => { live = false }
  }, [])
  const list = bench.projects || []
  const open = async id => {
    setBusy(id)
    await openProject(id)
    setBusy(null)
    onClose()
  }
  const del = async id => {
    setBusy(id)
    const env = await removeProject(id)
    setBusy(null)
    setConfirm(null)
    setMsg(env.ok ? { tone: 'ok', text: env.summary } : { tone: 'bad', text: env.error?.message || env.summary || 'Not deleted.' })
  }
  const boardText = p => {
    const v = variantInfo(p.chip, p.variant)
    return [devkitInfo(p.devkit)?.label || chipInfo(p.chip)?.label || p.chip, v?.label].filter(Boolean).join(' · ')
  }
  return h(Modal, { title: 'Bench projects', onClose, dataCb: 'projects-dialog', wide: true,
    footer: [h(Btn, { key: 'n', kind: 'ghost', 'data-cb': 'projects-new', onClick: () => patchAtom($ui, { modal: { type: 'new-project' } }) }, 'New project'),
      !list.some(p => p.id === 'laser-trigger') ? h(Btn, { key: 'd', kind: 'quiet', 'data-cb': 'projects-demo', onClick: async () => { onClose(); await loadDemo() } }, 'Load demo') : null,
      h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Close')] },
  !loaded && !list.length ? h('div', { className: 'cb-loading', style: { padding: '12px 0' } }, 'listing projects')
    : !list.length ? h('p', { className: 'cb-why cb-dim', 'data-cb': 'projects-empty' }, 'No bench projects yet.')
      : h('ul', { className: 'cb-projlist', 'data-cb': 'projects-list' }, list.map(p => {
        const here = p.id === current
        const asking = confirm === p.id
        return h('li', { key: p.id, className: 'cb-projrow', 'data-cb': 'project-row', 'data-cb-id': p.id, 'aria-current': here ? 'true' : undefined },
          h('div', { className: 'cb-projmain' },
            h('div', { className: 'cb-projtitle' }, h('span', { className: here ? 'cb-ok' : 'cb-dim', 'aria-hidden': 'true' }, here ? '▶' : '·'),
              h('b', null, p.id), p.title && p.title !== p.id ? h('span', { className: 'cb-dim cb-ellip', title: p.title, 'data-cb-truncate-ok': 'true' }, p.title) : null),
            // second line: the SIM badge first (it never gives way), then the meta text, which may end in an ellipsis
            h('div', { className: 'cb-projmeta cb-dim' },
              p.simulated ? h(SimBadge, { compact: true, dataCb: 'sim-badge-project' }) : null,
              h('span', { className: 'cb-ellip', title: `${boardText(p)} · rev ${p.rev} · ${formatStamp(p.updated)}`, 'data-cb-truncate-ok': 'true' },
                `${boardText(p)} · rev ${p.rev} · ${formatStamp(p.updated)}`))),
          asking
            ? h('div', { className: 'cb-projconfirm', role: 'group', 'aria-label': `Delete ${p.id}?` },
              h('span', { className: 'cb-warn' }, here ? 'Delete the open project?' : 'Delete?'),
              h(Btn, { kind: 'quiet', size: 'sm', onClick: () => setConfirm(null) }, 'Keep'),
              h(Btn, { kind: 'danger', size: 'sm', 'data-cb': 'project-delete-confirm', disabled: busy === p.id, onClick: () => del(p.id) },
                busy === p.id ? 'Moving…' : 'Move to trash'))
            : h('div', { className: 'cb-projact' },
              here ? h('span', { className: 'cb-tag' }, 'open') : h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'project-open', disabled: Boolean(busy), onClick: () => open(p.id) }, busy === p.id ? 'Opening…' : 'Open'),
              h(Btn, { kind: 'quiet', size: 'sm', 'data-cb': 'project-delete', disabled: Boolean(busy), title: `Move ${p.id} to the trash`, onClick: () => { setMsg(null); setConfirm(p.id) } }, 'Delete')))
      })),
  confirm ? h('p', { className: 'cb-dim', 'data-cb': 'projects-trash-note', style: { margin: '10px 0 0', lineHeight: 1.5 } },
    'The project folder (pins, parts, calculations, wiring, solder steps, a copied firmware/) moves to the bench trash folder; ',
    'nothing is erased, and firmware folders outside the project are not touched.') : null,
  msg ? h('div', { className: `cb-note cb-note--${msg.tone}`, 'data-cb': 'projects-msg', role: 'status', style: { marginTop: '12px', marginBottom: 0, wordBreak: 'break-word' } }, msg.text) : null)
}

function DoctorDialog({ env, onClose }) {
  const r = env?.ok ? env.result : null
  return h(Modal, { title: 'Bench doctor', onClose, dataCb: 'doctor-dialog', footer: [h(Btn, { key: 'c', kind: 'quiet', onClick: onClose }, 'Close'),
    h(Btn, { key: 'r', kind: 'ghost', onClick: () => runDoctor() }, 'Run again')] },
  !env ? h('div', { className: 'cb-loading', style: { padding: '12px 0' } }, 'checking tools')
    : !env.ok ? h('p', { className: 'cb-why cb-bad' }, `✕ ${env.error?.message || env.summary}`)
      : [h('p', { key: 's', className: 'cb-why' }, env.summary),
        h(ChecksList, { key: 'c', checks: env.checks, warnings: env.warnings, dataCb: 'doctor-checks' }),
        r?.hardware ? h('div', { key: 'h', className: 'cb-kv', style: { marginTop: '10px' } },
          h('span', null, 'hardware'), h('b', { className: r.hardware.enabled ? 'cb-ok' : 'cb-active' }, r.hardware.enabled ? 'on' : 'off (simulated boards only)'),
          h('span', null, 'allow flash'), h('b', null, r.settings?.allow_flash ? 'on' : 'off'),
          h('span', null, 'data'), h('b', { className: 'cb-ellip', title: r.data_dir?.path }, r.data_dir?.writable ? 'writable' : 'not writable')) : null])
}

// --- 47-dialog-modules.js
// Module dialog: openModules({q?, category?, interface?, module?, ref?, address?}); list → detail
// (add_module) or, with ref, the instance view

const MOD_CLASS_TITLE = { A: 'manufacturer', A1: 'manufacturer, archive copy', A2: 'manufacturer, third-party copy', B: 'unverified' }

function ModTags({ m }) {
  const ifs = modInterfaces(m.interfaces)
  const addrs = Array.isArray(m.addresses) ? m.addresses : modAddressChoices(m).list
  const sup = typeof m.supply === 'string' ? m.supply : modSupply(m.supplies)
  const cls = m.class || null
  return h('span', { className: 'cb-mod-tags' },
    ifs.map(t => h('span', { key: t, className: 'cb-mod-tag' }, t)),
    addrs.length ? h('span', { className: 'cb-mod-tag', title: `I²C addresses: ${modAddresses(addrs)}` },
      addrs.length > 3 ? `${modAddress(addrs[0])}–${modAddress(addrs[addrs.length - 1])} (${addrs.length})` : modAddresses(addrs)) : null,
    sup && sup !== '—' ? h('span', { className: 'cb-mod-tag cb-mod-tag--pwr', title: 'supply range' }, sup) : null,
    cls ? h('span', { className: `cb-mod-tag${cls === 'B' ? ' cb-mod-tag--warn' : ''}`, title: `source class ${cls}: ${MOD_CLASS_TITLE[cls] || cls}` },
      `${cls === 'B' ? '? ' : ''}class ${cls}`) : null)
}

const modShort = t => { const s = String(t || ''); const i = s.indexOf(' '); return i > 0 ? [s.slice(0, i), s.slice(i + 1)] : [s, ''] }

function ModulesDialog({ init = null, onClose }) {
  const project = sdk.useValue($project)
  const [q, setQ] = useState(init?.q || '')
  const [qx, setQx] = useState(init?.q || '')
  const [cat, setCat] = useState(init?.category || '')
  const startRef = init?.ref ? moduleInstances(project).find(i => i.ref === String(init.ref).toUpperCase()) : null
  const [pick, setPick] = useState(init?.module || startRef?.module || null)
  const box = useRef(null)
  const mem = useRef({ top: 0, id: null }) // list scroll + row picked in the list (restored by ‹ Catalog)
  useEffect(() => { const t = setTimeout(() => setQx(q.trim()), 200); return () => clearTimeout(t) }, [q])
  useEffect(() => {
    const dlg = box.current?.parentNode // the list box and ModuleDetail's box sit straight in the Modal dialog
    if (!pick && box.current) box.current.scrollTop = mem.current.top
    ;((pick ? dlg?.querySelector('[data-cb=modules-back]') : mem.current.id && dlg?.querySelector(`[data-cb=module-row][data-cb-id="${mem.current.id}"]`))
      || dlg?.querySelector('[data-cb=modules-search]'))?.focus?.({ preventScroll: true })
  }, [pick])
  const filter = { q: qx, category: cat, interface: init?.interface }
  const cat0 = useModuleCatalog(filter)
  const env = cat0.env
  const items = env?.ok ? env.result?.items || [] : []
  const total = env?.ok ? env.result?.total ?? items.length : 0
  const cats = modCategories(env?.ok ? env.result : null, ...(cat0.cats || []), cat)
  const info = useModuleInfo(pick)
  const pm = info.env?.ok ? info.env.result?.module ?? info.env.result : null
  const listed = pick && mem.current.id === pick
  const inst = listed || !startRef ? null : { ...startRef, address: startRef.address || init.address }
  // ↑/↓ between search and rows
  const keys = e => {
    const d = { ArrowDown: 1, ArrowUp: -1 }[e.key]
    const rows = [...box.current.querySelectorAll('[data-cb=modules-search],[data-cb=module-row]')]
    const i = rows.indexOf(document.activeElement)
    const to = d && i >= 0 && rows[i + d]
    if (to) { e.preventDefault(); to.focus() }
  }
  return h(Modal, { title: pick ? `${inst ? `${inst.ref} · ` : ''}${pm?.title || 'Module'}` : 'Module catalog', dataCb: 'modules-dialog', wide: true,
    onClose: listed ? () => setPick(null) : onClose, // Escape: back to the list
    footer: [pick ? h(Btn, { key: 'b', kind: 'quiet', onClick: () => setPick(null), 'data-cb': 'modules-back' }, '‹ Catalog') : null,
      h(Btn, { key: 'c', kind: 'quiet', onClick: onClose, 'data-cb': 'modules-close' }, 'Close')] },
  pick ? h(ModuleDetail, { id: pick, project, st: info, onClose, box, inst }) :
  h('div', { ref: box, className: 'cb-mod-dlg', onKeyDown: keys },
    h('div', { className: 'cb-mod-filter' },
      h('input', { className: 'cb-mod-search', 'data-cb': 'modules-search', 'aria-label': 'Search modules', value: q, maxLength: 40,
        placeholder: 'search: part, title, alias', autoComplete: 'off', spellCheck: false, onChange: e => setQ(e.target.value) }),
      h('select', { className: 'cb-mod-cat', 'data-cb': 'modules-category', 'aria-label': 'Category', value: cat, onChange: e => setCat(e.target.value) },
        h('option', { value: '' }, 'all categories'), cats.map(c => h('option', { key: c, value: c }, modCategoryLabel(c))))),
    cat0.status === 'loading' && !env ? h('div', { className: 'cb-loading cb-mod-pad' }, 'loading the catalog')
      : env && !env.ok ? h('p', { className: 'cb-why cb-bad', 'data-cb': 'modules-error' }, `✕ ${env.error?.message || env.summary}`)
        : [h('p', { key: 's', className: 'cb-mod-sum', 'data-cb': 'modules-summary', role: 'status' },
          items.length ? `${items.length} of ${total} module${total === 1 ? '' : 's'}${cat ? ` · ${modCategoryLabel(cat)}` : ''}${items.length > 6 ? ' · scroll ↓' : ''}`
            : 'No module matches. Try another word or all categories.'),
        items.length ? h('ul', { key: 'l', className: 'cb-mod-items', 'data-cb': 'modules-list' }, items.map(m => {
          const [name, rest] = modShort(m.title || m.id)
          return h('li', { key: m.id },
            h('button', { type: 'button', className: 'cb-mod-item', 'data-cb': 'module-row', 'data-cb-id': m.id, title: m.title,
              'aria-current': mem.current.id === m.id ? 'true' : undefined, onClick: () => { mem.current = { top: box.current.scrollTop, id: m.id }; setPick(m.id) } },
            h('span', { className: 'cb-mod-itemhead' }, h('b', null, name), h('span', { className: 'cb-mod-ellip', 'data-cb-truncate-ok': 'true' }, rest),
              h('span', { className: 'cb-mod-catl' }, modCategoryLabel(m.category))),
            h(ModTags, { m })))
        })) : null,
        items.length && items.length < total ? h(Btn, { key: 'm', kind: 'quiet', size: 'sm', 'data-cb': 'modules-more', disabled: cat0.status === 'loading',
          onClick: () => loadModuleCatalog(filter, { more: true }) }, `Load more (${total - items.length} left)`) : null]))
}

// fact line: label, value, page (title = quoted evidence)
function ModFact({ k, v, f }) {
  const ev = modEvidence(f)
  return h('div', { className: 'cb-mod-fact', title: ev || undefined },
    h('span', { className: 'cb-mod-k' }, k), h('span', null, v), ev ? h('span', { className: 'cb-mod-page' }, ev.split(' · ')[0]) : null)
}

function ModuleDetail({ id, project, st, onClose, box, inst = null }) {
  const env = st.env
  const m = env?.ok ? env.result?.module ?? env.result : null
  const assigns = project?.assignments || []
  const choice = modAddressChoices(m)
  const [addr, setAddr] = useState(null)
  const [wire, setWire] = useState(true)
  const [busy, setBusy] = useState(false)
  const [fail, setFail] = useState(null)
  const [ask, setAsk] = useState(false) // remove in two clicks
  const ws = useModuleCheck().findings.warnings.filter(w => inst && (w.refs || []).includes(inst.ref))
  const address = addr || choice.def || choice.list[0] || null
  const conn = m ? modSuggestConn(m, assigns, address) : {}
  const ref = modNextRef(project?.parts || [])
  const act = async () => {
    if (inst && !ask) return setAsk(true)
    setBusy(true)
    setFail(null)
    const res = await (inst ? removePartsFromProject([inst.ref]) : addModule({ module: id, ref, address: choice.list.length ? address : undefined, conn: wire ? conn : undefined }))
    setBusy(false)
    setAsk(false)
    if (res?.ok) onClose(); else setFail(res?.error?.message || res?.summary || 'Not saved.')
  }
  const sec = (title, body) => (body ? h('section', { key: title, className: 'cb-mod-sec' }, h(Label, null, title), body) : null)
  const io = m?.io || {}
  const IO = [['VIH', 'vih'], ['VIL', 'vil'], ['VOH', 'voh'], ['VOL', 'vol'], ['VIN max', 'v_in_max'], ['5 V tolerant', 'five_v_tolerant']].filter(([, k]) => io[k] != null)
  const sources = env?.sources || []
  return (
  h('div', { ref: box, className: 'cb-mod-dlg', 'data-cb': 'module-detail', 'data-cb-id': id },
    !m ? (env && !env.ok ? h('p', { className: 'cb-why cb-bad', 'data-cb': 'modules-error' }, `✕ ${env.error?.message || env.summary}`)
      : h('div', { className: 'cb-loading cb-mod-pad' }, 'loading the module'))
      : [h('div', { key: 'h', className: 'cb-mod-dhead' },
        h('span', { className: 'cb-mod-catl' }, [m.manufacturer, modCategoryLabel(m.category), m.kind].filter(Boolean).join(' · ')), h(ModTags, { m })),
      h('section', { key: 'a', className: 'cb-mod-addbox', 'data-cb': inst ? 'module-instance' : 'module-add' },
        h(Label, null, inst ? `// ${inst.ref} in this project` : `// add as ${ref}`),
        inst ? [h(ModFact, { key: 'a', k: 'address', v: modAddress(inst.address) || '—' }),
          h(ModFact, { key: 'c', k: 'conn', v: Object.entries(inst.conn).map(([p, n]) => `${p}→${n}`).join(' · ') || 'no pins connected' }),
          h('ul', { key: 'f', className: 'cb-mod-list', 'data-cb': 'module-inst-findings' }, ws.length ? ws.map(modFindingRow) : h('li', { className: 'cb-mod-dim' }, 'No module findings in the latest check.'))]
        : choice.list.length ? h('label', { className: 'cb-mod-inline' }, h('span', { className: 'cb-mod-k' }, 'address'),
          h('select', { 'data-cb': 'modules-address', value: address || '', onChange: e => setAddr(e.target.value) },
            choice.list.map(a => h('option', { key: a, value: a }, `${a}${a === choice.def ? ' (default)' : ''}`)))) : null,
        !inst && Object.keys(conn).length ? h('label', { className: 'cb-mod-inline' },
          h('input', { type: 'checkbox', checked: wire, 'data-cb': 'modules-connect', onChange: e => setWire(e.target.checked) }),
          h('span', null, 'connect pins: ', h('span', { className: 'cb-mod-dim', 'data-cb': 'modules-conn' }, Object.entries(conn).map(([p, n]) => `${p}→${n}`).join(' · ')))) : null,
        h('div', { className: 'cb-mod-addrow' },
          h('span', { className: 'cb-mod-dim cb-mod-note' }, inst ? 'Pins and roles are in the assignment table.' : 'Open signal pins appear as “— assign” in the table.'),
          inst ? h(Btn, { onClick: act, kind: ask ? 'danger' : 'quiet', size: 'sm', disabled: busy, 'data-cb': 'module-remove' }, busy ? 'Removing…' : `Remove ${inst.ref}${ask ? ' for good' : '…'}`)
            : h(Btn, { onClick: act, disabled: !m || busy || !project, 'data-cb': 'modules-add', title: project ? `Add as ${ref} to ${project.id}` : 'Open a project first' },
              busy ? 'Adding…' : 'Add to project ›')),
        fail ? h('div', { className: 'cb-note cb-note--bad', role: 'alert' }, `✕ ${fail}`) : null),
      h('div', { key: 'g', className: 'cb-mod-dgrid' },
        sec('// pins', h('table', { className: 'cb-mod-pins', 'data-cb': 'module-pins' }, h('tbody', null, (m.pins || []).map(p => h('tr', { key: p.name },
          h('td', { className: 'cb-mod-nw' }, h('b', null, p.name)), h('td', { className: 'cb-mod-dim cb-mod-nw' }, String(p.signal || '').replace(/_/g, ' ')),
          h('td', { className: 'cb-mod-dim' }, [p.tie ? `tie ${p.tie}` : '', p.must_connect ? 'must connect' : '', p.note || ''].filter(Boolean).join(' · '))))))),
        h('div', { className: 'cb-mod-dcol' },
          sec('// supply', Object.entries(m.supplies || {}).map(([pin, s]) => h(ModFact, { key: pin, k: pin, f: s.min || s.max,
            v: `${modSupply(s)}${s.typ ? ` · typ ${modFText(s.typ)}` : ''}${s.abs_max ? ` · abs max ${modFText(s.abs_max)}` : ''}` }))),
          sec('// levels', IO.length || io.outputs ? [io.domain ? h(ModFact, { key: 'd', k: 'domain', v: io.domain }) : null,
            ...IO.map(([k, key]) => h(ModFact, { key, k, v: modFText(io[key]), f: io[key] })),
            io.outputs ? h(ModFact, { key: 'o', k: 'outputs', v: String(io.outputs).replace(/_/g, ' ') }) : null] : null),
          sec('// current', m.current ? ['typ', 'max', 'peak', 'sleep'].filter(k => m.current[k]).map(k => h(ModFact, { key: k, k, v: modFText(m.current[k]), f: m.current[k] })) : null))),
      sec('// required parts', (m.requires || []).length ? h('ul', { key: 'r', className: 'cb-mod-list', 'data-cb': 'module-requires' }, m.requires.map((r, i) => {
        const calc = modRequireCalc(r, m)
        return h('li', { key: `${r.code}-${i}`, className: 'cb-mod-row cb-mod-row--r', title: modEvidence(r) || undefined },
          modSym('+'), h('span', null, modRequireText(r), r.page != null ? h('span', { className: 'cb-mod-page' }, ` p. ${r.page}`) : null),
          calc ? modCalcLink(calc, 'module', e => { const n = e.currentTarget; onClose(); openCalc(calc, n) }) : h('span'))
      })) : null),
      sec('// hazards', (m.hazards || []).length ? h('ul', { key: 'z', className: 'cb-mod-list' }, m.hazards.map((z, i) => h('li', { key: i, className: 'cb-mod-row cb-mod-row--f cb-mod-row--warn', title: modEvidence(z) || undefined },
        modSym('◇'), h('span', null, h('b', null, 'hazard'), ` ${z.text || z.code}`)))) : null),
      sec('// notes', (m.notes || []).length ? h('ul', { key: 'n', className: 'cb-mod-list' }, m.notes.map((n, i) => h('li', { key: i, className: `cb-mod-row cb-mod-row--f${n.verified ? '' : ' cb-mod-row--dim'}`, title: modEvidence(n) || undefined },
        modSym(n.verified ? 'i' : '?'), h('span', null, n.text, ' ', h('span', { className: 'cb-mod-page' }, n.verified ? `p. ${n.page ?? '—'}` : 'unverified'))))) : null),
      h('div', { key: 's', className: 'cb-mod-srcrow' }, h(SourceLine, { sources }))]))
}

// --- 50-console.js
// Console: tabs SERIAL | BUILD | FLASH, seq-based serial buffer, auto-scroll that pauses while the user reads
// older lines. The same component renders on the Bench page and in the serial pane.
// On the page it folds to one bar while no port is open (consoleMode, lib/serial.js); blank runs fold,
// a panic is one block with a red side bar, the log jumps once to "Guru Meditation…" and pauses following.

const CONSOLE_TABS = [['serial', 'Serial'], ['build', 'Build'], ['flash', 'Flash']]

function recordLines(kind, project, job) {
  if (job?.log_tail?.length) {
    return job.log_tail.map((text, i) => ({ k: 'line', seq: i + 1, ts: '', text }))
  }
  const fw = project?.firmware || {}
  const rec = kind === 'build' ? fw.last_build : fw.last_flash
  if (!rec) return []
  const at = rec.at ? formatClock(rec.at) : ''
  // a simulated build has no ELF, its hash is a "firmware hash", never "ELF SHA256"
  const sim = Boolean(job?.result?.simulated ?? project?.simulated)
  const hashLabel = sim ? 'firmware hash' : 'elf sha256'
  if (kind === 'build') {
    return [{ k: 'line', seq: 1, ts: at, text: `last build ${rec.ok ? 'ok' : 'FAILED'} · RAM ${formatPct(rec.ram_pct)} · flash ${formatPct(rec.flash_pct)}` },
      { k: 'line', seq: 2, ts: at, text: `${sim ? 'simulated build, no ELF' : `elf ${rec.elf || '—'}`} · ${hashLabel} ${shortHash(rec.elf_sha256, 16)}` }]
  }
  return [{ k: 'line', seq: 1, ts: at, text: `last flash ${rec.ok ? 'ok' : 'FAILED'} → ${rec.port || '—'} · mac ${rec.mac || '—'}` },
    { k: 'line', seq: 2, ts: at, text: `${hashLabel} ${shortHash(rec.elf_sha256, 16)}` }]
}

/** Console state of the page from the store. */
function useConsoleMode(project) {
  const ui = sdk.useValue($ui)
  const mon = sdk.useValue($monitor)
  const serial = sdk.useValue($serial)
  const jobs = sdk.useValue($jobs)
  const monitorOpen = mon.status !== 'closed' && Boolean(mon.port) && monitorActive(mon.port)
  const serialOpen = serial.status === 'open' && serial.buf.lines.some(l => l.k === 'line')
  const jobRunning = ['build', 'flash'].some(k => jobProgress(jobs[k]).running)
  const panic = Boolean((serial.port && serialPanicLive(serial.buf, project)) || projectPanicCurrent(project))
  return consoleMode({ paneOpen: ui.paneOpen, cons: ui.cons, pinned: ui.consPinned, monitorOpen, serialOpen, jobRunning, panic })
}

/** Log text with the hovered frame / register marked (lib/crash.js logMarkRanges; only inside the marked panic block). */
function LogText({ text, mark }) {
  const ranges = mark ? logMarkRanges(text, mark) : []
  if (!ranges.length) return h('span', null, text || ' ')
  return h('span', null, splitMarked(text, ranges).map((p, k) => (p.mark ? h('mark', { key: k, className: 'cb-logmark', 'data-cb': 'log-mark' }, p.t) : p.t)))
}

function LogLine({ l, i, mark = null }) {
  if (l.k === 'gap') return h('div', { className: 'cb-line cb-line--gap' }, h('span', { className: 'cb-ts' }, ''), h('span', null, `… ${l.to - l.from + 1} line(s) missed (seq ${l.from}–${l.to}) …`))
  if (l.k === 'epoch') return h('div', { className: 'cb-line cb-line--epoch' }, h('span', { className: 'cb-ts' }, ''), h('span', null, '— backend restarted, new stream —'))
  const cls = String(l.text || '').trim() ? lineClass(l.text) : 'blank'
  return h('div', { className: `cb-line${cls ? ` cb-line--${cls}` : ''}`, 'data-cb-seq': l.seq ?? i },
    h('span', { className: 'cb-ts' }, l.ts || ''), h(LogText, { text: l.text, mark }))
}

// Panic episodes: one per surface, stream (epoch + port) and flash. Each episode jumps once, to its first panic.
// A flash on the same stream starts a new episode after the lines seen so far (old panics never jump again); a new
// stream or the first episode counts every panic in it. Module-level, so a remount (route ↔ chat) does not jump again.
const EPISODE_START = new Map()
const EPISODE_JUMPED = new Set()
const STREAM_EPISODE = new Map()

function episodeStart(episode, stream, lastSeq) {
  if (!EPISODE_START.has(episode)) {
    const prev = STREAM_EPISODE.get(stream)
    EPISODE_START.set(episode, prev && prev !== episode ? lastSeq : 0)
    STREAM_EPISODE.set(stream, episode)
  }
  return EPISODE_START.get(episode)
}

/**
 * view: logView(lines). panicSeq: seq of the latest panic in the buffer (or null). lastSeq: newest line seq.
 * stream: surface|epoch|port; episode: stream|last flash (a new flash starts a new episode and releases the hold).
 * live: seq of the current panic (or null), for the marker. jumpReq: {seq, n} from the "▲ panic" chip.
 * While a panic is held, "Guru Meditation…" stays the top line and following pauses until the user scrolls, follows,
 * or a new flash arrives.
 */
const RENDER_LIMIT = 800 // DOM rows of the log (the buffer keeps 2000; copy and pane use the buffer)

function LogLines({ view, showTs = true, live = null, panicSeq = null, lastSeq = 0, stream = null, episode = null, jumpReq = null, mark = null, onFollow = null, resumeRef = null }) {
  const ref = useRef(null)
  const inner = useRef(null)
  const [paused, setPaused] = useState(false)
  const [unseen, setUnseen] = useState(0)
  const count = useRef(0)
  const pausedRef = useRef(false)
  const hold = useRef(null) // seq of the panic block kept at the top
  const expectTop = useRef(null) // scrollTop we set ourselves (its scroll event is not the user)
  const lastEpisode = useRef(episode)
  pausedRef.current = paused
  const size = view.reduce((n, e) => n + (e.k === 'panic' ? e.lines.length : 1), 0)
  const pause = on => { pausedRef.current = on; setPaused(on) }
  const setTop = (el, top) => { el.scrollTop = top; expectTop.current = el.scrollTop }
  const toBottom = () => { const el = ref.current; if (el) setTop(el, el.scrollHeight) }
  const placeHold = () => {
    const el = ref.current
    if (!el || hold.current === null) return false
    const blocks = [...el.querySelectorAll('[data-cb=panic-block]')]
    const blk = blocks.find(b => b.getAttribute('data-cb-seq') === String(hold.current)) || blocks[blocks.length - 1]
    if (!blk) return false
    setTop(el, Math.max(0, blk.offsetTop - 4))
    revealMark()
    return true
  }
  // a frame / register hovered on the station marks its address in the raw lines: scroll just enough to show it
  const revealMark = () => {
    const el = ref.current
    const m = el && el.querySelector('[data-cb=log-mark]')
    if (!m) return
    const box = el.getBoundingClientRect()
    const r = m.getBoundingClientRect()
    if (r.top >= box.top && r.bottom <= box.bottom) return
    setTop(el, Math.max(0, el.scrollTop + (r.bottom > box.bottom ? r.bottom - box.bottom + 8 : r.top - box.top - 8)))
  }
  const holdAt = seq => { hold.current = seq; pause(true); setUnseen(0); placeHold() }
  useEffect(() => {
    // keep the tail (or the held panic) in view when the content reflows (resize, wrapping)
    if (typeof ResizeObserver !== 'function' || !inner.current) return undefined
    const ro = new ResizeObserver(() => { if (hold.current !== null) placeHold(); else if (!pausedRef.current) toBottom() })
    ro.observe(inner.current)
    if (ref.current) ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const added = size - count.current
    count.current = size
    if (episode !== lastEpisode.current) {
      // a new flash (or stream): stop holding the old panic and follow the new firmware's output
      lastEpisode.current = episode
      if (hold.current !== null) { hold.current = null; pause(false); setUnseen(0) }
    }
    const start = episode ? episodeStart(episode, stream, lastSeq) : 0
    if (episode && panicSeq !== null && panicSeq > start && !EPISODE_JUMPED.has(episode)) {
      EPISODE_JUMPED.add(episode)
      holdAt(panicSeq)
      return
    }
    if (hold.current !== null) {
      placeHold()
      if (added > 0) setUnseen(n => n + added)
    } else if (!pausedRef.current) {
      toBottom()
      revealMark()
    } else if (added > 0) {
      setUnseen(n => n + added)
    }
  }, [view, panicSeq, episode])
  useEffect(() => { if (jumpReq) holdAt(jumpReq.seq) }, [jumpReq?.n])
  const onScroll = () => {
    const el = ref.current
    if (!el) return
    if (expectTop.current !== null && Math.abs(el.scrollTop - expectTop.current) <= 2) return // our own scroll
    expectTop.current = null
    hold.current = null // the user scrolls: stop holding the panic
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (atBottom === pausedRef.current) pause(!atBottom)
    if (atBottom) setUnseen(0)
  }
  const resume = () => {
    hold.current = null
    pause(false)
    setUnseen(0)
    toBottom()
  }
  // "▼ N new lines" lives in the console toolbar: report the count up, hand the resume over
  if (resumeRef) resumeRef.current = resume
  const newLines = paused && unseen > 0 ? unseen : 0
  useEffect(() => { onFollow?.(newLines) }, [newLines])
  useEffect(() => () => onFollow?.(0), [])
  // the mark applies to one panic block: the held one, else the live one, else the newest
  const blocks = view.filter(e => e.k === 'panic')
  const markSeq = mark && blocks.length ? (blocks.find(b => b.seq === hold.current) || blocks.find(b => b.seq === live) || blocks[blocks.length - 1]).seq : null
  const markKey = markSeq !== null ? `${mark.kind}:${mark.name || ''}:${mark.value}` : null
  useEffect(() => { if (markKey) revealMark() }, [markKey])
  return h('div', { className: cx('cb-log', !showTs && 'cb-log--nots'), ref, onScroll, 'data-cb': 'log', 'data-cb-paused': paused ? 'true' : 'false',
    'data-cb-hold': hold.current !== null ? String(hold.current) : undefined, 'data-cb-mark': markKey || undefined,
    role: 'log', 'aria-live': 'off' },
    h('div', { className: 'cb-log-inner', ref: inner }, renderWindow(view, hold.current, RENDER_LIMIT).map((e, i) => e.k === 'panic'
      ? h('div', { key: `p${e.seq}`, className: cx('cb-panicblk', e.seq === live && 'cb-panicblk--live'), 'data-cb': 'panic-block', 'data-cb-seq': e.seq,
        'data-cb-truncate-ok': 'true', role: 'group', 'aria-label': `Panic at seq ${e.seq}` }, e.lines.map((l, j) => h(LogLine, { key: l.seq ?? `${i}-${j}`, l, i: j, mark: e.seq === markSeq ? mark : null })))
      : h(LogLine, { key: e.k === 'line' ? e.seq ?? i : `${e.k}${e.from ?? e.epoch ?? ''}-${i}`, l: e, i }))))
}

/** Empty serial console: a clear sentence and the next step. */
function ConsoleEmpty({ state, inline = false }) {
  const act = state?.action
  const run = () => {
    goStation('debug')
    if (act?.port) openMonitor(act.port)
  }
  return h(inline ? 'span' : 'div', { className: inline ? 'cb-cons-idle' : 'cb-cons-empty', 'data-cb': inline ? 'console-collapsed' : 'console-empty', 'data-cb-kind': state?.kind },
    h('span', { className: state?.kind === 'sim' ? 'cb-active' : 'cb-faint', 'aria-hidden': 'true' }, state?.kind === 'sim' ? '◌' : '>'),
    h('span', { className: 'cb-ellip' }, state?.text || ''),
    act ? h('button', { type: 'button', className: 'cb-linkbtn', 'data-cb': 'console-open-monitor', onClick: run,
      title: act.port ? `Open the monitor on ${act.port} (06 DEBUG)` : 'Go to 06 DEBUG' }, act.label) : null)
}

// the tab panel takes the place of the log in the console column (flex child that passes the height on)
const CONSOLE_PANEL_STYLE = { display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0, minWidth: 0 }
let CONSOLE_UID = 0

function Console({ surface = 'page', project, mode = 'open', jumpChip = true }) {
  const ui = sdk.useValue($ui)
  const serial = sdk.useValue($serial)
  const jobs = sdk.useValue($jobs)
  const bench = sdk.useValue($bench)
  const ports = sdk.useValue($ports)
  const mark = sdk.useValue($logMark)
  const [jump, setJump] = useState(null)
  const [copied, setCopied] = useState(null)
  const [newLines, setNewLines] = useState(0)
  const resumeRef = useRef(null)
  // ids for tab ↔ panel (route, tile and pane may show a console at once)
  const uid = useRef(null)
  if (uid.current === null) uid.current = ++CONSOLE_UID
  const tabId = id => `cb-cons${uid.current}-tab-${id}`
  const panelId = `cb-cons${uid.current}-panel`
  const tab = ui.tab
  const shut = surface === 'page' && (mode === 'collapsed' || mode === 'idle')
  let lines = []
  let meta = ''
  let metaParts = null
  let empty = null
  if (tab === 'serial') {
    lines = serial.buf.lines
    const nLines = lines.filter(l => l.k === 'line').length
    meta = serial.port ? `${serial.port} · ${serial.status}${serial.mode === 'poll' ? ' · polling' : serial.mode === 'socket' ? ' · live' : ''}` : 'no port'
    // the port gives way first in a narrow console (19-styles-debug.js); the state stays readable
    metaParts = serial.port ? { port: serial.port, state: `${serial.status}${serial.mode === 'poll' ? ' · polling' : serial.mode === 'socket' ? ' · live' : ''}` } : null
    if (!nLines) empty = serialEmptyState({ ports: ports.ports, serial, backendDown: bench.phase === 'error' })
  } else {
    const job = jobs[tab]
    lines = recordLines(tab, project, job)
    // pio reports no percentage: progress null → indeterminate ("running…")
    meta = job ? `job ${job.job_id} · ${job.state === 'running' && (job.progress === null || job.progress === undefined) ? 'running…'
      : `${job.state}${typeof job.progress === 'number' && job.state === 'running' ? ` · ${formatFraction(job.progress)}` : ''}`}` : lines.length ? 'last record' : ''
    if (!lines.length) empty = { kind: tab, text: tab === 'build' ? 'No build yet. Build from 05 FLASH or ask Hermes to build.' : 'Nothing flashed yet. Flashing always asks first (05 FLASH).', action: null }
  }
  const view = useMemo(() => logView(lines), [lines])
  const blocks = tab === 'serial' ? panicBlocks(view) : []
  const live = tab === 'serial' && serialPanicLive(serial.buf, $project.get()) ? serial.buf.panic.seq : null
  const stream = tab === 'serial' && serial.port ? `${surface}|${serial.buf.epoch ?? ''}|${serial.port}` : null
  const episode = stream ? `${stream}|${project?.firmware?.last_flash?.at || ''}` : null
  const lastBlock = blocks.length ? blocks[blocks.length - 1] : null
  // in a reboot loop the serial panic is "not current" between two crashes; the stored panic (no flash after it) is
  const chipLive = live !== null || projectPanicCurrent(project)
  const canCopy = typeof CB.ctx?.os?.writeClipboard === 'function' && lines.some(l => l.k === 'line')
  const copy = async () => {
    const text = tab === 'serial' ? bufferText(serial.buf) : lines.map(l => `${l.ts ? `${l.ts} ` : ''}${l.text}`).join('\n')
    let ok = false
    try { ok = (await CB.ctx.os.writeClipboard(text)) !== false } catch { ok = false }
    setCopied(ok ? 'ok' : 'fail')
    timersOf(CB.ctx).setTimeout(() => setCopied(null), 1600)
  }
  const toggle = surface === 'page'
    ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-toggle', 'aria-expanded': shut ? 'false' : 'true',
      title: shut ? 'Show console' : 'Hide console', 'aria-label': shut ? 'Show console' : 'Hide console', onClick: () => setConsole(shut ? 'open' : 'collapsed') },
    shut ? '▴' : '▾', h('span', { className: 'cb-tbl' }, shut ? ' show' : ' hide'))
    : null
  const pane = surface === 'page'
    ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-to-pane', title: 'Open the serial monitor as a pane below the chat',
      'aria-label': 'Open as pane', onClick: () => openSerialPane() }, '⇲', h('span', { className: 'cb-tbl' }, ' pane'))
    : h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'pane-close', title: 'Close the serial monitor pane', 'aria-label': 'Close pane', onClick: () => closeSerialPane() },
      '✕', h('span', { className: 'cb-tbl' }, ' close'))
  const idleText = shut && tab === 'serial' && empty ? h(ConsoleEmpty, { key: 'idle', state: empty, inline: true }) : null
  const showLog = !shut && !empty
  const follow = showLog && newLines > 0
    ? h('button', { type: 'button', className: 'cb-iconbtn cb-followbtn', 'data-cb': 'log-follow', title: 'Follow the log again (jump to the newest line)',
      'aria-label': `${newLines} new line${newLines === 1 ? '' : 's'}, follow the log`, onClick: () => resumeRef.current?.() },
    `▼ ${newLines}`, h('span', { className: 'cb-tbl' }, ` new line${newLines === 1 ? '' : 's'}`))
    : null
  return h('div', { className: 'cb-console', 'data-cb': `console-${surface}`, 'data-cb-mode': surface === 'page' ? mode : undefined },
    h('div', { className: 'cb-tabs', role: 'tablist', 'aria-label': 'Console' },
      CONSOLE_TABS.map(([id, label]) => h('button', { key: id, type: 'button', role: 'tab', 'aria-selected': tab === id ? 'true' : 'false',
        id: tabId(id), 'aria-controls': shut ? undefined : panelId, 'data-cb': `tab-${id}`, onClick: () => { setConsoleTab(id); if (shut) setConsole('open') } }, label,
      id === 'serial' && serialPanicLive(serial.buf, $project.get()) ? h('span', { className: 'cb-bad', 'aria-label': 'panic' }, '●') : null)),
      h('div', { className: 'cb-meta' },
        idleText,
        follow,
        !shut && lastBlock && jumpChip ? h('button', { type: 'button', className: cx('cb-iconbtn cb-pjump', chipLive && 'cb-pjump--live'), 'data-cb': 'panic-jump',
          title: `Scroll to the panic at seq ${lastBlock.seq} (Guru Meditation …)${chipLive ? '' : ' — not current: a flash came after it'}`,
          onClick: () => setJump({ seq: lastBlock.seq, n: (jump?.n || 0) + 1 }) },
        '▲ ', chipLive ? null : h('span', { className: 'cb-cmd-long' }, 'last '), 'panic', h('span', { className: 'cb-tbx' }, ` · seq ${lastBlock.seq}`)) : null,
        tab === 'serial' && (serial.simulated || isSimPort(serial.port)) ? h(SimBanner, { compact: true, dataCb: 'sim-banner-console' }) : null,
        idleText ? null : h('span', { className: 'cb-consmeta', title: meta }, metaParts
          ? [h('span', { key: 'p', className: 'cb-consport' }, `${metaParts.port} · `), metaParts.state] : meta),
      ),
      // tools in their own group
      h('div', { className: 'cb-cons-tools' },
        canCopy && !shut ? h('button', { type: 'button', className: 'cb-iconbtn', 'data-cb': 'console-copy', onClick: copy,
          'aria-label': copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : 'Copy log',
          title: `Copy the ${tab} log (${lines.filter(l => l.k === 'line').length} lines) to the clipboard` }, copied === 'ok' ? ['✓', h('span', { key: 'l', className: 'cb-tbl' }, ' copied')]
          : copied === 'fail' ? ['✕', h('span', { key: 'l', className: 'cb-tbl' }, ' not copied')] : ['⧉', h('span', { key: 'l', className: 'cb-tbl' }, ' copy log')]) : null,
        pane, toggle)),
    shut ? null : h('div', { role: 'tabpanel', id: panelId, 'aria-labelledby': tabId(tab), style: CONSOLE_PANEL_STYLE },
      empty ? h(ConsoleEmpty, { state: empty })
        : h(LogLines, { view, showTs: ui.showTs, live, panicSeq: tab === 'serial' ? serial.buf.panic?.seq ?? null : null, lastSeq: serial.buf.lastSeq || 0,
          stream, episode, jumpReq: jump, mark: tab === 'serial' ? mark : null, onFollow: setNewLines, resumeRef })))
}

/** Console row on the page; outside 06 DEBUG the panic strip above the log. Pane open: a slim bar. */
function ConsoleRow({ project, mode }) {
  const nav = sdk.useValue($nav)
  if (mode === 'pane') {
    return h('section', { className: 'cb-cons', 'data-cb': 'console-row', 'data-cb-mode': mode, style: { gridTemplateColumns: 'minmax(0,1fr)' } },
      h('div', { className: 'cb-tabs' }, h('span', { className: 'cb-cons-empty', style: { padding: '0 14px', alignItems: 'center' } },
        h(Label, null, 'console'), 'The serial monitor is open in the pane below.',
        h('button', { type: 'button', className: 'cb-iconbtn', onClick: () => closeSerialPane(), 'data-cb': 'pane-back' }, '⇱ back to bench'))))
  }
  const debug = nav.station === 'debug'
  return h('section', { className: 'cb-cons cb-cons--page', 'data-cb': 'console-row', 'data-cb-audit-root': 'console', 'data-cb-mode': mode },
    mode !== 'open' || debug ? null : h(PanicStrip, { project }),
    h(Console, { surface: 'page', project, mode, jumpChip: debug }))
}

/** Serial pane (PANES_AREA, docked under the workspace). Registered on demand so it never takes room unasked; its
 *  own ✕ disposes the registration (the app's tab ✕ would disable the whole plugin: single-pane rule). */
function SerialPane() {
  const project = sdk.useValue($project)
  const ui = sdk.useValue($ui)
  useEffect(() => { ensureBench() }, [])
  return h('div', { className: 'cb-root cb-pane', 'data-cb': 'serial-pane', 'data-cb-look': ui.look },
    h(Styles, null),
    h('section', { className: 'cb-cons' }, h(Console, { surface: 'pane', project }), h(PanicCard, { project })))
}

function openSerialPane() {
  if (CB.paneDispose || !CB.ctx) {
    patchAtom($ui, { paneOpen: true })
    return
  }
  const area = sdk.PANES_AREA || 'panes'
  CB.paneDispose = CB.ctx.register({ id: 'serial', area, title: 'Serial',
    data: { placement: 'bottom', dock: { pane: 'workspace', pos: 'bottom' }, height: '240px', uncloseable: true },
    render: () => h(SerialPane, null) })
  patchAtom($ui, { paneOpen: true })
  store('paneOpen', true)
}

function closeSerialPane() {
  const d = CB.paneDispose
  CB.paneDispose = null
  try { d?.() } catch (e) { console.warn('[circuit-bench] pane dispose', e) }
  patchAtom($ui, { paneOpen: false })
  store('paneOpen', false)
}

// --- 60-directive.js
// Directive ::bench{project="…" view="pins|calc|wire|solder|flash|crash"}: a compact card in the
// chat. Garbage attributes render nothing (lib/directive.js). "Open in Bench" sets the nav atom first, then opens
// the Bench beside the chat (host.openWorkspace) or, without it, the route. Live through project.updated.

const DIRECTIVE_CACHE = new Map() // project id → {env, at}
const $directiveTick = sdk.atom(0)

function directiveProjectChanged(id) {
  if (DIRECTIVE_CACHE.has(id)) DIRECTIVE_CACHE.delete(id)
  $directiveTick.set($directiveTick.get() + 1)
}

function useDirectiveProject(id) {
  const tick = sdk.useValue($directiveTick)
  const live = sdk.useValue($project)
  const [env, setEnv] = useState(() => DIRECTIVE_CACHE.get(id)?.env || null)
  useEffect(() => {
    let gone = false
    if (live?.id === id) return undefined
    const hit = DIRECTIVE_CACHE.get(id)
    if (hit && Date.now() - hit.at < 5000) { setEnv(hit.env); return undefined }
    CB.api?.project(id).then(e => {
      DIRECTIVE_CACHE.set(id, { env: e, at: Date.now() })
      if (!gone) setEnv(e)
    })
    return () => { gone = true }
  }, [id, tick, live?.id === id ? live.rev : null])
  if (live?.id === id) return { project: live, env: { ok: true } }
  return { project: env?.ok ? env.result?.project || null : null, env }
}

function BenchDirectiveCard(props) {
  const a = parseDirectiveAttrs(props?.attrs)
  if (!a) return null
  return h(BenchDirectiveInner, { a, sessionId: directiveSession(props), streaming: Boolean(props?.streaming) })
}

// ─── The card shows the thing itself — a mini pin header, the schematic, frame #0 ────────────────────────────

const DIRECTIVE_BOARDS = new Map() // devkit id → layout (GET /boards/{id})
const DIRECTIVE_SVGS = new Map() // project|rev|circuit → {svg, summary} | {error}

function useBoardLayout(devkit) {
  const board = sdk.useValue($board)
  const [layout, setLayout] = useState(() => DIRECTIVE_BOARDS.get(devkit) || null)
  const live = board.id === devkit && board.layout ? board.layout : null
  useEffect(() => {
    if (!devkit || live || DIRECTIVE_BOARDS.has(devkit) || typeof CB.api?.board !== 'function') return undefined
    let gone = false
    CB.api.board(devkit).then(env => {
      if (!env?.ok || !env.result) return
      DIRECTIVE_BOARDS.set(devkit, env.result)
      if (!gone) setLayout(env.result)
    })
    return () => { gone = true }
  }, [devkit, Boolean(live)])
  return live || layout || DIRECTIVE_BOARDS.get(devkit) || null
}

const DIRECTIVE_MAPS = new Map() // [chip, variant, wifi, devkit] → POST /pins/check of all header GPIOs (the PLAN map)

/** Pin map of the card's board (free / caution / blocked for the unassigned pins), fetched once per board. */
function useDirectiveMap(project, layout) {
  const b = boardOf(project)
  const key = layout ? JSON.stringify([b.chip, b.variant, b.wifi, layout.id]) : null
  const [env, setEnv] = useState(() => (key && DIRECTIVE_MAPS.get(key)) || null)
  useEffect(() => {
    if (!key) return undefined
    if (DIRECTIVE_MAPS.has(key)) { setEnv(DIRECTIVE_MAPS.get(key)); return undefined }
    if (typeof CB.api?.pinsCheck !== 'function') return undefined
    let gone = false
    CB.api.pinsCheck({ chip: b.chip, variant: b.variant, wifi: b.wifi, devkit: layout.id, assignments: mapAssignments(layout) }).then(e => {
      if (e?.ok) DIRECTIVE_MAPS.set(key, e)
      if (!gone) setEnv(e)
    })
    return () => { gone = true }
  }, [key])
  const hit = env || (key && DIRECTIVE_MAPS.get(key)) || null
  return hit?.ok ? mapByGpio(hit.result) : null
}

/** GPIO list of a reservation in short words: consecutive → "IO33–37", else "IO19/20". */
function directiveIoRun(ios) {
  const n = [...new Set(ios)].sort((a, b) => a - b)
  if (!n.length) return ''
  const run = n.length > 2 && n.every((v, i) => !i || v === n[i - 1] + 1)
  return ` IO${run ? `${n[0]}–${n[n.length - 1]}` : n.join('/')}`
}

const DIRECTIVE_PIN_STATE = { ok: 'assigned', caution: 'caution', blocked: 'assigned_blocked' }
const DIRECTIVE_PIN_WORD = { ok: 'ok', caution: 'caution', blocked: 'blocked' }

/** Key figures of the pins card in the HUD's words (lib/art-shell.js shellKpis): symbol + number + word, the whole
 *  sentence in aria-label. The card has the room, so zero counts keep their word too (dimmed). */
function DirectiveKpis({ assignments }) {
  const kpi = shellKpis(countVerdicts(assignments), null, null).pins
  kpi.label = `${assignments.length} pins assigned: ${kpi.label.replace(/^Pins: /, '')}`
  return h('div', { className: 'cb-dcard-hl cb-dkpis', 'data-cb': 'directive-headline', role: 'group', 'aria-label': kpi.label, title: kpi.label },
    h(Label, { className: 'cb-dkpis-l' }, `${assignments.length} assigned`),
    kpi.items.map(it => h('span', { key: it.key, className: `cb-dkpi cb-${it.tone}`, 'data-cb-kpi': it.key },
      h('span', { 'aria-hidden': 'true' }, it.symbol), h('b', null, String(it.n)), h('span', { className: 'cb-dkpi-w' }, it.word))))
}

/** The thing itself for view pins: the compact board model (own id prefix per card), the assignments beside it, the legend
 *  with the model's symbols below. Without a layout the list stands alone. */
function DirectivePins({ project }) {
  const layout = useBoardLayout(project?.board?.devkit)
  const base = useDirectiveMap(project, layout)
  const prefix = useTwinPrefix('chat')
  // hover coupling: the row rings its pad
  const [hot, setHot] = useState(null)
  const as = project.assignments || []
  const where = new Map()
  for (const side of ['left', 'right']) for (const hp of layout?.[side] || []) if (Number.isInteger(hp.gpio)) where.set(hp.gpio, `${hp.header}-${hp.n}`)
  const shown = as.slice(0, 6)
  const b = project.board || {}
  const variant = variantInfo(b.chip, b.variant)
  // the same model the drawing gets (BoardTwin): map + assignments, so the words match the dashed frames
  const model = layout ? boardArtModel({ layout, chip: chipInfo(b.chip), variant, base: base || new Map(), used: new Map(as.map(a => [a.pin, a])) }) : null
  // the dashed frames on the strips: their reservation in words (the compact drawing has no text)
  const reserved = []
  for (const side of ['left', 'right']) {
    for (const br of model?.brackets?.[side] || []) {
      const ios = model.views[side].filter(v => v.view && v.slot >= br.from && v.slot <= br.to && Number.isInteger(v.hp.gpio)).map(v => v.hp.gpio)
      const key = `${br.label}|${ios.join(',')}`
      if (!reserved.some(r => r.key === key)) reserved.push({ key, label: br.label, tone: br.tone, ios })
    }
  }
  const spec = model ? [model.module.name, model.module.flash_mb ? `${model.module.flash_mb} MB flash` : null,
    model.module.psram_mb ? `${model.module.psram_mb} MB ${variant?.psram === 'octal' ? 'octal ' : ''}PSRAM` : null].filter(Boolean) : []
  return h('div', { className: cx('cb-dpins', !layout && 'cb-dpins--list'), 'data-cb': 'directive-pins' },
    layout ? h(BoardTwin, { layout, project, base, prefix, hot, dataCb: 'directive-mini-pins', className: 'cb-dpins-board',
      label: `${layout.title} board model: ${twinPinsText(project)}` }) : null,
    h('div', { className: 'cb-dpins-side' },
      h(DirectiveKpis, { assignments: as }),
      as.length ? h('ul', { className: 'cb-dpins-list', 'data-cb': 'directive-rows' }, shown.map(a => {
        const st = DIRECTIVE_PIN_STATE[a.verdict] || 'assigned'
        const word = DIRECTIVE_PIN_WORD[a.verdict] || 'not checked'
        return h('li', { key: `${a.role}-${a.pin}`, className: `cb-dpin cb-dpin--${a.verdict || 'none'}`, 'data-cb-role': a.role,
          'data-cb-hot': hot === a.pin ? 'true' : undefined, onMouseOver: () => setHot(a.pin), onMouseOut: () => setHot(null),
          title: `${a.role} → GPIO${a.pin} (${modeLabel(a.mode)}): ${word}` },
        h(BoardGlyph, { state: st }), h('b', { className: 'cb-dpin-role' }, a.role), h('span', { className: 'cb-dpin-io' }, `IO${a.pin}`),
        h('span', { className: 'cb-dpin-at cb-dim' }, where.get(a.pin) || ''), h('span', { className: 'cb-dpin-mode cb-dim' }, modeLabel(a.mode)), h('span', { className: `cb-dpin-w cb-${a.verdict === 'blocked' ? 'bad' : a.verdict === 'caution' ? 'warn' : 'dim'}` }, word))
      }), as.length > shown.length ? h('li', { key: 'more', className: 'cb-dpin cb-dpin--more cb-dim' }, `+ ${as.length - shown.length} more in 01 PLAN`) : null)
        : h('p', { className: 'cb-why cb-dim' }, 'No pins assigned yet.'),
      model ? h('div', { className: 'cb-dpins-foot', 'data-cb': 'directive-board-facts' },
        reserved.length ? h('div', { className: 'cb-dpins-res' }, h(Label, null, 'reserved'),
          reserved.map(r => h('span', { key: r.key, className: `cb-dres cb-dres--${r.tone}`, title: `${r.label}: ${r.ios.map(n => `GPIO${n}`).join(', ')} (dashed frame on the strip)` },
            h('i', { 'aria-hidden': 'true' }), h('b', null, r.label), directiveIoRun(r.ios)))) : null,
        spec.length ? h('div', { className: 'cb-dpins-spec' }, h(Label, null, 'module'), spec.map(t => h('span', { key: t }, t))) : null) : null),
    layout ? h(Legend, { dataCb: 'directive-legend', className: 'cb-dpins-legend' }) : null)
}

function useCircuitSvg(project) {
  const c = (project?.circuits || [])[0] || null
  const key = c ? `${project.id}|${project.rev}|${c.id}` : null
  const [res, setRes] = useState(() => (key && DIRECTIVE_SVGS.get(key)) || null)
  useEffect(() => {
    if (!key) return undefined
    if (DIRECTIVE_SVGS.has(key)) { setRes(DIRECTIVE_SVGS.get(key)); return undefined }
    if (typeof CB.api?.schematic !== 'function') return undefined
    let gone = false
    const gpio = circuitGpio(project, c)
    CB.api.schematic({ block: c.block, params: c.params, project: project.id, ...(Number.isInteger(gpio) ? { gpio } : {}) }).then(env => {
      const safe = env?.ok ? sanitizeSvg(env.result?.svg) : { ok: false, reason: env?.error?.message || 'schematic unavailable' }
      const v = safe.ok ? { svg: safe.svg, summary: env.summary, circuit: c.id, block: c.block } : { error: safe.reason }
      DIRECTIVE_SVGS.set(key, v)
      if (!gone) setRes(v)
    })
    return () => { gone = true }
  }, [key])
  return { circuit: c, res }
}

function MiniSchematic({ project }) {
  const { circuit, res } = useCircuitSvg(project)
  if (!circuit) return null
  if (!res) return h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'drawing schematic')
  if (res.error) return h('p', { className: 'cb-why cb-dim', 'data-cb': 'directive-svg-error' }, `Schematic not shown: ${res.error}`)
  return h('div', { className: 'cb-svg cb-svg--media cb-svg--dcard', 'data-cb': 'directive-svg', role: 'img', 'aria-label': res.summary || circuit.block,
    dangerouslySetInnerHTML: { __html: res.svg } })
}

/** Frame #0 of the stored panic (red while it is current, dim once a flash came after it). */
function MiniFrame({ project, live }) {
  const p = project?.debug?.last_panic
  if (!p?.top_frame) return null
  const t = splitTopFrame(p.top_frame)
  const base = String(t.file || '??').split('/').pop()
  return h('div', { className: cx('cb-frame', live && 'cb-frame--top', 'cb-dframe'), 'data-cb': 'directive-frame', title: p.top_frame },
    h('span', { className: 'cb-i' }, '#0'), h('span', { className: 'cb-f' }, shortFunction(t.fn)),
    h('span', { className: 'cb-l' }, t.line !== null ? `${base}:${t.line}` : base))
}

function BenchDirectiveInner({ a, sessionId }) {
  const ui = sdk.useValue($ui)
  const { project, env } = useDirectiveProject(a.project)
  const sum = directiveSummary(a.view, project, { panicCurrent: projectPanicCurrent })
  const missing = env && !env.ok
  const open = beside => {
    goStation(a.station, a.project)
    if (CB.mounts > 0) return
    openBench({ beside })
  }
  const live = a.view === 'crash' && project ? projectPanicCurrent(project) : false
  const pins = a.view === 'pins'
  const visual = !project ? null
    : pins ? h(DirectivePins, { key: 'v', project })
      : a.view === 'wire' ? h(MiniSchematic, { key: 'v', project })
        : a.view === 'crash' ? h(MiniFrame, { key: 'v', project, live }) : null
  // the frame row replaces the "#0" text row; the pins card carries its own key figures and list (DirectivePins)
  const rows = pins ? [] : sum.rows.filter(r => !(a.view === 'crash' && r.k === 't' && project?.debug?.last_panic?.top_frame))
  return h(Fragment, null, h(Styles, null),
    h('div', { className: 'cb-root cb-dcard cb-bracket', 'data-cb': 'directive-card', 'data-cb-look': ui.look, 'data-cb-view': a.view, 'data-cb-project': a.project,
      'data-cb-session': sessionId || undefined, 'data-cb-audit-root': 'directive' },
    h('div', { className: 'cb-dcard-head' },
      h('span', { className: 'cb-brand cb-brand--sm' }, '◢ BENCH'),
      h('b', null, a.project), h(Label, null, `${STATIONS.find(s => s.id === a.station)?.n || ''} // ${a.title}`),
      project?.simulated ? h(SimBanner, { compact: true, dataCb: 'directive-sim' }) : null),
    missing ? h('p', { className: 'cb-why cb-warn' }, env.error?.code === 'project_not_found' ? `No bench project “${a.project}”.` : env.error?.message || 'Bench backend not available.')
      : !project ? h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'loading')
        : [pins ? null : h('div', { key: 'hl', className: `cb-dcard-hl cb-${sum.headline.tone}`, 'data-cb': 'directive-headline' }, sum.headline.text),
          visual,
          rows.length ? h('div', { key: 'r', className: 'cb-kv cb-kv--dcard', 'data-cb': 'directive-rows' },
            rows.map(r => [h('span', { key: `${r.k}l` }, r.label), h('b', { key: `${r.k}v`, className: `cb-${r.tone}` }, r.value)])) : null],
    h('div', { className: 'cb-actions' },
      // the card's one primary action
      h(Btn, { size: 'sm', 'data-cb': 'directive-open', onClick: () => open(true) }, 'Open in Bench ›'))))
}

// --- 61-media.js
// Optional: own card for the MEDIA: SVG of bench_schematic in the chat, only when the host has
// TOOL_MEDIA_RENDERER_AREA (typeof === 'string'; v0.22.5 shows its built-in image). The SVG is inlined in bench
// colours (stroke = currentColor); anything unsafe or unreadable falls back to the host's own rendering.

function decodeDataSvg(url) {
  const m = /^data:image\/svg\+xml(;base64)?,(.*)$/s.exec(String(url || ''))
  if (!m) return null
  try {
    if (!m[1]) return decodeURIComponent(m[2])
    const bin = atob(m[2])
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0))
    return new TextDecoder('utf-8').decode(bytes)
  } catch {
    return null
  }
}

function resultObject(result) {
  if (result && typeof result === 'object') return result
  if (typeof result === 'string') { try { return JSON.parse(result) } catch { return null } }
  return null
}

function SchematicMediaCard(props) {
  const ui = sdk.useValue($ui)
  const [svg, setSvg] = useState(null)
  const [failed, setFailed] = useState(false)
  const file = props?.file
  useEffect(() => {
    let gone = false
    const run = async () => {
      try {
        const url = typeof file?.resolveUrl === 'function' ? await Promise.resolve(file.resolveUrl()) : null
        const text = decodeDataSvg(url)
        const safe = text ? sanitizeSvg(text) : { ok: false }
        if (!gone) { if (safe.ok) setSvg(safe.svg); else setFailed(true) }
      } catch {
        if (!gone) setFailed(true)
      }
    }
    run()
    return () => { gone = true }
  }, [file?.path])
  if (failed) return props?.fallback ?? null
  const res = resultObject(props?.result)
  const env = res?.action === 'schematic.render' ? res : res?.result?.action ? res.result : res
  const summary = env?.summary || (typeof props?.args?.block === 'string' ? props.args.block.replace(/_/g, ' ') : 'schematic')
  return h(Fragment, null, h(Styles, null),
    h('div', { className: 'cb-root cb-dcard cb-bracket cb-media', 'data-cb': 'media-card', 'data-cb-look': ui.look },
      h('div', { className: 'cb-dcard-head' }, h('span', { className: 'cb-brand cb-brand--sm' }, '◢ BENCH'), h(Label, null, '03 // WIRING'),
        h('span', { className: 'cb-dim cb-ellip' }, summary)),
      svg ? h('div', { className: 'cb-svg cb-svg--media', role: 'img', 'aria-label': summary, dangerouslySetInnerHTML: { __html: svg } })
        : h('div', { className: 'cb-loading', style: { padding: '8px 0' } }, 'loading schematic'),
      h('div', { className: 'cb-actions' }, h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'media-open', onClick: () => { goStation('wire'); openBench({ beside: true }) } }, 'Open in Bench ›'))))
}

// --- 70-theme.js
// Theme "Bench Phosphor" (THEMES_AREA): colours + typography only, no customCSS, no fontUrl.
// Listed in Settings → Appearance → Theme; never selected automatically.

const BENCH_THEME = {
  name: 'bench-phosphor',
  label: 'Bench Phosphor',
  description: 'Phosphor green on near-black — circuit bench',
  colors: {
    background: PHOSPHOR.bg,
    foreground: PHOSPHOR.fg,
    card: PHOSPHOR.panel,
    cardForeground: PHOSPHOR.fg,
    muted: PHOSPHOR.raised,
    // between fg and fg-dim: app icons and the status bar must not look dimmed
    mutedForeground: THEME_MUTED,
    popover: PHOSPHOR.panel,
    popoverForeground: PHOSPHOR.fg,
    primary: PHOSPHOR.ok,
    primaryForeground: PHOSPHOR.ink,
    secondary: '#0f2418',
    secondaryForeground: PHOSPHOR.fg,
    accent: '#0f2418',
    accentForeground: PHOSPHOR.ok,
    border: PHOSPHOR['stroke-strong'],
    input: PHOSPHOR['stroke-strong'],
    ring: PHOSPHOR.ok,
    midground: PHOSPHOR.ok,
    destructive: PHOSPHOR.bad,
    destructiveForeground: PHOSPHOR.ink,
    sidebarBackground: '#030604',
    sidebarBorder: PHOSPHOR.stroke,
    userBubble: PHOSPHOR.raised,
    userBubbleBorder: PHOSPHOR['stroke-strong']
  },
  typography: {
    fontSans: 'system-ui, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    fontMono: MONO.replace('var(--dt-font-mono), ', '')
  }
}

// --- 80-settings.js
// Settings → Plugins → Circuit Bench (ctx.registerSettingsPage): desktop-only state. The agent settings
// (allow_flash, hardware_access, baud, limits …) come from config_schema and appear as "Agent settings" next to
// this page; it links there. Fixture mode only in development builds and only with ?dev=1.

function devSettingsVisible() {
  if (CB_FIXTURES === null) return false
  try { return /[?&]dev=1\b/.test(String(typeof window !== 'undefined' ? window.location?.hash || '' : '')) } catch { return false }
}

function setLook(look) {
  patchAtom($ui, { look })
  store('look', look)
}

function setTimestamps(on) {
  patchAtom($ui, { showTs: on })
  store('timestamps', on)
}

function SettingsRow({ title, desc, children, dataCb }) {
  return h('div', { className: 'cb-setrow', 'data-cb': dataCb }, h('div', null, h('div', { className: 'cb-settitle' }, title), desc ? h('div', { className: 'cb-setdesc' }, desc) : null),
    h('div', { className: 'cb-setctl' }, children))
}

function BenchSettingsPage() {
  const ui = sdk.useValue($ui)
  const bench = sdk.useValue($bench)
  const health = bench.health
  const dev = devSettingsVisible()
  useEffect(() => {
    if (!bench.health && CB.api) CB.api.health().then(env => { if (env.ok) patchAtom($bench, { health: env.result }) })
  }, [])
  return h('div', { className: 'cb-root cb-settings', 'data-cb': 'settings-page', 'data-cb-look': 'theme' }, h(Styles, null),
    h('h2', { className: 'cb-set-h' }, 'Circuit Bench'),
    h('p', { className: 'cb-setdesc' }, 'Desktop settings of the bench. Flashing, hardware access and serial limits are agent settings.'),
    h(SettingsRow, { title: 'Bench look', desc: 'Phosphor: fixed dark bench colours. Follow app theme: the bench uses the colours of your Hermes theme (light themes, accessibility).', dataCb: 'set-look' },
      h(Seg, { label: 'Bench look', dataCb: 'seg-look', value: ui.look, onChange: setLook,
        options: [{ id: 'phosphor', label: 'Phosphor' }, { id: 'theme', label: 'Follow app theme' }] })),
    h(SettingsRow, { title: 'Console timestamps', desc: 'Show the receive time of every serial line.', dataCb: 'set-ts' },
      h(Toggle, { checked: ui.showTs, onChange: setTimestamps, dataCb: 'toggle-ts' }, ui.showTs ? 'On' : 'Off')),
    h(SettingsRow, { title: 'Agent settings', dataCb: 'set-agent',
      desc: [`Allow flashing real boards (now ${health ? (health.allow_flash ? 'on' : 'off') : '—'}), hardware access (now ${health ? (health.hardware_access ? 'on' : 'off') : '—'}), `,
        'approval for serial ports, default baud rate, monitor and build time limits.'] },
    h(Btn, { kind: 'ghost', size: 'sm', 'data-cb': 'agent-settings', onClick: () => openAgentSettings() }, 'Agent settings ›')),
    dev ? h(SettingsRow, { title: 'Fixture data (development)', desc: 'Development build only: answer every route from the embedded fixtures instead of the backend. Reload after a change.', dataCb: 'set-fixtures' },
      h(Toggle, { checked: stored('useFixtures', true) !== false, dataCb: 'toggle-fixtures', onChange: on => store('useFixtures', on) }, 'Fixtures')) : null)
}

function registerSettings(ctx) {
  if (typeof ctx.registerSettingsPage !== 'function') return null
  try {
    return ctx.registerSettingsPage({ id: 'bench', title: 'Circuit Bench', icon: 'circuit-board', order: 50, render: () => h(BenchSettingsPage, null) })
  } catch (e) {
    console.warn('[circuit-bench] settings page not registered', e)
    return null
  }
}

// --- 90-register.js
// Registration: route /bench + nav, status chip, palette, theme, serial pane on demand.

function registerDevHooks() {
  // Development builds only (CB_FIXTURES embedded): lets the E2E harness play the agent against the fixture backend.
  if (CB_FIXTURES === null || !CB.api?.fixtures || typeof window === 'undefined') return
  window.__cbDev = {
    mode: () => CB.api.mode,
    agentAssign: async op => {
      const p = $project.get()
      if (!p) return null
      const env = await CB.api.fixtures.handle('PATCH', `/projects/${p.id}`, { expected_rev: p.rev, ops: [{ op: 'assign', ...op }], by: 'agent' })
      if (env.ok) {
        CB.lastEventAt = Date.now()
        onProjectUpdated({ id: p.id, rev: env.result.rev, changed: env.result.changed, by: 'agent' })
      }
      return env
    },
    jobEvent: (payload = {}) => {
      CB.lastEventAt = Date.now()
      const job = CB_FIXTURES[`job.${payload.kind || 'build'}.done`]?.result
      return onJobUpdated({ job_id: job?.job_id, kind: job?.kind, state: 'done', progress: 1, ...payload })
    },
    state: () => ({ phase: $bench.get().phase, station: $nav.get().station, selected: $view.get().selected, rev: $project.get()?.rev,
      check: $check.get().status, map: $map.get().status, mounts: CB.mounts, paneOpen: $ui.get().paneOpen, monitor: $monitor.get().status,
      serialMode: $serial.get().mode, jobs: Object.fromEntries(Object.entries($jobs.get()).map(([k, j]) => [k, j?.state || null])) })
  }
}

export default {
  id: PLUGIN_ID,
  name: 'Circuit Bench',
  description: 'ESP32 electronics bench: pin map, calculators, wiring, solder order, flash and serial debug.',
  register(ctx) {
    initStore(ctx)
    const regs = [
      { id: 'page', area: sdk.ROUTES_AREA, data: { path: '/bench' }, render: () => h(BenchPage, { surface: 'route' }) },
      { id: 'nav', area: sdk.SIDEBAR_NAV_AREA, data: { path: '/bench', label: 'Circuit Bench', codicon: 'circuit-board' } }
    ]
    if (sdk.STATUSBAR_AREAS?.right) regs.push({ id: 'board-chip', area: sdk.STATUSBAR_AREAS.right, order: 480, render: () => h(BoardChip, null) })
    if (typeof sdk.PALETTE_AREA !== 'undefined') {
      const cmd = (id, label, keywords, run, detail) => ({ id: `palette-${id}`, area: sdk.PALETTE_AREA,
        data: { id: `circuit-bench.${id}`, label, keywords: [...keywords, 'bench', 'circuit'], run, ...(detail ? { detail } : {}) } })
      const focus = what => { openBench({ station: 'flash' }); patchAtom($flow, { focus: what, at: Date.now() }) }
      regs.push(
        cmd('open', 'Open Bench', ['circuit', 'esp32', 'pins'], () => openBench(), () => $project.get()?.id || ''),
        cmd('serial', 'Open serial monitor', ['serial', 'monitor', 'console', 'uart'], () => openSerialPane()),
        cmd('new', 'New bench project', ['project', 'create', 'new'], () => { openBench(); patchAtom($ui, { modal: { type: 'new-project' } }) }),
        cmd('projects', 'Manage bench projects', ['projects', 'switch', 'open', 'delete'], () => { openBench(); patchAtom($ui, { modal: { type: 'projects' } }) }),
        cmd('demo', 'Load demo project', ['demo', 'laser-trigger', 'simulated'], () => { openBench(); loadDemo() }),
        // detect and build only open station 05 and point at its button: no hardware access from the palette
        cmd('detect', 'Detect board', ['detect', 'esptool', 'port', 'board'], () => focus('detect'), () => 'opens 05 FLASH'),
        cmd('build', 'Build firmware', ['build', 'platformio', 'pio', 'firmware'], () => focus('build'), () => 'opens 05 FLASH'),
        cmd('doctor', 'Run bench doctor', ['doctor', 'tools', 'check', 'health'], () => { openBench(); runDoctor() }))
    }
    if (typeof sdk.THEMES_AREA !== 'undefined') regs.push({ id: 'theme', area: sdk.THEMES_AREA, data: BENCH_THEME })
    if (typeof sdk.TRANSCRIPT_DIRECTIVE_AREA !== 'undefined') {
      regs.push({ id: 'directive-bench', area: sdk.TRANSCRIPT_DIRECTIVE_AREA, data: { name: 'bench', render: props => h(BenchDirectiveCard, props) } })
    }
    // own card for bench_schematic images only where the host has the area (absent in v0.22.5)
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA === 'string') {
      regs.push({ id: 'media-schematic', area: sdk.TOOL_MEDIA_RENDERER_AREA, data: { tools: ['bench_schematic'], render: props => h(SchematicMediaCard, props) } })
    }
    ctx.registerMany(regs)
    registerSettings(ctx)
    if (stored('paneOpen', false)) openSerialPane()
    ctx.onDispose(() => {
      CB.paneDispose = null
      if (MONITOR) { MONITOR.stop(); MONITOR = null } // the backend keeps the port; the next start does not reopen it
      for (const k of Object.keys(JOB_WATCH)) { if (typeof JOB_WATCH[k] === 'function') JOB_WATCH[k](); JOB_WATCH[k] = null }
    })
    registerDevHooks()
  }
}
