// The board model layer (lib/art-board.js + boardParts/boardArtModel in lib/pins.js) for all seven
// boards: no label overlap, every pin with symbol shape and state word, generic placement without `drawing`, only
// known kinds with it, escaping, compact mode, instance prefixes, determinism.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const LIB = join(ROOT, 'desktop-src', 'lib')
const FXDIR = join(ROOT, 'desktop-src', 'fixtures')
// lib files share one scope in the bundle: concatenate the four this layer needs into one test module
const src = ['art.js', 'board-geom.js', 'pins.js', 'art-board.js'].map(f => readFileSync(join(LIB, f), 'utf8')).join('\n')
const M = await import(`data:text/javascript;base64,${Buffer.from(src).toString('base64')}`)
const { artBoard, artBoardPlan, boardGeom, boardArtModel, boardParts, boardTagW, chipInfo, variantInfo, CHIPS, DRAWING_KINDS, ART_STATE_WORDS, pinStateWord, PIN_ART_STATE } = M

const LAYOUTS = readdirSync(FXDIR).filter(f => /^board\..*\.json$/.test(f)).sort()
  .map(f => JSON.parse(readFileSync(join(FXDIR, f), 'utf8')).result)
const clone = x => JSON.parse(JSON.stringify(x))
const gpios = l => [...l.left, ...l.right].filter(p => p.kind === 'gpio' && Number.isInteger(p.gpio)).map(p => p.gpio)

/** Pin-state scenarios per board: not checked, all free, mixed (blocked/caution/assigned with long roles). */
function scenarios(layout) {
  const all = gpios(layout)
  const free = new Map(all.map(g => [g, { pin: g, verdict: 'ok', reasons: [] }]))
  const mixed = new Map(all.map((g, i) => [g, i % 3 === 0
    ? { pin: g, verdict: 'blocked', reasons: [{ severity: 'blocked', rule_id: 'esp32.input_only', message: 'input only' }] }
    : i % 3 === 1 ? { pin: g, verdict: 'caution', reasons: [{ severity: 'caution', rule_id: 'x.strapping', message: 'strap' }] }
      : { pin: g, verdict: 'ok', reasons: [] }]))
  const used = new Map(all.filter((_, i) => i % 4 === 0).map((g, i) => [g, { pin: g, role: i % 2 ? 'LASER_TRIGGER_OUT' : 'BTN', mode: 'out', verdict: i % 3 === 0 ? 'blocked' : 'ok' }]))
  return [
    { name: 'unchecked', base: new Map(), used: new Map() },
    { name: 'free', base: free, used: new Map() },
    { name: 'mixed', base: mixed, used, selected: all[2], suggest: [all[3]] }
  ]
}

const variantsOf = chip => [null, ...(chipInfo(chip)?.variants || []).map(v => v.id)]

function modelFor(layout, sc, variant) {
  return boardArtModel({ layout, chip: chipInfo(layout.chip), variant: variantInfo(layout.chip, variant), base: sc.base, used: sc.used,
    selected: sc.selected ?? null, suggest: sc.suggest || [] })
}
function geomFor(layout, model, width, height = null) {
  const tags = [...model.views.left, ...model.views.right].filter(s => s.view).map(s => boardTagW(s.view.tag))
  return boardGeom({ layout, width, height, tagWidth: Math.ceil(Math.max(0, ...tags) / 8) * 8 })
}
const overlap = (a, b) => a.x0 < b.x1 - 0.5 && b.x0 < a.x1 - 0.5 && a.y0 < b.y1 - 0.5 && b.y0 < a.y1 - 0.5

