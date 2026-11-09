// Board geometry (lib/board-geom.js) and its use by the DOM rows and the SVG layer.
//   geometry = CSS variables = SVG measures; width/height budget; pitch from the available height; tag column.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { boardGeom, boardGeomVars, boardSlots, boardSlotY, boardPadX, boardTagW, BOARD_GEOM_BODY, BOARD_GEOM_TAG } from '../desktop-src/lib/board-geom.js'
import { build } from '../scripts/build-desktop.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const FXDIR = join(ROOT, 'desktop-src', 'fixtures')
const LAYOUTS = readdirSync(FXDIR).filter(f => /^board\..*\.json$/.test(f)).sort()
  .map(f => JSON.parse(readFileSync(join(FXDIR, f), 'utf8')).result)

test('seven layouts, slots include the WT32 header separators', () => {
  assert.equal(LAYOUTS.length, 7)
  const wt = LAYOUTS.find(l => l.id === 'wt32-eth01')
  assert.deepEqual(boardSlots(wt.left).filter(s => s.sep).map(s => s.sep), ['IO'])
  assert.equal(boardGeom({ layout: wt }).slots, 14)
  assert.equal(boardGeom({ layout: LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1') }).slots, 22)
})

test('the gutter adds up from its columns; body 220–340; the box never exceeds the width; bottom zone ≤ 36', () => {
  for (const layout of LAYOUTS) {
    for (const width of [380, 480, 548, 560, 640, 900]) {
      for (const tagWidth of [0, 64, 96, 200]) {
        const g = boardGeom({ layout, width, tagWidth })
        assert.ok(g.bodyW >= BOARD_GEOM_BODY[0] && g.bodyW <= BOARD_GEOM_BODY[1], `${layout.id} ${width}: body ${g.bodyW}`)
        assert.ok(g.tagW >= BOARD_GEOM_TAG[0] && g.tagW <= BOARD_GEOM_TAG[1])
        assert.equal(g.gutterL, (g.markW ? g.markW + 4 : 0) + g.tagW + g.nameW + 29)
        assert.equal(g.width, 2 * g.gutterL + g.bodyW)
        assert.equal(g.rowW, g.gutterL + g.stripX + 7)
        assert.equal(g.pitch, g.rowH + g.rowGap)
        assert.equal(g.height, g.topZone + g.slots * g.pitch + g.bottomZone)
        assert.ok(g.bottomZone <= 36)
        if (width >= 548) assert.ok(g.width <= width, `${layout.id} ${width}/${tagWidth}: ${g.width}`)
        // the tag column holds the widest tag unless it is narrower than needed (then tags get an ellipsis)
        assert.equal(g.tagFits, g.tagW >= tagWidth)
        // names stay 12 px legible: rows ≥ 14 px
        assert.ok(g.rowH >= 14)
      }
    }
  }
})

test('pitch: the largest candidate whose board fits the available height; floor 15 px', () => {
  const s2 = LAYOUTS.find(l => l.id === 'esp32-s2-devkitc-1')
  assert.equal(boardGeom({ layout: s2 }).pitch, 18)
  assert.equal(boardGeom({ layout: s2, consoleOpen: false }).pitch, 20)
  for (const hh of [600, 440, 420, 400, 380, 300]) {
    const g = boardGeom({ layout: s2, height: hh })
    if (hh >= 16 + 22 * 15 + 26) assert.ok(g.height <= hh, `${hh}: ${g.height}`)
    else assert.equal(g.pitch, 15)
  }
  assert.equal(boardGeom({ layout: s2, height: 376 }).pitch, 15) // 1100×800 what-if room
})

test('the mark column gives way before the tags; compact mode has no gutters', () => {
  const s3 = LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1')
  // the selection caret moved into the name→glyph gap, the mark column is gone
  assert.equal(boardGeom({ layout: s3, width: 640, tagWidth: 80 }).markW, 0)
  const narrow = boardGeom({ layout: s3, width: 500, tagWidth: 96 })
  assert.equal(narrow.markW, 0)
  const c = boardGeom({ layout: s3, mode: 'compact' })
  assert.deepEqual([c.gutterL, c.markW, c.tagW, c.nameW, c.pitch, c.mode], [0, 0, 0, 0, 18, 'compact'])
  assert.equal(boardTagW(''), 0)
  assert.equal(boardTagW('UART0 · 43'), Math.ceil(10 * 6.4 + 12))
})

test('CSS variables come from the same numbers', () => {
  const g = boardGeom({ layout: LAYOUTS[0], width: 600, tagWidth: 70 })
  const v = boardGeomVars(g)
  assert.equal(v['--cb-row-h'], `${g.rowH}px`)
  assert.equal(v['--cb-row-gap'], `${g.rowGap}px`)
  assert.equal(v['--cb-body-w'], `${g.bodyW}px`)
  assert.equal(v['--cb-gutter'], `${g.gutterL}px`)
  assert.equal(v['--cb-board-w'], `${g.width}px`)
  assert.equal(v['--cb-board-h'], `${g.height}px`)
  assert.equal(boardPadX(g, 'left'), g.gutterL + 15)
  assert.equal(boardPadX(g, 'right'), g.gutterL + g.bodyW - 15)
  assert.equal(boardSlotY(g, 0), g.topZone + g.rowH / 2)
})

// ------------------------------------------------------------------- the rendered BoardView uses the geometry
const FX = Object.fromEntries(readdirSync(FXDIR).filter(f => f.endsWith('.json')).map(f => [f.slice(0, -5), JSON.parse(readFileSync(join(FXDIR, f), 'utf8'))]))
function fakeSdk() {
  const atom = v => { let cur = v; const subs = new Set(); return { get: () => cur, set: n => { cur = n; subs.forEach(f => f(n)) }, subscribe: f => { subs.add(f); return () => subs.delete(f) } } }
  return { atom, useValue: a => a.get(), ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'nav', PALETTE_AREA: 'palette', THEMES_AREA: 'themes',
    TRANSCRIPT_DIRECTIVE_AREA: 'directives', STATUSBAR_AREAS: { right: 'statusBar.right' }, PANES_AREA: 'panes',
    host: { navigate: () => {}, openWorkspace: () => {}, notify: () => {} } }
}
async function loadBundle() {
  const text = build({ withFixtures: false })
    .replace("import * as sdk from '@hermes/plugin-sdk'", 'const sdk = globalThis.__cbSdk')
    .replace("import { useState, useEffect, useMemo, useRef, useCallback } from 'react'",
      'const useState = v => [typeof v === "function" ? v() : v, () => {}], useEffect = () => {}, useMemo = f => f(), useRef = v => ({ current: v }), useCallback = f => f')
    .replace("import { jsx, jsxs, Fragment } from 'react/jsx-runtime'",
      'const Fragment = "#fragment", jsx = (type, props, key) => ({ type, props: props || {}, key }), jsxs = jsx')
    + '\nexport const __t = { BoardView, boardGeom, boardArtModel, boardTagW, BoardPin, Legend }\n'
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}#${Math.random()}`)
}
function render(node) {
  if (node === null || node === undefined || node === false || node === true) return []
  if (Array.isArray(node)) return node.flatMap(render)
  if (typeof node !== 'object') return [String(node)]
  if (typeof node.type === 'function') return render(node.type(node.props))
  if (node.type === '#fragment') return render(node.props.children)
  const { children, ...props } = node.props || {}
  return [{ type: node.type, props, children: render(children) }]
}
function walk(tree, fn) { for (const n of tree) { if (typeof n === 'string') continue; fn(n); walk(n.children, fn) } }
const byCb = (tree, cb) => { const out = []; walk(tree, n => { if (n.props['data-cb'] === cb) out.push(n) }); return out }

test('BoardView: style variables, SVG size and pad centres are one geometry (all seven boards)', async () => {
  globalThis.__cbSdk = fakeSdk()
  const { __t: t } = await loadBundle()
  for (const layout of LAYOUTS) {
    const tree = render(t.BoardView({ layoutState: { status: 'ready', id: layout.id, layout }, mapState: { status: 'idle', env: null }, rows: [],
      board: { chip: layout.chip, variant: null, wifi: true, devkit: layout.id }, selected: null, suggestPins: [], onSelect: () => {} }))
    const [board] = byCb(tree, 'board')
    const st = board.props.style
    const model = t.boardArtModel({ layout, chip: null })
    const tags = [...model.views.left, ...model.views.right].filter(s => s.view).map(s => t.boardTagW(s.view.tag))
    // the fake store has no monitor, job or pinned console: the console is idle (a bar), so the board gets the free
    // pitch candidates (only a really open console limits the pitch)
    const g = t.boardGeom({ layout, consoleOpen: false, tagWidth: Math.ceil(Math.max(0, ...tags) / 8) * 8 })
    assert.deepEqual(st, boardGeomVars(g), layout.id)
    let svg = null
    walk(tree, n => { if (n.props.className === 'cb-board-art') svg = n.props.dangerouslySetInnerHTML.__html })
    assert.ok(svg.startsWith('<svg'), layout.id)
    assert.match(svg, new RegExp(`viewBox="0 0 ${g.width} ${g.height}" width="${g.width}" height="${g.height}"`))
    // every pad of the left strip sits on the slot centre line at the left pad x
    const pads = [...svg.matchAll(/class="cb-art-pad" data-cb-art-state="[a-z_]+"[^>]*>(?:<circle[^>]*\/>)?<(circle|rect) ([^>]*)\/>/g)]
    assert.ok(pads.length >= 2 * 13, `${layout.id}: ${pads.length} pads`)
    const xs = new Set(pads.map(([, tag, a]) => tag === 'circle' ? Number(/cx="([\d.]+)"/.exec(a)[1]) : Number(/x="([\d.]+)"/.exec(a)[1]) + 6.5))
    assert.deepEqual([...xs].sort((a, b) => a - b), [boardPadX(g, 'left'), boardPadX(g, 'right')], layout.id)
  }
})
