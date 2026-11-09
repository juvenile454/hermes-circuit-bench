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

export const BOARD_GEOM_BODY = [220, 340] // pcb body width range in px
export const BOARD_GEOM_MARK = 0 // no mark column any more (the selection caret sits in the name→glyph gap)
export const BOARD_GEOM_TAG = [56, 120] // tag column range
export const BOARD_GEOM_STRIP_X = 15 // strip (pad) centre, from the pcb edge
export const BOARD_GEOM_STRIP_HW = 9 // half width of the plastic strip
export const BOARD_GEOM_LANE = 16 // lane between strip and the inner parts (reservation brackets print here)
export const BOARD_GEOM_PAD_CELL = 14 // DOM pad cell (pad Ø 13)
export const BOARD_GEOM_TAIL = 14 // pcb below the last slot
export const BOARD_GEOM_PORT_OUT = 9 // ports overhang the bottom pcb edge by this much
export const BOARD_GEOM_BOTTOM = BOARD_GEOM_TAIL + BOARD_GEOM_PORT_OUT + 3 // 26 px ≤ 36
const BG_FIXED = 2 + 6 + 5 + 12 + 4 // outer pad, tag→name, name→glyph, glyph, glyph→pcb edge
const BG_MARK_GAP = 4

const bgClamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
/** Monospace width estimate (0.6 em per code point + letter-spacing). */
export const boardTextW = (s, px = 12, ls = 0) => [...String(s ?? '')].length * (0.6 * px + ls)
/** Width a pin tag needs: 10 px capitals, letter-spacing 0.4 px, 5 px padding and 1 px border each side. */
export const boardTagW = s => (String(s ?? '') ? Math.ceil(boardTextW(String(s).toUpperCase(), 10, 0.4) + 12) : 0)

/** Slots of one side: the pins in data order, a separator slot where the header id changes (WT32: PROG → IO). */
export function boardSlots(rows) {
  const out = []
  const list = Array.isArray(rows) ? rows : []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i].header !== list[i - 1].header) out.push({ sep: String(list[i].header ?? '') })
    out.push({ pin: list[i], index: i })
  }
  return out
}

/** The name a pin row shows (same rule as pinView in lib/pins.js: "4" and "IO4" → IO4, ground → GND). */
export function boardPinName(hp) {
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
export function boardGeom({ rows = null, consoleOpen = true, width = null, layout = null, height = null, tagWidth = 0, mode = 'full' } = {}) {
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
export function boardSlotTop(g, i) {
  return g.topZone + i * g.pitch
}

/** Centre line (board coordinates) of slot i. */
export function boardSlotY(g, i) {
  return g.topZone + i * g.pitch + g.rowH / 2
}

/** Pad centre x (board coordinates) of a side. */
export function boardPadX(g, side) {
  return side === 'left' ? g.gutterL + g.stripX : g.gutterL + g.bodyW - g.stripX
}

/** CSS variables for [data-cb=board]: the DOM rows use exactly these numbers (the geometry test compares them). */
export function boardGeomVars(g) {
  const px = v => `${v}px`
  return {
    '--cb-row-h': px(g.rowH), '--cb-row-gap': px(g.rowGap), '--cb-body-w': px(g.bodyW), '--cb-gutter': px(g.gutterL),
    '--cb-top': px(g.topZone), '--cb-mark-w': px(g.markW), '--cb-tag-w': px(g.tagW), '--cb-name-w': px(g.nameW),
    '--cb-strip-x': px(g.stripX), '--cb-row-w': px(g.rowW), '--cb-board-w': px(g.width), '--cb-board-h': px(g.height)
  }
}