test('no overlap: silk and can texts, parts, module and notes (7 boards × variants × states × widths × heights)', () => {
  let n = 0
  for (const layout of LAYOUTS) {
    for (const variant of variantsOf(layout.chip)) {
      for (const sc of scenarios(layout)) {
        for (const width of [480, 548, 640]) {
          for (const height of [null, 380]) {
            const model = modelFor(layout, sc, variant)
            const g = geomFor(layout, model, width, height)
            const plan = artBoardPlan(model, g)
            const at = `${layout.id}/${variant}/${sc.name}/${width}/${height}`
            // text boxes pairwise free and inside the inner area of the pcb
            for (let i = 0; i < plan.texts.length; i++) {
              const a = plan.texts[i]
              assert.ok(a.x0 >= g.inner.x0 - 1 && a.x1 <= g.inner.x1 + 1, `${at}: "${a.text}" outside the inner area ${a.x0}..${a.x1}`)
              for (let j = i + 1; j < plan.texts.length; j++) assert.ok(!overlap(a, plan.texts[j]), `${at}: "${a.text}" / "${plan.texts[j].text}"`)
            }
            // part footprints, module and notes do not overlap; everything stays inside the pcb (ports overhang the bottom)
            const boxes = [
              { id: 'module', x0: plan.module.x, x1: plan.module.x + plan.module.w, y0: plan.module.y, y1: plan.module.y + plan.module.h },
              ...plan.notes.map(r => ({ id: `note ${r.text}`, x0: r.x, x1: r.x + r.w, y0: r.y, y1: r.y + r.h })),
              ...plan.parts.map(p => ({ id: `${p.part.kind} ${p.part.label}`, x0: p.x, x1: p.x + p.fp.w, y0: p.y, y1: p.y + p.fp.h, port: p.band === 'bottom' }))
            ]
            for (let i = 0; i < boxes.length; i++) {
              const a = boxes[i]
              assert.ok(a.x0 >= g.inner.x0 - 1 && a.x1 <= g.inner.x1 + 1, `${at}: ${a.id} outside x ${a.x0}..${a.x1} (${g.inner.x0}..${g.inner.x1})`)
              assert.ok(a.y0 >= 0 && a.y1 <= (a.port ? g.pcbBottom + g.portOut + 0.5 : g.pcbBottom), `${at}: ${a.id} outside y ${a.y0}..${a.y1}`)
              for (let j = i + 1; j < boxes.length; j++) assert.ok(!overlap(a, boxes[j]), `${at}: ${a.id} / ${boxes[j].id}`)
            }
            // the antenna lies within the span of the first pin rows, the module is not squeezed flat
            assert.ok(plan.module.y < g.topZone + 3 * g.pitch, at)
            assert.ok(plan.module.h >= 50, `${at}: module ${plan.module.h}`)
            // DOM label columns: the widest tag either fits or the geometry says so (ellipsis + title)
            const widest = Math.max(0, ...[...model.views.left, ...model.views.right].filter(s => s.view).map(s => boardTagW(s.view.tag)))
            if (g.tagFits) assert.ok(widest <= g.tagW, `${at}: tag ${widest} > ${g.tagW}`)
            n++
          }
        }
      }
    }
  }
  assert.ok(n > 100, `${n} cases`)
})

test('every pin has a symbol shape and a state word', () => {
  for (const layout of LAYOUTS) {
    for (const sc of scenarios(layout)) {
      const model = modelFor(layout, sc, null)
      const g = geomFor(layout, model, 640)
      const svg = artBoard(model, g, { prefix: 't' })
      for (const side of ['left', 'right']) {
        for (const s of model.views[side].filter(v => v.view)) {
          const word = pinStateWord(s.view.state)
          assert.ok(word && word !== 'undefined', `${layout.id} ${s.hp.header}-${s.hp.n}`)
          if (s.view.state === 'unchecked') assert.equal(s.art, null)
          else assert.ok(s.art in ART_STATE_WORDS, `${layout.id} ${s.view.state} → ${s.art}`)
        }
      }
      const pads = (svg.match(/class="cb-art-pad"/g) || []).length
      assert.equal(pads, layout.left.length + layout.right.length, layout.id)
    }
  }
  assert.deepEqual(Object.keys(PIN_ART_STATE).sort(), ['bad', 'free', 'ground', 'nc', 'power', 'reset', 'signal', 'unchecked', 'used', 'used-bad', 'used-warn', 'warn'])
})

test('with drawing: only known kinds, quoted connector forms, generic jack for connector null', () => {
  for (const layout of LAYOUTS) {
    const { parts, drawing } = boardParts(layout)
    assert.equal(drawing, true, layout.id)
    assert.ok(parts.every(p => DRAWING_KINDS.includes(p.kind)), layout.id)
    for (const p of parts.filter(x => x.kind === 'usb_port')) {
      const d = layout.drawing.parts.find(x => x.kind === 'usb_port' && x.ref === p.ref)
      assert.equal(p.connector, d?.connector || 'generic_usb', `${layout.id} ${p.ref}`)
    }
  }
  const s3 = clone(LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1'))
  s3.drawing.parts.push({ kind: 'laser_diode', label: 'LASER', zone: 'middle', side: 'left' }, { kind: 'usb_port', ref: 'NOPE', edge: 'bottom', order: 3 })
  const { parts } = boardParts(s3)
  assert.ok(!parts.some(p => p.kind === 'laser_diode' || p.ref === 'NOPE'))
  const usb = parts.find(p => p.ref === 'USB')
  assert.deepEqual([usb.connector, usb.schematic], ['generic_usb', false])
  const svg = artBoard(boardArtModel({ layout: s3, chip: chipInfo('esp32s3') }), boardGeom({ layout: s3 }), { prefix: 's3' })
  assert.ok(!svg.includes('LASER'))
  assert.match(svg, /data-cb-port="micro_usb"/)
  assert.match(svg, /data-cb-port="generic_usb" data-cb-schematic="true"/)
  // WT32: RJ45 + PHY from the drawing, no buttons, no antenna
  const wt = LAYOUTS.find(l => l.id === 'wt32-eth01')
  const wsvg = artBoard(boardArtModel({ layout: wt, chip: chipInfo('esp32') }), boardGeom({ layout: wt }), { prefix: 'wt' })
  assert.match(wsvg, /data-cb-port="rj45"/)
  assert.match(wsvg, /data-cb-part="phy_ic"/)
  assert.ok(!wsvg.includes('cb-art-antenna') && !wsvg.includes('cb-art-button'))
  // C6: USB-C both
  const c6 = LAYOUTS.find(l => l.id === 'esp32-c6-devkitc-1')
  assert.equal((artBoard(boardArtModel({ layout: c6 }), boardGeom({ layout: c6 })).match(/data-cb-port="usb_c"/g) || []).length, 2)
})

test('without drawing: generic standard placement, every part and the model marked schematic', () => {
  for (const l of LAYOUTS) {
    const layout = clone(l)
    delete layout.drawing
    const { parts, drawing } = boardParts(layout)
    assert.equal(drawing, false)
    assert.ok(parts.every(p => p.schematic === true), layout.id)
    assert.deepEqual(parts.filter(p => p.kind === 'usb_port').map(p => p.ref), (layout.usb || []).map(u => u.label))
    assert.ok(parts.filter(p => p.kind === 'usb_port').every(p => p.connector === 'generic_usb'))
    const model = boardArtModel({ layout, chip: chipInfo(layout.chip) })
    assert.equal(model.schematic, true)
    const svg = artBoard(model, boardGeom({ layout }), { prefix: 'x' })
    assert.match(svg, /^<svg[^>]* data-cb-schematic="true"/)
    assert.match(svg, /schematic/)
    assert.match(svg, /not to scale/)
    // nothing of the drawing-only kinds appears without a drawing
    assert.ok(!/data-cb-part="(ldo|bridge_ic|phy_ic|power_led)"/.test(svg), layout.id)
  }
  // no buttons field and no drawing: the old BOOT/RST pair; buttons [] (WT32): none
  assert.deepEqual(boardParts({ usb: [] }).parts.map(p => p.label), ['BOOT', 'RST'])
  assert.deepEqual(boardParts({ buttons: [] }).parts, [])
})

test('silk print: title, revision and "schematic · not to scale" on every board', () => {
  for (const layout of LAYOUTS) {
    const svg = artBoard(boardArtModel({ layout, chip: chipInfo(layout.chip) }), boardGeom({ layout, width: 548 }), { prefix: 'p' })
    assert.match(svg, /schematic/, layout.id)
    assert.match(svg, /not to scale/, layout.id)
  }
})

test('escaping: data never reaches the SVG raw', () => {
  const s3 = clone(LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1'))
  s3.title = 'X<script>alert(1)</script>"&\''
  s3.revision = '<b>'
  s3.drawing.parts.find(p => p.kind === 'button').label = '<img src=x onerror=1>'
  s3.drawing.parts.find(p => p.kind === 'ldo').label = '"><g onload="x'
  const model = boardArtModel({ layout: s3, chip: chipInfo('esp32s3'), variant: variantInfo('esp32s3', 'n16r8') })
  const svg = artBoard(model, boardGeom({ layout: s3, width: 900 }), { prefix: '"><x' })
  assert.ok(!/<script|<img|<b>|<g onload|onerror=1>/.test(svg), svg.slice(0, 200))
  for (const bad of ['<style', 'href', '<image', 'foreignObject']) assert.ok(!svg.includes(bad), bad)
  assert.ok(!/<[^>]*\son[a-z]+=/i.test(svg), 'no event attribute')
})

test('compact mode: body, pads with state, ports; no text at all; width = body', () => {
  for (const layout of LAYOUTS) {
    const sc = scenarios(layout)[2]
    const model = modelFor(layout, sc, null)
    const g = boardGeom({ layout, mode: 'compact' })
    const svg = artBoard(model, g, { prefix: 'chat-1', mode: 'compact' })
    assert.ok(!svg.includes('<text'), layout.id)
    assert.match(svg, new RegExp(`viewBox="0 0 ${g.bodyW} ${g.height}"`))
    assert.ok(!/ width="/.test(svg.slice(0, svg.indexOf('>'))), 'compact scales: no fixed size')
    assert.match(svg, /data-cb-mode="compact"/)
    assert.equal((svg.match(/class="cb-art-pad"/g) || []).length, layout.left.length + layout.right.length)
    assert.match(svg, /data-cb-art-state="blocked"|data-cb-art-state="assigned_blocked"/)
    assert.ok(!svg.includes(' data-cb-state='), 'the drawing never uses the pin rows\' attribute')
    assert.match(svg, /cb-art-port/, layout.id)
  }
})

test('instance prefixes: two models on one page share no id; output is deterministic', () => {
  const layout = LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1')
  const model = boardArtModel({ layout, chip: chipInfo('esp32s3'), variant: variantInfo('esp32s3', 'n16r8') })
  const g = boardGeom({ layout })
  const a = artBoard(model, g, { prefix: 'board-1' })
  const b = artBoard(model, g, { prefix: 'chat-7', mode: 'compact' })
  const ids = s => [...s.matchAll(/ id="([^"]+)"/g)].map(m => m[1])
  assert.ok(ids(a).length >= 6)
  assert.deepEqual(ids(a).filter(x => ids(b).includes(x)), [])
  for (const s of [a, b]) for (const [, ref] of s.matchAll(/url\(#([^)]+)\)/g)) assert.ok(ids(s).includes(ref), ref)
  assert.equal(artBoard(model, g, { prefix: 'board-1' }), a)
})

test('octal PSRAM: one bracket on the strip over IO35–37 (S3 N16R8), none for N16; reservations from the rules', () => {
  const layout = LAYOUTS.find(l => l.id === 'esp32-s3-devkitc-1')
  const octal = boardArtModel({ layout, chip: chipInfo('esp32s3'), variant: variantInfo('esp32s3', 'n16r8') })
  assert.deepEqual(octal.brackets.right.map(b => [b.label, b.to - b.from + 1]), [['OCTAL PSRAM', 3]])
  const svg = artBoard(octal, boardGeom({ layout }), { prefix: 'o' })
  assert.equal((svg.match(/class="cb-art-bracket"/g) || []).length, 1)
  assert.match(svg, /rotate\(-90\)[^>]*>OCTAL PSRAM</)
  const quad = boardArtModel({ layout, chip: chipInfo('esp32s3'), variant: variantInfo('esp32s3', 'n16r2') })
  assert.deepEqual(quad.brackets.right, [])
  assert.deepEqual(quad.notes.map(n => n.id), ['quad'])
  // USB pins 19/20 (caution, usb_jtag rule) neighbour on J3: a USB bracket
  const base = new Map([19, 20].map(g => [g, { pin: g, verdict: 'caution', reasons: [{ severity: 'caution', rule_id: 'esp32s3.usb_jtag', message: 'usb' }] }]))
  const usb = boardArtModel({ layout, chip: chipInfo('esp32s3'), variant: variantInfo('esp32s3', 'n16'), base })
  assert.deepEqual(usb.brackets.right.map(b => [b.label, b.tone]), [['USB', 'warn']])
  // DevKitC V4 + WROVER: the SPI PSRAM note; unknown WT32 module: the variant note
  const dk = LAYOUTS.find(l => l.id === 'esp32-devkitc-v4')
  assert.deepEqual(boardArtModel({ layout: dk, chip: chipInfo('esp32'), variant: variantInfo('esp32', 'wrover-e') }).notes.map(n => n.id), ['spi'])
  const wt = LAYOUTS.find(l => l.id === 'wt32-eth01')
  assert.deepEqual(boardArtModel({ layout: wt, chip: chipInfo('esp32') }).notes.map(n => n.id), ['unknown'])
  assert.ok(CHIPS.length >= 5)
})
